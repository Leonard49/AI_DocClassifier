# -*- coding: utf-8 -*-
"""Extract document metadata: product line (tag1), modules, doc type, author."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import List, Optional, Sequence, Tuple

from .module_product_map import (
    PRODUCT_LINES,
    detect_product_line,
    extract_module_mentions,
)

DOC_TYPES: Tuple[str, ...] = (
    "技术文档",
    "FAQ",
    "知识分享",
    "流程规范",
    "测试认证",
    "培训材料",
    "问题跟踪",
    "其他",
)

DEFAULT_DOC_TYPE = "其他"
DEFAULT_PRODUCT_LINE = "Others"

_DOC_TYPE_RULES: List[Tuple[str, List[re.Pattern]]] = [
    (
        "问题跟踪",
        [
            re.compile(
                r"Issue\s*Tracking|客户问题|重点客户跟踪|Customer\s*Issue|关闭问题|新增问题",
                re.I,
            ),
        ],
    ),
    (
        "FAQ",
        [
            re.compile(r"\bFAQ\b|常见问题|排障|troubleshooting", re.I),
        ],
    ),
    (
        "流程规范",
        [
            re.compile(
                r"流程|规范|SOP|checklist|步骤|申请流程|Jira|共享盘|周报|日报|会议纪要",
                re.I,
            ),
        ],
    ),
    (
        "培训材料",
        [
            re.compile(r"培训|新人|onboarding|自学计划|学习参考", re.I),
        ],
    ),
    (
        "测试认证",
        [
            re.compile(r"测试|验证|ESD|兼容|认证|certif|compliance|用例", re.I),
        ],
    ),
    (
        "知识分享",
        [
            re.compile(
                r"工作分享|分享主题|技术小站|学习总结|学习文档|心得|"
                r"G[_-][A-Z]{2}\d+|简介|介绍",
                re.I,
            ),
        ],
    ),
    (
        "技术文档",
        [
            re.compile(
                r"技术|调试|驱动|SDK|API|原理|配置|移植|编译|BSP|QuecOpen|"
                r"OpenLinux|datasheet|spec|AT指令|指令",
                re.I,
            ),
        ],
    ),
]


@dataclass
class DocMetadata:
    title: str
    obj_token: str
    node_token: str
    product_line: str
    modules: str
    doc_type: str
    author: str
    source_folder: str
    source_path: str
    wiki_url: str

    def to_dict(self) -> dict:
        return asdict(self)


def classify_doc_type_by_rules(title: str, content: str = "") -> Optional[str]:
    text = f"{title or ''}\n{(content or '')[:2000]}"
    for dtype, patterns in _DOC_TYPE_RULES:
        for pat in patterns:
            if pat.search(text):
                return dtype
    return None


def doc_type_prompt(title: str, content: str) -> str:
    body = (content or "")[:1200]
    return (
        "请把下面文档归入且仅归入下列「文档类型」之一。"
        "只输出类型名称本身，不要解释。\n\n"
        "可选类型:\n- " + "\n- ".join(DOC_TYPES) + "\n\n"
        f"标题: {title or '(无)'}\n"
        f"正文摘录:\n{body or '(无)'}\n"
    )


def parse_doc_type_response(raw: str) -> str:
    text = (raw or "").strip().splitlines()[0].strip().strip("\"'`")
    for name in DOC_TYPES:
        if text == name or name in text:
            return name
    return DEFAULT_DOC_TYPE


def format_module_models(title: str, content: str = "", *, limit: int = 12) -> str:
    hits = extract_module_mentions(title, content)
    seen = set()
    tokens: List[str] = []
    for h in hits:
        key = h.token.upper()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(h.token)
        if len(tokens) >= limit:
            break
    return ", ".join(tokens)


def resolve_product_line(title: str, content: str = "") -> str:
    line = detect_product_line(title, content)
    if line and line in PRODUCT_LINES:
        return line
    if line:
        return line
    return DEFAULT_PRODUCT_LINE


def build_wiki_url(node_token: str) -> str:
    if not node_token:
        return ""
    return f"https://feishu.cn/wiki/{node_token}"


def extract_doc_metadata(
    *,
    title: str,
    content: str,
    obj_token: str,
    node_token: str,
    source_folder: str = "",
    source_path: str = "",
    author: str = "",
    doc_type: Optional[str] = None,
) -> DocMetadata:
    dtype = doc_type or classify_doc_type_by_rules(title, content) or DEFAULT_DOC_TYPE
    return DocMetadata(
        title=title or "",
        obj_token=obj_token or "",
        node_token=node_token or "",
        product_line=resolve_product_line(title, content),
        modules=format_module_models(title, content),
        doc_type=dtype,
        author=author or "",
        source_folder=source_folder or "",
        source_path=source_path or "",
        wiki_url=build_wiki_url(node_token),
    )


__all__ = [
    "DOC_TYPES",
    "DEFAULT_DOC_TYPE",
    "DEFAULT_PRODUCT_LINE",
    "PRODUCT_LINES",
    "DocMetadata",
    "classify_doc_type_by_rules",
    "doc_type_prompt",
    "parse_doc_type_response",
    "format_module_models",
    "resolve_product_line",
    "build_wiki_url",
    "extract_doc_metadata",
]
