# 创建节点
# 2026-05-13
# Linkin WANG
from typing import Optional, Tuple

import requests

from .token_manager import TokenManager


class FeishuNodeCreator:
    def __init__(self, token_manager: TokenManager, space_id: str):
        self.token_manager = token_manager
        self.space_id = space_id
        """
        初始化
            token_manager: TokenManager 实例
            space_id: 知识库的 space_id
        """

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json",
        }

    def create_lark_node(
        self,
        node_token: str,
        title: str,
        *,
        obj_type: str = "docx",
    ) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
        """
        在指定父节点下创建一个新节点。

        Args:
            node_token: 父节点 token；空字符串则创建到空间根
            title: 节点标题
            obj_type: wiki 对象类型，默认 docx；多维表格用 bitable

        Returns:
            (response_data, new_node_token, new_title)；失败时 token/title 为 None
        """
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{self.space_id}/nodes"
        headers = self._get_headers()

        payload = {
            "obj_type": obj_type,
            "parent_node_token": node_token,
            "node_type": "origin",
            "title": title,
        }

        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response_data = response.json()
        if response_data.get("code") == 0:
            node = response_data["data"]["node"]
            new_node_token = node["node_token"]
            new_title = node.get("title") or title
            print(f"节点创建成功！新节点 token: {new_node_token} ({obj_type})")
            print(f"节点创建成功！新节点 title: {new_title}")
            return (response_data, new_node_token, new_title)

        print(f"节点创建失败: {response_data.get('msg', '未知错误')}")
        return response_data, None, None
