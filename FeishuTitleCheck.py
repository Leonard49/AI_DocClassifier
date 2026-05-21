import requests
from collections import Counter
from typing import Dict, List, Optional


class FolderNameChecker:
    """飞书知识库节点重复检查器（基于 requests）"""

    def __init__(self, app_id: str, app_secret: str):
        """
        初始化检查器

        :param app_id:     飞书应用 App ID
        :param app_secret: 飞书应用 App Secret
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self._access_token = None

    def _get_tenant_access_token(self) -> str:
        """获取飞书 tenant_access_token（自建应用）并缓存"""
        if self._access_token:
            return self._access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            result = response.json()
        except Exception as e:
            raise Exception(f"请求 token 失败: {e}")

        if result.get("code") != 0:
            raise Exception(f"获取 token 失败: code={result.get('code')}, msg={result.get('msg')}")

        token = result.get("tenant_access_token")
        if not token:
            raise Exception("返回结果中未包含 tenant_access_token")
        self._access_token = token
        return token

    def check_duplicate(
        self,
        space_id: str,
        target_name: str,
        parent_node_token: Optional[str] = None,
    ) -> Dict:
        """
        判断知识库指定父节点下是否存在同名子节点

        :param space_id:           知识空间 ID
        :param target_name:        需要检查的节点名称
        :param parent_node_token:  父节点 token，传 None 或空字符串表示获取根节点下的子节点
        :return:                   包含检查结果的字典
        """
        access_token = self._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}/nodes"
        headers = {"Authorization": f"Bearer {access_token}"}
        all_titles = []
        page_token = None

        while True:
            params = {"page_size": 50}
            if parent_node_token:   # 如果传了空字符串或 None，都不加该参数（即查询根节点）
                params["parent_node_token"] = parent_node_token
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
                title = item.get("title")
                if title:
                    all_titles.append(title)

            # 分页判断
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token")

        # 判断目标名称是否重复
        is_duplicate = target_name in all_titles
        # 统计所有重复名称（可选）
        name_counts = Counter(all_titles)
        duplicates = [name for name, count in name_counts.items() if count > 1]

        return {
            "is_duplicate": is_duplicate,
            "target_name": target_name,
            "duplicates": duplicates,
            "total_count": len(all_titles),
            "all_titles": all_titles,
        }


