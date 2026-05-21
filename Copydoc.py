import json
import requests
import sys
import urllib.parse
from typing import Dict, Any, Tuple, Optional


class FeishuWikiCopier:
    """飞书知识库节点复制"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        node_token: str,
        target_folder_token: str,
        new_file_name: str,
        source_space_id: str,
        target_space_id: Optional[str] = None,
    ):
        """
        初始化

        Args:
            app_id: 应用ID
            app_secret: 应用密钥
            node_token: 源节点token
            target_folder_token: 目标文件夹token
            new_file_name: 新文件名称
            source_space_id: 源空间ID
            target_space_id: 目标空间ID
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.node_token = node_token
        self.target_folder_token = target_folder_token
        self.new_file_name = new_file_name
        self.source_space_id = source_space_id
        self.target_space_id = target_space_id 

    def _get_tenant_access_token(self) -> Tuple[str, Exception]:
        """获取 tenant_access_token"""
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        headers = {"Content-Type": "application/json; charset=utf-8"}

        try:
            print(f"POST: {url}")
            print(f"Request body: {json.dumps(payload)}")
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()

            result = response.json()
            #print(f"Response: {json.dumps(result, indent=2)}")

            if result.get("code", 0) != 0:
                msg = result.get("msg", "unknown error")
                print(f"ERROR: failed to get tenant_access_token: {msg}", file=sys.stderr)
                return "", Exception(f"failed to get tenant_access_token: {response.text}")

            return result["tenant_access_token"], None

        except Exception as e:
            print(f"ERROR: getting tenant_access_token: {e}", file=sys.stderr)
            if hasattr(e, "response") and e.response is not None:
                print(f"ERROR: Response text: {e.response.text}", file=sys.stderr)
            return "", e

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
            #print(f"Response: {json.dumps(result, indent=2)}")

            if result.get("code", 0) != 0:
                print(f"ERROR: 获取知识空间节点信息失败 {result}", file=sys.stderr)
                raise Exception(f"failed to get wiki node info: {result.get('msg', 'unknown error')}")

            if not result.get("data") or not result["data"].get("node"):
                raise Exception("未获取到节点信息")

            node_info = result["data"]["node"]
            # print("节点信息获取成功:", {
            #     "node_token": node_info.get("node_token"),
            #     "obj_type": node_info.get("obj_type"),
            #     "obj_token": node_info.get("obj_token"),
            #     "title": node_info.get("title"),
            # })
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

            # 根据飞书API文档，成功返回 data.node
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
            tenant_access_token, err = self._get_tenant_access_token()
            if err:
                print(f"ERROR: 获取 tenant_access_token 失败: {err}", file=sys.stderr)
                return False

            # 2. 获取源节点信息
            print("步骤2: 获取知识空间节点信息")
            node_info = self._get_wiki_node_info(tenant_access_token, self.node_token)

            # 3. 提取文档信息（如果需要校验或记录）
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


# def main():
#     """命令行入口，使用原有全局变量保持兼容"""
#     # 原脚本中的全局变量值
#     app_id = "cli_a93910bbc5f95cc2"
#     app_secret = "srbaL4nDLMAoEa9jYFQMrhtipJv2ZfvD"
#     node_token = "EwLVwVxUjixszGkCltxcFPsfndh"
#     target_folder_token = "T0HSwWCf0i9ijpkn2gPcda87nOf"
#     new_file_name = "1111111111"
#     SPACE_ID = "7540196657544347650"
#     # 原脚本中定义了但未使用的 Target_Space_ID，现在可通过参数传入（这里与源空间相同）
#     # Target_Space_ID = "123"

#     copier = FeishuWikiCopier(
#         app_id=app_id,
#         app_secret=app_secret,
#         node_token=node_token,
#         target_folder_token=target_folder_token,
#         new_file_name=new_file_name,
#         source_space_id=SPACE_ID,
#         target_space_id=SPACE_ID,   # 与原逻辑一致，若需不同空间可修改
#     )
#     success = copier.copy_document_by_node_token()
#     if success:
#         print("SUCCESS: 文档复制成功!")
#         sys.exit(0)
#     else:
#         print("ERROR: 文档复制失败!", file=sys.stderr)
#         sys.exit(1)


# if __name__ == "__main__":
#     main()