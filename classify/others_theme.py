# -*- coding: utf-8 -*-
"""Theme buckets for leftover TARGET/Others documents (not product-line tags)."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Theme folders hang only under the primary Others node (not Others 2+).
OTHERS_THEMES: List[str] = [
    "开发与平台工具",
    "测试与认证",
    "知识分享与培训",
    "FAQ与排障",
    "模组与产品相关",
    "硬件相关",
    "流程与协作",
    "杂项",
]

DEFAULT_THEME = "杂项"

# (theme, compiled patterns) — first match wins
_RULES: List[Tuple[str, List[re.Pattern]]] = [
    (
        "FAQ与排障",
        [
            re.compile(r"FAQ|faq|常见问题|排障|troubleshooting", re.I),
        ],
    ),
    (
        "流程与协作",
        [
            re.compile(r"周报|日报|会议|纪要|Jira|共享盘|通知", re.I),
        ],
    ),
    (
        "知识分享与培训",
        [
            re.compile(
                r"工作分享|分享主题|技术小站|学习总结|学习文档|心得|培训|"
                r"G[_-][A-Z]{2}\d+",
                re.I,
            ),
        ],
    ),
    (
        "测试与认证",
        [
            re.compile(r"测试|验证|ESD|兼容|认证|certif|compliance", re.I),
        ],
    ),
    (
        "硬件相关",
        [
            re.compile(
                r"硬件|flash|PCB|天线|射频|原理图|layout|原理图|外挂",
                re.I,
            ),
        ],
    ),
    (
        "模组与产品相关",
        [
            re.compile(
                r"智能模组|模组|Smart|CAN|ECU|两轮|车载|Quectel|移远|"
                r"\bAG\d|\bEG\d|\bEC\d|\bSG\d|\bSC\d|\bBG\d|\bRG\d|\bEM\d",
                re.I,
            ),
        ],
    ),
    (
        "开发与平台工具",
        [
            re.compile(
                r"OpenLinux|QuecOpen|ADB|dump|写号|AT指令|linux|ubuntu|DNS|"
                r"NAT|Git|服务器|python|android|SDK|驱动|调试|Wireshark|"
                r"opengrok|grokit|patch|API|代码",
                re.I,
            ),
        ],
    ),
]


def classify_theme_by_rules(title: str, content: str = "") -> Optional[str]:
    """Return a theme name if title/content matches a rule; else None."""
    text = f"{title or ''}\n{(content or '')[:2000]}"
    for theme, patterns in _RULES:
        for pat in patterns:
            if pat.search(text):
                return theme
    return None


def theme_prompt(title: str, content: str, themes: Optional[List[str]] = None) -> str:
    names = themes or OTHERS_THEMES
    body = (content or "")[:1200]
    return (
        "你是文档归档助手。请把下面这篇无法归入产品线标签树的文档，"
        "分到且仅分到下列主题之一。\n"
        "只输出主题名称本身，不要解释，不要标点。\n\n"
        f"可选主题:\n- " + "\n- ".join(names) + "\n\n"
        f"标题: {title or '(无)'}\n"
        f"正文摘录:\n{body or '(无)'}\n"
    )


def parse_theme_response(raw: str, themes: Optional[List[str]] = None) -> str:
    names = themes or OTHERS_THEMES
    text = (raw or "").strip().splitlines()[0].strip().strip("\"'`")
    for name in names:
        if text == name or name in text:
            return name
    return DEFAULT_THEME


__all__ = [
    "OTHERS_THEMES",
    "DEFAULT_THEME",
    "classify_theme_by_rules",
    "theme_prompt",
    "parse_theme_response",
]
