#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thread-safe rate limiter for Feishu Open API (docx raw_content: 5 req/s)."""

import threading
import time


class FeishuRateLimiter:
    """Serialize/spacing for API calls; default 4/s leaves headroom under the 5/s cap."""

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


# Shared limiter for docx document reads across threads
DOCX_READ_LIMITER = FeishuRateLimiter(max_per_second=4.0)
