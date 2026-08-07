# -*- coding: utf-8 -*-
"""Lightweight ToolJob bootstrap for side tools (TARGET scope + ledger)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import config
from feishu.token_manager import TokenManager
from state.operation_ledger import OperationLedger
from state.scan_folders import ScanFolder
from tools._tool_scope import (
    SCOPE_SCAN,
    SCOPE_TARGET,
    load_tool_documents,
    open_tool_ledger,
    resolve_scan_folders_from_args,
    resolve_scope,
    resolve_skip_existing,
)


def ensure_utf8_stdio() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope",
        choices=(SCOPE_TARGET, SCOPE_SCAN),
        default=None,
        help="target=只处理 TARGET 下文档（默认）；scan=扫源清单",
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument("--folder", action="append", default=None, metavar="ID")
    parser.add_argument("--all-assigned", action="store_true")
    parser.add_argument("--all-enabled", action="store_true")
    parser.add_argument("--folders-file", default=None)
    parser.add_argument("--scan-token", default=None)
    parser.add_argument("--scan-name", default=None)


def write_tool_report(name: str, payload: Dict[str, Any]) -> str:
    log_dir = getattr(config, "LOG_DIR", None) or "logs"
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, name if name.endswith(".json") else f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


@dataclass
class ToolJobContext:
    args: argparse.Namespace
    scope: str
    skip_existing: bool
    tm: TokenManager
    docs: List[Dict]
    scope_label: str
    ledger: OperationLedger
    ledger_skipped: int = 0
    folders: Optional[List[ScanFolder]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def close(self) -> None:
        try:
            self.ledger.close()
        except Exception:
            pass


class ToolJob:
    """
    Shared bootstrap: validate config → resolve scope → load TARGET/scan docs →
    open ledger → optional skip filter → write logs/.
    """

    def __init__(
        self,
        *,
        title: str,
        ops: Sequence[str],
        skip_config_key: str,
        require_llm: bool = False,
        require_target: bool = True,
        require_scan_source: bool = False,
        max_documents_attr: str = "max_documents",
    ):
        self.title = title
        self.ops = list(ops)
        self.skip_config_key = skip_config_key
        self.require_llm = require_llm
        self.require_target = require_target
        self.require_scan_source = require_scan_source
        self.max_documents_attr = max_documents_attr

    def validate(self, *, require_llm: Optional[bool] = None) -> None:
        config.validate(
            require_scan_source=self.require_scan_source,
            require_llm=self.require_llm if require_llm is None else require_llm,
            require_target=self.require_target,
        )

    def open(
        self,
        args: argparse.Namespace,
        *,
        require_llm: Optional[bool] = None,
        banner_extra: str = "",
    ) -> ToolJobContext:
        self.validate(require_llm=require_llm)
        scope = resolve_scope(getattr(args, "scope", None))
        skip_existing = resolve_skip_existing(
            flag_skip=bool(getattr(args, "skip_existing", False)),
            flag_no_skip=bool(getattr(args, "no_skip_existing", False)),
            config_key=self.skip_config_key,
        )
        folders = None
        if scope == SCOPE_SCAN:
            folders = resolve_scan_folders_from_args(args)

        max_docs = int(getattr(args, self.max_documents_attr, 0) or 0)
        if max_docs < 0:
            max_docs = 0
        # enrich uses --limit
        if max_docs == 0 and hasattr(args, "limit"):
            max_docs = int(getattr(args, "limit") or 0)

        tm = TokenManager(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
        print("=" * 60)
        print(self.title)
        line = f"scope={scope} | skip_existing={skip_existing}"
        if banner_extra:
            line = f"{line} | {banner_extra}"
        print(line)
        print("=" * 60)

        docs, label = load_tool_documents(
            tm, scope=scope, max_documents=max_docs, folders=folders
        )
        print(f"📦 文档宇宙: {label} | 唯一叶子: {len(docs)}")

        ledger = open_tool_ledger()
        skipped = 0
        if skip_existing and self.ops and docs:
            before = len(docs)
            docs = ledger.filter_pending(docs, self.ops, require_all_ops=True)
            skipped = before - len(docs)
            if skipped:
                print(f"⏭️ ledger 已写跳过: {skipped}，剩余 {len(docs)}")

        return ToolJobContext(
            args=args,
            scope=scope,
            skip_existing=skip_existing,
            tm=tm,
            docs=docs,
            scope_label=label,
            ledger=ledger,
            ledger_skipped=skipped,
            folders=folders,
        )

    def finish_report(
        self,
        ctx: ToolJobContext,
        report_name: str,
        payload: Dict[str, Any],
    ) -> str:
        body = {
            "generated_at": datetime.now().isoformat(),
            "scope": ctx.scope,
            "scope_label": ctx.scope_label,
            "ledger_skipped": ctx.ledger_skipped,
            **payload,
        }
        path = write_tool_report(report_name, body)
        print(f"📝 报告: {path}")
        return path


__all__ = [
    "ToolJob",
    "ToolJobContext",
    "add_scope_args",
    "ensure_utf8_stdio",
    "write_tool_report",
]
