"""Shared copy registry for multi-worker parallel classification runs."""

from __future__ import annotations

import logging
import os
import shutil
import socket
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional, Set, TypeVar

logger = logging.getLogger(__name__)

_DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "shared_copy_state.db",
)

T = TypeVar("T")


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _is_network_path(db_path: str) -> bool:
    """UNC paths and mapped network drives should not use SQLite WAL."""
    abs_path = os.path.abspath(db_path)
    if abs_path.startswith("\\\\"):
        return True
    drive, _ = os.path.splitdrive(abs_path)
    if drive and len(drive) == 2:
        try:
            import ctypes

            remote = ctypes.create_unicode_buffer(512)
            if ctypes.windll.kernel32.WNetGetConnectionW(
                drive.rstrip(":"), remote, ctypes.byref(ctypes.c_ulong(512))
            ) == 0:
                return True
        except Exception:
            pass
    return False


class SharedCopyState:
    """
    Cross-process registry of copied documents, keyed by obj_token.

    Place SHARED_STATE_DB on a path visible to all workers (e.g. shared drive).
    Network shares use DELETE journal mode (not WAL) to reduce corruption risk.
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
        self._use_wal = not _is_network_path(self.db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        if self._use_wal:
            conn.execute("PRAGMA journal_mode=WAL")
        else:
            conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _remove_sidecar_files(self) -> None:
        base = self.db_path
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = base + suffix
            if os.path.isfile(sidecar):
                try:
                    os.remove(sidecar)
                except OSError:
                    pass

    def _recreate_db(self) -> None:
        """Remove corrupted DB and sidecars, then recreate schema."""
        logger.warning("重建共享去重库: %s", self.db_path)
        for path in (self.db_path, self.db_path + ".corrupt"):
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError as exc:
                    logger.error("无法删除 %s: %s", path, exc)
        self._remove_sidecar_files()
        self._init_db_schema()

    def _init_db_schema(self) -> None:
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

    def _init_db(self) -> None:
        try:
            self._init_db_schema()
        except sqlite3.DatabaseError:
            self._recreate_db()

    def _recover_from_corruption(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        corrupt_path = f"{self.db_path}.corrupt_{stamp}"
        try:
            if os.path.isfile(self.db_path):
                shutil.move(self.db_path, corrupt_path)
                logger.warning("已备份损坏库到 %s", corrupt_path)
        except OSError:
            pass
        self._remove_sidecar_files()
        self._init_db_schema()

    def _with_db(self, fn: Callable[[sqlite3.Connection], T], default: T) -> T:
        with self._lock:
            try:
                with self._connect() as conn:
                    return fn(conn)
            except sqlite3.DatabaseError as exc:
                logger.error("共享去重库异常 (%s): %s", self.db_path, exc)
                try:
                    self._recover_from_corruption()
                    with self._connect() as conn:
                        return fn(conn)
                except sqlite3.DatabaseError as exc2:
                    logger.error("共享去重库恢复失败: %s", exc2)
                    return default

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
        def _query(conn: sqlite3.Connection) -> bool:
            row = conn.execute(
                "SELECT 1 FROM copy_registry WHERE obj_token = ? AND status = 'copied'",
                (obj_token,),
            ).fetchone()
            return row is not None

        return self._with_db(_query, False)

    def copied_obj_tokens(self) -> Set[str]:
        def _query(conn: sqlite3.Connection) -> Set[str]:
            rows = conn.execute(
                "SELECT obj_token FROM copy_registry WHERE status = 'copied'"
            ).fetchall()
            return {row["obj_token"] for row in rows}

        return self._with_db(_query, set())

    def try_claim(self, obj_token: str) -> bool:
        """Atomically claim obj_token for copying. Returns False if already copied/claimed."""
        now = datetime.now().isoformat()

        def _claim(conn: sqlite3.Connection) -> bool:
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

        return self._with_db(_claim, True)

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
    ) -> bool:
        now = datetime.now().isoformat()

        def _mark(conn: sqlite3.Connection) -> bool:
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
            return True

        ok = self._with_db(_mark, False)
        if not ok:
            logger.warning(
                "无法写入共享去重库（文档已复制成功）: obj_token=%s", obj_token
            )
        return ok

    def release_claim(self, obj_token: str) -> None:
        def _release(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                DELETE FROM copy_registry
                WHERE obj_token = ? AND status = 'claiming' AND worker_id = ?
                """,
                (obj_token, self.worker_id),
            )
            conn.commit()

        self._with_db(_release, None)

    def worker_stats(self) -> Dict[str, int]:
        def _stats(conn: sqlite3.Connection) -> Dict[str, int]:
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

        return self._with_db(_stats, {"total_copied": 0, "worker_copied": 0})
