import logging
from typing import Optional

from token_manager import TokenManager
from feishu_http import feishu_request

logger = logging.getLogger(__name__)

FEISHU_FREQ_LIMIT_CODE = 99991400


class FeishuDocumentReader:
    """飞书文档内容读取器（支持获取纯文本内容和标题，使用 TokenManager）"""

    def __init__(self, token_manager: TokenManager, rate_limiter=None):
        self.token_manager = token_manager
        # rate_limiter kept for backward compatibility; feishu_request applies global limit
        self.rate_limiter = rate_limiter
        self.base_url = "https://open.feishu.cn/open-apis/docx/v1/documents"
        self.wiki_get_node_url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json",
        }

    def _resolve_via_wiki(self, node_token: str) -> Optional[str]:
        try:
            resp = feishu_request(
                "GET",
                self.wiki_get_node_url,
                headers=self._get_headers(),
                params={"token": node_token},
            )
            data = resp.json()
            if data.get("code") != 0:
                return None
            node = data.get("data", {}).get("node", {})
            if node.get("obj_type") == "docx" and node.get("obj_token"):
                return node["obj_token"]
            logger.warning(
                "节点 %s 非 docx: obj_type=%s",
                node_token,
                node.get("obj_type"),
            )
        except Exception as e:
            logger.warning("解析 wiki 节点失败 %s: %s", node_token, e)
        return None

    def _fetch_raw_content(self, doc_id: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
        """返回 (content, api_code, api_msg)"""
        url = f"{self.base_url}/{doc_id}/raw_content"
        response = feishu_request("GET", url, headers=self._get_headers())
        try:
            data = response.json()
        except ValueError:
            return None, None, f"非 JSON 响应 HTTP {response.status_code}"

        code = data.get("code")
        if code == 0:
            payload = data.get("data", {})
            content = payload.get("content", "")
            if not (content or "").strip():
                return None, 0, data.get("msg")
            return content, 0, data.get("msg")
        return None, code, data.get("msg")

    def get_raw_content(
        self,
        document_id: str,
        wiki_node_token: Optional[str] = None,
    ) -> Optional[str]:
        """
        通过 raw_content 接口获取文档纯文本内容。

        :param document_id: obj_token（docx document_id）
        :param wiki_node_token: 可选，失败时用于重新解析 document_id
        """
        candidates = [document_id]
        if wiki_node_token and wiki_node_token not in candidates:
            candidates.append(wiki_node_token)

        last_code: Optional[int] = None
        last_msg: Optional[str] = None

        for doc_id in candidates:
            try:
                content, code, msg = self._fetch_raw_content(doc_id)
                last_code, last_msg = code, msg
                if code == 0:
                    return content
            except Exception as e:
                print(f"获取文档内容网络异常: {e}")

            if last_code not in (None, FEISHU_FREQ_LIMIT_CODE, 0):
                print(
                    f"获取文档内容失败: code={last_code}, msg={last_msg}, doc_id={doc_id}"
                )

        if wiki_node_token:
            resolved = self._resolve_via_wiki(wiki_node_token)
            if resolved and resolved not in candidates:
                try:
                    content, code, msg = self._fetch_raw_content(resolved)
                    if code == 0:
                        return content
                    print(
                        f"获取文档内容失败(解析后): code={code}, msg={msg}, doc_id={resolved}"
                    )
                except Exception as e:
                    print(f"获取文档内容网络异常(解析后): {e}")

        return None

    def get_title(self, document_id: str) -> Optional[str]:
        """获取文档标题"""
        url = f"{self.base_url}/{document_id}"
        try:
            response = feishu_request("GET", url, headers=self._get_headers())
            data = response.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("document", {}).get("title")
        except Exception:
            pass
        return None
