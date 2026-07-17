#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite cache for AI classification results."""

import hashlib
import json
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional


class ClassifyCache:
    """Cache classification by obj_token; invalidate when content hash changes."""

    def __init__(self, db_path: str = "classify_cache.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS classify_cache (
                        obj_token TEXT PRIMARY KEY,
                        content_hash TEXT NOT NULL,
                        tag_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()

    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256((content or "").encode("utf-8")).hexdigest()

    def get(self, obj_token: str, content: str) -> Optional[Dict[str, List[str]]]:
        digest = self.content_hash(content)
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT content_hash, tag_json FROM classify_cache WHERE obj_token = ?",
                    (obj_token,),
                ).fetchone()
        if not row or row["content_hash"] != digest:
            return None
        return json.loads(row["tag_json"])

    def set(self, obj_token: str, content: str, tag: Dict[str, List[str]]) -> None:
        digest = self.content_hash(content)
        now = datetime.now().isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO classify_cache
                        (obj_token, content_hash, tag_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (obj_token, digest, json.dumps(tag, ensure_ascii=False), now),
                )
                conn.commit()
