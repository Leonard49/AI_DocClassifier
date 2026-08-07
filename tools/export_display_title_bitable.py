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
    fallback_purpose,
    purpose_prompt,
    sanitize_purpose,
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
from state.shared_state import default_worker_id
from tools._tool_scope import (
    SCOPE_SCAN,
    SCOPE_TARGET,
    load_tool_documents,
    open_tool_ledger,
    resolve_scan_folders_from_args,
    resolve_scope,
    resolve_skip_existing,
)

from openai import OpenAI


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="展示标题 → 多维表格（默认只处理 TARGET 下已分类复制文档）"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--list-folders", action="store_true")
    p.add_argument(
        "--scope",
        choices=(SCOPE_TARGET, SCOPE_SCAN),
        default=None,
        help="target=TARGET（默认）；scan=源清单",
    )
    p.add_argument("--folder", action="append", default=None)
    p.add_argument("--all-assigned", action="store_true")
    p.add_argument("--all-enabled", action="store_true")
    p.add_argument("--folders-file", default=None)
    p.add_argument("--scan-token", default=None)
    p.add_argument("--scan-name", default=None)
    p.add_argument("--parent-token", default=None, help="多维表格挂载父节点，默认 TARGET")
    p.add_argument("--aggregated-title", default=None)
    p.add_argument("--max-documents", type=int, default=0)
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--skip-read", action="store_true")
    p.add_argument("--skip-date-api", action="store_true")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--no-skip-existing", action="store_true")
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
            {"role": "system", "content": "只输出一句简洁中文短语，概括文档作用。"},
            {"role": "user", "content": purpose_prompt(title, content)},
        ]
        fallback = fallback_purpose(title, content)
        with LLM_CONCURRENCY:
            for attempt in range(self.max_retries):
                LLM_RATE_LIMITER.wait()
                try:
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=48,
                    )
                    raw = (resp.choices[0].message.content or "").strip()
                    return sanitize_purpose(raw, fallback=fallback)
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
                        print(f"⚠️ 文章作用 LLM 失败 ({title}): {e} → {fallback}")
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
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    args = _parse_args()
    if args.list_folders:
        path = args.folders_file or config.SCAN_FOLDERS_FILE or default_scan_folders_path()
        worker = config.WORKER_ID or default_worker_id()
        print(format_folder_table(load_scan_folders(path), worker_id=worker))
        return 0

    scope = resolve_scope(args.scope)
    skip_existing = resolve_skip_existing(
        flag_skip=args.skip_existing,
        flag_no_skip=args.no_skip_existing,
        config_key="DISPLAY_TITLE_SKIP_EXISTING",
    )
    use_llm = (not args.no_llm) and config.DISPLAY_TITLE_USE_LLM_PURPOSE
    parent_token = (args.parent_token or config.TARGET_PARENT_TOKEN or "").strip()
    agg_title = (
        args.aggregated_title
        or config.DISPLAY_TITLE_BITABLE_TITLE
        or "文档展示标题"
    )

    try:
        config.validate(
            require_scan_source=False,
            require_llm=use_llm,
            require_target=True,
        )
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1
    if not parent_token:
        print("❌ 需要 TARGET_PARENT_TOKEN 或 --parent-token")
        return 1

    tm = TokenManager(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    folders = resolve_scan_folders_from_args(args) if scope == SCOPE_SCAN else None

    print("=" * 60)
    print("展示标题 → 多维表格（不改 wiki 原标题）")
    print(f"scope={scope} | skip_existing={skip_existing} | use_llm={use_llm}")
    print("=" * 60)

    unique_docs, label = load_tool_documents(
        tm,
        scope=scope,
        max_documents=args.max_documents,
        folders=folders,
    )
    print(f"📦 文档宇宙: {label} | 唯一叶子: {len(unique_docs)}")
    if not unique_docs:
        print("✅ 无文档（TARGET 下尚无叶子，或请先跑分类复制）")
        return 0

    ledger = open_tool_ledger()
    try:
        if skip_existing:
            before = len(unique_docs)
            unique_docs = ledger.filter_pending(
                unique_docs,
                [OP_DISPLAY_TITLE_BITABLE],
                require_all_ops=True,
            )
            n = before - len(unique_docs)
            if n:
                print(f"⏭️ ledger 已写跳过: {n}，剩余 {len(unique_docs)}")
        if not unique_docs:
            print("✅ 全部已处理")
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

        llm = PurposeLLM() if use_llm else None
        print("\n🏷️ 生成展示标题…")
        rows: List[DisplayTitleRow] = []
        for doc in unique_docs:
            obj = doc.get("obj_token") or doc["node_token"]
            node = doc["node_token"]
            title, content = read_map.get(obj, (doc.get("title") or "", ""))
            purpose = llm.summarize(title, content) if llm else None
            row = build_display_title_row(
                title=title,
                content=content,
                obj_token=obj,
                node_token=node,
                source_path=doc.get("target_path")
                or doc.get("source_path")
                or "",
                source_folder=doc.get("source_folder_name") or "TARGET",
                purpose=purpose,
                wiki_node=node_map.get(node),
            )
            rows.append(row)
            print(f"  · {row.original_title}\n    → {row.display_title}")

        report = {
            "scope": scope,
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
            index = MetadataRecordIndex(config.DISPLAY_TITLE_BITABLE_INDEX_DB)
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

        os.makedirs(config.LOG_DIR or "logs", exist_ok=True)
        path = os.path.join(config.LOG_DIR or "logs", "display_title_bitable.json")
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n📄 报告: {path}")
        print("✅ 完成")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
