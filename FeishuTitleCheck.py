import threading
import requests
from collections import Counter
from typing import Dict, List, Optional, Tuple
from TokenManager import TokenManager


class FolderNameChecker:
    """飞书知识库节点重复检查器（基于 requests，带子节点列表缓存）"""

    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
        self._children_cache: Dict[Tuple[str, str], Dict[str, str]] = {}
        self._cache_lock = threading.Lock()

    def _cache_key(self, space_id: str, parent_node_token: Optional[str]) -> Tuple[str, str]:
        return (space_id, parent_node_token or "")

    def invalidate_children(self, space_id: str, parent_node_token: Optional[str] = None) -> None:
        """创建子节点后调用，使该父节点下的缓存失效。"""
        key = self._cache_key(space_id, parent_node_token)
        with self._cache_lock:
            self._children_cache.pop(key, None)

    def list_children(
        self, space_id: str, parent_node_token: Optional[str] = None
    ) -> Dict[str, str]:
        """列出父节点下直接子节点：title -> node_token（带内存缓存）。"""
        key = self._cache_key(space_id, parent_node_token)
        with self._cache_lock:
            if key in self._children_cache:
                return self._children_cache[key]

        access_token = self.token_manager.get_token()
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}/nodes"
        headers = {"Authorization": f"Bearer {access_token}"}
        children: Dict[str, str] = {}
        page_token = None

        while True:
            params: Dict = {"page_size": 50}
            if parent_node_token:
                params["parent_node_token"] = parent_node_token
            if page_token:
                params["page_token"] = page_token

            try:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                raise Exception(f"调用飞书 API 失败: {e}") from e

            if data.get("code") != 0:
                raise Exception(f"API 返回错误: code={data.get('code')}, msg={data.get('msg')}")

            for item in data.get("data", {}).get("items", []):
                title = item.get("title")
                node_token = item.get("node_token")
                if title and node_token:
                    children[title] = node_token

            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token")

        with self._cache_lock:
            self._children_cache[key] = children
        return children

    def get_child_token(
        self, space_id: str, target_name: str, parent_node_token: Optional[str] = None
    ) -> Optional[str]:
        return self.list_children(space_id, parent_node_token).get(target_name)

    def check_duplicate(
        self,
        space_id: str,
        target_name: str,
        parent_node_token: Optional[str] = None,
    ) -> Dict:
        """
        判断知识库指定父节点下是否存在同名子节点

        :return: 包含 is_duplicate、node_token（若存在）等字段的字典
        """
        children = self.list_children(space_id, parent_node_token)
        all_titles = list(children.keys())
        is_duplicate = target_name in children
        name_counts = Counter(all_titles)
        duplicates = [name for name, count in name_counts.items() if count > 1]

        return {
            "is_duplicate": is_duplicate,
            "node_token": children.get(target_name),
            "target_name": target_name,
            "duplicates": duplicates,
            "total_count": len(all_titles),
            "all_titles": all_titles,
        }


