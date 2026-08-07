# -*- coding: utf-8 -*-
"""Shared document scope for side tools: TARGET corpus by default."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import config
from feishu.token_manager import TokenManager
from feishu.wiki_scanner import SimpleWikiScanner
from state.operation_ledger import OperationLedger, default_tool_ops_db_path
from state.scan_folders import (
    ScanFolder,
    default_scan_folders_path,
    filter_folders,
    load_scan_folders,
)
from state.shared_state import default_worker_id
from state.target_docs import dedupe_by_obj_token, list_target_leaf_docs

SCOPE_TARGET = "target"
SCOPE_SCAN = "scan"
VALID_SCOPES = (SCOPE_TARGET, SCOPE_SCAN)


def resolve_scope(cli_scope: Optional[str]) -> str:
    raw = (cli_scope or getattr(config, "TOOL_DOC_SCOPE", None) or SCOPE_TARGET)
    scope = str(raw).strip().lower()
    if scope not in VALID_SCOPES:
        raise SystemExit(f"❌ 无效 scope={scope!r}，应为 {VALID_SCOPES}")
    return scope


def open_tool_ledger(db_path: Optional[str] = None) -> OperationLedger:
    path = (
        db_path
        or getattr(config, "TOOL_OPS_DB", None)
        or default_tool_ops_db_path()
    )
    return OperationLedger(path)


def resolve_skip_existing(
    *,
    flag_skip: bool,
    flag_no_skip: bool,
    config_key: str,
) -> bool:
    if flag_no_skip:
        return False
    if flag_skip:
        return True
    return bool(getattr(config, config_key, False))


def load_tool_documents(
    tm: TokenManager,
    *,
    scope: str,
    max_documents: int = 0,
    # scan-scope options
    folders: Optional[Sequence[ScanFolder]] = None,
) -> Tuple[List[Dict], str]:
    """
    Returns (unique_docs, scope_label).

    target: leaf docx under TARGET_PARENT_TOKEN
    scan: leaf docx under provided scan folders (legacy / optional)
    """
    if scope == SCOPE_TARGET:
        parent = (config.TARGET_PARENT_TOKEN or "").strip()
        if not parent:
            raise SystemExit(
                "❌ scope=target 需要 TARGET_PARENT_TOKEN（工具只处理已分类复制到目标目录的文档）"
            )
        docs = list_target_leaf_docs(
            tm,
            space_id=config.SPACE_ID,
            target_root_token=parent,
            max_documents=max_documents,
        )
        unique = dedupe_by_obj_token(docs)
        label = f"target:{parent[:16]}…"
        return unique, label

    if not folders:
        raise SystemExit("❌ scope=scan 需要提供扫描文件夹列表")
    scanner = SimpleWikiScanner(tm, enable_db_cache=False)
    all_docs: List[Dict] = []
    for folder in folders:
        if max_documents > 0 and len(all_docs) >= max_documents:
            break
        remaining = (
            max_documents - len(all_docs) if max_documents > 0 else 0
        )
        print(f"\n📂 扫描源: {folder.name} ({folder.token})", flush=True)
        docs = scanner.scan_space(
            space_id=config.SPACE_ID,
            root_token=folder.token,
            use_cache=False,
            max_documents=remaining if remaining > 0 else 0,
        )
        for d in docs:
            item = dict(d)
            item["source_folder_id"] = folder.id
            item["source_folder_name"] = folder.name
            item["source_folder_token"] = folder.token
            all_docs.append(item)
            if max_documents > 0 and len(all_docs) >= max_documents:
                break
        print(f"   叶子文档: {len(docs)} | 累计: {len(all_docs)}", flush=True)
    return dedupe_by_obj_token(all_docs), f"scan:{len(folders)}_folders"


def resolve_scan_folders_from_args(args) -> List[ScanFolder]:
    """Reuse export-tool folder CLI conventions when scope=scan."""
    if getattr(args, "scan_token", None):
        name = (getattr(args, "scan_name", None) or "").strip() or (
            f"scan-{(args.scan_token or '')[:8]}"
        )
        return [
            ScanFolder(
                id="cli-scan-token",
                name=name,
                token=args.scan_token.strip(),
                assignee="",
                enabled=True,
                priority=1,
            )
        ]

    path = (
        getattr(args, "folders_file", None)
        or config.SCAN_FOLDERS_FILE
        or default_scan_folders_path()
    )
    worker = config.WORKER_ID or default_worker_id()
    registry = load_scan_folders(path)

    if getattr(args, "folder", None):
        return filter_folders(registry, ids=args.folder, enabled_only=False)
    if getattr(args, "all_enabled", False):
        return filter_folders(registry, enabled_only=True)
    if getattr(args, "all_assigned", False):
        assigned = filter_folders(
            registry, worker_id=worker, assigned_only=True, enabled_only=True
        )
        if not assigned:
            raise SystemExit(
                f"❌ 没有分配给 WORKER_ID={worker} 的文件夹"
            )
        return assigned

    assigned = filter_folders(
        registry, worker_id=worker, assigned_only=True, enabled_only=True
    )
    if assigned:
        return assigned
    if config.SCAN_ROOT_TOKEN:
        return [
            ScanFolder(
                id="env-scan-root",
                name="SCAN_ROOT_TOKEN",
                token=config.SCAN_ROOT_TOKEN,
                assignee=worker or "",
                enabled=True,
                priority=1,
            )
        ]
    raise SystemExit(
        "❌ scope=scan 请指定: --folder / --all-assigned / --all-enabled / --scan-token"
    )


__all__ = [
    "SCOPE_TARGET",
    "SCOPE_SCAN",
    "VALID_SCOPES",
    "resolve_scope",
    "open_tool_ledger",
    "resolve_skip_existing",
    "load_tool_documents",
    "resolve_scan_folders_from_args",
]
