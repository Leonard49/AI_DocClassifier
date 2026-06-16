import requests
import sqlite3
import json
import time
from typing import List, Dict, Optional, Set
from datetime import datetime
from collections import deque
import logging
import os

from token_manager import TokenManager

_DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wiki_scan_cache.db")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleWikiScanner:
    """简单但高性能的飞书知识库扫描器（同步版本，使用 TokenManager）"""
    
    def __init__(
        self,
        token_manager: TokenManager,
        db_path: Optional[str] = None,
        enable_db_cache: bool = False,
    ):
        """
        初始化扫描器
        :param token_manager: TokenManager 实例，用于获取有效的 tenant_access_token
        :param db_path: 数据库文件路径，默认自动生成
        :param enable_db_cache: 是否启用数据库缓存（节点缓存和进度保存）
        """
        self.token_manager = token_manager
        self.enable_db_cache = enable_db_cache
        self.db_path = db_path or _DEFAULT_DB
        self._use_cache = False   # 运行时控制是否读写缓存

        self.stats = {
            "api_calls": 0,
            "nodes_scanned": 0,
            "documents_found": 0,
            "non_leaf_docx_skipped": 0,
        }

        if self.enable_db_cache:
            try:
                self._init_database()
            except sqlite3.OperationalError as exc:
                self.enable_db_cache = False
                logger.warning("无法初始化 wiki_scan_cache.db，已禁用扫描缓存: %s", exc)

    def _disable_cache_writes(self, exc: Exception) -> None:
        """缓存不可写时降级为无缓存扫描，避免中断主流程。"""
        if not self._use_cache:
            return
        self._use_cache = False
        logger.warning("扫描缓存写入失败，本次运行不再写入 wiki_scan_cache.db: %s", exc)

    def _connect_db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30)
    
    def _init_database(self):
        """初始化数据库"""
        conn = self._connect_db()
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
        """通过 TokenManager 获取有效的 tenant_access_token"""
        return self.token_manager.get_token()

    @staticmethod
    def _is_leaf_node(node: Dict) -> bool:
        """叶子节点：无子节点。"""
        return not node.get("has_child")

    def _maybe_collect_leaf_document(self, node: Dict, all_documents: List[Dict]) -> None:
        """仅收集叶子 docx 节点，跳过作为目录/索引的非叶子文档。"""
        if node.get("obj_type") != "docx":
            return

        node_token = node.get("node_token")
        title = node.get("title")

        if not self._is_leaf_node(node):
            self.stats["non_leaf_docx_skipped"] += 1
            logger.debug(f"跳过非叶子文档: {title} ({node_token})")
            return

        all_documents.append(node)
        logger.info(f"找到叶子文档: {title} ({node_token})")
        self.stats["documents_found"] += 1
    
    def scan_space(self, space_id: str, root_token: Optional[str] = None, use_cache: bool = True) -> List[Dict]:
        """
        扫描知识空间

        :param space_id: 空间ID
        :param root_token: 起始节点token（如果指定，只扫描该节点下的内容）
        :param use_cache: 是否使用缓存（False 时不读写 SQLite）
        :return: 文档列表
        """
        self._use_cache = use_cache and self.enable_db_cache
        self.stats["documents_found"] = 0
        self.stats["non_leaf_docx_skipped"] = 0
        logger.info(f"开始扫描知识空间 {space_id}（仅收集叶子 docx）")
        
        # 验证空间访问
        if not self._verify_space_access(space_id):
            logger.error(f"无法访问空间 {space_id}")
            return []
        
        # 如果没有指定 root_token，扫描整个空间
        if not root_token:
            logger.info("未指定根节点，将扫描整个知识库")
            return self._scan_from_root(space_id, use_cache)
        else:
            logger.info(f"指定根节点: {root_token}，只扫描该节点下的内容")
            return self._scan_from_node(space_id, root_token, use_cache)
    
    def _scan_from_root(self, space_id: str, use_cache: bool) -> List[Dict]:
        """从根节点扫描整个知识库"""
        all_documents = []
        scanned_nodes = set()
        pending_nodes = deque()
        
        cache_key = "ROOT_leaf"
        if use_cache and self.enable_db_cache:
            cached_docs, scanned_nodes, pending_nodes = self._load_progress(space_id, cache_key)
            all_documents.extend(cached_docs)
            logger.info(
                f"从缓存恢复: 已扫描 {len(scanned_nodes)} 个节点，"
                f"已找到 {len(all_documents)} 个叶子文档"
            )
        
        if not pending_nodes:
            pending_nodes.append(None)
        
        processed_count = 0
        
        while pending_nodes:
            current_parent = pending_nodes.popleft()
            parent_key = current_parent if current_parent else "ROOT"
            
            if parent_key in scanned_nodes:
                continue
            
            logger.info(f"扫描节点: {parent_key}")
            
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
                    
                    node["parent_node_token"] = current_parent
                    self._cache_node(node)
                    
                    self._maybe_collect_leaf_document(node, all_documents)

                    if node.get("has_child"):
                        pending_nodes.append(node_token)
                
                scanned_nodes.add(parent_key)
                processed_count += 1
                page_token = next_page_token
                time.sleep(0.1)
            
            if processed_count % 50 == 0:
                self._save_progress(space_id, cache_key, scanned_nodes, pending_nodes, all_documents)
                logger.info(
                    f"进度: 已扫描 {processed_count} 个节点，"
                    f"找到 {len(all_documents)} 个叶子文档，"
                    f"跳过非叶子 docx {self.stats['non_leaf_docx_skipped']} 个"
                )
        
        logger.info(
            f"扫描完成！共找到 {len(all_documents)} 个叶子文档，"
            f"跳过非叶子 docx {self.stats['non_leaf_docx_skipped']} 个"
        )
        self.stats["nodes_scanned"] = processed_count
        self._save_progress(space_id, cache_key, scanned_nodes, pending_nodes, all_documents)
        
        return all_documents
    
    def _scan_from_node(self, space_id: str, node_token: str, use_cache: bool) -> List[Dict]:
        """从指定节点开始扫描（只扫描该节点下的内容）"""
        all_documents = []
        scanned_nodes = set()
        pending_nodes = deque()
        
        # 检查缓存
        cache_key = f"NODE_{node_token}_leaf"
        if use_cache and self.enable_db_cache:
            cached_docs, scanned_nodes, pending_nodes = self._load_progress(space_id, cache_key)
            all_documents.extend(cached_docs)
            logger.info(
                f"从缓存恢复: 已扫描 {len(scanned_nodes)} 个节点，"
                f"已找到 {len(all_documents)} 个叶子文档"
            )
        
        if not pending_nodes:
            # 直接从指定节点开始
            pending_nodes.append(node_token)
        
        processed_count = 0
        
        while pending_nodes:
            current_parent = pending_nodes.popleft()
            
            if current_parent in scanned_nodes:
                continue
            
            logger.info(f"扫描节点: {current_parent}")
            
            page_token = None
            has_more = True
            
            while has_more:
                nodes, next_page_token, has_more = self._fetch_nodes(space_id, current_parent, page_token)
                
                if nodes is None:
                    logger.error(f"获取节点失败: {current_parent}")
                    break
                
                for node in nodes:
                    node_token_child = node.get("node_token")
                    if not node_token_child:
                        continue
                    
                    node["parent_node_token"] = current_parent
                    self._cache_node(node)
                    
                    self._maybe_collect_leaf_document(node, all_documents)

                    if node.get("has_child"):
                        pending_nodes.append(node_token_child)
                
                scanned_nodes.add(current_parent)
                processed_count += 1
                page_token = next_page_token
                time.sleep(0.1)
            
            if processed_count % 50 == 0:
                self._save_progress(space_id, cache_key, scanned_nodes, pending_nodes, all_documents)
                logger.info(
                    f"进度: 已扫描 {processed_count} 个节点，"
                    f"找到 {len(all_documents)} 个叶子文档，"
                    f"跳过非叶子 docx {self.stats['non_leaf_docx_skipped']} 个"
                )
        
        logger.info(
            f"扫描完成！共找到 {len(all_documents)} 个叶子文档，"
            f"跳过非叶子 docx {self.stats['non_leaf_docx_skipped']} 个"
        )
        self.stats["nodes_scanned"] = processed_count
        self._save_progress(space_id, cache_key, scanned_nodes, pending_nodes, all_documents)
        
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
        if parent_token:
            params["parent_node_token"] = parent_token
        
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
                elif result.get("code") == 99991663:
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
        if not self._use_cache:
            return
        if not node.get("node_token"):
            return

        try:
            conn = self._connect_db()
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
        except sqlite3.OperationalError as exc:
            self._disable_cache_writes(exc)
    
    def _save_progress(self, space_id: str, scan_root: str, scanned_nodes: Set, pending_nodes: deque, documents: List):
        """保存进度"""
        if not self._use_cache:
            return

        try:
            conn = self._connect_db()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO scan_progress 
                (id, space_id, scan_root, last_scan_time, scanned_nodes, pending_nodes)
                VALUES (1, ?, ?, ?, ?, ?)
            """, (
                space_id,
                scan_root,
                datetime.now(),
                json.dumps(list(scanned_nodes)),
                json.dumps([None if x is None else x for x in pending_nodes])
            ))
            
            conn.commit()
            conn.close()
            
            with open(f"scanned_documents_{scan_root}.json", "w", encoding="utf-8") as f:
                json.dump(documents, f, ensure_ascii=False, indent=2)
        except (sqlite3.OperationalError, OSError) as exc:
            self._disable_cache_writes(exc)
    
    def _load_progress(self, space_id: str, scan_root: str) -> tuple:
        """加载进度"""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT scanned_nodes, pending_nodes FROM scan_progress 
                WHERE space_id = ? AND scan_root = ? 
                ORDER BY last_scan_time DESC LIMIT 1
            """, (space_id, scan_root))
            
            row = cursor.fetchone()
            conn.close()
        except sqlite3.OperationalError as exc:
            self._disable_cache_writes(exc)
            return [], set(), deque()
        
        if row:
            scanned_nodes = set(json.loads(row[0]))
            pending_list = json.loads(row[1])
            pending_nodes = deque([None if x is None else x for x in pending_list])
            
            try:
                with open(f"scanned_documents_{scan_root}.json", "r", encoding="utf-8") as f:
                    documents = json.load(f)
                return documents, scanned_nodes, pending_nodes
            except:
                return [], scanned_nodes, pending_nodes
        
        return [], set(), deque()