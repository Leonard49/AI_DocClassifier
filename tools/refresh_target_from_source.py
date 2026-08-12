#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Refresh TARGET copies from SCAN sources (one-way, on demand).

Strategy (Feishu wiki has no reliable node-delete OpenAPI):
  1. Find pairs in SHARED_STATE_DB (source_node → copied_node)
  2. If source obj_edit_time is newer than last refresh (default), proceed
  3. Re-copy source into the same TARGET parent folder
  4. Restore the previous TARGET title on the new copy (keeps renamed titles)
  5. Move the old TARGET node into TARGET/_已废弃_源刷新
  6. Update SHARED_STATE copied_node_token
  7. Re-run enrichment on the new copy (metadata table / attachment separator)

Never modifies SCAN source titles/content beyond what was already there.

Usage:
  python -m tools.refresh_target_from_source --dry-run --limit 20
  python -m tools.refresh_target_from_source --only-changed
  python -m tools.refresh_target_from_source --force
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from enrichment.hooks import enrich_after_copy, format_results
from feishu.copy_doc import FeishuCopyError, FeishuWikiCopier
from feishu.create_feishu_node import FeishuNodeCreator
from feishu.read_doc import FeishuDocumentReader
from feishu.title_check import FolderNameChecker
from feishu.token_manager import TokenManager
from feishu.wiki_meta import WikiMetaClient
from feishu.wiki_move import FeishuWikiMover
from state.operation_ledger import OP_TARGET_CONTENT_REFRESH, OperationLedger
from state.shared_state import SharedCopyState, default_worker_id
from state.tag_folder_path import ensure_child_folder
from tools.runner import ensure_utf8_stdio, maybe_setup_run_log, write_tool_report


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="源 → TARGET 单向刷新正文（保留整理标题；旧副本移入废弃夹）"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="最多处理条数（0=不限）")
    p.add_argument(
        "--only-changed",
        action="store_true",
        help="仅当源更新时间新于上次刷新时处理（与配置默认一致时可省略）",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="忽略变更检测，对共享库全部 copied 记录刷新",
    )
    p.add_argument(
        "--no-enrich",
        action="store_true",
        help="刷新后不自动贴元数据表/附件分隔",
    )
    p.add_argument(
        "--obsolete-folder",
        default=None,
        help="旧副本移入的 TARGET 子目录名",
    )
    return p.parse_args()


def _node_edit_ts(node: Dict[str, Any]) -> int:
    for key in ("obj_edit_time", "node_edit_time", "obj_create_time"):
        raw = node.get(key)
        if raw is None or raw == "":
            continue
        try:
            ts = int(str(raw).strip())
        except ValueError:
            continue
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    return 0


def _open_shared() -> SharedCopyState:
    db = (getattr(config, "SHARED_STATE_DB", None) or "").strip()
    if not db:
        raise SystemExit("❌ 需要 SHARED_STATE_DB（含 source→copied 映射）")
    return SharedCopyState(
        db_path=db,
        worker_id=config.WORKER_ID or default_worker_id(),
    )


def _open_ledger() -> OperationLedger:
    from state.operation_ledger import default_tool_ops_db_path

    path = (
        getattr(config, "TOOL_OPS_DB", None)
        or default_tool_ops_db_path()
    )
    return OperationLedger(path)


def _should_refresh(
    *,
    force: bool,
    only_changed: bool,
    ledger: OperationLedger,
    obj_token: str,
    copied_node: str,
    source_edit_ts: int,
    copy_edit_ts: int = 0,
) -> Tuple[bool, str]:
    if force:
        return True, "force"
    if not only_changed:
        return True, "all"
    if source_edit_ts <= 0:
        return True, "no_source_edit_ts"
    prev = ledger.get_result_ref(
        obj_token, OP_TARGET_CONTENT_REFRESH, node_token=copied_node
    )
    last = 0
    if prev:
        try:
            last = int(str(prev).strip())
        except ValueError:
            last = 0
    # No prior refresh ledger → compare source vs current TARGET copy edit time
    if last <= 0 and copy_edit_ts > 0:
        last = copy_edit_ts
    if last <= 0:
        return True, "no_baseline_ts"
    if source_edit_ts <= last:
        return False, f"unchanged(src={source_edit_ts}<=last={last})"
    return True, f"changed(src={source_edit_ts}>last={last})"


def main() -> int:
    ensure_utf8_stdio()
    maybe_setup_run_log()
    args = _parse_args()

    space_id = (config.SPACE_ID or "").strip()
    target_root = (config.TARGET_PARENT_TOKEN or "").strip()
    if not space_id or not target_root:
        print("❌ 需要 SPACE_ID 与 TARGET_PARENT_TOKEN")
        return 1

    # --force → all; else prefer change detection (config or --only-changed)
    only_changed = (not args.force) and (
        bool(args.only_changed) or bool(config.REFRESH_TARGET_SKIP_UNCHANGED)
    )
    if args.force:
        only_changed = False

    obsolete_name = (
        (args.obsolete_folder or config.REFRESH_TARGET_OBSOLETE_FOLDER or "")
        .strip()
        or "_已废弃_源刷新"
    )

    print("=" * 60)
    print("源 → TARGET 内容刷新（单向）")
    print(
        f"dry_run={args.dry_run} | only_changed={only_changed} | "
        f"force={args.force} | enrich={not args.no_enrich}"
    )
    print(f"obsolete_folder={obsolete_name}")
    print("=" * 60)

    shared = _open_shared()
    ledger = _open_ledger()
    rows = shared.list_copied(require_copied_node=True)
    if args.limit and args.limit > 0:
        rows = rows[: int(args.limit)]
    print(f"📦 共享库 copied 记录: {len(rows)}")

    if not rows:
        print("✅ 无待刷新项")
        return 0

    tm = TokenManager(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    wiki_meta = WikiMetaClient(tm)
    name_checker = FolderNameChecker(tm)
    creator = FeishuNodeCreator(tm, space_id)
    mover = FeishuWikiMover(tm, space_id)
    reader = FeishuDocumentReader(tm)

    obsolete_token = None
    if not args.dry_run:
        obsolete_token = ensure_child_folder(
            creator, name_checker, space_id, target_root, obsolete_name
        )
        if not obsolete_token:
            print(f"❌ 无法创建/定位废弃目录: {obsolete_name}")
            return 1
        print(f"📁 废弃目录: {obsolete_name} ({obsolete_token})")

    counts = {
        "refreshed": 0,
        "skipped": 0,
        "failed": 0,
        "dry": 0,
    }
    details: List[Dict[str, Any]] = []

    try:
        for i, row in enumerate(rows, 1):
            obj = (row.get("obj_token") or "").strip()
            src_node = (row.get("source_node_token") or "").strip()
            old_copy = (row.get("copied_node_token") or "").strip()
            title_hint = row.get("title") or ""
            print(f"\n[{i}/{len(rows)}] {title_hint or obj}")
            if not obj or not src_node or not old_copy:
                print("  ⚠️ 映射字段不完整，跳过")
                counts["skipped"] += 1
                continue

            try:
                src_info = wiki_meta.get_node(src_node)
                old_info = wiki_meta.get_node(old_copy)
            except Exception as exc:
                print(f"  ❌ get_node 失败: {exc}")
                counts["failed"] += 1
                details.append(
                    {
                        "obj_token": obj,
                        "status": "failed",
                        "error": f"get_node: {exc}",
                    }
                )
                continue

            src_edit = _node_edit_ts(src_info)
            copy_edit = _node_edit_ts(old_info)
            parent = (old_info.get("parent_node_token") or "").strip() or target_root
            keep_title = (old_info.get("title") or title_hint or "未命名").strip()

            ok, reason = _should_refresh(
                force=bool(args.force),
                only_changed=only_changed,
                ledger=ledger,
                obj_token=obj,
                copied_node=old_copy,
                source_edit_ts=src_edit,
                copy_edit_ts=copy_edit,
            )
            if not ok:
                print(f"  ⏭️ 跳过: {reason}")
                counts["skipped"] += 1
                details.append(
                    {
                        "obj_token": obj,
                        "status": "skipped",
                        "reason": reason,
                        "keep_title": keep_title,
                    }
                )
                continue

            print(
                f"  源={src_node} edit={src_edit} | "
                f"旧副本={old_copy} | 父={parent} | 保留标题={keep_title} | {reason}"
            )

            if args.dry_run:
                counts["dry"] += 1
                details.append(
                    {
                        "obj_token": obj,
                        "status": "dry_run",
                        "source_node": src_node,
                        "old_copied_node": old_copy,
                        "parent": parent,
                        "keep_title": keep_title,
                        "source_edit_ts": src_edit,
                        "reason": reason,
                    }
                )
                continue

            try:
                # 1) copy source into same parent with a unique temp title
                temp_title = name_checker.resolve_unique_child_title(
                    space_id, parent, f"{keep_title}.刷新中"
                )
                copier = FeishuWikiCopier(
                    token_manager=tm,
                    node_token=src_node,
                    target_folder_token=parent,
                    new_file_name=temp_title,
                    source_space_id=space_id,
                    target_space_id=space_id,
                )
                new_copy = copier.copy_document_by_node_token()
                if not new_copy:
                    raise RuntimeError("copy returned empty node_token")

                # 2) restore curated title on the new copy
                final_title = name_checker.resolve_unique_child_title(
                    space_id, parent, keep_title
                )
                # If keep_title still taken by old node, rename old first
                if final_title != keep_title:
                    # old still occupies keep_title — move old aside first
                    pass
                try:
                    wiki_meta.update_title(space_id, old_copy, f"{keep_title}.旧版")
                    name_checker.invalidate_children(space_id, parent)
                    wiki_meta.update_title(space_id, new_copy, keep_title)
                    final_title = keep_title
                except Exception:
                    wiki_meta.update_title(space_id, new_copy, final_title)

                # 3) retire old copy into obsolete folder
                assert obsolete_token
                mover.move_node(old_copy, obsolete_token)

                # 4) update shared registry
                shared.mark_copied(
                    obj,
                    title=final_title,
                    source_node_token=src_node,
                    copied_node_token=new_copy,
                    target_parent_token=target_root,
                    target_folder_token=parent,
                    scan_root=row.get("scan_root") or "",
                    source_path=row.get("source_path") or "",
                )

                # 5) enrichment on new copy
                enrich_msg = ""
                if not args.no_enrich and (
                    config.ENABLE_METADATA_TABLE or config.ENABLE_ATTACHMENT_SEPARATOR
                ):
                    content = ""
                    try:
                        new_info = wiki_meta.get_node(new_copy)
                        new_obj = new_info.get("obj_token") or ""
                        if new_obj:
                            content = (
                                reader.get_raw_content(
                                    new_obj, wiki_node_token=new_copy
                                )
                                or ""
                            )
                    except Exception as exc:
                        print(f"  ⚠️ 读取新副本正文失败: {exc}")
                    author = ""
                    if config.METADATA_TABLE_FETCH_AUTHOR:
                        try:
                            author = (
                                wiki_meta.get_author_display_name(src_node) or ""
                            )
                        except Exception:
                            pass
                    results = enrich_after_copy(
                        tm,
                        target_node_token=new_copy,
                        title=final_title,
                        obj_token=obj,
                        source_node_token=src_node,
                        source_path=row.get("source_path") or "",
                        content=content,
                        author=author,
                        enable_metadata_table=config.ENABLE_METADATA_TABLE,
                        enable_attachment_separator=config.ENABLE_ATTACHMENT_SEPARATOR,
                    )
                    enrich_msg = format_results(results)
                    print(f"  ✨ enrichment: {enrich_msg}")

                ledger.mark(
                    obj,
                    OP_TARGET_CONTENT_REFRESH,
                    node_token=new_copy,
                    status="done",
                    result_ref=str(src_edit or int(datetime.now().timestamp())),
                    detail=f"old={old_copy}; enrich={enrich_msg}",
                )
                # Also mark old node as superseded so skip filters don't confuse
                ledger.mark(
                    obj,
                    OP_TARGET_CONTENT_REFRESH,
                    node_token=old_copy,
                    status="skipped",
                    detail="retired",
                )

                counts["refreshed"] += 1
                print(f"  ✅ 已刷新 → {new_copy} | 标题={final_title}")
                details.append(
                    {
                        "obj_token": obj,
                        "status": "refreshed",
                        "old_copied_node": old_copy,
                        "new_copied_node": new_copy,
                        "keep_title": final_title,
                        "source_edit_ts": src_edit,
                        "enrich": enrich_msg,
                    }
                )
            except (FeishuCopyError, Exception) as exc:
                counts["failed"] += 1
                print(f"  ❌ 刷新失败: {exc}")
                ledger.mark(
                    obj,
                    OP_TARGET_CONTENT_REFRESH,
                    node_token=old_copy,
                    status="failed",
                    detail=str(exc),
                )
                details.append(
                    {
                        "obj_token": obj,
                        "status": "failed",
                        "error": str(exc),
                        "old_copied_node": old_copy,
                    }
                )

        print(
            f"\n✅ 结束: refreshed={counts['refreshed']} dry={counts['dry']} "
            f"skipped={counts['skipped']} failed={counts['failed']}"
        )
        path = write_tool_report(
            "refresh_target_from_source.json",
            {
                "generated_at": datetime.now().isoformat(),
                "dry_run": args.dry_run,
                "only_changed": only_changed,
                "force": bool(args.force),
                "obsolete_folder": obsolete_name,
                "counts": counts,
                "items": details,
            },
        )
        print(f"📄 报告: {path}")
        return 1 if counts["failed"] else 0
    finally:
        try:
            ledger.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
