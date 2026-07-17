"""Feishu wiki node move helper."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

import requests

from .copy_doc import FeishuCopyError
from .token_manager import TokenManager


class FeishuWikiMover:
    """Move a wiki node under a new parent (same or other space)."""

    def __init__(self, token_manager: TokenManager, space_id: str):
        self.token_manager = token_manager
        self.space_id = space_id

    def move_node(
        self,
        node_token: str,
        target_parent_token: str,
        *,
        target_space_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        space = self.space_id
        url = (
            f"https://open.feishu.cn/open-apis/wiki/v2/spaces/"
            f"{space}/nodes/{node_token}/move"
        )
        headers = {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "target_parent_token": target_parent_token,
            "target_space_id": target_space_id or space,
        }
        print(f"POST: {url}")
        print(f"Request body: {json.dumps(payload, ensure_ascii=False)}")
        response = requests.post(url, json=payload, headers=headers, timeout=90)
        try:
            result = response.json()
        except Exception:
            result = {"raw": response.text}
        print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")

        if response.status_code >= 400 or result.get("code", 0) != 0:
            code = result.get("code") if isinstance(result, dict) else None
            msg = (
                result.get("msg", response.reason)
                if isinstance(result, dict)
                else response.reason
            )
            print(f"ERROR: 移动节点失败 code={code} msg={msg}", file=sys.stderr)
            raise FeishuCopyError(
                f"failed to move node: code={code} msg={msg}",
                feishu_code=code,
                body=result,
            )
        return result
