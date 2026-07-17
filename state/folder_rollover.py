"""Rollover leaf folders when Feishu single-layer node limit (131003) is hit."""

from __future__ import annotations

import re
import threading
from typing import Callable, Optional, Tuple

from .shared_folder_rollover import SharedFolderRolloverStore

# Feishu wiki: too many direct children under one parent
FEISHU_NODE_LIMIT_CODE = 131003


def is_node_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "131003" in text:
        return True
    if "out of limit" in text and "single-layer" in text:
        return True
    if "单层" in str(exc) and ("上限" in str(exc) or "超限" in str(exc)):
        return True
    code = getattr(exc, "feishu_code", None)
    return code == FEISHU_NODE_LIMIT_CODE


def part_index_from_title(base_name: str, title: str) -> int:
    if title == base_name:
        return 1
    m = re.search(r"\((\d+)\)$", title or "")
    return int(m.group(1)) if m else 1


class FolderRolloverManager:
    """
    Keep an active leaf folder per (parent_token, base_name).

    When copy/create hits Feishu 131003, create a sibling folder named
    ``{base} (2)``, ``{base} (3)``, … under the same parent and route
    subsequent documents of that type there.

    Optional ``shared_store`` syncs the active bucket across workers.
    """

    def __init__(
        self,
        ensure_folder: Callable[[Optional[str], str], Optional[str]],
        *,
        max_parts: int = 50,
        shared_store: Optional[SharedFolderRolloverStore] = None,
    ):
        self._ensure_folder = ensure_folder
        self._max_parts = max_parts
        self._shared = shared_store
        self._lock = threading.Lock()
        # (parent_token, base_name) -> (active_token, active_title)
        self._active: dict[Tuple[str, str], Tuple[str, str]] = {}

    @staticmethod
    def _key(parent_token: Optional[str], base_name: str) -> Tuple[str, str]:
        return (parent_token or "", base_name)

    @staticmethod
    def base_folder_name(name: str) -> str:
        """Strip trailing ' (N)' suffix to recover the logical type name."""
        return re.sub(r"\s+\(\d+\)$", "", (name or "").strip()) or name

    def _remember(
        self,
        parent_token: Optional[str],
        base_name: str,
        token: str,
        title: str,
    ) -> Tuple[str, str]:
        key = self._key(parent_token, base_name)
        with self._lock:
            self._active[key] = (token, title)
        if self._shared:
            self._shared.set_active(
                parent_token,
                base_name,
                token,
                title,
                part_index_from_title(base_name, title),
            )
        return token, title

    def resolve(
        self,
        parent_token: Optional[str],
        base_name: str,
    ) -> Optional[Tuple[str, str]]:
        """Return (folder_token, folder_title) for the active bucket."""
        key = self._key(parent_token, base_name)
        with self._lock:
            if key in self._active:
                return self._active[key]

        if self._shared:
            shared = self._shared.get_active(parent_token, base_name)
            if shared:
                token, title, _ = shared
                with self._lock:
                    self._active[key] = (token, title)
                return token, title

        token = self._ensure_folder(parent_token, base_name)
        if not token:
            return None
        return self._remember(parent_token, base_name, token, base_name)

    def rollover(
        self,
        parent_token: Optional[str],
        base_name: str,
    ) -> Optional[Tuple[str, str]]:
        """
        Create / switch to the next sibling bucket after a node-limit error.
        Returns the new (token, title) or None.
        """
        key = self._key(parent_token, base_name)
        start_n = 2
        with self._lock:
            current = self._active.get(key)
        if current:
            start_n = max(2, part_index_from_title(base_name, current[1]) + 1)
        elif self._shared:
            start_n = self._shared.next_part_index(parent_token, base_name)

        for n in range(start_n, self._max_parts + 2):
            title = f"{base_name} ({n})"
            token = self._ensure_folder(parent_token, title)
            if not token:
                continue
            result = self._remember(parent_token, base_name, token, title)
            print(
                f"📂 单层节点超限，已切换同类型文件夹: "
                f"'{base_name}' → '{title}'"
            )
            return result
        print(f"❌ 无法为 '{base_name}' 创建更多分卷文件夹（已尝试至 {self._max_parts}）")
        return None
