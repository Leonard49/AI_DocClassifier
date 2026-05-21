import requests
import time
from urllib.parse import urlparse, parse_qs
from typing import List, Optional


class FeishuBitableExtractor:
    """飞书多维表格数据提取器"""
    
    def __init__(self, app_id: str, app_secret: str, app_token: str, table_id: str):
        """
        初始化提取器
        :param app_id: 飞书应用的 app_id
        :param app_secret: 飞书应用的 app_secret
        :param app_token: 多维表格的 app_token（从 URL 中获取）
        :param table_id: 数据表的 table_id（从 URL 中获取）
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self.table_id = table_id
        self.access_token = None
        self.token_expires_at = 0
    
    def _get_app_access_token(self) -> str:
        """
        获取 app_access_token（有效期 2 小时）
        参考文档：https://open.feishu.cn/document/server-docs/authentication-management/access-token/app_access_token
        """
        # 检查缓存的 token 是否还有效
        if self.access_token and time.time() < self.token_expires_at:
            return self.access_token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        headers = {
            "Content-Type": "application/json; charset=utf-8"
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") != 0:
                raise Exception(f"获取 access_token 失败: {result.get('msg')}")
            
            self.access_token = result.get("app_access_token")
            # token 有效期通常为 7200 秒，预留 300 秒的缓冲时间
            self.token_expires_at = time.time() + 7200 - 300
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"请求 access_token 失败: {e}")
    
    def extract_node_token_from_url(self, url: str) -> Optional[str]:
        """
        从飞书知识库 URL 中提取 node_token 参数
        URL 示例: https://quectel.feishu.cn/wiki/7555708594691178498?node_token=CJmgwoOaWiKk9ikow2Nc5R0ynDf
        """
        if not url or not isinstance(url, str):
            return None
        
        try:
            # 解析 URL
            parsed = urlparse(url)
            # 提取查询参数
            query_params = parse_qs(parsed.query)
            # parse_qs 返回的值为列表，取第一个元素
            node_token_list = query_params.get("node_token", [])
            return node_token_list[0] if node_token_list else None
        except Exception as e:
            print(f"解析 URL 失败: {url}, 错误: {e}")
            return None
    
    def get_column_records(self, column_name: str) -> List[str]:
        """
        获取指定列的所有数据，并提取其中的 node_token
        :param column_name: 列名称，例如 "文档链接"
        :return: node_token 列表（按查询顺序排列）
        """
        # 获取访问凭证
        token = self._get_app_access_token()
        if not token:
            raise Exception("无法获取 access_token")
        
        # 构建 API 请求 URL
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        node_tokens = []
        page_token = None
        page_num = 1
        
        while True:
            # 构建查询参数
            params = {
                "page_size": 500  # 每页最多 500 条
            }
            if page_token:
                params["page_token"] = page_token
            
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                response.raise_for_status()
                result = response.json()
                
                if result.get("code") != 0:
                    raise Exception(f"查询记录失败: {result.get('msg')}")
                
                data = result.get("data", {})
                records = data.get("items", [])
                
                # 提取当前页的数据
                for record in records:
                    fields = record.get("fields", {})
                    field_value = fields.get(column_name)
                    
                    # 处理字段值（可能是字符串或字符串列表）
                    if isinstance(field_value, str):
                        node_token = self.extract_node_token_from_url(field_value)
                        if node_token:
                            node_tokens.append(node_token)
                    elif isinstance(field_value, list):
                        # 如果字段是数组类型（如多维表格的"链接"字段可能返回数组）
                        for item in field_value:
                            if isinstance(item, str):
                                node_token = self.extract_node_token_from_url(item)
                                if node_token:
                                    node_tokens.append(node_token)
                
                print(f"第 {page_num} 页获取完成，本页 {len(records)} 条记录，当前累计提取 {len(node_tokens)} 个 token")
                
                # 检查是否还有下一页
                has_more = data.get("has_more", False)
                if not has_more:
                    break

              
                    # ... 处理代码 ...
                
                page_token = data.get("page_token")
                page_num += 1
               
            except requests.exceptions.RequestException as e:
                raise Exception(f"请求记录数据失败: {e}")
        
        print(f"数据提取完成，共提取 {len(node_tokens)} 个 node_token")
        return node_tokens



# if __name__ == "__main__":
#     # ========== 配置信息（请替换为实际值）==========
#     # 1. 飞书应用凭证（在飞书开发者后台获取）
#     APP_ID = "cli_a93910bbc5f95cc2"
#     APP_SECRET = "srbaL4nDLMAoEa9jYFQMrhtipJv2ZfvD"
    
#     # 2. 多维表格标识
#     # 从多维表格 URL 中获取，示例:
#     # https://xxxxxxxxxx.feishu.cn/base/PtRdbPjCFa5Og5sry0lcD1yPnKg?table=tblVBqxDbGXOJZPv
#     APP_TOKEN = "OZypbpofiaI774szaGlcCVaUnjd"  # 替换为你的 app_token
#     TABLE_ID = "tblIX6fxzFKzGe3b"                # 替换为你的 table_id
    
#     # 3. 目标列名称
#     COLUMN_NAME = "文档链接"
    
#     # ========== 执行提取 ==========
#     try:
#         extractor = FeishuBitableExtractor(APP_ID, APP_SECRET, APP_TOKEN, TABLE_ID)
#         node_token_list = extractor.get_column_records(COLUMN_NAME)
        
#         print("\n===== 提取结果 =====")
#         for idx, token in enumerate(node_token_list, 1):
#             print(f"{idx}. {token}")
        
#         print(f"\n共计提取 {len(node_token_list)} 个 node_token")
        
#     except Exception as e:
#         print(f"程序执行失败: {e}")