import requests


class FeishuDocumentTagAdder:
    """飞书文档标签块添加器"""

    def __init__(self, tenant_access_token: str):
        """
        初始化
        :param tenant_access_token: 飞书 tenant_access_token
        """
        self.tenant_access_token = tenant_access_token
        self.base_url = "https://open.feishu.cn/open-apis/docx/v1/documents"

    def add_tag_block(self, document_id: str, content: str):
        """
        在文档开头添加一个标签文本块

        :param document_id: 文档 ID
        :param content: 标签内容（纯文本）
        :return: API 响应的 JSON 数据
        """
        url = f"{self.base_url}/{document_id}/blocks/{document_id}/children"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }
        data = {
            "index": 1,  # 添加到首尾，实现另起一行
            "children": [
                {
                    "block_type": 2,  # 文本块类型
                    "text": {
                        "elements": [
                            {
                                "text_run": {
                                    "content": content
                                }
                            }
                        ]
                    }
                }
            ]
        }
        response = requests.post(url, headers=headers, json=data)
        return response.json()