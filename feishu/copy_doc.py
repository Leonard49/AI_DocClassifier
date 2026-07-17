import json
import sys
import urllib.parse
from typing import Any, Dict, Optional

import requests

from .token_manager import TokenManager


class FeishuCopyError(Exception):
    """Wiki copy API failure with optional Feishu business code."""

    def __init__(self, message: str, *, feishu_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.feishu_code = feishu_code
        self.body = body


class FeishuWikiCopier:
    """飞书知识库节点复制 - 使用 TokenManager 管理 token"""

    def __init__(
        self,
        token_manager: TokenManager,
        node_token: str,
        target_folder_token: str,
        new_file_name: str,
        source_space_id: str,
        target_space_id: Optional[str] = None,
    ):
        self.token_manager = token_manager
        self.node_token = node_token
        self.target_folder_token = target_folder_token
        self.new_file_name = new_file_name
        self.source_space_id = source_space_id
        self.target_space_id = target_space_id if target_space_id else source_space_id

    def _get_tenant_access_token(self) -> str:
        return self.token_manager.get_token()

    def _get_wiki_node_info(self, tenant_access_token: str, node_token: str) -> Dict[str, Any]:
        url = (
            "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
            f"?token={urllib.parse.quote(node_token)}"
        )
        headers = {
            "Authorization": f"Bearer {tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            print(f"GET: {url}")
            response = requests.get(url, headers=headers, timeout=60)
            try:
                result = response.json()
            except Exception:
                result = {"raw": response.text}
            if response.status_code >= 400:
                print(f"ERROR: 获取知识空间节点信息失败 HTTP {response.status_code} {result}", file=sys.stderr)
                raise FeishuCopyError(
                    f"failed to get wiki node info: HTTP {response.status_code}",
                    feishu_code=result.get("code") if isinstance(result, dict) else None,
                    body=result,
                )
            if result.get("code", 0) != 0:
                print(f"ERROR: 获取知识空间节点信息失败 {result}", file=sys.stderr)
                raise FeishuCopyError(
                    f"failed to get wiki node info: {result.get('msg', 'unknown error')}",
                    feishu_code=result.get("code"),
                    body=result,
                )
            if not result.get("data") or not result["data"].get("node"):
                raise FeishuCopyError("未获取到节点信息", body=result)
            return result["data"]["node"]
        except FeishuCopyError:
            raise
        except Exception as e:
            print(f"ERROR: getting wiki node info: {e}", file=sys.stderr)
            raise

    def _copy_file(
        self,
        tenant_access_token: str,
        current_space_id: str,
        target_space_id: str,
        current_node_token: str,
        target_parent_token: str,
        title: str,
    ) -> Dict[str, Any]:
        url = (
            f"https://open.feishu.cn/open-apis/wiki/v2/spaces/"
            f"{current_space_id}/nodes/{current_node_token}/copy"
        )
        headers = {
            "Authorization": f"Bearer {tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "target_space_id": target_space_id,
            "target_parent_token": target_parent_token,
            "title": title,
        }

        print(f"POST: {url}")
        print(f"Request body: {json.dumps(payload, ensure_ascii=False)}")
        response = requests.post(url, json=payload, headers=headers, timeout=90)
        try:
            result = response.json()
        except Exception:
            result = {"raw": response.text}

        print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")

        if response.status_code >= 400 or result.get("code", 0) != 0:
            code = result.get("code") if isinstance(result, dict) else None
            msg = result.get("msg", response.reason) if isinstance(result, dict) else response.reason
            print(f"ERROR: 复制文件失败 code={code} msg={msg}", file=sys.stderr)
            raise FeishuCopyError(
                f"failed to copy file: code={code} msg={msg}",
                feishu_code=code,
                body=result,
            )

        if not result.get("data") or not result["data"].get("node"):
            raise FeishuCopyError("未获取到复制节点信息", body=result)

        copied_node = result["data"]["node"]
        print(
            "节点复制成功:",
            {
                "node_token": copied_node.get("node_token"),
                "obj_token": copied_node.get("obj_token"),
                "title": copied_node.get("title"),
                "url": copied_node.get("url"),
            },
        )
        return result

    def copy_document_by_node_token(self) -> Optional[str]:
        """Copy wiki node; raises FeishuCopyError on API failure, returns None on soft errors."""
        print("步骤1: 获取 tenant_access_token")
        tenant_access_token = self._get_tenant_access_token()

        print("步骤2: 获取知识空间节点信息")
        node_info = self._get_wiki_node_info(tenant_access_token, self.node_token)

        doc_token = node_info.get("obj_token")
        doc_type = node_info.get("obj_type")
        if not doc_token:
            print("ERROR: 未获取到文档 token", file=sys.stderr)
            return None
        if not doc_type:
            print("ERROR: 未获取到文档类型", file=sys.stderr)
            return None
        print(f"获取到文档信息 - token: {doc_token}, type: {doc_type}")

        print("步骤3: 复制文档")
        result = self._copy_file(
            tenant_access_token=tenant_access_token,
            current_space_id=self.source_space_id,
            target_space_id=self.target_space_id,
            current_node_token=self.node_token,
            target_parent_token=self.target_folder_token,
            title=self.new_file_name,
        )
        copied_node = result.get("data", {}).get("node", {})
        copied_token = copied_node.get("node_token")
        print("文档复制完成!")
        return copied_token
