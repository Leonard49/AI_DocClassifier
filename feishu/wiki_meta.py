# -*- coding: utf-8 -*-
"""Wiki node metadata helpers (owner/creator → display name, source path)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Sequence, Set

from .http import feishu_request
from .token_manager import TokenManager

logger = logging.getLogger(__name__)

_OPEN_ID_RE = re.compile(r"^(ou_|on_|cli_)[A-Za-z0-9]+$")


class WikiMetaClient:
    _contact_denied_logged = False

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

        last_err = ""
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
                else:
                    last_err = f"code={data.get('code')} msg={data.get('msg')}"
            except Exception as exc:
                last_err = str(exc)
                logger.debug("contact lookup %s as %s: %s", user_id, id_type, exc)

        if last_err and not WikiMetaClient._contact_denied_logged:
            WikiMetaClient._contact_denied_logged = True
            logger.warning("通讯录无法解析作者（%s）；回退 SCAN 源路径文件夹人名", last_err)
            print(
                f"⚠️ 通讯录读不到作者（{last_err}）。"
                "应用需 contact:user.base:readonly 且用户在通讯录可用范围内；"
                "将改用源路径一级/二级文件夹人名。",
                flush=True,
            )
        self._name_cache[user_id] = ""
        return ""

    def get_author_display_name(
        self, node_token: str, *, source_path: str = ""
    ) -> str:
        """Prefer document creator display name; else SCAN folder person name."""
        if node_token:
            try:
                node = self.get_node(node_token)
            except Exception as exc:
                logger.warning("get_node for author failed %s: %s", node_token, exc)
                node = {}
            for key in ("creator", "node_creator", "owner", "creator_id", "owner_id"):
                uid = _extract_user_id((node or {}).get(key))
                if uid:
                    name = self.resolve_user_name(uid)
                    if name:
                        return name
        if source_path:
            path = source_path
        elif node_token:
            path = self.build_folder_path(node_token)
        else:
            path = ""
        if path:
            from classify.display_title import author_from_source_path

            return author_from_source_path(path)
        return ""

    def source_identity(self, source_node_token: str) -> Dict[str, Any]:
        """SCAN source title + create time from one get_node (cached)."""
        out: Dict[str, Any] = {"title": "", "created_at": "", "created_ms": 0}
        token = (source_node_token or "").strip()
        if not token:
            return out
        try:
            node = self.get_node(token)
        except Exception as exc:
            logger.warning("get_node for source identity failed %s: %s", token, exc)
            return out
        out["title"] = (node.get("title") or "").strip()
        ms = wiki_node_millis(node)
        out["created_ms"] = ms
        out["created_at"] = format_wiki_datetime(ms)
        return out

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


def wiki_node_unix_seconds(
    node: Optional[Dict[str, Any]],
    keys: Sequence[str] = ("obj_create_time", "node_create_time"),
) -> Optional[int]:
    if not node:
        return None
    for key in keys:
        raw = node.get(key)
        if raw is None or raw == "":
            continue
        try:
            ts = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if ts > 10_000_000_000:
            ts //= 1000
        if ts > 0:
            return ts
    return None


def wiki_node_millis(node: Optional[Dict[str, Any]]) -> int:
    sec = wiki_node_unix_seconds(node)
    return int(sec * 1000) if sec else 0


def format_wiki_datetime(ts: Optional[int], fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not ts:
        return ""
    seconds = int(ts)
    if seconds > 10_000_000_000:
        seconds //= 1000
    try:
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone()
        return dt.strftime(fmt)
    except (OverflowError, OSError, ValueError):
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


__all__ = [
    "WikiMetaClient",
    "format_wiki_datetime",
    "wiki_node_millis",
    "wiki_node_unix_seconds",
]
