#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate display titles → Feishu bitable (never renames wiki).

Default document universe: TARGET_PARENT_TOKEN (classified copies only).

Usage:
  python -m tools.export_display_title_bitable --dry-run --max-documents 20
  python -m tools.export_display_title_bitable --skip-existing
  python -m tools.export_display_title_bitable --scope scan --all-assigned
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from classify.display_title import (
    DisplayTitleRow,
    build_display_title_row,
    fallback_theme,
    sanitize_theme,
    theme_prompt,
)
from classify.llm_rate_limit import LLM_CONCURRENCY, LLM_RATE_LIMITER
from feishu.bitable import FeishuBitableClient
from feishu.create_feishu_node import FeishuNodeCreator
from feishu.read_doc import FeishuDocumentReader
from feishu.title_check import FolderNameChecker
from feishu.token_manager import TokenManager
from feishu.wiki_meta import WikiMetaClient
from state.display_title_bitable import (
    DisplayTitleBitableRef,
    ensure_display_title_bitable,
    upsert_display_title_record,
)
from state.metadata_bitable import MetadataRecordIndex
from state.operation_ledger import OP_DISPLAY_TITLE_BITABLE, OperationLedger
from state.scan_folders import format_folder_table, load_scan_folders, default_scan_folders_path
from state.shared_state import SharedCopyState, default_worker_id
from tools._tool_scope import SCOPE_SCAN, SCOPE_TARGET
from tools.runner import ToolJob, add_scope_args, ensure_utf8_stdio, write_tool_report

from openai import OpenAI


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="展示标题 → 多维表格（格式：主题-产品线-作者；默认只处理 TARGET）"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--list-folders", action="store_true")
    p.add_argument("--parent-token", default=None, help="多维表格挂载父节点，默认 TARGET")
    p.add_argument("--aggregated-title", default=None)
    p.add_argument("--max-documents", type=int, default=0)
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--skip-read", action="store_true")
    p.add_argument("--skip-date-api", action="store_true")
    add_scope_args(p)
    return p.parse_args()


class PurposeLLM:
    def __init__(self):
        self.client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
            max_retries=0,
        )
        self.model = config.LLM_MODEL
        self.max_retries = config.LLM_MAX_RETRIES

    def summarize(self, title: str, content: str) -> str:
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        )

        messages = [
            {"role": "system", "content": "只输出极短中文主题短语，不要解释。"},
            {"role": "user", "content": theme_prompt(title, content)},
        ]
        fallback = fallback_theme(title, content)
        with LLM_CONCURRENCY:
            for attempt in range(self.max_retries):
                LLM_RATE_LIMITER.wait()
                try:
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=32,
                    )
                    raw = (resp.choices[0].message.content or "").strip()
                    return sanitize_theme(raw, fallback=fallback)
                except Exception as e:
                    retryable = isinstance(
                        e,
                        (
                            APIConnectionError,
                            APITimeoutError,
                            InternalServerError,
                            RateLimitError,
                        ),
                    ) or (
                        isinstance(e, APIStatusError)
                        and e.status_code in {408, 429, 500, 502, 503, 504}
                    )
                    if not retryable or attempt >= self.max_retries - 1:
                        print(f"⚠️ 文章主题 LLM 失败 ({title}): {e} → {fallback}")
                        return fallback
                    time.sleep(min(2**attempt + random.uniform(0.2, 1.0), 30.0))
        return fallback


def _write_rows(
    *,
    bitable: FeishuBitableClient,
    ref: DisplayTitleBitableRef,
    index: MetadataRecordIndex,
    ledger: OperationLedger,
    rows: List[DisplayTitleRow],
    skip_existing: bool,
) -> Dict[str, int]:
    created = updated = skipped = failed = 0
    print(f"\n✍️ 写入 {ref.title} …", flush=True)
    for i, row in enumerate(rows, 1):
        try:
            if skip_existing and ledger.is_done(
                row.obj_token, OP_DISPLAY_TITLE_BITABLE, node_token=row.node_token
            ):
                skipped += 1
                continue
            action, rid = upsert_display_title_record(
                bitable, ref, index, row, skip_existing=False
            )
            if action == "created":
                created += 1
            else:
                updated += 1
            ledger.mark(
                row.obj_token,
                OP_DISPLAY_TITLE_BITABLE,
                node_token=row.node_token,
                status="done",
                result_ref=rid,
            )
            if i % 20 == 0 or i == len(rows):
                print(
                    f"   {i}/{len(rows)} | created={created} updated={updated} skipped={skipped}",
                    flush=True,
                )
        except Exception as exc:
            failed += 1
            ledger.mark(
                row.obj_token,
                OP_DISPLAY_TITLE_BITABLE,
                node_token=row.node_token,
                status="failed",
                detail=str(exc),
            )
            print(f"❌ 写入失败 {row.original_title}: {exc}")
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "total": len(rows),
    }


def main() -> int:
    ensure_utf8_stdio()

    args = _parse_args()
    if args.list_folders:
        path = args.folders_file or config.SCAN_FOLDERS_FILE or default_scan_folders_path()
        worker = config.WORKER_ID or default_worker_id()
        print(format_folder_table(load_scan_folders(path), worker_id=worker))
        return 0

    use_llm = (not args.no_llm) and config.DISPLAY_TITLE_USE_LLM_PURPOSE
    parent_token = (args.parent_token or config.TARGET_PARENT_TOKEN or "").strip()
    agg_title = (
        args.aggregated_title
        or config.DISPLAY_TITLE_BITABLE_TITLE
        or "文档展示标题"
    )
    if not parent_token:
        print("❌ 需要 TARGET_PARENT_TOKEN 或 --parent-token")
        return 1

    job = ToolJob(
        title="展示标题 → 多维表格（主题-产品线-作者；不改 wiki）",
        ops=[OP_DISPLAY_TITLE_BITABLE],
        skip_config_key="DISPLAY_TITLE_SKIP_EXISTING",
        require_llm=use_llm,
        require_target=True,
        require_scan_source=False,
    )
    try:
        ctx = job.open(args, require_llm=use_llm, banner_extra=f"use_llm={use_llm}")
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    skip_existing = ctx.skip_existing
    tm = ctx.tm
    ledger = ctx.ledger
    unique_docs = ctx.docs

    try:
        if not unique_docs:
            print("✅ 无文档（TARGET 下尚无叶子，或请先跑分类复制）")
            return 0

        reader = FeishuDocumentReader(tm)
        read_map: Dict[str, Tuple[str, str]] = {}
        if args.skip_read:
            for d in unique_docs:
                obj = d.get("obj_token") or d["node_token"]
                read_map[obj] = (d.get("title") or "", "")
        else:
            print("\n📖 读取正文…")

            def _read(doc: Dict):
                title = doc.get("title") or ""
                obj = doc.get("obj_token") or doc["node_token"]
                try:
                    content = (
                        reader.get_raw_content(obj, wiki_node_token=doc["node_token"])
                        or ""
                    )
                except Exception as exc:
                    print(f"⚠️ 读取失败 {title}: {exc}")
                    content = ""
                return obj, title, content

            with ThreadPoolExecutor(max_workers=max(1, config.READ_WORKERS)) as pool:
                futs = [pool.submit(_read, d) for d in unique_docs]
                for fut in as_completed(futs):
                    obj, title, content = fut.result()
                    read_map[obj] = (title, content)

        wiki_meta = WikiMetaClient(tm)
        node_map: Dict[str, dict] = {}
        if not args.skip_date_api:
            print("\n🕒 读取节点时间…")
            for d in unique_docs:
                node = d["node_token"]
                try:
                    node_map[node] = wiki_meta.get_node(node)
                except Exception as exc:
                    print(f"⚠️ get_node 失败 {d.get('title')}: {exc}")

        registry_by_copy: Dict[str, Dict] = {}
        shared_db = (getattr(config, "SHARED_STATE_DB", None) or "").strip()
        if shared_db and config.METADATA_TABLE_FETCH_AUTHOR:
            try:
                shared = SharedCopyState(
                    db_path=shared_db,
                    worker_id=config.WORKER_ID or default_worker_id(),
                )
                registry_by_copy = shared.index_by_copied_node()
                print(f"🔗 共享库映射: {len(registry_by_copy)} 条（用于作者）")
            except Exception as exc:
                print(f"⚠️ 打开 SHARED_STATE_DB 失败（作者可能为空）: {exc}")

        llm = PurposeLLM() if use_llm else None
        print("\n🏷️ 生成展示标题（主题-产品线-作者）…")
        rows: List[DisplayTitleRow] = []
        for doc in unique_docs:
            obj = doc.get("obj_token") or doc["node_token"]
            node = doc["node_token"]
            title, content = read_map.get(obj, (doc.get("title") or "", ""))
            theme = llm.summarize(title, content) if llm else None

            author = ""
            if config.METADATA_TABLE_FETCH_AUTHOR:
                src = (registry_by_copy.get(node) or {}).get("source_node_token") or ""
                author_node = src or node
                try:
                    author = wiki_meta.get_author_display_name(author_node) or ""
                except Exception as exc:
                    print(f"⚠️ 作者解析失败 {title}: {exc}")

            row = build_display_title_row(
                title=title,
                content=content,
                obj_token=obj,
                node_token=node,
                source_path=doc.get("target_path")
                or doc.get("source_path")
                or "",
                source_folder=doc.get("source_folder_name") or "TARGET",
                theme=theme,
                author=author,
                wiki_node=node_map.get(node),
            )
            rows.append(row)
            print(f"  · {row.original_title}\n    → {row.display_title}")

        report = {
            "scope": ctx.scope,
            "dry_run": args.dry_run,
            "documents": [r.to_dict() for r in rows],
            "writes": {},
        }
        if args.dry_run:
            print("\n(dry-run，未写入)")
        else:
            name_checker = FolderNameChecker(tm)
            creator = FeishuNodeCreator(tm, config.SPACE_ID)
            bitable = FeishuBitableClient(tm)
            index = MetadataRecordIndex(
                ledger=ledger,
                op=OP_DISPLAY_TITLE_BITABLE,
                legacy_index_db=getattr(
                    config, "DISPLAY_TITLE_BITABLE_INDEX_DB", None
                ),
            )
            try:
                ref = ensure_display_title_bitable(
                    space_id=config.SPACE_ID,
                    target_parent_token=parent_token,
                    title=agg_title,
                    creator=creator,
                    name_checker=name_checker,
                    bitable=bitable,
                    wiki_meta=wiki_meta,
                    app_token_override=config.DISPLAY_TITLE_BITABLE_APP_TOKEN or None,
                )
                report["writes"]["aggregated"] = _write_rows(
                    bitable=bitable,
                    ref=ref,
                    index=index,
                    ledger=ledger,
                    rows=rows,
                    skip_existing=skip_existing,
                )
            finally:
                index.close()

        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        path = write_tool_report("display_title_bitable.json", report)
        print(f"\n📄 报告: {path}")
        print("✅ 完成")
        return 0
    finally:
        ctx.close()


if __name__ == "__main__":
    raise SystemExit(main())
