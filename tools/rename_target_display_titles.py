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
from datetime import datetime
from typing import Dict, List, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from classify.display_title import (
    DisplayTitleRow,
    build_display_title_row,
    title_has_leading_date_noise,
)
from feishu.read_doc import FeishuDocumentReader
from feishu.wiki_meta import WikiMetaClient
from state.operation_ledger import OP_DISPLAY_TITLE_RENAME
from state.shared_state import SharedCopyState, default_worker_id
from tools._tool_scope import SCOPE_TARGET
from classify.display_llm import PurposeLLM
from tools.runner import ToolJob, add_scope_args, ensure_utf8_stdio, write_tool_report
from util.progress import iter_with_progress, map_parallel_with_progress, print_progress


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
        title="展示标题 → 重命名 TARGET（主题-模组型号-作者；不改源）",
        ops=[OP_DISPLAY_TITLE_RENAME],
        skip_config_key="DISPLAY_TITLE_RENAME_SKIP_EXISTING",
        require_llm=use_llm,
        require_target=True,
        require_scan_source=False,
        keep_date_prefixed_titles=True,
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
        progress_every = max(1, int(getattr(config, "PROGRESS_INTERVAL", 10) or 10))
        if args.skip_read:
            for d in docs:
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
                docs,
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
            print(f"\n🕒 读取节点元数据（共 {len(docs)} 篇）…", flush=True)
            start_nodes = datetime.now()
            for i, d in enumerate(docs, 1):
                node = d["node_token"]
                try:
                    node_map[node] = wiki_meta.get_node(node)
                except Exception as exc:
                    print(f"⚠️ get_node 失败 {d.get('title')}: {exc}", flush=True)
                if i == 1 or i == len(docs) or i % progress_every == 0:
                    print_progress(
                        "🕒 节点元数据", i, len(docs), start=start_nodes
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
            docs,
            total=len(docs),
            label="🏷️ 生成展示标题",
            progress_interval=progress_every,
        ):
            obj = doc.get("obj_token") or doc["node_token"]
            node = doc["node_token"]
            title, content = read_map.get(obj, (doc.get("title") or "", ""))
            reg = registry_by_copy.get(node) or {}
            src = (reg.get("source_node_token") or "").strip()
            source_title = (reg.get("title") or "").strip()
            scan_path = (reg.get("source_path") or "").strip()
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
                    if title_has_leading_date_noise(row.original_title):
                        print(
                            f"  [{i}/{len(rows)}] ↺ 标题仍像日期开头，重新命名: "
                            f"{row.original_title}",
                            flush=True,
                        )
                    else:
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
