# -*- coding: utf-8 -*-
"""Compose display titles: 文章主题-产品线-作者 (TARGET tools; optional wiki rename)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from classify.doc_metadata import (
    DEFAULT_DOC_TYPE,
    build_wiki_url,
    classify_doc_type_by_rules,
    format_module_models,
)
from classify.module_product_map import extract_module_mentions

_DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})"),
    re.compile(r"(20\d{2})(\d{2})(\d{2})"),
]

_SEP = "-"


@dataclass
class DisplayTitleRow:
    original_title: str
    display_title: str
    obj_token: str
    node_token: str
    # New format segments
    theme: str
    product_line: str
    author: str
    # Legacy aliases (bitable / reports backward compatible)
    date_part: str
    model_or_path: str
    purpose: str
    modules: str
    path_breadcrumb: str
    source_folder: str
    source_path: str
    wiki_url: str

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_date_parts(year: int, month: int, day: int) -> Optional[str]:
    try:
        dt = datetime(year, month, day)
    except ValueError:
        return None
    return dt.strftime("%Y%m%d")


def extract_date_from_title(title: str) -> Optional[str]:
    text = title or ""
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        y, mo, d = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        got = normalize_date_parts(y, mo, d)
        if got:
            return got
    return None


def extract_date_from_wiki_node(node: dict) -> Optional[str]:
    """Parse Feishu wiki node create/edit timestamps (unix seconds as str/int)."""
    if not node:
        return None
    for key in ("obj_create_time", "node_create_time", "obj_edit_time", "node_edit_time"):
        raw = node.get(key)
        if raw is None or raw == "":
            continue
        try:
            ts = int(str(raw).strip())
        except ValueError:
            continue
        if ts > 10_000_000_000:
            ts //= 1000
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
            return dt.strftime("%Y%m%d")
        except (OverflowError, OSError, ValueError):
            continue
    return None


def path_segments(path: str) -> list:
    text = (path or "").strip()
    if not text:
        return []
    if " / " in text:
        return [p.strip() for p in text.split(" / ") if p.strip()]
    return [p.strip() for p in text.split("/") if p.strip()]


def path_breadcrumb(source_path: str) -> str:
    """Convert scanner breadcrumb `A / B / C` → `A|B|C`."""
    return "|".join(path_segments(source_path))


def target_l1_l2(target_path: str) -> str:
    """
    TARGET 下一级+二级目录，用作识别不到模组时的产品线回退。
    例: ShortRange / WiFi / 某文 → ShortRange|WiFi
    """
    parts = path_segments(target_path)
    if len(parts) >= 2:
        return f"{parts[0]}|{parts[1]}"
    if len(parts) == 1:
        return parts[0]
    return ""


def primary_module(title: str, content: str = "") -> str:
    """Only the single main module PN (never a comma list)."""
    hits = extract_module_mentions(title, content)
    if not hits:
        return ""
    # Prefer title hits; else first content hit (extract order is relevance-ish)
    title_hits = extract_module_mentions(title, None)
    if title_hits:
        return title_hits[0].token
    return hits[0].token


def resolve_product_line(
    title: str,
    content: str = "",
    *,
    target_path: str = "",
) -> str:
    """
    产品线段：只取文章主要提到的一个模组；
    识别不到则用 TARGET 一级|二级目录。
    """
    module = primary_module(title, content)
    if module:
        return module
    fallback = target_l1_l2(target_path)
    return fallback or "未知产品线"


def resolve_model_or_path(
    title: str,
    content: str = "",
    *,
    source_path: str = "",
) -> str:
    """Backward-compatible alias → product_line segment."""
    return resolve_product_line(title, content, target_path=source_path)


def theme_prompt(title: str, content: str) -> str:
    body = (content or "")[:600]
    return (
        "用中文概括这篇文档的「文章主题」，要极短。\n"
        "只输出主题短语本身：不要标点收尾，不要解释，尽量不超过 8 个汉字（最多 12）。\n"
        "示例：休眠掉电 / GNSS配置 / 客户问题排查 / ATOTA升级\n\n"
        f"标题: {title or '(空)'}\n"
        f"正文摘录:\n{body or '(空)'}\n"
    )


# Keep old name for import compatibility
purpose_prompt = theme_prompt


def sanitize_theme(raw: str, *, fallback: str = DEFAULT_DOC_TYPE) -> str:
    text = (raw or "").strip().splitlines()[0].strip().strip("\"'`。；;,. ")
    text = re.sub(r"\s+", "", text)
    text = text.replace(_SEP, "·")
    if not text:
        return fallback
    if len(text) > 12:
        text = text[:12]
    return text


def sanitize_purpose(raw: str, *, fallback: str = DEFAULT_DOC_TYPE) -> str:
    return sanitize_theme(raw, fallback=fallback)


def fallback_theme(title: str, content: str = "") -> str:
    # Prefer a short slice of title over long doc-type names when possible
    t = re.sub(r"\s+", "", (title or "").strip())
    t = t.replace(_SEP, "·")
    if t:
        return t[:12]
    return classify_doc_type_by_rules(title, content) or DEFAULT_DOC_TYPE


def fallback_purpose(title: str, content: str = "") -> str:
    return fallback_theme(title, content)


def sanitize_author(author: str) -> str:
    text = (author or "").strip()
    text = re.sub(r"\s+", "", text)
    text = text.replace(_SEP, "·")
    if not text:
        return "未知作者"
    if len(text) > 20:
        text = text[:20]
    return text


def sanitize_product_line(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+", "", text)
    # Keep | in L1|L2 fallback; strip other dashes that break the 3-part title
    text = text.replace(_SEP, "·")
    if not text:
        return "未知产品线"
    if len(text) > 40:
        text = text[:40]
    return text


def compose_display_title(theme: str, product_line: str, author: str) -> str:
    theme = sanitize_theme(theme)
    product_line = sanitize_product_line(product_line)
    author = sanitize_author(author)
    return f"{theme}{_SEP}{product_line}{_SEP}{author}"


def build_display_title_row(
    *,
    title: str,
    content: str,
    obj_token: str,
    node_token: str,
    source_path: str = "",
    source_folder: str = "",
    purpose: Optional[str] = None,
    theme: Optional[str] = None,
    author: str = "",
    wiki_node: Optional[dict] = None,
) -> DisplayTitleRow:
    """
    source_path: for TARGET tools pass target_path (L1/L2 fallback).
    purpose/theme: optional LLM theme; same meaning.
    """
    _ = wiki_node  # date no longer in title; kept for API compatibility
    theme_raw = theme if theme is not None else purpose
    theme_text = sanitize_theme(
        theme_raw if theme_raw is not None else fallback_theme(title, content)
    )
    product = resolve_product_line(title, content, target_path=source_path)
    product = sanitize_product_line(product)
    author_text = sanitize_author(author)
    display = compose_display_title(theme_text, product, author_text)
    modules = primary_module(title, content) or ""
    return DisplayTitleRow(
        original_title=title or "",
        display_title=display,
        obj_token=obj_token or "",
        node_token=node_token or "",
        theme=theme_text,
        product_line=product,
        author=author_text,
        date_part="",
        model_or_path=product,
        purpose=theme_text,
        modules=modules or format_module_models(title, content, limit=1) or "",
        path_breadcrumb=path_breadcrumb(source_path),
        source_folder=source_folder or "",
        source_path=source_path or "",
        wiki_url=build_wiki_url(node_token),
    )


__all__ = [
    "DisplayTitleRow",
    "build_display_title_row",
    "compose_display_title",
    "extract_date_from_title",
    "extract_date_from_wiki_node",
    "fallback_purpose",
    "fallback_theme",
    "path_breadcrumb",
    "primary_module",
    "purpose_prompt",
    "resolve_model_or_path",
    "resolve_product_line",
    "sanitize_purpose",
    "sanitize_theme",
    "target_l1_l2",
    "theme_prompt",
]
