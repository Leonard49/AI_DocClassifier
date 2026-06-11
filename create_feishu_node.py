# 创建节点
# 2026-05-13
# Linkin WANG
import requests
from token_manager import TokenManager
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
            "Content-Type": "application/json"
        }
    
    def create_lark_node(self, node_token: str, title: str):
        """
        在指定父节点下创建一个新的文档节点（docx类型）
        Args:
            node_token: 为空字符串则创建
            title: 节点标题     
        Returns:
            成功时返回 (response_data, new_node_token)
            失败时返回 response_data
        """
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{self.space_id}/nodes"
        headers = self._get_headers()
        
        payload = {
            "obj_type": "docx",                 # 文档类型：docx表示新版文档
            "parent_node_token": node_token,           # 节点token
            "node_type": "origin",              # origin表示实体节点
            "title": title                      # 可选，不填则使用默认标题
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response_data = response.json()
        '''
        json返回格式：
                    {
                "code": 0,
                "data": {
                    "node": {
                        "node_token": "新节点的token",
                        "obj_type": "docx",
                        "title": "节点标题",
                        ...
                    }
                },
                "msg": "success"
            }
        '''
        if response_data.get("code") == 0:
            new_node_token = response_data["data"]["node"]["node_token"]  # 返回新节点token
            new_title = response_data["data"]["node"]["title"]            # 返回新节点名称
            print(f"节点创建成功！新节点 token: {new_node_token}")
            print(f"节点创建成功！新节点 title: {new_title}")
            return (response_data, new_node_token,new_title)
        else:
            print(f"节点创建失败: {response_data.get('msg', '未知错误')}")
            return response_data, None


