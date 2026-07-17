"""Resolve classification tag paths to Feishu folder tokens (with rollover)."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from feishu.create_feishu_node import FeishuNodeCreator
from feishu.title_check import FolderNameChecker
from .folder_rollover import FolderRolloverManager, is_node_limit_error


def ensure_child_folder(
    creator: FeishuNodeCreator,
    name_checker: FolderNameChecker,
    space_id: str,
    parent_token: Optional[str],
    folder_name: str,
    *,
    max_retries: int = 3,
) -> Optional[str]:
    for attempt in range(max_retries):
        dup = name_checker.check_duplicate(space_id, folder_name, parent_token)
        if dup["is_duplicate"]:
            token = dup.get("node_token")
            if token:
                print(f"✅ 找到已存在的节点: {folder_name}")
                return token
            return None

        _, token, new_title = creator.create_lark_node(parent_token or "", folder_name)
        if token:
            name_checker.invalidate_children(space_id, parent_token)
            print(f"✅ 创建新节点: {new_title}")
            return token

        name_checker.invalidate_children(space_id, parent_token)
        if attempt < max_retries - 1:
            print(f"⚠️ 创建文件夹失败，重试 ({attempt + 2}/{max_retries}): {folder_name}")
    return None


def resolve_tag_leaf_folder(
    tag: Dict,
    *,
    creator: FeishuNodeCreator,
    name_checker: FolderNameChecker,
    space_id: str,
    target_root_token: Optional[str],
    rollover: Optional[FolderRolloverManager] = None,
) -> Optional[Tuple[str, Optional[str], str, str]]:
    """
    Walk tag1→tag2→tag3 and return:
      (leaf_folder_token, leaf_parent_token, leaf_base_name, active_title)
    """
    levels = []
    idx = 1
    while True:
        key = f"tag{idx}"
        if key not in tag or not tag[key]:
            break
        levels.append(tag[key][0])
        idx += 1
    if not levels:
        return None

    parent = target_root_token
    leaf_parent = target_root_token
    active_title = levels[-1]
    leaf_token: Optional[str] = None

    for i, name in enumerate(levels):
        is_leaf = i == len(levels) - 1
        if rollover is not None:
            resolved = rollover.resolve(parent, name)
            if not resolved:
                return None
            token, title = resolved
        else:
            token = ensure_child_folder(
                creator, name_checker, space_id, parent, name
            )
            if not token:
                return None
            title = name

        if is_leaf:
            leaf_parent = parent
            leaf_token = token
            active_title = title
            return leaf_token, leaf_parent, name, active_title
        parent = token

    return None


__all__ = [
    "ensure_child_folder",
    "resolve_tag_leaf_folder",
    "is_node_limit_error",
]
