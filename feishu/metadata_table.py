# -*- coding: utf-8 -*-
"""Insert a document-metadata key/value table at the top of a Feishu Docx."""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional, Sequence, Tuple

from classify.doc_metadata import DocMetadata
from .add_tag_block import FeishuDocumentTagAdder
from .http import feishu_request
from .token_manager import TokenManager

logger = logging.getLogger(__name__)

_HEADING_TITLE = "文档元数据"


def _tmp_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _text_block(block_id: str, content: str, *, bold: bool = False) -> dict:
    text_run: dict = {"content": content if content is not None else ""}
    if bold:
        text_run["text_element_style"] = {"bold": True}
    return {
        "block_id": block_id,
        "block_type": 2,
        "text": {"elements": [{"text_run": text_run}]},
        "children": [],
    }


class MetadataTableInserter:
    """Paste metadata as a 2-column table at the start of the target Docx."""

    def __init__(self, token_manager: TokenManager, timeout: int = 60):
        self.token_manager = token_manager
        self.timeout = timeout
        self._resolver = FeishuDocumentTagAdder(token_manager, timeout=timeout)
        self.base_url = "https://open.feishu.cn/open-apis/docx/v1/documents"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def insert_at_document_start(
        self,
        *,
        document_id: Optional[str] = None,
        wiki_node_token: Optional[str] = None,
        rows: Sequence[Tuple[str, str]],
        heading: str = _HEADING_TITLE,
        index: int = 0,
    ) -> bool:
        """
        Insert heading + key/value table at document top.

        Prefer wiki_node_token of the *copied* target node so we resolve its
        docx obj_token correctly.
        """
        doc_id = document_id
        if wiki_node_token:
            resolved = self._resolver.resolve_document_id(wiki_node_token)
            if not resolved:
                logger.error("无法解析目标文档 ID: %s", wiki_node_token)
                return False
            doc_id = resolved
        if not doc_id:
            logger.error("缺少 document_id / wiki_node_token")
            return False
        if not rows:
            logger.warning("元数据行为空，跳过插入")
            return False

        payload = self._build_descendant_payload(rows, heading=heading, index=index)
        url = (
            f"{self.base_url}/{doc_id}/blocks/{doc_id}/descendant"
            "?document_revision_id=-1"
        )
        try:
            resp = feishu_request(
                "POST",
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            data = resp.json()
        except Exception as exc:
            logger.error("插入元数据表请求异常: %s", exc)
            return False

        if data.get("code") == 0:
            logger.info("元数据表已写入文档 %s", doc_id)
            return True
        logger.error(
            "插入元数据表失败: code=%s msg=%s",
            data.get("code"),
            data.get("msg"),
        )
        return False

    def insert_from_metadata(
        self,
        meta: DocMetadata,
        *,
        wiki_node_token: str,
        heading: str = _HEADING_TITLE,
    ) -> bool:
        return self.insert_at_document_start(
            wiki_node_token=wiki_node_token,
            rows=meta.table_rows(),
            heading=heading,
        )

    def _build_descendant_payload(
        self,
        rows: Sequence[Tuple[str, str]],
        *,
        heading: str,
        index: int,
    ) -> dict:
        heading_id = _tmp_id("heading")
        table_id = _tmp_id("table")
        descendants: List[dict] = [
            {
                "block_id": heading_id,
                "block_type": 4,  # heading2
                "heading2": {
                    "elements": [{"text_run": {"content": heading}}],
                },
                "children": [],
            },
            {
                "block_id": table_id,
                "block_type": 31,
                "table": {
                    "property": {
                        "row_size": len(rows),
                        "column_size": 2,
                    }
                },
                "children": [],
            },
        ]

        cell_ids: List[str] = []
        for key, value in rows:
            key_cell = _tmp_id("cell")
            val_cell = _tmp_id("cell")
            key_text = _tmp_id("text")
            val_text = _tmp_id("text")
            cell_ids.extend([key_cell, val_cell])

            descendants.append(
                {
                    "block_id": key_cell,
                    "block_type": 32,
                    "table_cell": {},
                    "children": [key_text],
                }
            )
            descendants.append(
                {
                    "block_id": val_cell,
                    "block_type": 32,
                    "table_cell": {},
                    "children": [val_text],
                }
            )
            descendants.append(_text_block(key_text, str(key), bold=True))
            descendants.append(_text_block(val_text, str(value)))

        # Wire table -> cells
        for block in descendants:
            if block["block_id"] == table_id:
                block["children"] = cell_ids
                break

        return {
            "index": index,
            "children_id": [heading_id, table_id],
            "descendants": descendants,
        }


__all__ = ["MetadataTableInserter"]
