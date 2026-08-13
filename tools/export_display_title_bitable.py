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
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from util.progress import iter_with_progress, map_parallel_with_progress, print_progress
from classify.display_title import (
    DisplayTitleRow,
    build_display_title_row,
)
from classify.display_llm import PurposeLLM
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


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="展示标题 → 多维表格（格式：主题-模组型号-作者；默认只处理 TARGET）"
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
        title="展示标题 → 多维表格（主题-模组型号-作者；不改 wiki）",
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
        progress_every = max(1, int(getattr(config, "PROGRESS_INTERVAL", 10) or 10))
        if args.skip_read:
            for d in unique_docs:
                obj = d.get("obj_token") or d["node_token"]
                read_map[obj] = (d.get("title") or "", "")
        else:

            def _read(doc: Dict):
                title = doc.get("title") or ""
                obj = doc.get("obj_token") or doc["node_token"]
                try:
                    content = (
                        reader.get_raw_content(obj, wiki_node_token=doc["node_token"])
                        or ""
                    )
                except Exception as exc:
                    print(f"⚠️ 读取失败 {title}: {exc}", flush=True)
                    content = ""
                return obj, title, content

            for obj, title, content in map_parallel_with_progress(
                unique_docs,
                _read,
                workers=max(1, config.READ_WORKERS),
                label="📖 读取正文",
                progress_interval=progress_every,
                is_ok=lambda r: bool((r[2] or "").strip()),
            ):
                read_map[obj] = (title, content)

        wiki_meta = WikiMetaClient(tm)
        node_map: Dict[str, dict] = {}
        if not args.skip_date_api:
            print(
                f"\n🕒 读取节点元数据（共 {len(unique_docs)} 篇）…",
                flush=True,
            )
            start_nodes = datetime.now()
            for i, d in enumerate(unique_docs, 1):
                node = d["node_token"]
                try:
                    node_map[node] = wiki_meta.get_node(node)
                except Exception as exc:
                    print(f"⚠️ get_node 失败 {d.get('title')}: {exc}", flush=True)
                if i == 1 or i == len(unique_docs) or i % progress_every == 0:
                    print_progress(
                        "🕒 节点元数据",
                        i,
                        len(unique_docs),
                        start=start_nodes,
                    )

        registry_by_copy: Dict[str, Dict] = {}
        shared_db = (getattr(config, "SHARED_STATE_DB", None) or "").strip()
        if shared_db:
            try:
                shared = SharedCopyState(
                    db_path=shared_db,
                    worker_id=config.WORKER_ID or default_worker_id(),
                )
                registry_by_copy = shared.index_by_copied_node()
                print(
                    f"🔗 共享库映射: {len(registry_by_copy)} 条（原标题/源路径/作者）",
                    flush=True,
                )
            except Exception as exc:
                print(f"⚠️ 打开 SHARED_STATE_DB 失败（作者可能为空）: {exc}", flush=True)

        llm = PurposeLLM() if use_llm else None
        rows: List[DisplayTitleRow] = []
        for doc in iter_with_progress(
            unique_docs,
            total=len(unique_docs),
            label="🏷️ 生成展示标题",
            progress_interval=progress_every,
        ):
            obj = doc.get("obj_token") or doc["node_token"]
            node = doc["node_token"]
            title, content = read_map.get(obj, (doc.get("title") or "", ""))
            reg = registry_by_copy.get(node) or {}
            src = (reg.get("source_node_token") or "").strip()
            source_title = (reg.get("title") or "").strip()
            scan_path = (reg.get("source_path") or doc.get("source_path") or "").strip()
            if not scan_path and src:
                try:
                    scan_path = wiki_meta.build_folder_path(src) or ""
                except Exception:
                    scan_path = ""
            guess = llm.summarize(source_title or title, content) if llm else None
            theme = guess.theme if guess else None
            llm_module = guess.module if guess else ""

            author = ""
            author_node = src or node
            if config.METADATA_TABLE_FETCH_AUTHOR:
                try:
                    author = wiki_meta.get_author_display_name(
                        author_node, source_path=scan_path
                    ) or ""
                except Exception as exc:
                    print(f"⚠️ 作者解析失败 {title}: {exc}", flush=True)
            if not author:
                from classify.display_title import author_from_source_path

                author = author_from_source_path(scan_path)

            row = build_display_title_row(
                title=title,
                content=content,
                obj_token=obj,
                node_token=node,
                source_path=scan_path,
                source_folder=doc.get("source_folder_name") or "TARGET",
                theme=theme,
                author=author,
                wiki_node=node_map.get(node),
                source_title=source_title,
                target_path=(doc.get("target_path") or "").strip(),
                llm_module=llm_module,
            )
            rows.append(row)
            print(f"  · {row.original_title}\n    → {row.display_title}", flush=True)

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
