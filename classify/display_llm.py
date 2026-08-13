# -*- coding: utf-8 -*-
"""Shared LLM helper: article theme + primary module/product in one call."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import config
from classify.display_title import (
    fallback_theme,
    parse_theme_module_response,
    sanitize_llm_module,
    sanitize_theme,
    theme_and_module_prompt,
)
from classify.llm_rate_limit import LLM_CONCURRENCY, LLM_RATE_LIMITER
from openai import OpenAI


@dataclass
class ThemeModuleGuess:
    theme: str
    module: str = ""


class PurposeLLM:
    """Induct 文章主题 and 主要型号/产品 from the article body."""

    def __init__(self):
        self.client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
            max_retries=0,
        )
        self.model = config.LLM_MODEL
        self.max_retries = config.LLM_MAX_RETRIES

    @staticmethod
    def _message_text(message) -> str:
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(
                        str(getattr(item, "text", None) or getattr(item, "content", None) or "")
                    )
            joined = "".join(parts).strip()
            if joined:
                return joined
        return ""

    def summarize(self, title: str, content: str) -> ThemeModuleGuess:
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        )

        fallback = fallback_theme(title, content)
        messages = [
            {
                "role": "system",
                "content": (
                    "根据正文归纳文章主题，并给出本文主要针对的模组或产品型号。"
                    "按指定两行格式输出。禁止日期、编号、照抄原标题。不要解释。"
                ),
            },
            {"role": "user", "content": theme_and_module_prompt(title, content)},
        ]
        with LLM_CONCURRENCY:
            for attempt in range(self.max_retries):
                LLM_RATE_LIMITER.wait()
                try:
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=256,
                    )
                    choices = getattr(resp, "choices", None) or []
                    if not choices:
                        raise IndexError("LLM choices empty")
                    raw = self._message_text(choices[0].message)
                    if not raw:
                        raise ValueError("LLM content empty")
                    theme_raw, module_raw = parse_theme_module_response(raw)
                    theme = sanitize_theme(theme_raw, fallback=fallback)
                    module = sanitize_llm_module(module_raw)
                    if not module:
                        preview = " ".join((raw or "").split())[:80]
                        print(f"  · LLM 未给出可用型号（raw={preview!r}）", flush=True)
                    return ThemeModuleGuess(theme=theme, module=module)
                except Exception as e:
                    retryable = isinstance(
                        e,
                        (
                            APIConnectionError,
                            APITimeoutError,
                            InternalServerError,
                            RateLimitError,
                            IndexError,
                            ValueError,
                        ),
                    ) or (
                        isinstance(e, APIStatusError)
                        and e.status_code in {408, 429, 500, 502, 503, 504}
                    )
                    if not retryable or attempt >= self.max_retries - 1:
                        print(f"⚠️ 文章主题/型号 LLM 失败 ({title}): {e} → {fallback}")
                        return ThemeModuleGuess(theme=fallback, module="")
                    time.sleep(min(2**attempt + random.uniform(0.2, 1.0), 30.0))
        return ThemeModuleGuess(theme=fallback, module="")


__all__ = ["PurposeLLM", "ThemeModuleGuess"]
