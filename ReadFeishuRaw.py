import requests
from typing import Optional
from TokenManager import TokenManager

class FeishuDocumentReader:
    """飞书文档内容读取器（支持获取纯文本内容和标题，使用 TokenManager）"""

    def __init__(self, token_manager: TokenManager):
        """
        初始化读取器
        :param token_manager: TokenManager 实例
        """
        self.token_manager = token_manager
        self.base_url = "https://open.feishu.cn/open-apis/docx/v1/documents"

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json"
        }

    def get_raw_content(self, document_id: str) -> Optional[str]:
        """
        通过 raw_content 接口获取文档纯文本内容
        :param document_id: 文档 ID
        :return: 文档的纯文本内容，失败返回 None
        """
        url = f"{self.base_url}/{document_id}/raw_content"
        headers = self._get_headers()

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0:
                content = data.get("data", {}).get("content", "")
                title = data.get("data", {}).get("title", "")
                if title:
                    print(f"文档标题: {title}")
                return content
            else:
                print(f"获取文档内容失败: {data}")
                return None
        except Exception as e:
            print(f"获取文档内容异常: {e}")
            return None

    def get_title(self, document_id: str) -> Optional[str]:
        """
        获取文档标题（单独调用，用于展示）
        :param document_id: 文档 ID
        :return: 文档标题，失败返回 None
        """
        url = f"{self.base_url}/{document_id}"
        headers = self._get_headers()

        try:
            response = requests.get(url, headers=headers, timeout=30)
            data = response.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("document", {}).get("title")
            else:
                return None
        except Exception:
            return None