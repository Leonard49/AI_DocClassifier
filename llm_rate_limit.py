#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rate limit and concurrency cap for LiteLLM classification calls."""

import threading

from feishu_rate_limit import FeishuRateLimiter

# LiteLLM 网关在高并发时易返回 502；限制并发与 QPS
LLM_RATE_LIMITER = FeishuRateLimiter(max_per_second=1.2)
LLM_CONCURRENCY = threading.Semaphore(2)
