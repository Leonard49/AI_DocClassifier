# -*- coding: utf-8 -*-
"""Compose display titles: 文章主题-模组型号-作者 (TARGET tools; optional wiki rename)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from classify.doc_metadata import (
    DEFAULT_DOC_TYPE,
    build_wiki_url,
    classify_doc_type_by_rules,
)
from classify.module_product_map import extract_module_mentions

_DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})"),
    re.compile(r"(20\d{2})(\d{2})(\d{2})"),
]

# Leading noise on source titles (serial + date) — must not become 文章主题
_LEADING_NOISE_PATTERNS = [
    re.compile(r"^\d{1,3}[-_./\s]+(?=20\d{2}|\d{2}[-./]\d{1,2})"),  # 17-2026 / 51.26.8
    re.compile(r"^(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})日?"),
    re.compile(r"^(20\d{2})[-./](\d{1,2})[-./](\d{1,2})"),
    re.compile(r"^(20\d{2})(\d{2})(\d{2})"),
    re.compile(r"^(\d{2})[-./](\d{1,2})[-./](\d{1,2})"),  # 26.8.7
    re.compile(r"^(20\d{2})H[12]", re.I),
    re.compile(r"^\d{6,8}(?!\d)"),  # 20200818 / 20230523
]

_DATEISH_THEME = re.compile(
    r"^(20\d{2}|19\d{2}|\d{2}[-./]\d{1,2}|H[12]\b|\d{4,})",
    re.I,
)

_SEP = "-"

# SCAN folders that are teams/archives, not people
_FOLDER_NOT_PERSON = re.compile(
    r"Team|存档|Sharing|分享|FAQ|工作|文档|资料|知识|Archive|Folder|目录|"
    r"Others|Services|Cellular|Automotive|ShortRange|GNSS|Satellite|"
    r"Antenna|QuecOpen|Smart|NorthAmerica|East\s*China|FAE\b",
    re.I,
)

_META_PREAMBLE_KEYS = (
    "文档元数据",
    "原文档名称",
    "文章主题",
    "源文档路径",
    "源路径",
    "源文档创建时间",
    "分类路径",
    "来源文件夹",
    "模块型号",
    "产品线",
    "作者",
    "文档类型",
)


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


def resolve_module_model(
    title: str,
    content: str = "",
    *,
    target_path: str = "",
    llm_module: str = "",
) -> str:
    """Middle segment: regex PN → LLM 主型号/产品 → TARGET L1|L2."""
    module = primary_module(title, content)
    if module:
        return module
    guessed = sanitize_llm_module(llm_module)
    if guessed:
        return guessed
    return target_l1_l2(target_path) or "未知型号"


def resolve_product_line(
    title: str,
    content: str = "",
    *,
    target_path: str = "",
) -> str:
    """Kept for callers that want module or TARGET L1|L2. Display titles use resolve_module_model."""
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


def strip_title_noise(title: str) -> str:
    """Drop leading serial numbers and dates so theme is not 20260730-…."""
    text = (title or "").strip()
    for _ in range(6):
        nxt = text
        for pat in _LEADING_NOISE_PATTERNS:
            nxt = pat.sub("", nxt, count=1).strip()
        nxt = re.sub(r"^[-_./|·\s]+", "", nxt)
        if nxt == text:
            break
        text = nxt
    return text.strip()


def looks_like_date_theme(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return True
    if extract_date_from_title(raw):
        return True
    if _DATEISH_THEME.match(raw):
        return True
    if re.match(r"^\d{4,}", raw):
        return True
    letters = re.sub(r"[\d\s\-./年月日_·]+", "", raw)
    return len(letters) < 2


def title_has_leading_date_noise(title: str) -> bool:
    """True when wiki title still starts with serial/date (needs theme rewrite)."""
    raw = (title or "").strip()
    if not raw:
        return False
    first = re.split(r"[-·]", raw, maxsplit=1)[0].strip()
    if looks_like_date_theme(first):
        return True
    cleaned = strip_title_noise(raw)
    return (not cleaned) or cleaned != raw


def title_looks_like_display_title(title: str) -> bool:
    """True when TARGET title is already 主题-模组型号-作者 (colleague may have finished it)."""
    raw = (title or "").strip()
    if not raw or "未知作者" in raw:
        return False
    if title_has_leading_date_noise(raw):
        return False
    parts = [p.strip() for p in raw.split(_SEP) if p.strip()]
    if len(parts) < 3:
        return False
    theme, module, author = parts[0], parts[1], _SEP.join(parts[2:])
    if looks_like_date_theme(theme):
        return False
    if not module or module == "未知型号":
        return False
    if not author:
        return False
    return True


def strip_metadata_preamble(content: str) -> str:
    """Drop the inline 文档元数据 table so theme LLM reads the article body."""
    lines = (content or "").splitlines()
    if not lines:
        return ""
    start = 0
    for i, line in enumerate(lines[:12]):
        if any(k in line for k in ("文档元数据", "原文档名称", "源文档路径")):
            start = i
            break
    else:
        return content or ""
    kept: list[str] = []
    skipping = True
    for line in lines[start:]:
        s = line.strip()
        if skipping:
            if (not s) or any(s.startswith(k) or k in s[:16] for k in _META_PREAMBLE_KEYS):
                continue
            skipping = False
        kept.append(line)
    return "\n".join(kept).strip() or (content or "")


def _split_person_folder(folder: str) -> tuple[str, str]:
    """Pull 中文名 and English name out of a SCAN person folder (either order)."""
    text = (folder or "").strip()
    m = re.search(r"[\u4e00-\u9fff]{2,4}", text)
    zh = m.group(0) if m else ""
    rest = ((text[: m.start()] + " " + text[m.end() :]) if m else text).strip()
    rest = re.sub(r"[()（）\[\]【】]", " ", rest)
    rest = re.sub(r"^[\s_\-·]+|[\s_\-·]+$", "", rest)
    rest = re.sub(r"[\s_\-·]+", " ", rest).strip()
    en = rest if re.search(r"[A-Za-z]{2,}", rest) else ""
    return zh, en


def _folder_to_person_name(folder: str) -> str:
    """Keep both 中文 and English when the folder has both (吴恩荣_Natalie.Wu)."""
    text = (folder or "").strip()
    if not text or _FOLDER_NOT_PERSON.search(text):
        return ""
    zh, en = _split_person_folder(text)
    if zh and en:
        return f"{zh}·{en}"
    if zh:
        return zh
    if re.match(r"^[A-Z][a-zA-Z.]+(?:\s+[A-Z][a-zA-Z.]+)+$", text):
        return text
    if re.match(r"^[A-Za-z]{2,}(?:\s+[A-Za-z.]{2,})+$", text) and len(text) <= 40:
        return text
    if re.match(r"^[A-Z][a-zA-Z]+(?:[.\s][A-Z][a-zA-Z]+)+$", text) and len(text) <= 40:
        return text
    return ""


def author_from_source_path(source_path: str) -> str:
    """
    SCAN breadcrumb fallback when contact API cannot resolve creator.

    Team folders are usually L1; person folders are L2 or L3
    (e.g. Fei Xie / 吴恩荣_Natalie.Wu / 梁波-Edwin Liang).
    """
    parts = path_segments(source_path)
    if not parts:
        return ""
    ordered = list(parts[1:]) + parts[:1]
    for folder in ordered:
        name = _folder_to_person_name(folder)
        if name:
            return name
    return ""


def _is_bilingual_person(name: str) -> bool:
    text = name or ""
    return bool(re.search(r"[\u4e00-\u9fff]{2,}", text) and re.search(r"[A-Za-z]{2,}", text))


def resolve_author(contact_name: str = "", source_path: str = "") -> str:
    """Prefer SCAN folder when it already has both 中文 and English names."""
    folder_name = author_from_source_path(source_path)
    if _is_bilingual_person(folder_name):
        return folder_name
    text = (contact_name or "").strip()
    if text and not re.match(r"^(ou_|on_|cli_)", text):
        return text
    return folder_name


def _compact_theme_text(text: str, *, max_len: int = 12) -> str:
    """Short theme fragment. Keep CJK compact; keep a few Latin words."""
    text = (text or "").strip().replace(_SEP, "·")
    if not text:
        return ""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk >= 2:
        text = re.sub(r"[\s_]+", "", text)
        return text[:max_len]
    parts = [p for p in re.split(r"[\s\-_/·]+", text) if p]
    phrase = "·".join(parts[:4])
    if len(phrase) > 24:
        phrase = phrase[:24].rstrip("·")
    return phrase


def theme_prompt(title: str, content: str) -> str:
    body = strip_metadata_preamble(content)[:1500]
    cleaned = strip_title_noise(title)
    return (
        "请根据【正文】用中文归纳这篇文章要说明什么、想表达什么。\n"
        "输出一个短主题短语（尽量 ≤8 个汉字，最多 12），不要解释，不要句号。\n"
        "禁止：日期、年份、流水号、文件名、人名；禁止照抄原标题（尤其是以数字/日期开头的标题）。\n"
        "主题应是内容摘要，例如：JSD使用注意 / ODM服务说明 / 项目命名规则 / 模组休眠掉电排查\n\n"
        f"去噪后的标题仅供理解，不要当主题照抄: {cleaned or '(空)'}\n"
        f"正文:\n{body or '(空)'}\n"
    )


def theme_and_module_prompt(title: str, content: str) -> str:
    """One prompt: article theme + primary module/product the doc is about."""
    body = strip_metadata_preamble(content)[:1500]
    cleaned = strip_title_noise(title)
    hits = extract_module_mentions(title, body)
    found = ", ".join(h.token for h in hits[:8]) or "无"
    return (
        "请根据【正文】同时给出两项，各占一行，不要解释，不要句号。\n"
        "主题: <短中文主题，尽量≤8个汉字，最多12；禁止日期/流水号/照抄原标题>\n"
        "型号: <本文主要针对的对象：优先模组PN如 BG95、EC200A、FC41D；"
        "没有 PN 时写产品/平台/项目名，如 JSD、ODM、移远云、QuecThing、RMA；"
        "JSD、ODM、移远云都算型号不要写无；仅当完全没有对象时写无。"
        "禁止写目录名 Cellular/Services>\n"
        "主题示例：JSD使用注意 / ODM服务说明 / 项目命名规则 / 模组休眠掉电排查\n\n"
        f"标题中已用规则扫到的型号（仅供参考）: {found}\n"
        f"去噪后的标题仅供理解，不要当主题照抄: {cleaned or '(空)'}\n"
        f"正文:\n{body or '(空)'}\n"
    )


def parse_theme_module_response(raw: str) -> tuple[str, str]:
    """Parse LLM output into (theme, module). Module may be empty."""
    text = (raw or "").strip()
    if not text:
        return "", ""
    compact = " ".join(text.split())
    m = re.search(
        r"(?:文章)?主题\s*[:：]\s*(.+?)\s+(?:模组|产品)?型号\s*[:：]\s*(.+)$",
        compact,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    theme, module = "", ""
    for line in text.splitlines():
        s = line.strip().strip("-*• ").strip()
        s = re.sub(r"^\d+[\.)、]\s*", "", s)
        if not s:
            continue
        m = re.match(r"^(?:文章)?主题\s*[:：]\s*(.+)$", s)
        if m:
            theme = m.group(1).strip()
            continue
        m = re.match(
            r"^(?:模组|产品)?型号\s*[:：]\s*(.+)$"
            r"|^(?:模组|产品|针对|对象|Model|Module)\s*[:：]\s*(.+)$",
            s,
            re.I,
        )
        if m:
            module = (m.group(1) or m.group(2) or "").strip()
            continue
    if not theme and not module:
        first = text.splitlines()[0].strip()
        if "|" in first:
            left, right = first.split("|", 1)
            theme, module = left.strip(), right.strip()
        else:
            theme = first
    return theme, module


_LLM_MODULE_EMPTY = re.compile(
    r"^(无|没有|未知|空|none|n/?a|-|未知型号|未知产品线|不适用)$",
    re.I,
)
_LLM_MODULE_FOLDER = re.compile(
    r"^(Services|Cellular|Automotive|ShortRange|GNSS|Satellite|"
    r"Antenna|QuecOpen|Smart|Others|WiFi|LTE)$",
    re.I,
)


def sanitize_llm_module(raw: str) -> str:
    """Keep a short PN or product name; drop '无' / folder names / sentences."""
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.splitlines()[0].strip().strip("\"'`。；;,. ")
    text = re.sub(r"^(?:模组|产品|型号)[:：]\s*", "", text)
    text = re.sub(r"(?:模组|模块|产品|系列)$", "", text).strip()
    if not text or _LLM_MODULE_EMPTY.match(text) or _LLM_MODULE_FOLDER.match(text):
        return ""
    if text.startswith("无") or text.startswith("没有"):
        return ""
    if looks_like_date_theme(text):
        return ""
    if text in ("技术文档", "FAQ", "知识分享", "流程规范", "测试认证", "培训材料", "问题跟踪", "其他"):
        return ""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk > 12:
        return ""
    if len(text) > 24:
        text = text[:24]
    return text


# Keep old name for import compatibility
purpose_prompt = theme_prompt


def sanitize_theme(raw: str, *, fallback: str = DEFAULT_DOC_TYPE) -> str:
    text = (raw or "").strip().splitlines()[0].strip().strip("\"'`。；;,. ")
    text = _compact_theme_text(strip_title_noise(text))
    if not text or looks_like_date_theme(text):
        return fallback
    return text


def sanitize_purpose(raw: str, *, fallback: str = DEFAULT_DOC_TYPE) -> str:
    return sanitize_theme(raw, fallback=fallback)


def _unusable_theme_snippet(snippet: str, titles: list) -> bool:
    if not snippet or looks_like_date_theme(snippet):
        return True
    if any(x in snippet for x in ("未知作者", "未知型号", "未知产品线")):
        return True
    for t in titles:
        t = (t or "").strip()
        if not t:
            continue
        if snippet == _compact_theme_text(strip_title_noise(t)):
            return True
        if snippet in t.replace(" ", "") or t.replace(" ", "")[:12] in snippet:
            return True
    return False


def fallback_theme(title: str, content: str = "") -> str:
    """Prefer a content-based phrase; never keep a date/serial prefix."""
    body = strip_metadata_preamble(content)
    dtype = classify_doc_type_by_rules(title, body)
    skip = {
        "文档元数据",
        "产品线",
        "模块型号",
        "源路径",
        "源文档路径",
        "分类路径",
        "作者",
        "原文档名称",
        "文章主题",
        "源文档路径",
        "源文档创建时间",
        "来源文件夹",
        "文档类型",
    }
    titles = [title]
    prev_was_key = False
    for line in body.splitlines():
        raw_line = line.strip()
        if any(raw_line == k or raw_line.startswith(k) for k in _META_PREAMBLE_KEYS):
            prev_was_key = True
            continue
        if prev_was_key:
            prev_was_key = False
            continue
        if extract_date_from_title(raw_line) or looks_like_date_theme(raw_line):
            continue
        if " / " in raw_line or re.match(r"^\d{1,3}\.", raw_line):
            continue
        if _FOLDER_NOT_PERSON.search(raw_line):
            continue
        snippet = _compact_theme_text(strip_title_noise(raw_line))
        snippet = re.sub(r"^本文(将|介绍|说明|描述|主要)?", "", snippet)
        if snippet in skip or _unusable_theme_snippet(snippet, titles):
            continue
        if len(snippet) >= 2:
            return snippet
    cleaned = _compact_theme_text(strip_title_noise(title))
    cleaned = re.sub(r"（持续更新）", "", cleaned)
    cleaned = re.sub(r"\[[Ss]haring\]", "", cleaned)
    cleaned = re.sub(r"··.*$", "", cleaned)
    cleaned = re.sub(r"[·\-](Services|未知作者|未知型号).*$", "", cleaned)
    if cleaned and not looks_like_date_theme(cleaned) and "未知作者" not in cleaned:
        if not re.match(r"^\d", cleaned) and len(cleaned) >= 2:
            return cleaned
    if dtype and dtype != DEFAULT_DOC_TYPE:
        return dtype
    return dtype or DEFAULT_DOC_TYPE


def fallback_purpose(title: str, content: str = "") -> str:
    return fallback_theme(title, content)


def sanitize_author(author: str) -> str:
    """Keep 中文·English; preserve spaces inside English names (Edwin Liang)."""
    text = (author or "").strip()
    text = text.replace(_SEP, "·")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*·\s*", "·", text)
    if not text:
        return "未知作者"
    if len(text) > 40:
        text = text[:40]
    return text


def sanitize_module_model(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+", "", text)
    text = text.replace(_SEP, "·")
    if not text:
        return "未知型号"
    if len(text) > 40:
        text = text[:40]
    return text


def sanitize_product_line(value: str) -> str:
    """Legacy alias used by older display-title rows."""
    text = sanitize_module_model(value)
    if text == "未知型号":
        return "未知产品线" if not (value or "").strip() else text
    return text


def compose_display_title(theme: str, module_model: str, author: str) -> str:
    theme = sanitize_theme(theme)
    module_model = sanitize_module_model(module_model)
    author = sanitize_author(author)
    return f"{theme}{_SEP}{module_model}{_SEP}{author}"


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
    source_title: str = "",
    target_path: str = "",
    llm_module: str = "",
) -> DisplayTitleRow:
    """
    title: current wiki title (TARGET display name after rename).
    source_title: SCAN original title, preferred for theme/module extraction.
    source_path: SCAN breadcrumb (author fallback / path column).
    target_path: TARGET hub breadcrumb (L1|L2 when no module PN / LLM module).
    purpose/theme: optional LLM theme; same meaning.
    llm_module: optional LLM primary module/product when regex finds no PN.
    """
    _ = wiki_node
    theme_src = (source_title or title or "").strip()
    body = strip_metadata_preamble(content)
    fb = fallback_theme(theme_src, body)
    theme_raw = theme if theme is not None else purpose
    if theme_raw is None:
        theme_text = sanitize_theme(fb, fallback=fb)
    else:
        theme_text = sanitize_theme(theme_raw, fallback=fb)
    module = sanitize_module_model(
        resolve_module_model(
            theme_src, body, target_path=target_path, llm_module=llm_module
        )
    )
    author_text = sanitize_author(resolve_author(author, source_path))
    display = compose_display_title(theme_text, module, author_text)
    return DisplayTitleRow(
        original_title=title or "",
        display_title=display,
        obj_token=obj_token or "",
        node_token=node_token or "",
        theme=theme_text,
        product_line=module,
        author=author_text,
        date_part="",
        model_or_path=module,
        purpose=theme_text,
        modules=module if module and module != "未知型号" else "",
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
    "looks_like_date_theme",
    "strip_title_noise",
    "title_has_leading_date_noise",
    "title_looks_like_display_title",
    "author_from_source_path",
    "resolve_author",
    "resolve_module_model",
    "sanitize_module_model",
    "strip_metadata_preamble",
    "parse_theme_module_response",
    "primary_module",
    "purpose_prompt",
    "resolve_model_or_path",
    "resolve_product_line",
    "sanitize_llm_module",
    "sanitize_purpose",
    "sanitize_theme",
    "target_l1_l2",
    "theme_and_module_prompt",
    "theme_prompt",
]
