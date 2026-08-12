# -*- coding: utf-8 -*-
"""Wiki node metadata helpers (owner/creator → display name, source path)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, Optional, Set

from .http import feishu_request
from .token_manager import TokenManager

logger = logging.getLogger(__name__)

_OPEN_ID_RE = re.compile(r"^(ou_|on_|cli_)[A-Za-z0-9]+$")


class WikiMetaClient:
    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
        self._name_cache: Dict[str, str] = {}
        self._node_cache: Dict[str, Dict[str, Any]] = {}

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token_manager.get_token()}"}

    def get_node(self, node_token: str) -> Dict[str, Any]:
        token = (node_token or "").strip()
        if not token:
            return {}
        if token in self._node_cache:
            return self._node_cache[token]
        url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
        resp = feishu_request(
            "GET",
            url,
            headers=self._headers(),
            params={"token": token},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"get_node failed code={data.get('code')} msg={data.get('msg')}"
            )
        node = (data.get("data") or {}).get("node") or {}
        self._node_cache[token] = node
        return node

    def resolve_user_name(self, user_id: str) -> str:
        """Best-effort display name; empty string if unresolvable (never return raw id)."""
        if not user_id:
            return ""
        if user_id in self._name_cache:
            return self._name_cache[user_id]

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
                    if name and not _looks_like_user_id(name):
                        self._name_cache[user_id] = name
                        return name
            except Exception as exc:
                logger.debug("contact lookup %s as %s: %s", user_id, id_type, exc)

        # Do not paste ou_xxx into metadata tables.
        self._name_cache[user_id] = ""
        return ""

    def get_author_display_name(self, node_token: str) -> str:
        """Prefer document creator (author), then node_creator, then owner."""
        try:
            node = self.get_node(node_token)
        except Exception as exc:
            logger.warning("get_node for author failed %s: %s", node_token, exc)
            return ""

        for key in ("creator", "node_creator", "owner", "creator_id", "owner_id"):
            uid = _extract_user_id(node.get(key))
            if uid:
                name = self.resolve_user_name(uid)
                if name:
                    return name
        return ""

    def update_title(self, space_id: str, node_token: str, title: str) -> None:
        """Rename a wiki node (TARGET copy). Does not touch source SCAN nodes."""
        sid = (space_id or "").strip()
        token = (node_token or "").strip()
        new_title = (title or "").strip()
        if not sid or not token:
            raise ValueError("space_id / node_token required")
        if not new_title:
            raise ValueError("title is empty")
        # Feishu wiki title practical limit
        if len(new_title) > 800:
            new_title = new_title[:797] + "..."
        url = (
            f"https://open.feishu.cn/open-apis/wiki/v2/spaces/"
            f"{sid}/nodes/{token}/update_title"
        )
        resp = feishu_request(
            "POST",
            url,
            headers={
                **self._headers(),
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"title": new_title},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"update_title failed code={data.get('code')} msg={data.get('msg')}"
            )
        # Invalidate cache so subsequent get_node sees new title
        self._node_cache.pop(token, None)

    def build_folder_path(
        self,
        node_token: str,
        *,
        stop_at_tokens: Optional[Iterable[str]] = None,
        max_depth: int = 40,
    ) -> str:
        """
        Breadcrumb of folder titles from scan root down to the doc's parent.

        Mirrors SimpleWikiScanner._build_source_path, but walks via get_node.
        Stops after including a token listed in stop_at_tokens (typically SCAN roots).
        """
        token = (node_token or "").strip()
        if not token:
            return ""
        stops: Set[str] = {t.strip() for t in (stop_at_tokens or []) if t and t.strip()}
        try:
            node = self.get_node(token)
        except Exception as exc:
            logger.warning("get_node for path failed %s: %s", token, exc)
            return ""

        current = (node.get("parent_node_token") or "").strip() or None
        parts: list[str] = []
        visited: Set[str] = set()
        depth = 0
        while current and current not in visited and depth < max_depth:
            visited.add(current)
            depth += 1
            try:
                info = self.get_node(current)
            except Exception:
                break
            title = (info.get("title") or "").strip()
            if title:
                parts.append(title)
            if current in stops:
                break
            parent = (info.get("parent_node_token") or "").strip()
            current = parent or None
        parts.reverse()
        return " / ".join(parts)


def _looks_like_user_id(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if _OPEN_ID_RE.match(text):
        return True
    # Long opaque ids without CJK / spaces are usually not display names.
    if len(text) >= 20 and " " not in text and not re.search(r"[\u4e00-\u9fff]", text):
        return True
    return False


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
