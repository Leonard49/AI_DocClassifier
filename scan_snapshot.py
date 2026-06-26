#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent leaf-doc snapshot for incremental scan (Plan B)."""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "scan_snapshot.db",
)


class ScanSnapshot:
    """
    Track leaf docx nodes under a scan root across runs.

    - Compare snapshots to find newly discovered node_token values.
    - Periodic full calibration refreshes baseline and meta timestamps.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        space_id: str,
        scan_root: str,
    ):
        self.db_path = db_path or _DEFAULT_DB
        self.space_id = space_id
        self.scan_root = scan_root or ""
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_meta (
                    space_id TEXT NOT NULL,
                    scan_root TEXT NOT NULL,
                    last_scan_at TEXT,
                    last_full_calibration_at TEXT,
                    leaf_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (space_id, scan_root)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leaf_snapshot (
                    space_id TEXT NOT NULL,
                    scan_root TEXT NOT NULL,
                    node_token TEXT NOT NULL,
                    obj_token TEXT,
                    title TEXT,
                    parent_node_token TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (space_id, scan_root, node_token)
                )
                """
            )
            conn.commit()

    def has_baseline(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM scan_meta
                WHERE space_id = ? AND scan_root = ?
                """,
                (self.space_id, self.scan_root),
            ).fetchone()
        return row is not None

    def known_leaf_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM leaf_snapshot
                WHERE space_id = ? AND scan_root = ?
                """,
                (self.space_id, self.scan_root),
            ).fetchone()
        return int(row["c"]) if row else 0

    def needs_full_calibration(self, interval_days: int) -> bool:
        """True when baseline missing or last calibration older than interval."""
        if interval_days <= 0:
            return False
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT last_full_calibration_at FROM scan_meta
                WHERE space_id = ? AND scan_root = ?
                """,
                (self.space_id, self.scan_root),
            ).fetchone()
        if not row or not row["last_full_calibration_at"]:
            return True
        try:
            last = datetime.fromisoformat(row["last_full_calibration_at"])
        except ValueError:
            return True
        return datetime.now() - last >= timedelta(days=interval_days)

    def delta_node_tokens(self, documents: List[Dict]) -> Set[str]:
        """Return node_token values present in documents but not in snapshot."""
        current = {
            doc["node_token"]
            for doc in documents
            if doc.get("node_token")
        }
        if not current:
            return set()

        with self._connect() as conn:
            placeholders = ",".join("?" * len(current))
            rows = conn.execute(
                f"""
                SELECT node_token FROM leaf_snapshot
                WHERE space_id = ? AND scan_root = ?
                  AND node_token IN ({placeholders})
                """,
                (self.space_id, self.scan_root, *current),
            ).fetchall()
        known = {row["node_token"] for row in rows}
        return current - known

    def save_scan(
        self,
        documents: List[Dict],
        *,
        full_calibration: bool = False,
    ) -> None:
        """Upsert leaf snapshot and refresh meta after a successful scan."""
        now = datetime.now().isoformat()
        current_tokens = set()

        with self._connect() as conn:
            for doc in documents:
                node_token = doc.get("node_token")
                if not node_token:
                    continue
                current_tokens.add(node_token)
                existing = conn.execute(
                    """
                    SELECT first_seen_at FROM leaf_snapshot
                    WHERE space_id = ? AND scan_root = ? AND node_token = ?
                    """,
                    (self.space_id, self.scan_root, node_token),
                ).fetchone()
                first_seen = (
                    existing["first_seen_at"] if existing else now
                )
                conn.execute(
                    """
                    INSERT INTO leaf_snapshot (
                        space_id, scan_root, node_token, obj_token, title,
                        parent_node_token, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(space_id, scan_root, node_token) DO UPDATE SET
                        obj_token = excluded.obj_token,
                        title = excluded.title,
                        parent_node_token = excluded.parent_node_token,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        self.space_id,
                        self.scan_root,
                        node_token,
                        doc.get("obj_token") or "",
                        doc.get("title") or "",
                        doc.get("parent_node_token") or "",
                        first_seen,
                        now,
                    ),
                )

            if current_tokens:
                placeholders = ",".join("?" * len(current_tokens))
                conn.execute(
                    f"""
                    DELETE FROM leaf_snapshot
                    WHERE space_id = ? AND scan_root = ?
                      AND node_token NOT IN ({placeholders})
                    """,
                    (self.space_id, self.scan_root, *current_tokens),
                )
            else:
                conn.execute(
                    """
                    DELETE FROM leaf_snapshot
                    WHERE space_id = ? AND scan_root = ?
                    """,
                    (self.space_id, self.scan_root),
                )

            meta = conn.execute(
                """
                SELECT last_full_calibration_at FROM scan_meta
                WHERE space_id = ? AND scan_root = ?
                """,
                (self.space_id, self.scan_root),
            ).fetchone()
            calibration_at = now if full_calibration else (
                meta["last_full_calibration_at"] if meta else now
            )
            if full_calibration or not meta:
                calibration_at = now

            conn.execute(
                """
                INSERT INTO scan_meta (
                    space_id, scan_root, last_scan_at,
                    last_full_calibration_at, leaf_count
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(space_id, scan_root) DO UPDATE SET
                    last_scan_at = excluded.last_scan_at,
                    last_full_calibration_at = excluded.last_full_calibration_at,
                    leaf_count = excluded.leaf_count
                """,
                (
                    self.space_id,
                    self.scan_root,
                    now,
                    calibration_at,
                    len(current_tokens),
                ),
            )
            conn.commit()

        logger.info(
            "扫描快照已更新: %s/%s 叶子 %d 个%s",
            self.space_id,
            self.scan_root,
            len(current_tokens),
            "（全量校准）" if full_calibration else "",
        )

    def summary(self) -> Tuple[Optional[str], Optional[str], int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT last_scan_at, last_full_calibration_at, leaf_count
                FROM scan_meta
                WHERE space_id = ? AND scan_root = ?
                """,
                (self.space_id, self.scan_root),
            ).fetchone()
        if not row:
            return None, None, 0
        return row["last_scan_at"], row["last_full_calibration_at"], int(row["leaf_count"])
