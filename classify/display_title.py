# -*- coding: utf-8 -*-
"""Compose display titles: 日期-型号或路径-文章作用 (never renames wiki)."""

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

_DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})"),
    re.compile(r"(20\d{2})(\d{2})(\d{2})"),
]


@dataclass
class DisplayTitleRow:
    original_title: str
    display_title: str
    obj_token: str
    node_token: str
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
        # Feishu sometimes returns ms
        if ts > 10_000_000_000:
            ts //= 1000
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
            return dt.strftime("%Y%m%d")
        except (OverflowError, OSError, ValueError):
            continue
    return None


def path_breadcrumb(source_path: str) -> str:
    """Convert scanner breadcrumb `A / B / C` → `A|B|C`."""
    text = (source_path or "").strip()
    if not text:
        return ""
    if " / " in text:
        parts = [p.strip() for p in text.split(" / ") if p.strip()]
    else:
        parts = [p.strip() for p in text.split("/") if p.strip()]
    return "|".join(parts)


def primary_module(title: str, content: str = "") -> str:
    modules = format_module_models(title, content, limit=3)
    if not modules:
        return ""
    return modules.split(",")[0].strip()


def resolve_model_or_path(
    title: str,
    content: str = "",
    *,
    source_path: str = "",
) -> str:
    model = primary_module(title, content)
    if model:
        return model
    crumb = path_breadcrumb(source_path)
    return crumb or "未知路径"


def purpose_prompt(title: str, content: str) -> str:
    body = (content or "")[:800]
    return (
        "用中文概括这篇文档的核心作用/用途，尽量简洁。\n"
        "只输出一句短语，不要标点收尾，不要解释，控制在 16 个汉字以内。\n"
        "示例：说明休眠掉电原因 / GNSS定位配置说明 / 客户问题排查步骤\n\n"
        f"标题: {title or '(空)'}\n"
        f"正文摘录:\n{body or '(空)'}\n"
    )


def sanitize_purpose(raw: str, *, fallback: str = DEFAULT_DOC_TYPE) -> str:
    text = (raw or "").strip().splitlines()[0].strip().strip("\"'`。；;,. ")
    text = re.sub(r"\s+", "", text)
    if not text:
        return fallback
    # Soft length cap for title segment
    if len(text) > 20:
        text = text[:20]
    return text


def fallback_purpose(title: str, content: str = "") -> str:
    return classify_doc_type_by_rules(title, content) or DEFAULT_DOC_TYPE


def compose_display_title(date_part: str, model_or_path: str, purpose: str) -> str:
    date_part = (date_part or "未知日期").strip()
    model_or_path = (model_or_path or "未知路径").strip()
    purpose = (purpose or DEFAULT_DOC_TYPE).strip()
    # Avoid pipe/dash blow-ups in model segment only; keep path pipes
    return f"{date_part}-{model_or_path}-{purpose}"


def build_display_title_row(
    *,
    title: str,
    content: str,
    obj_token: str,
    node_token: str,
    source_path: str = "",
    source_folder: str = "",
    purpose: Optional[str] = None,
    wiki_node: Optional[dict] = None,
) -> DisplayTitleRow:
    date_part = (
        extract_date_from_title(title)
        or extract_date_from_wiki_node(wiki_node or {})
        or "未知日期"
    )
    model_or_path = resolve_model_or_path(title, content, source_path=source_path)
    purpose_text = sanitize_purpose(
        purpose if purpose is not None else fallback_purpose(title, content)
    )
    display = compose_display_title(date_part, model_or_path, purpose_text)
    return DisplayTitleRow(
        original_title=title or "",
        display_title=display,
        obj_token=obj_token or "",
        node_token=node_token or "",
        date_part=date_part,
        model_or_path=model_or_path,
        purpose=purpose_text,
        modules=format_module_models(title, content) or "",
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
    "path_breadcrumb",
    "purpose_prompt",
    "resolve_model_or_path",
    "sanitize_purpose",
]
