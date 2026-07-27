# -*- coding: utf-8 -*-
"""Wiki node metadata helpers (owner/creator → display name)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .http import feishu_request
from .token_manager import TokenManager

logger = logging.getLogger(__name__)


class WikiMetaClient:
    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
        self._name_cache: Dict[str, str] = {}

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token_manager.get_token()}"}

    def get_node(self, node_token: str) -> Dict[str, Any]:
        url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
        resp = feishu_request(
            "GET",
            url,
            headers=self._headers(),
            params={"token": node_token},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"get_node failed code={data.get('code')} msg={data.get('msg')}"
            )
        return (data.get("data") or {}).get("node") or {}

    def resolve_user_name(self, user_id: str) -> str:
        """Best-effort display name; falls back to user_id."""
        if not user_id:
            return ""
        if user_id in self._name_cache:
            return self._name_cache[user_id]

        # Try open_id / user_id via contact API
        for id_type in ("open_id", "user_id", "union_id"):
            try:
                url = f"https://open.feishu.cn/open-apis/contact/v3/users/{user_id}"
                resp = feishu_request(
                    "GET",
                    url,
                    headers=self._headers(),
                    params={"user_id_type": id_type},
                    retry_http_errors=False,
                )
                data = resp.json()
                if data.get("code") == 0:
                    user = (data.get("data") or {}).get("user") or {}
                    name = (
                        user.get("name")
                        or user.get("en_name")
                        or user.get("nickname")
                        or ""
                    )
                    if name:
                        self._name_cache[user_id] = name
                        return name
            except Exception as exc:
                logger.debug("contact lookup %s as %s: %s", user_id, id_type, exc)

        self._name_cache[user_id] = user_id
        return user_id

    def get_author_display_name(self, node_token: str) -> str:
        """Prefer owner, then creator, from wiki node."""
        try:
            node = self.get_node(node_token)
        except Exception as exc:
            logger.warning("get_node for author failed %s: %s", node_token, exc)
            return ""

        # Feishu may return owner / creator as string id or nested object
        for key in ("owner", "creator", "obj_edit_time"):  # last is not id
            if key == "obj_edit_time":
                continue
            raw = node.get(key)
            uid = _extract_user_id(raw)
            if uid:
                return self.resolve_user_name(uid)

        # Some tenants expose creator_id / owner_id
        for key in ("owner_id", "creator_id"):
            uid = _extract_user_id(node.get(key))
            if uid:
                return self.resolve_user_name(uid)
        return ""


def _extract_user_id(raw: Any) -> Optional[str]:
    if not raw:
        return None
    if isinstance(raw, str):
        return raw.strip() or None
    if isinstance(raw, dict):
        for k in ("id", "open_id", "user_id", "member_id"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


__all__ = ["WikiMetaClient"]
