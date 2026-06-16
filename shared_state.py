"""Shared copy registry for multi-worker parallel classification runs."""

from __future__ import annotations

import os
import socket
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Set

_DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "shared_copy_state.db",
)


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class SharedCopyState:
    """
    Cross-process registry of copied documents, keyed by obj_token.

    Place SHARED_STATE_DB on a path visible to all workers (e.g. shared drive).
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        worker_id: Optional[str] = None,
        claim_timeout_minutes: int = 30,
    ):
        self.db_path = db_path or _DEFAULT_DB
        self.worker_id = worker_id or default_worker_id()
        self.claim_timeout = timedelta(minutes=max(1, claim_timeout_minutes))
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        parent = os.path.dirname(os.path.abspath(self.db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS copy_registry (
                    obj_token TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    title TEXT,
                    source_node_token TEXT,
                    copied_node_token TEXT,
                    target_parent_token TEXT,
                    target_folder_token TEXT,
                    scan_root TEXT,
                    worker_id TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_copy_status ON copy_registry(status)"
            )
            conn.commit()

    def _cleanup_stale_claims(self, conn: sqlite3.Connection) -> None:
        cutoff = (datetime.now() - self.claim_timeout).isoformat()
        conn.execute(
            """
            DELETE FROM copy_registry
            WHERE status = 'claiming' AND updated_at < ?
            """,
            (cutoff,),
        )

    def is_copied(self, obj_token: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM copy_registry WHERE obj_token = ? AND status = 'copied'",
                    (obj_token,),
                ).fetchone()
                return row is not None

    def copied_obj_tokens(self) -> Set[str]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT obj_token FROM copy_registry WHERE status = 'copied'"
                ).fetchall()
                return {row["obj_token"] for row in rows}

    def try_claim(self, obj_token: str) -> bool:
        """Atomically claim obj_token for copying. Returns False if already copied/claimed."""
        now = datetime.now().isoformat()
        with self._lock:
            with self._connect() as conn:
                self._cleanup_stale_claims(conn)
                cur = conn.execute(
                    """
                    INSERT INTO copy_registry (
                        obj_token, status, worker_id, updated_at
                    ) VALUES (?, 'claiming', ?, ?)
                    ON CONFLICT(obj_token) DO NOTHING
                    """,
                    (obj_token, self.worker_id, now),
                )
                conn.commit()
                return cur.rowcount == 1

    def mark_copied(
        self,
        obj_token: str,
        *,
        title: str,
        source_node_token: str,
        copied_node_token: str,
        target_parent_token: str,
        target_folder_token: str,
        scan_root: Optional[str],
    ) -> None:
        now = datetime.now().isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO copy_registry (
                        obj_token, status, title, source_node_token,
                        copied_node_token, target_parent_token,
                        target_folder_token, scan_root, worker_id, updated_at
                    ) VALUES (?, 'copied', ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(obj_token) DO UPDATE SET
                        status = 'copied',
                        title = excluded.title,
                        source_node_token = excluded.source_node_token,
                        copied_node_token = excluded.copied_node_token,
                        target_parent_token = excluded.target_parent_token,
                        target_folder_token = excluded.target_folder_token,
                        scan_root = excluded.scan_root,
                        worker_id = excluded.worker_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        obj_token,
                        title,
                        source_node_token,
                        copied_node_token,
                        target_parent_token,
                        target_folder_token,
                        scan_root or "",
                        self.worker_id,
                        now,
                    ),
                )
                conn.commit()

    def release_claim(self, obj_token: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    DELETE FROM copy_registry
                    WHERE obj_token = ? AND status = 'claiming' AND worker_id = ?
                    """,
                    (obj_token, self.worker_id),
                )
                conn.commit()

    def worker_stats(self) -> Dict[str, int]:
        with self._lock:
            with self._connect() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) AS c FROM copy_registry WHERE status = 'copied'"
                ).fetchone()["c"]
                mine = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM copy_registry
                    WHERE status = 'copied' AND worker_id = ?
                    """,
                    (self.worker_id,),
                ).fetchone()["c"]
                return {"total_copied": total, "worker_copied": mine}
