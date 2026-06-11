import logging
from typing import Any, Dict, Optional
import requests
from token_manager import TokenManager
logger = logging.getLogger(__name__)
class FeishuDocumentTagAdder:
    """在飞书 Docx 文档顶部插入分类标签文本块。"""
    def __init__(self, token_manager: TokenManager, timeout: int = 30):
        self.token_manager = token_manager
        self.timeout = timeout
        self.base_url = "https://open.feishu.cn/open-apis/docx/v1/documents"
        self.wiki_node_url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json",
        }
    
    def resolve_document_id(self, wiki_node_token: str) -> Optional[str]:
        """
        将知识库 node_token 解析为 Docx document_id (obj_token)。
        若传入的已是 document_id，wiki 接口会失败，可回退为原值。
        """
        try:
            resp = requests.get(
                self.wiki_node_url,
                headers=self._headers(),
                params={"token": wiki_node_token},
                timeout=self.timeout,
            )
            data = resp.json()
            if data.get("code") == 0:
                node = data.get("data", {}).get("node", {})
                obj_token = node.get("obj_token")
                if obj_token and node.get("obj_type") == "docx":
                    return obj_token
                logger.warning(
                    "节点 %s 不是 docx 或缺少 obj_token: obj_type=%s",
                    wiki_node_token,
                    node.get("obj_type"),
                )
                return None
        except Exception as e:
            logger.warning("解析 wiki 节点失败 %s: %s", wiki_node_token, e)
        # 兼容：部分环境 node_token 可直接用于 docx API
        return wiki_node_token
    def add_tag_block(
        self,
        document_id: str,
        content: str,
        *,
        wiki_node_token: Optional[str] = None,
        index: int = 0,
    ) -> bool:
        """
        在文档开头插入标签文本块。
        :param document_id: Docx document_id (obj_token)，或配合 wiki_node_token
        :param wiki_node_token: 若提供，优先通过 wiki API 解析 obj_token
        :param index: 插入位置，0 通常紧贴文档顶部
        :return: 是否成功
        """
        doc_id = document_id
        if wiki_node_token:
            resolved = self.resolve_document_id(wiki_node_token)
            if not resolved:
                logger.error("无法解析文档 ID: %s", wiki_node_token)
                return False
            doc_id = resolved
        if not content or not content.strip():
            logger.warning("标签内容为空，跳过")
            return False
        # 根 block_id 在 docx 中通常等于 document_id
        url = f"{self.base_url}/{doc_id}/blocks/{doc_id}/children"
        payload = {
            "index": index,
            "children": [
                {
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {"text_run": {"content": content.strip()}}
                        ]
                    },
                }
            ],
        }
        try:
            resp = requests.post(
                url, headers=self._headers(), json=payload, timeout=self.timeout
            )
            data = resp.json()
        except Exception as e:
            logger.error("添加标签块请求异常: %s", e)
            return False
        if data.get("code") == 0:
            logger.info("标签块已写入文档 %s", doc_id)
            return True
        logger.error(
            "添加标签块失败: code=%s msg=%s",
            data.get("code"),
            data.get("msg"),
        )
        return False


