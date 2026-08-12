#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate display titles and RENAME TARGET wiki node titles.

Only touches documents under TARGET_PARENT_TOKEN (classified copies).
Never renames SCAN / source wiki nodes.

Usage:
  python -m tools.rename_target_display_titles --dry-run --max-documents 20
  python -m tools.rename_target_display_titles
  python -m tools.rename_target_display_titles --skip-existing
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from classify.display_title import DisplayTitleRow, build_display_title_row
from feishu.read_doc import FeishuDocumentReader
from feishu.token_manager import TokenManager
from feishu.wiki_meta import WikiMetaClient
from state.operation_ledger import OP_DISPLAY_TITLE_RENAME
from state.shared_state import SharedCopyState, default_worker_id
from tools._tool_scope import SCOPE_TARGET
from tools.export_display_title_bitable import PurposeLLM
from tools.runner import ToolJob, add_scope_args, ensure_utf8_stdio, write_tool_report


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="按展示标题格式重命名 TARGET 副本标题（不改 SCAN 源文档）"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-documents", type=int, default=0)
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--skip-read", action="store_true")
    p.add_argument("--skip-date-api", action="store_true")
    add_scope_args(p)
    return p.parse_args()


def main() -> int:
    ensure_utf8_stdio()
    args = _parse_args()

    # Hard-enforce TARGET: renaming SCAN would mutate source knowledge base.
    if getattr(args, "scope", None) and str(args.scope).strip().lower() == "scan":
        print("❌ 本工具禁止 --scope scan（会改源知识库标题）。请只用默认 TARGET。")
        return 1
    args.scope = SCOPE_TARGET

    use_llm = (not args.no_llm) and config.DISPLAY_TITLE_USE_LLM_PURPOSE
    space_id = (config.SPACE_ID or "").strip()
    if not space_id:
        print("❌ 需要 SPACE_ID")
        return 1

    job = ToolJob(
        title="展示标题 → 重命名 TARGET（主题-产品线-作者；不改源）",
        ops=[OP_DISPLAY_TITLE_RENAME],
        skip_config_key="DISPLAY_TITLE_RENAME_SKIP_EXISTING",
        require_llm=use_llm,
        require_target=True,
        require_scan_source=False,
    )
    try:
        ctx = job.open(
            args,
            require_llm=use_llm,
            banner_extra=f"use_llm={use_llm} | rename TARGET only",
        )
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    skip_existing = ctx.skip_existing
    tm = ctx.tm
    ledger = ctx.ledger
    docs = ctx.docs

    try:
        if not docs:
            print("✅ 无文档（TARGET 下尚无叶子，或请先跑分类复制）")
            return 0

        reader = FeishuDocumentReader(tm)
        read_map: Dict[str, Tuple[str, str]] = {}
        if args.skip_read:
            for d in docs:
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
                futs = [pool.submit(_read, d) for d in docs]
                for fut in as_completed(futs):
                    obj, title, content = fut.result()
                    read_map[obj] = (title, content)

        wiki_meta = WikiMetaClient(tm)
        node_map: Dict[str, dict] = {}
        if not args.skip_date_api:
            print("\n🕒 读取节点时间…")
            for d in docs:
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
        for doc in docs:
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

        counts = {
            "renamed": 0,
            "skipped_same": 0,
            "skipped_ledger": 0,
            "failed": 0,
            "total": len(rows),
        }
        report = {
            "scope": ctx.scope,
            "dry_run": args.dry_run,
            "documents": [r.to_dict() for r in rows],
            "counts": counts,
        }

        if args.dry_run:
            print("\n(dry-run，未改 wiki 标题)")
        else:
            print("\n✏️ 重命名 TARGET 节点标题…")
            for i, row in enumerate(rows, 1):
                entity = row.obj_token or row.node_token
                if skip_existing and ledger.is_done(
                    entity, OP_DISPLAY_TITLE_RENAME, node_token=row.node_token
                ):
                    counts["skipped_ledger"] += 1
                    continue
                if (row.original_title or "").strip() == (row.display_title or "").strip():
                    counts["skipped_same"] += 1
                    ledger.mark(
                        entity,
                        OP_DISPLAY_TITLE_RENAME,
                        node_token=row.node_token,
                        status="skipped",
                        detail="already display title",
                    )
                    continue
                try:
                    wiki_meta.update_title(
                        space_id, row.node_token, row.display_title
                    )
                    counts["renamed"] += 1
                    ledger.mark(
                        entity,
                        OP_DISPLAY_TITLE_RENAME,
                        node_token=row.node_token,
                        status="done",
                        detail=row.display_title,
                    )
                    print(
                        f"  [{i}/{len(rows)}] ✅ {row.original_title} → {row.display_title}"
                    )
                except Exception as exc:
                    counts["failed"] += 1
                    ledger.mark(
                        entity,
                        OP_DISPLAY_TITLE_RENAME,
                        node_token=row.node_token,
                        status="failed",
                        detail=str(exc),
                    )
                    print(f"  [{i}/{len(rows)}] ❌ {row.original_title}: {exc}")

            print(
                f"\n✅ 完成: renamed={counts['renamed']} "
                f"same={counts['skipped_same']} "
                f"ledger_skip={counts['skipped_ledger']} "
                f"failed={counts['failed']}"
            )

        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        path = write_tool_report("display_title_rename.json", report)
        print(f"📄 报告: {path}")
        return 1 if counts["failed"] else 0
    finally:
        ctx.close()


if __name__ == "__main__":
    raise SystemExit(main())
