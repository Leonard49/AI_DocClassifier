# -*- coding: utf-8 -*-
"""Inspect Feishu Docx blocks for enrichment idempotency."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from enrichment.markers import (
    ATTACHMENT_HEADING_PREFIX,
    ATTACHMENT_SECTION_PREFIX,
    METADATA_HEADING_TITLE,
)
from feishu.http import feishu_request
from feishu.token_manager import TokenManager


def _headers(tm: TokenManager) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {tm.get_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def resolve_docx_id(tm: TokenManager, wiki_node_token: str) -> Optional[str]:
    url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
    resp = feishu_request(
        "GET",
        url,
        headers=_headers(tm),
        params={"token": wiki_node_token},
    )
    data = resp.json()
    if data.get("code") != 0:
        return None
    node = (data.get("data") or {}).get("node") or {}
    if node.get("obj_type") != "docx":
        return None
    return node.get("obj_token")


def list_all_blocks(tm: TokenManager, document_id: str) -> List[Dict[str, Any]]:
    url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{document_id}/blocks"
    items: List[Dict[str, Any]] = []
    page_token = ""
    while True:
        params = {"page_token": page_token} if page_token else None
        resp = feishu_request("GET", url, headers=_headers(tm), params=params)
        if resp.status_code != 200:
            break
        data = resp.json()
        if data.get("code") != 0:
            break
        items.extend((data.get("data") or {}).get("items") or [])
        if not (data.get("data") or {}).get("has_more"):
            break
        page_token = (data.get("data") or {}).get("page_token") or ""
        if not page_token:
            break
    return items


def list_root_children(
    tm: TokenManager, document_id: str
) -> List[Dict[str, Any]]:
    url = (
        f"https://open.feishu.cn/open-apis/docx/v1/documents/"
        f"{document_id}/blocks/{document_id}/children"
    )
    items: List[Dict[str, Any]] = []
    page_token = ""
    while True:
        params = {"page_token": page_token} if page_token else None
        resp = feishu_request("GET", url, headers=_headers(tm), params=params)
        if resp.status_code != 200:
            break
        data = resp.json()
        if data.get("code") != 0:
            break
        items.extend((data.get("data") or {}).get("items") or [])
        if not (data.get("data") or {}).get("has_more"):
            break
        page_token = (data.get("data") or {}).get("page_token") or ""
        if not page_token:
            break
    return items


def _heading_text(block: Dict[str, Any]) -> str:
    for key in (
        "heading1",
        "heading2",
        "heading3",
        "heading4",
        "heading5",
        "heading6",
        "heading7",
        "heading8",
        "heading9",
    ):
        heading = block.get(key) or {}
        parts = [
            (el.get("text_run") or {}).get("content", "")
            for el in heading.get("elements") or []
        ]
        text = "".join(parts).strip()
        if text:
            return text
    return ""


def has_metadata_table(blocks: List[Dict[str, Any]]) -> bool:
    for block in blocks:
        if _heading_text(block) == METADATA_HEADING_TITLE:
            return True
    return False


def metadata_root_span(
    root_children: List[Dict[str, Any]],
) -> Optional[Tuple[int, int]]:
    """
    Return [start, end) indices among root children covering the metadata
    heading and the following table block (if present).
    """
    for i, block in enumerate(root_children):
        if _heading_text(block) != METADATA_HEADING_TITLE:
            continue
        end = i + 1
        if end < len(root_children):
            nxt = root_children[end]
            # 31 = table in Feishu Docx block_type enum
            if int(nxt.get("block_type") or 0) == 31:
                end += 1
        return i, end
    return None


def batch_delete_root_children(
    tm: TokenManager,
    document_id: str,
    *,
    start_index: int,
    end_index: int,
) -> Tuple[bool, str]:
    if end_index <= start_index:
        return True, "empty"
    url = (
        f"https://open.feishu.cn/open-apis/docx/v1/documents/"
        f"{document_id}/blocks/{document_id}/children/batch_delete"
        "?document_revision_id=-1"
    )
    resp = feishu_request(
        "DELETE",
        url,
        headers=_headers(tm),
        json={"start_index": start_index, "end_index": end_index},
    )
    try:
        data = resp.json()
    except Exception:
        return False, f"HTTP {resp.status_code}"
    if data.get("code") == 0:
        return True, "ok"
    return False, f"code={data.get('code')} msg={data.get('msg')}"


def has_attachment_section(blocks: List[Dict[str, Any]]) -> bool:
    for block in blocks:
        if _heading_text(block).startswith(ATTACHMENT_SECTION_PREFIX):
            return True
    return False


def first_attachment_heading_index(
    root_children: List[Dict[str, Any]],
) -> Optional[int]:
    """Index among root children of the first `附件：…` heading."""
    for i, block in enumerate(root_children):
        text = _heading_text(block)
        if text.startswith(ATTACHMENT_HEADING_PREFIX):
            return i
    return None


def insert_children_at(
    tm: TokenManager,
    document_id: str,
    blocks: List[Dict[str, Any]],
    *,
    index: int,
) -> Tuple[bool, str]:
    if not blocks:
        return True, "empty"
    url = (
        f"https://open.feishu.cn/open-apis/docx/v1/documents/"
        f"{document_id}/blocks/{document_id}/children"
        "?document_revision_id=-1"
    )
    # API allows up to 50 children; our banners are small.
    resp = feishu_request(
        "POST",
        url,
        headers=_headers(tm),
        json={"index": index, "children": blocks},
    )
    try:
        data = resp.json()
    except Exception:
        return False, f"HTTP {resp.status_code}"
    if data.get("code") == 0:
        return True, "ok"
    return False, f"code={data.get('code')} msg={data.get('msg')}"
