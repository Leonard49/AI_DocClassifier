import requests
from typing import Dict, Optional
from TokenManager import TokenManager
class FeishuWikiNodeFinder:
    """飞书知识库节点查找器（支持按标题查找节点及其父节点 token）"""

    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
    
    def _get_tenant_access_token(self) -> str:
        return self.token_manager.get_token()

    def find_node_by_title(
        self, space_id: str, target_title: str, start_parent_token: Optional[str] = None
    ) -> Optional[Dict]:
        """
        在知识库中根据节点标题查找节点详情（包含父节点token）。

        :param space_id:           知识空间 ID
        :param target_title:       需要查找的节点标题
        :param start_parent_token: 开始搜索的父节点 token，传 None 表示从根节点开始搜索
        :return:                   包含节点详细信息的字典，未找到返回 None
        """
        access_token = self._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}/nodes"
        headers = {"Authorization": f"Bearer {access_token}"}

        # BFS 遍历节点树
        nodes_to_visit = [start_parent_token] if start_parent_token else [None]
        visited_nodes = set()

        while nodes_to_visit:
            current_parent = nodes_to_visit.pop(0)
            page_token = None

            while True:
                params = {"page_size": 50}
                if current_parent:
                    params["parent_node_token"] = current_parent
                if page_token:
                    params["page_token"] = page_token

                try:
                    resp = requests.get(url, headers=headers, params=params, timeout=10)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    raise Exception(f"调用飞书 API 失败: {e}")

                if data.get("code") != 0:
                    raise Exception(f"API 返回错误: code={data.get('code')}, msg={data.get('msg')}")

                items = data.get("data", {}).get("items", [])
                for item in items:
                    node_token = item.get("node_token")
                    if node_token and node_token not in visited_nodes:
                        visited_nodes.add(node_token)
                        # 检查是否匹配目标标题
                        if item.get("title") == target_title:
                            return {
                                "node_token": node_token,
                                "parent_node_token": current_parent,
                                "title": item.get("title"),
                                "obj_type": item.get("obj_type"),
                                "node_type": item.get("node_type"),
                            }
                        # 如果节点可能有子节点，将其加入待遍历队列
                        if item.get("has_child") or item.get("node_type") == "origin":
                            nodes_to_visit.append(node_token)

                # 分页判断
                if not data.get("data", {}).get("has_more"):
                    break
                page_token = data.get("data", {}).get("page_token")

        return None

    def get_parent_token_by_node_name(
        self, space_id: str, target_name: str, start_parent_token: Optional[str] = None
    ) -> Dict:
        """
        根据节点名称获取其父节点 token。

        :param space_id:           知识空间 ID
        :param target_name:        需要查找的节点名称
        :param start_parent_token: 开始搜索的父节点 token，传 None 表示从根节点开始搜索
        :return:                   包含查找结果的字典
        """
        node_info = self.find_node_by_title(space_id, target_name, start_parent_token)

        if node_info:
            return {
                "found": True,
                "node_token": node_info["node_token"],
                "parent_node_token": node_info["parent_node_token"],
                "title": node_info["title"],
                "message": "节点已找到",
            }
        else:
            return {
                "found": False,
                "parent_node_token": None,
                "message": f"未找到名称为 '{target_name}' 的节点",
            }


# if __name__ == "__main__":
#     # 使用示例
#     APP_ID = "cli_a93910bbc5f95cc2"
#     APP_SECRET = "srbaL4nDLMAoEa9jYFQMrhtipJv2ZfvD"
#     SPACE_ID = "7540196657544347650"
#     START_PARENT_TOKEN = "OlTJwD9J0iO8gdkdkFIc6EUfnPg"   # 可选，限制搜索范围
#     TARGET_NAME = "TEST1"

#     finder = FeishuWikiNodeFinder(APP_ID, APP_SECRET)

#     # 方式1：直接获取父节点 token
#     result = finder.get_parent_token_by_node_name(
#         space_id=SPACE_ID,
#         target_name=TARGET_NAME,
#         start_parent_token=START_PARENT_TOKEN,
#     )
#     print(result)

#     # 方式2：获取完整节点信息
#     node = finder.find_node_by_title(
#         space_id=SPACE_ID,
#         target_title=TARGET_NAME,
#         start_parent_token=START_PARENT_TOKEN,
#     )
#     if node:
#         print(f"找到节点：{node}")
#     else:
#         print("未找到节点")