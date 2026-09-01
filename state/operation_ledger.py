# -*- coding: utf-8 -*-
"""
Unified operation ledger for side tools (not core classify/copy).

Each (entity_key, op, node_token) is independent so e.g. metadata_table done
does not block attachment_separator.

Bitable record_ids use node_token = "bitable:{app_token}/{table_id}" and
result_ref; skip-existing for a wiki doc uses the wiki node_token.
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Iterable, List, Optional, Sequence, Set

# Canonical op ids
OP_METADATA_TABLE = "metadata_table"
OP_ATTACHMENT_SEPARATOR = "attachment_separator"
OP_METADATA_BITABLE = "metadata_bitable"
OP_DISPLAY_TITLE_BITABLE = "display_title_bitable"
OP_DISPLAY_TITLE_RENAME = "display_title_rename"
OP_TARGET_CONTENT_REFRESH = "target_content_refresh"
OP_REPAIR_EXTRACTED_IMAGES = "repair_extracted_images"

KNOWN_OPS = (
    OP_METADATA_TABLE,
    OP_ATTACHMENT_SEPARATOR,
    OP_METADATA_BITABLE,
    OP_DISPLAY_TITLE_BITABLE,
    OP_DISPLAY_TITLE_RENAME,
    OP_TARGET_CONTENT_REFRESH,
    OP_REPAIR_EXTRACTED_IMAGES,
)


def bitable_scope_key(app_token: str, table_id: str) -> str:
    return f"bitable:{(app_token or '').strip()}/{(table_id or '').strip()}"


class OperationLedger:
    """SQLite ledger: skip-existing is per (entity_key, op, node_token)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(db_path, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=DELETE")
        self._ensure_schema()
        self._conn.commit()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
                entity_key TEXT NOT NULL,
                op TEXT NOT NULL,
                node_token TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                result_ref TEXT,
                detail TEXT,
                updated_at REAL,
                PRIMARY KEY (entity_key, op, node_token)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ops_op_status ON operations(op, status)"
        )

    def is_done(
        self,
        entity_key: str,
        op: str,
        *,
        node_token: str = "",
    ) -> bool:
        if not entity_key or not op:
            return False
        row = self._conn.execute(
            """
            SELECT 1 FROM operations
            WHERE entity_key = ? AND op = ? AND node_token = ?
              AND status IN ('done', 'skipped')
            """,
            (entity_key, op, node_token or ""),
        ).fetchone()
        return row is not None

    def has_all_ops(
        self,
        entity_key: str,
        ops: Iterable[str],
        *,
        node_token: str = "",
    ) -> bool:
        ids = [o for o in ops if o]
        if not ids or not entity_key:
            return False
        for op in ids:
            if not self.is_done(entity_key, op, node_token=node_token):
                return False
        return True

    def mark(
        self,
        entity_key: str,
        op: str,
        *,
        node_token: str = "",
        status: str = "done",
        result_ref: str = "",
        detail: str = "",
    ) -> None:
        if not entity_key or not op:
            return
        self._conn.execute(
            """
            INSERT INTO operations
                (entity_key, op, node_token, status, result_ref, detail, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_key, op, node_token) DO UPDATE SET
                status = excluded.status,
                result_ref = excluded.result_ref,
                detail = excluded.detail,
                updated_at = excluded.updated_at
            """,
            (
                entity_key,
                op,
                node_token or "",
                status,
                result_ref or "",
                detail or "",
                time.time(),
            ),
        )
        self._conn.commit()

    def get_result_ref(
        self,
        entity_key: str,
        op: str,
        *,
        node_token: str = "",
    ) -> Optional[str]:
        row = self._conn.execute(
            """
            SELECT result_ref FROM operations
            WHERE entity_key = ? AND op = ? AND node_token = ?
            """,
            (entity_key, op, node_token or ""),
        ).fetchone()
        if not row:
            return None
        ref = row["result_ref"]
        return ref or None

    def filter_pending(
        self,
        docs: Sequence[dict],
        ops: Sequence[str],
        *,
        entity_key_field: str = "obj_token",
        node_token_field: str = "node_token",
        require_all_ops: bool = True,
    ) -> List[dict]:
        """
        Drop docs that already have ops done.

        require_all_ops=True: skip only if EVERY op is done (doc still runs if any op pending).
        require_all_ops=False: skip if ANY listed op is done (rarely useful).
        """
        op_list = [o for o in ops if o]
        if not op_list:
            return list(docs)
        kept: List[dict] = []
        for d in docs:
            entity = (d.get(entity_key_field) or d.get("obj_token") or "").strip()
            if not entity:
                entity = (d.get(node_token_field) or d.get("node_token") or "").strip()
            node = (d.get(node_token_field) or d.get("node_token") or "").strip()
            if require_all_ops:
                if self.has_all_ops(entity, op_list, node_token=node):
                    continue
            else:
                if any(self.is_done(entity, op, node_token=node) for op in op_list):
                    continue
            kept.append(d)
        return kept

    def close(self) -> None:
        self._conn.close()


def default_tool_ops_db_path() -> str:
    try:
        import config

        path = getattr(config, "TOOL_OPS_DB", None)
        if path:
            return path
    except Exception:
        pass
    return os.path.join("data", "tools", "tool_ops.db")


__all__ = [
    "OP_METADATA_TABLE",
    "OP_ATTACHMENT_SEPARATOR",
    "OP_METADATA_BITABLE",
    "OP_DISPLAY_TITLE_BITABLE",
    "OP_DISPLAY_TITLE_RENAME",
    "OP_TARGET_CONTENT_REFRESH",
    "OP_REPAIR_EXTRACTED_IMAGES",
    "KNOWN_OPS",
    "OperationLedger",
    "bitable_scope_key",
    "default_tool_ops_db_path",
]
