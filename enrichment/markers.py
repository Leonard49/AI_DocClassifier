# -*- coding: utf-8 -*-
"""Shared markers / block builders for document enrichment steps."""

from __future__ import annotations

from typing import Any, Dict, List

# Metadata table banner (must match feishu.metadata_table heading)
METADATA_HEADING_TITLE = "文档元数据"

# Attachment extract section banner
ATTACHMENT_HEADING_PREFIX = "附件："
ATTACHMENT_SECTION_TITLE = "【附件提取】以下内容由系统从附件自动提取"
ATTACHMENT_SECTION_PREFIX = "【附件提取】"

_DIVIDER: Dict[str, Any] = {"block_type": 22, "divider": {}}


def attachment_section_blocks() -> List[Dict[str, Any]]:
    """Eye-catching separator placed before extracted attachment content."""
    return [
        dict(_DIVIDER),
        {
            "block_type": 3,
            "heading1": {
                "elements": [
                    {
                        "text_run": {
                            "content": ATTACHMENT_SECTION_TITLE,
                            "text_element_style": {"bold": True},
                        }
                    }
                ]
            },
        },
        {
            "block_type": 2,
            "text": {
                "elements": [
                    {
                        "text_run": {
                            "content": (
                                "▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼"
                            ),
                            "text_element_style": {"bold": True},
                        }
                    }
                ]
            },
        },
        dict(_DIVIDER),
    ]
