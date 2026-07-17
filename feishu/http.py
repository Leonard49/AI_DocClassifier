"""Feishu HTTP client with cross-process rate limiting and retries."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from typing import Any, Optional

import requests

import config

logger = logging.getLogger(__name__)

RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_FEISHU_CODES = {99991400}


class RetryableFeishuError(Exception):
    """Transient Feishu API failure worth retrying."""


class FeishuRateLimiter:
    """In-process spacing for API calls (per worker)."""

    def __init__(self, max_per_second: float = 4.0):
        if max_per_second <= 0:
            raise ValueError("max_per_second must be positive")
        self._min_interval = 1.0 / max_per_second
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                time.sleep(self._next_allowed - now)
            self._next_allowed = time.monotonic() + self._min_interval


class CrossProcessFeishuRateLimiter:
    """
    Global spacing across workers via SQLite on a shared path.
    Uses BEGIN IMMEDIATE so only one process advances the slot at a time.
    """

    def __init__(self, db_path: str, max_per_second: float):
        if max_per_second <= 0:
            raise ValueError("max_per_second must be positive")
        self.db_path = db_path
        self._min_interval = 1.0 / max_per_second
        self._init_lock = threading.Lock()
        self._initialized = False

    def _ensure_db(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            directory = os.path.dirname(self.db_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=30)
            try:
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS feishu_rate_limit (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        next_allowed REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT OR IGNORE INTO feishu_rate_limit (id, next_allowed) VALUES (1, 0)"
                )
                conn.commit()
            finally:
                conn.close()
            self._initialized = True

    def wait(self) -> None:
        self._ensure_db()
        while True:
            conn = sqlite3.connect(self.db_path, timeout=30)
            try:
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT next_allowed FROM feishu_rate_limit WHERE id = 1"
                ).fetchone()
                now = time.time()
                allowed_at = float(row[0]) if row else 0.0
                if allowed_at > now:
                    delay = min(allowed_at - now, 1.0)
                    conn.rollback()
                    time.sleep(delay)
                    continue
                conn.execute(
                    "UPDATE feishu_rate_limit SET next_allowed = ? WHERE id = 1",
                    (now + self._min_interval,),
                )
                conn.commit()
                return
            except sqlite3.OperationalError:
                time.sleep(0.05)
            finally:
                conn.close()


class CombinedFeishuRateLimiter:
    """Apply in-process and optional cross-process spacing."""

    def __init__(
        self,
        local: FeishuRateLimiter,
        cross_process: Optional[CrossProcessFeishuRateLimiter] = None,
    ):
        self._local = local
        self._cross_process = cross_process

    def wait(self) -> None:
        if self._cross_process is not None:
            self._cross_process.wait()
        self._local.wait()


def default_rate_limit_db_path() -> str:
    override = (config.FEISHU_RATE_LIMIT_DB or "").strip()
    if override:
        return override
    shared_db = (config.SHARED_STATE_DB or "").strip()
    if shared_db:
        return os.path.join(os.path.dirname(os.path.abspath(shared_db)), "feishu_rate_limit.db")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "feishu_rate_limit.db")


def _build_api_limiter() -> CombinedFeishuRateLimiter:
    local = FeishuRateLimiter(max_per_second=config.FEISHU_LOCAL_MAX_PER_SECOND)
    cross: Optional[CrossProcessFeishuRateLimiter] = None
    if config.ENABLE_CROSS_PROCESS_FEISHU_LIMIT:
        cross = CrossProcessFeishuRateLimiter(
            default_rate_limit_db_path(),
            config.FEISHU_GLOBAL_MAX_PER_SECOND,
        )
    return CombinedFeishuRateLimiter(local, cross)


FEISHU_API_LIMITER = _build_api_limiter()


def is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, RetryableFeishuError):
        return True
    if isinstance(
        exc,
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ),
    ):
        return True
    return False


def _response_should_retry(resp: requests.Response) -> bool:
    if resp.status_code in RETRYABLE_HTTP_STATUS:
        return True
    try:
        data = resp.json()
    except ValueError:
        return False
    return data.get("code") in RETRYABLE_FEISHU_CODES


def feishu_request(
    method: str,
    url: str,
    *,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    rate_limit: bool = True,
    retry_http_errors: bool = True,
    **kwargs: Any,
) -> requests.Response:
    """
    Issue a Feishu API request with optional global rate limit and retries.

    Retries on timeouts, connection errors, HTTP 429/5xx, and Feishu code 99991400.
    """
    timeout = config.FEISHU_API_TIMEOUT if timeout is None else timeout
    max_retries = config.FEISHU_API_MAX_RETRIES if max_retries is None else max_retries
    last_error: Optional[BaseException] = None

    for attempt in range(max(1, max_retries)):
        if rate_limit:
            FEISHU_API_LIMITER.wait()
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            if retry_http_errors and _response_should_retry(resp):
                hint = resp.status_code
                try:
                    hint = resp.json().get("code", hint)
                except ValueError:
                    pass
                raise RetryableFeishuError(f"HTTP {resp.status_code} / code {hint}")
            return resp
        except BaseException as exc:
            last_error = exc
            if not is_retryable_error(exc) or attempt >= max_retries - 1:
                raise
            delay = min(2**attempt, 30)
            logger.warning(
                "Feishu API 重试 %s/%s %s %s: %s",
                attempt + 1,
                max_retries,
                method,
                url[:100],
                exc,
            )
            time.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("feishu_request failed without response")
