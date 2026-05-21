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
        
        response = requests.post(url, json=payload, timeout=30)
        result = response.json()
        
        if result.get("code") != 0:
            raise Exception(f"获取token失败: {result.get('msg')}")
        
        self._access_token = result.get("tenant_access_token")
        self.token_expire_time = time.time() + 7000
        return self._access_token
    
    def scan_space(self, space_id: str, root_token: Optional[str] = None, use_cache: bool = True) -> List[Dict]:
        """扫描知识空间"""
        logger.info(f"开始扫描知识空间 {space_id}")
        
        # 恢复进度
        all_documents = []
        scanned_nodes = set()
        pending_nodes = deque()
        
        if use_cache:
            cached_docs, scanned_nodes, pending_nodes = self._load_progress(space_id, root_token)
            all_documents.extend(cached_docs)
            logger.info(f"从缓存恢复: 已扫描 {len(scanned_nodes)} 个节点，已找到 {len(all_documents)} 个文档")
        
        if not pending_nodes:
            pending_nodes.append(root_token)
        
        processed_count = 0
        
        while pending_nodes:
            current_parent = pending_nodes.popleft()
            
            if current_parent in scanned_nodes:
                continue
            
            # 获取节点列表
            page_token = None
            while True:
                nodes, next_page_token = self._fetch_nodes(space_id, current_parent, page_token)
                
                for node in nodes:
                    # 缓存节点
                    self._cache_node(node)
                    
                    if node.get("obj_type") == "docx":
                        all_documents.append(node)
                        logger.info(f"找到文档: {node.get('title')} ({node.get('node_token')})")
                    
                    if node.get("has_child"):
                        pending_nodes.append(node.get("node_token"))
                
                scanned_nodes.add(current_parent)
                processed_count += 1
                
                if not next_page_token:
                    break
                page_token = next_page_token
            
            # 每处理50个节点保存一次进度
            if processed_count % 50 == 0:
                self._save_progress(space_id, root_token, scanned_nodes, pending_nodes, all_documents)
                logger.info(f"进度: 已扫描 {processed_count} 个节点，找到 {len(all_documents)} 个文档")
            
            time.sleep(0.1)  # 避免请求过快
        
        logger.info(f"扫描完成！共找到 {len(all_documents)} 个文档")
        self._save_progress(space_id, root_token, scanned_nodes, pending_nodes, all_documents)
        
        return all_documents
    
    def _fetch_nodes(self, space_id: str, parent_token: Optional[str], page_token: Optional[str] = None) -> tuple:
        """获取节点列表"""
        token = self._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}/nodes"
        
        params = {"page_size": 100}
        if parent_token:
            params["parent_node_token"] = parent_token
        if page_token:
            params["page_token"] = page_token
        
        headers = {"Authorization": f"Bearer {token}"}
        
        for retry in range(3):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                self.stats["api_calls"] += 1
                result = response.json()
                
                if result.get("code") == 0:
                    items = result.get("data", {}).get("items", [])
                    next_page_token = result.get("data", {}).get("page_token")
                    return items, next_page_token
                elif result.get("code") == 99991663:  # 限流
                    time.sleep((retry + 1) * 2)
                else:
                    logger.error(f"API错误: {result}")
                    return [], None
            except Exception as e:
                logger.error(f"请求失败: {e}")
                time.sleep(1)
        
        return [], None
    
    def _cache_node(self, node: Dict):
        """缓存节点"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO node_cache 
            (node_token, parent_token, title, obj_type, has_child, node_type, scan_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            node.get("node_token"),
            node.get("parent_node_token"),
            node.get("title"),
            node.get("obj_type"),
            1 if node.get("has_child") else 0,
            node.get("node_type"),
            datetime.now()
        ))
        
        conn.commit()
        conn.close()
    
    def _save_progress(self, space_id: str, root_token: Optional[str], scanned_nodes: Set, pending_nodes: deque, documents: List):
        """保存进度"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        root_str = root_token if root_token else "ROOT"
        
        cursor.execute("""
            INSERT OR REPLACE INTO scan_progress 
            (id, space_id, scan_root, last_scan_time, scanned_nodes, pending_nodes)
            VALUES (1, ?, ?, ?, ?, ?)
        """, (
            space_id,
            root_str,
            datetime.now(),
            json.dumps(list(scanned_nodes)),
            json.dumps(list(pending_nodes))
        ))
        
        conn.commit()
        conn.close()
        
        # 保存文档列表
        with open("scanned_documents.json", "w", encoding="utf-8") as f:
            json.dump(documents, f, ensure_ascii=False, indent=2)
    
    def _load_progress(self, space_id: str, root_token: Optional[str]) -> tuple:
        """加载进度"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        root_str = root_token if root_token else "ROOT"
        
        cursor.execute("""
            SELECT scanned_nodes, pending_nodes FROM scan_progress 
            WHERE space_id = ? AND scan_root = ? 
            ORDER BY last_scan_time DESC LIMIT 1
        """, (space_id, root_str))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            scanned_nodes = set(json.loads(row[0]))
            pending_nodes = deque(json.loads(row[1]))
            
            try:
                with open("scanned_documents.json", "r", encoding="utf-8") as f:
                    documents = json.load(f)
                return documents, scanned_nodes, pending_nodes
            except:
                return [], scanned_nodes, pending_nodes
        
        return [], set(), deque()