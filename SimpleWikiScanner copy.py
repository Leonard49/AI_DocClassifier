import requests
import sqlite3
import json
import time
from typing import List, Dict, Optional, Set
from datetime import datetime
from collections import deque
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleWikiScanner:
    """简单但高性能的飞书知识库扫描器（同步版本）"""
    
    def __init__(self, app_id: str, app_secret: str, db_path: str = "wiki_scan_cache.db"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.db_path = db_path
        self._access_token = None
        self.token_expire_time = 0
        
        # 统计信息
        self.stats = {
            "api_calls": 0,
            "nodes_scanned": 0,
            "documents_found": 0
        }
        
        self._init_database()
    
    def _init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS node_cache (
                node_token TEXT PRIMARY KEY,
                parent_token TEXT,
                title TEXT,
                obj_type TEXT,
                has_child INTEGER,
                node_type TEXT,
                scan_time TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scan_progress (
                id INTEGER PRIMARY KEY,
                space_id TEXT,
                scan_root TEXT,
                last_scan_time TIMESTAMP,
                scanned_nodes TEXT,
                pending_nodes TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("数据库初始化完成")
    
    def _get_tenant_access_token(self) -> str:
        """获取token"""
        if self._access_token and time.time() < self.token_expire_time:
            return self._access_token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        
        try:
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get("code") != 0:
                raise Exception(f"获取token失败: {result.get('msg')}")
            
            self._access_token = result.get("tenant_access_token")
            self.token_expire_time = time.time() + 7000
            logger.info("获取token成功")
            return self._access_token
        except Exception as e:
            logger.error(f"获取token异常: {e}")
            raise
    
    def scan_space(self, space_id: str, root_token: Optional[str] = None, use_cache: bool = True) -> List[Dict]:
        """扫描知识空间"""
        logger.info(f"开始扫描知识空间 {space_id}")
        
        # 验证空间访问
        if not self._verify_space_access(space_id):
            logger.error(f"无法访问空间 {space_id}")
            return []
        
        # 获取根节点（如果没有指定）
        if not root_token:
            # 直接使用空间ID作为根节点来获取顶层节点
            # 根据API响应，parent_node_token 为空字符串表示获取根节点下的节点
            root_token = None  # None 表示获取根节点
        
        # 恢复进度
        all_documents = []
        scanned_nodes = set()
        pending_nodes = deque()
        
        if use_cache:
            cached_docs, scanned_nodes, pending_nodes = self._load_progress(space_id, str(root_token))
            all_documents.extend(cached_docs)
            logger.info(f"从缓存恢复: 已扫描 {len(scanned_nodes)} 个节点，已找到 {len(all_documents)} 个文档")
        
        # 初始化待扫描队列
        if not pending_nodes:
            # 先获取根节点下的所有节点
            pending_nodes.append(None)  # None 表示获取根节点
        
        processed_count = 0
        
        while pending_nodes:
            current_parent = pending_nodes.popleft()
            parent_key = current_parent if current_parent else "ROOT"
            
            if parent_key in scanned_nodes:
                continue
            
            logger.info(f"扫描节点: {parent_key}")
            
            # 获取节点列表
            page_token = None
            has_more = True
            
            while has_more:
                nodes, next_page_token, has_more = self._fetch_nodes(space_id, current_parent, page_token)
                
                if nodes is None:
                    logger.error(f"获取节点失败: {current_parent}")
                    break
                
                for node in nodes:
                    node_token = node.get("node_token")
                    if not node_token:
                        continue
                    
                    # 设置父节点token
                    node["parent_node_token"] = current_parent
                    
                    # 缓存节点
                    self._cache_node(node)
                    
                    # 如果是文档类型，添加到结果
                    if node.get("obj_type") == "docx":
                        all_documents.append(node)
                        logger.info(f"找到文档: {node.get('title')} ({node_token})")
                        self.stats["documents_found"] += 1
                    
                    # 如果节点有子节点，加入待扫描队列
                    if node.get("has_child") or node.get("node_type") == "origin":
                        pending_nodes.append(node_token)
                        logger.debug(f"添加子节点到队列: {node.get('title')} ({node_token})")
                
                scanned_nodes.add(parent_key)
                processed_count += 1
                page_token = next_page_token
                
                # 避免请求过快
                time.sleep(0.1)
            
            # 每处理50个节点保存一次进度
            if processed_count % 50 == 0:
                self._save_progress(space_id, str(root_token), scanned_nodes, pending_nodes, all_documents)
                logger.info(f"进度: 已扫描 {processed_count} 个节点，找到 {len(all_documents)} 个文档，剩余 {len(pending_nodes)} 个待扫描")
        
        logger.info(f"扫描完成！共找到 {len(all_documents)} 个文档")
        self.stats["nodes_scanned"] = processed_count
        self._save_progress(space_id, str(root_token), scanned_nodes, pending_nodes, all_documents)
        
        return all_documents
    
    def _verify_space_access(self, space_id: str) -> bool:
        """验证是否能访问空间"""
        try:
            token = self._get_tenant_access_token()
            url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}"
            headers = {"Authorization": f"Bearer {token}"}
            
            response = requests.get(url, headers=headers, timeout=30)
            result = response.json()
            
            if result.get("code") == 0:
                space_info = result.get("data", {})
                logger.info(f"成功访问空间: {space_info.get('name', space_id)}")
                return True
            else:
                logger.error(f"无法访问空间: {result.get('msg')}")
                return False
        except Exception as e:
            logger.error(f"验证空间访问失败: {e}")
            return False
    
    def _fetch_nodes(self, space_id: str, parent_token: Optional[str], page_token: Optional[str] = None):
        """获取节点列表"""
        token = self._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}/nodes"
        
        params = {"page_size": 50}
        # 注意：parent_node_token 为空字符串表示获取根节点下的节点
        if parent_token:
            params["parent_node_token"] = parent_token
        # 如果 parent_token 为 None，不添加 parent_node_token 参数，表示获取根节点
        
        if page_token:
            params["page_token"] = page_token
        
        headers = {"Authorization": f"Bearer {token}"}
        
        logger.debug(f"请求节点: parent={parent_token}, page={page_token}")
        
        for retry in range(3):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                self.stats["api_calls"] += 1
                result = response.json()
                
                if result.get("code") == 0:
                    items = result.get("data", {}).get("items", [])
                    next_page_token = result.get("data", {}).get("page_token")
                    has_more = result.get("data", {}).get("has_more", False)
                    
                    # 转换节点数据格式
                    formatted_items = []
                    for item in items:
                        formatted_items.append({
                            "node_token": item.get("node_token"),
                            "title": item.get("title"),
                            "obj_type": item.get("obj_type"),
                            "obj_token": item.get("obj_token"),
                            "has_child": item.get("has_child", False),
                            "node_type": item.get("node_type"),
                            "url": item.get("url")
                        })
                    
                    return formatted_items, next_page_token, has_more
                elif result.get("code") == 99991663:  # 限流
                    wait_time = (retry + 1) * 2
                    logger.warning(f"遇到限流，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API错误: code={result.get('code')}, msg={result.get('msg')}")
                    if retry == 2:
                        return None, None, False
                    time.sleep(1)
            except Exception as e:
                logger.error(f"请求失败: {e}")
                if retry == 2:
                    return None, None, False
                time.sleep(1)
        
        return [], None, False
    
    def _cache_node(self, node: Dict):
        """缓存节点"""
        if not node.get("node_token"):
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO node_cache 
            (node_token, parent_token, title, obj_type, has_child, node_type, scan_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            node.get("node_token"),
            node.get("parent_node_token"),
            node.get("title", ""),
            node.get("obj_type", ""),
            1 if node.get("has_child") else 0,
            node.get("node_type", ""),
            datetime.now()
        ))
        
        conn.commit()
        conn.close()
    
    def _get_cached_node(self, node_token: str) -> Optional[Dict]:
        """从缓存获取节点"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM node_cache WHERE node_token = ?", (node_token,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "node_token": row[0],
                "parent_node_token": row[1],
                "title": row[2],
                "obj_type": row[3],
                "has_child": bool(row[4]),
                "node_type": row[5]
            }
        return None
    
    def _save_progress(self, space_id: str, root_token: str, scanned_nodes: Set, pending_nodes: deque, documents: List):
        """保存进度"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO scan_progress 
            (id, space_id, scan_root, last_scan_time, scanned_nodes, pending_nodes)
            VALUES (1, ?, ?, ?, ?, ?)
        """, (
            space_id,
            root_token,
            datetime.now(),
            json.dumps(list(scanned_nodes)),
            json.dumps([None if x is None else x for x in pending_nodes])  # 处理None值
        ))
        
        conn.commit()
        conn.close()
        
        # 保存文档列表
        with open("scanned_documents.json", "w", encoding="utf-8") as f:
            json.dump(documents, f, ensure_ascii=False, indent=2)
    
    def _load_progress(self, space_id: str, root_token: str) -> tuple:
        """加载进度"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT scanned_nodes, pending_nodes FROM scan_progress 
            WHERE space_id = ? AND scan_root = ? 
            ORDER BY last_scan_time DESC LIMIT 1
        """, (space_id, root_token))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            scanned_nodes = set(json.loads(row[0]))
            pending_list = json.loads(row[1])
            # 将字符串 "null" 转换回 None
            pending_nodes = deque([None if x is None else x for x in pending_list])
            
            try:
                with open("scanned_documents.json", "r", encoding="utf-8") as f:
                    documents = json.load(f)
                return documents, scanned_nodes, pending_nodes
            except:
                return [], scanned_nodes, pending_nodes
        
        return [], set(), deque()