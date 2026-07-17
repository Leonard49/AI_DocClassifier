#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thread-safe rate limiter for Feishu Open API (docx raw_content: 5 req/s)."""

from .http import FEISHU_API_LIMITER, FeishuRateLimiter

# Backward-compatible alias used by feishu/read_doc.py
DOCX_READ_LIMITER = FEISHU_API_LIMITER

__all__ = ["FeishuRateLimiter", "DOCX_READ_LIMITER", "FEISHU_API_LIMITER"]
