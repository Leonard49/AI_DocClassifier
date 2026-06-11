import json
import requests
import sys
import urllib.parse
from typing import Dict, Any, Tuple, Optional
from token_manager import TokenManager

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
        """
        初始化

        Args:
            token_manager: TokenManager 实例
            node_token: 源节点token
            target_folder_token: 目标文件夹token
            new_file_name: 新文件名称
            source_space_id: 源空间ID
            target_space_id: 目标空间ID
        """
        self.token_manager = token_manager
        self.node_token = node_token
        self.target_folder_token = target_folder_token
        self.new_file_name = new_file_name
        self.source_space_id = source_space_id
        self.target_space_id = target_space_id if target_space_id else source_space_id

    def _get_tenant_access_token(self) -> str:
        """通过 TokenManager 获取有效的 tenant_access_token"""
        return self.token_manager.get_token()

    def _get_wiki_node_info(self, tenant_access_token: str, node_token: str) -> Dict[str, Any]:
        """获取知识空间节点信息"""
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token={urllib.parse.quote(node_token)}"
        headers = {
            "Authorization": f"Bearer {tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            print(f"GET: {url}")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()

            if result.get("code", 0) != 0:
                print(f"ERROR: 获取知识空间节点信息失败 {result}", file=sys.stderr)
                raise Exception(f"failed to get wiki node info: {result.get('msg', 'unknown error')}")

            if not result.get("data") or not result["data"].get("node"):
                raise Exception("未获取到节点信息")

            node_info = result["data"]["node"]
            return node_info

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
        """复制文件（节点）"""
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{current_space_id}/nodes/{current_node_token}/copy"
        headers = {
            "Authorization": f"Bearer {tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "target_space_id": target_space_id,
            "target_parent_token": target_parent_token,
            "title": title,
        }

        try:
            print(f"POST: {url}")
            print(f"Request body: {json.dumps(payload, ensure_ascii=False)}")
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()

            result = response.json()
            print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")

            if result.get("code", 0) != 0:
                print(f"ERROR: 复制文件失败 {result}", file=sys.stderr)
                raise Exception(f"failed to copy file: {result.get('msg', 'unknown error')}")

            if not result.get("data") or not result["data"].get("node"):
                raise Exception("未获取到复制节点信息")

            copied_node = result["data"]["node"]
            print("节点复制成功:", {
                "node_token": copied_node.get("node_token"),
                "obj_token": copied_node.get("obj_token"),
                "title": copied_node.get("title"),
                "url": copied_node.get("url"),
            })
            return result

        except Exception as e:
            print(f"ERROR: copying file: {e}", file=sys.stderr)
            raise

    def copy_document_by_node_token(self) -> bool:
        """通过节点token复制文档的主流程"""
        try:
            # 1. 获取 tenant_access_token
            print("步骤1: 获取 tenant_access_token")
            tenant_access_token = self._get_tenant_access_token()

            # 2. 获取源节点信息
            print("步骤2: 获取知识空间节点信息")
            node_info = self._get_wiki_node_info(tenant_access_token, self.node_token)

            # 3. 提取文档信息
            doc_token = node_info.get("obj_token")
            doc_type = node_info.get("obj_type")
            if not doc_token:
                print("ERROR: 未获取到文档 token", file=sys.stderr)
                return False
            if not doc_type:
                print("ERROR: 未获取到文档类型", file=sys.stderr)
                return False
            print(f"获取到文档信息 - token: {doc_token}, type: {doc_type}")

            # 4. 复制文档
            print("步骤3: 复制文档")
            self._copy_file(
                tenant_access_token=tenant_access_token,
                current_space_id=self.source_space_id,
                target_space_id=self.target_space_id,
                current_node_token=self.node_token,
                target_parent_token=self.target_folder_token,
                title=self.new_file_name,
            )
            print("文档复制完成!")
            return True

        except Exception as e:
            print(f"ERROR: 复制文档过程中发生错误: {e}", file=sys.stderr)
            return False