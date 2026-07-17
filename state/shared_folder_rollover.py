"""Cross-process active folder-bucket registry for 131003 rollover."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional, Tuple

from .shared_state import _is_network_path, default_worker_id

logger = logging.getLogger(__name__)


def default_rollover_db_path(shared_state_db: Optional[str] = None) -> str:
    """Place rollover DB beside shared_copy_state.db when possible."""
    if shared_state_db:
        parent = os.path.dirname(shared_state_db)
        if parent:
            return os.path.join(parent, "folder_rollover_state.db")
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "folder_rollover_state.db",
    )


class SharedFolderRolloverStore:
    """
    Persist active ``{base}`` / ``{base} (N)`` bucket per parent.

    Safe for multi-worker use on a shared network path (DELETE journal).
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        worker_id: Optional[str] = None,
    ):
        self.db_path = db_path or default_rollover_db_path()
        self.worker_id = worker_id or default_worker_id()
        self._lock = threading.Lock()
        self._use_wal = not _is_network_path(self.db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(os.path.abspath(self.db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        if self._use_wal:
            conn.execute("PRAGMA journal_mode=WAL")
        else:
            conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS folder_buckets (
                    parent_token TEXT NOT NULL,
                    base_name TEXT NOT NULL,
                    active_token TEXT NOT NULL,
                    active_title TEXT NOT NULL,
                    part_index INTEGER NOT NULL DEFAULT 1,
                    worker_id TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (parent_token, base_name)
                )
                """
            )
            conn.commit()

    def get_active(
        self,
        parent_token: Optional[str],
        base_name: str,
    ) -> Optional[Tuple[str, str, int]]:
        """Return (active_token, active_title, part_index) or None."""
        key_parent = parent_token or ""
        with self._lock:
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        """
                        SELECT active_token, active_title, part_index
                        FROM folder_buckets
                        WHERE parent_token = ? AND base_name = ?
                        """,
                        (key_parent, base_name),
                    ).fetchone()
                if not row:
                    return None
                return row["active_token"], row["active_title"], int(row["part_index"])
            except sqlite3.DatabaseError as exc:
                logger.error("读取分卷状态失败: %s", exc)
                return None

    def set_active(
        self,
        parent_token: Optional[str],
        base_name: str,
        active_token: str,
        active_title: str,
        part_index: int,
    ) -> bool:
        key_parent = parent_token or ""
        now = datetime.now().isoformat()
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO folder_buckets (
                            parent_token, base_name, active_token, active_title,
                            part_index, worker_id, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(parent_token, base_name) DO UPDATE SET
                            active_token = excluded.active_token,
                            active_title = excluded.active_title,
                            part_index = excluded.part_index,
                            worker_id = excluded.worker_id,
                            updated_at = excluded.updated_at
                        """,
                        (
                            key_parent,
                            base_name,
                            active_token,
                            active_title,
                            part_index,
                            self.worker_id,
                            now,
                        ),
                    )
                    conn.commit()
                return True
            except sqlite3.DatabaseError as exc:
                logger.error("写入分卷状态失败: %s", exc)
                return False

    def next_part_index(
        self,
        parent_token: Optional[str],
        base_name: str,
    ) -> int:
        """Atomically peek current part and return the next index to create."""
        current = self.get_active(parent_token, base_name)
        if not current:
            return 2
        return max(2, current[2] + 1)
