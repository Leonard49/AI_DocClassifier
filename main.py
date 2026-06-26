#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feishu wiki document classifier: scan leaf documents, classify with LLM, copy to tagged folders.
"""

import json
import sys
import threading
import requests

# Windows 终端/PowerShell 默认 GBK，管道重定向时 emoji 会 UnicodeEncodeError
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Set

import config
from add_tag_block import FeishuDocumentTagAdder
from classify_cache import ClassifyCache
from copy_doc import FeishuWikiCopier
from create_feishu_node import FeishuNodeCreator
from feishu_title_check import FolderNameChecker
from llm_tree_classifier import (
    EXCLUDED_REPORT_TYPES,
    LLMTreeClassifier,
    excluded_report_category,
    is_excluded_report_tag,
)
from read_feishu_doc import FeishuDocumentReader
from run_logging import setup_run_log
from scan_snapshot import ScanSnapshot
from shared_state import SharedCopyState, default_worker_id
from token_manager import TokenManager
from wiki_scanner import SimpleWikiScanner

FEISHU_APP_ID = config.FEISHU_APP_ID
FEISHU_APP_SECRET = config.FEISHU_APP_SECRET
SPACE_ID = config.SPACE_ID
SCAN_ROOT_TOKEN = config.SCAN_ROOT_TOKEN
SCAN_FOLDER_NAME = config.SCAN_FOLDER_NAME
TARGET_PARENT_TOKEN = config.TARGET_PARENT_TOKEN
TARGET_ROOT_NAME = config.TARGET_ROOT_NAME
FALLBACK_PARENT_TOKEN = config.FALLBACK_PARENT_TOKEN
USE_CACHE = config.USE_CACHE
MAX_DOCUMENTS = config.MAX_DOCUMENTS
ENABLE_TAG_ADD = config.ENABLE_TAG_ADD
SAVE_PROGRESS = config.SAVE_PROGRESS
FORCE_RESCAN = config.FORCE_RESCAN
ENABLE_SCAN_SNAPSHOT = config.ENABLE_SCAN_SNAPSHOT
SCAN_SNAPSHOT_DB = config.SCAN_SNAPSHOT_DB
FULL_SCAN_CALIBRATION_DAYS = config.FULL_SCAN_CALIBRATION_DAYS
SAVE_RUN_LOG = config.SAVE_RUN_LOG
LOG_DIR = config.LOG_DIR
READ_WORKERS = config.READ_WORKERS
CLASSIFY_WORKERS = config.CLASSIFY_WORKERS
CLASSIFY_MAX_CHARS = config.CLASSIFY_MAX_CHARS
USE_CLASSIFY_CACHE = config.USE_CLASSIFY_CACHE
CLASSIFY_VERBOSE = config.CLASSIFY_VERBOSE
LLM_MAX_RETRIES = config.LLM_MAX_RETRIES
LLM_REQUEST_TIMEOUT = config.LLM_REQUEST_TIMEOUT
PROGRESS_INTERVAL = config.PROGRESS_INTERVAL
LLM_API_KEY = config.LLM_API_KEY
LLM_BASE_URL = config.LLM_BASE_URL
LLM_MODEL = config.LLM_MODEL
ENABLE_SHARED_DEDUP = config.ENABLE_SHARED_DEDUP
SHARED_STATE_DB = config.SHARED_STATE_DB
WORKER_ID = config.WORKER_ID
CLAIM_TIMEOUT_MINUTES = config.CLAIM_TIMEOUT_MINUTES

# ============================================================
# 辅助函数（使用 TokenManager 统一 token 管理）
# ============================================================

def has_body_content(content: Optional[str]) -> bool:
    """正文是否有实质内容（仅空白视为空，与标题无关）。"""
    return bool((content or "").strip())


def _format_eta(elapsed: float, done: int, total: int) -> str:
    if done <= 0 or done >= total:
        return "—"
    remaining = elapsed / done * (total - done)
    if remaining >= 3600:
        return f"{remaining / 3600:.1f} 小时"
    return f"{remaining / 60:.1f} 分钟"


def _print_batch_progress(
    label: str,
    done: int,
    total: int,
    ok: int,
    fail: int,
    start_time: datetime,
    extra: str = "",
) -> None:
    elapsed = (datetime.now() - start_time).total_seconds()
    pct = (done / total * 100) if total else 0
    eta = _format_eta(elapsed, done, total)
    suffix = f" | {extra}" if extra else ""
    print(
        f"\r{label}: {done}/{total} ({pct:.1f}%) | "
        f"成功: {ok} | 失败: {fail} | "
        f"已用: {elapsed / 60:.1f} 分钟 | 预计剩余: {eta}{suffix}",
        end="",
        flush=True,
    )


def find_node_by_name_direct(token_manager: TokenManager, space_id: str, node_name: str) -> Optional[str]:
    """直接通过API查找节点（使用 TokenManager）"""
    print(f"\n🔍 正在查找节点: {node_name}")
    
    token = token_manager.get_token()
    if not token:
        return None
    
    url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}/nodes"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"page_size": 50}
    
    page_token = None
    
    while True:
        if page_token:
            params["page_token"] = page_token
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            result = response.json()
            
            if result.get("code") != 0:
                print(f"⚠️ 获取节点列表失败: {result.get('msg')}")
                break
            
            items = result.get("data", {}).get("items", [])
            
            for item in items:
                if item.get("title") == node_name:
                    node_token = item.get("node_token")
                    print(f"✅ 找到节点 '{node_name}'")
                    print(f"   Token: {node_token}")
                    print(f"   父节点: {item.get('parent_node_token')}")
                    return node_token
            
            if not result.get("data", {}).get("has_more"):
                break
            page_token = result.get("data", {}).get("page_token")
            
        except Exception as e:
            print(f"⚠️ 查找节点异常: {e}")
            break
    
    print(f"⚠️ 未找到节点 '{node_name}'")
    return None

def get_scan_root_token(token_manager: TokenManager) -> Optional[str]:
    """获取要扫描的根目录token"""
    if SCAN_ROOT_TOKEN:
        print(f"📁 使用指定的扫描根节点token: {SCAN_ROOT_TOKEN}")
        return SCAN_ROOT_TOKEN
    
    if SCAN_FOLDER_NAME:
        token = find_node_by_name_direct(token_manager, SPACE_ID, SCAN_FOLDER_NAME)
        if token:
            print(f"📁 将只扫描文件夹: {SCAN_FOLDER_NAME}")
            return token
    
    print(f"📁 未指定扫描范围，将扫描整个知识库")
    return None

def get_target_root_token(token_manager: TokenManager) -> Optional[str]:
    """获取目标根节点token（文档复制到这里）"""
    if TARGET_PARENT_TOKEN:
        print(f"📁 使用指定的目标根节点token: {TARGET_PARENT_TOKEN}")
        return TARGET_PARENT_TOKEN
    
    if TARGET_ROOT_NAME:
        token = find_node_by_name_direct(token_manager, SPACE_ID, TARGET_ROOT_NAME)
        if token:
            print(f"📁 文档将复制到: {TARGET_ROOT_NAME}")
            return token
    
    if FALLBACK_PARENT_TOKEN:
        print(f"📁 使用备选根节点: {FALLBACK_PARENT_TOKEN}")
        # 如果备选是字符串，尝试查找
        if isinstance(FALLBACK_PARENT_TOKEN, str) and not FALLBACK_PARENT_TOKEN.startswith("VtQb"):
            token = find_node_by_name_direct(token_manager, SPACE_ID, FALLBACK_PARENT_TOKEN)
            if token:
                return token
        return FALLBACK_PARENT_TOKEN
    
    print(f"📁 未找到目标节点，将使用知识库根目录")
    return None

def save_processing_progress(processed_tokens: set, filename: str = "processing_progress.json"):
    """保存处理进度"""
    if not SAVE_PROGRESS:
        return
    
    progress_data = {
        "processed_tokens": list(processed_tokens),
        "total_processed": len(processed_tokens),
        "last_update": datetime.now().isoformat(),
        "scan_root": SCAN_ROOT_TOKEN,
        "target_root": TARGET_ROOT_NAME
    }
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, ensure_ascii=False, indent=2)

def load_processing_progress(filename: str = "processing_progress.json") -> set:
    """加载处理进度"""
    if not SAVE_PROGRESS or FORCE_RESCAN:
        if FORCE_RESCAN:
            print("⚠️ FORCE_RESCAN 已启用，将重新处理所有文档")
        return set()
    
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 如果扫描目录变了，清空进度
            if data.get("scan_root") != SCAN_ROOT_TOKEN:
                print("⚠️ 扫描目录已更改，将重新处理所有文档")
                return set()
            return set(data.get("processed_tokens", []))
    except OSError:
        return set()

def count_target_leaf_documents(
    scanner: SimpleWikiScanner,
    space_id: str,
    target_root_token: Optional[str],
    *,
    use_cache: bool = False,
) -> int:
    """递归统计目标目录下的叶子 docx 数量（与扫描源口径一致）。"""
    if not target_root_token:
        return 0
    docs = scanner.scan_space(
        space_id=space_id,
        root_token=target_root_token,
        use_cache=use_cache,
    )
    return len(docs)


def group_docs_by_obj_token(docs: List[Dict]) -> Dict[str, List[Dict]]:
    """按 obj_token 分组，合并快捷方式/重复引用。"""
    groups: Dict[str, List[Dict]] = {}
    for doc in docs:
        obj_token = doc.get("obj_token") or doc["node_token"]
        groups.setdefault(obj_token, []).append(doc)
    return groups

# ============================================================
# 文档处理函数
# ============================================================

def batch_read_contents(
    docs: List[Dict],
    reader: FeishuDocumentReader,
    workers: int,
    progress_interval: int = PROGRESS_INTERVAL,
) -> Dict[str, Tuple[str, Optional[str], str]]:
    """并行读取文档，返回 obj_token -> (title, content, source_path)"""
    results: Dict[str, Tuple[str, Optional[str], str]] = {}
    total = len(docs)
    done = 0
    ok = 0
    lock = threading.Lock()
    start_time = datetime.now()

    def _read_one(doc: Dict) -> Tuple[str, str, Optional[str], str]:
        obj_token = doc.get("obj_token") or doc["node_token"]
        node_token = doc["node_token"]
        title = doc["title"]
        source_path = doc.get("source_path") or ""
        content = reader.get_raw_content(obj_token, wiki_node_token=node_token)
        return obj_token, title, content, source_path

    def _on_done(obj_token: str, title: str, content: Optional[str], source_path: str) -> None:
        nonlocal done, ok
        results[obj_token] = (title, content, source_path)
        with lock:
            done += 1
            if has_body_content(content):
                ok += 1
            if done == 1 or done == total or done % progress_interval == 0:
                _print_batch_progress(
                    "📖 读取进度", done, total, ok, done - ok, start_time
                )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_read_one, doc): doc for doc in docs}
        for future in as_completed(futures):
            obj_token, title, content, source_path = future.result()
            _on_done(obj_token, title, content, source_path)

    print()
    elapsed = (datetime.now() - start_time).total_seconds()
    print(
        f"📖 读取汇总: {ok}/{total} 有内容 | "
        f"{total - ok} 为空 | 耗时 {elapsed / 60:.1f} 分钟"
    )
    return results


def batch_classify_documents(
    read_results: Dict[str, Tuple[str, Optional[str], str]],
    classifier: LLMTreeClassifier,
    workers: int,
    progress_interval: int = PROGRESS_INTERVAL,
) -> Dict[str, Optional[Dict]]:
    """并行 AI 分类，返回 obj_token -> tag（失败或空内容为 None）"""
    tags: Dict[str, Optional[Dict]] = {}
    to_classify: List[Tuple[str, Tuple[str, Optional[str], str]]] = []
    empty_skip = 0

    for obj_token, item in read_results.items():
        title, content, source_path = item
        if not has_body_content(content):
            tags[obj_token] = None
            empty_skip += 1
        else:
            to_classify.append((obj_token, item))

    total = len(to_classify)
    done = 0
    ok = 0
    cached = 0
    excluded = 0
    lock = threading.Lock()
    start_time = datetime.now()

    print(
        f"   待 AI 分类: {total} | 内容为空已跳过: {empty_skip} | "
        f"合计: {len(read_results)}"
    )

    def _classify_one(item: Tuple[str, Tuple[str, Optional[str], str]]) -> Tuple[str, Optional[Dict], bool]:
        obj_token, (title, content, source_path) = item
        from_cache = False
        if classifier.cache and obj_token:
            cached_tag = classifier.cache.get(obj_token, content or "")
            if cached_tag is not None:
                if is_excluded_report_tag(cached_tag):
                    return obj_token, cached_tag, True
                cached_path = classifier._tag_to_path(cached_tag)
                domain_hint = classifier.detect_source_domain_hint(source_path)
                if (
                    classifier._is_leaf_path(cached_path)
                    and (
                        not domain_hint
                        or classifier._path_under_domain(cached_path, domain_hint)
                    )
                ):
                    return obj_token, cached_tag, True
        tag = classifier.classify(
            content,
            obj_token=obj_token,
            title=title,
            source_path=source_path,
        )
        return obj_token, tag, from_cache

    def _on_done(obj_token: str, tag: Optional[Dict], from_cache: bool) -> None:
        nonlocal done, ok, cached, excluded
        tags[obj_token] = tag
        with lock:
            done += 1
            if is_excluded_report_tag(tag):
                excluded += 1
            elif tag:
                ok += 1
            if from_cache:
                cached += 1
            if done == 1 or done == total or done % progress_interval == 0:
                _print_batch_progress(
                    "🤖 AI 分类进度",
                    done,
                    total,
                    ok,
                    done - ok - excluded,
                    start_time,
                    extra=f"缓存命中: {cached} | 排除类: {excluded}",
                )

    if not to_classify:
        print("🤖 无需 AI 分类（均无正文）")
        return tags

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_classify_one, item) for item in to_classify]
        for future in as_completed(futures):
            obj_token, tag, from_cache = future.result()
            _on_done(obj_token, tag, from_cache)

    print()
    elapsed = (datetime.now() - start_time).total_seconds()
    print(
        f"🤖 分类汇总: 成功 {ok}/{total} | 排除类 {excluded} | "
        f"失败 {total - ok - excluded} | "
        f"缓存命中 {cached} | 空文档跳过 {empty_skip} | 耗时 {elapsed / 60:.1f} 分钟"
    )
    return tags


def process_single_document(
    node_token: str,
    obj_token: str,
    doc_title: str,
    creator: FeishuNodeCreator,
    name_checker: FolderNameChecker,
    tag_adder: FeishuDocumentTagAdder,
    token_manager: TokenManager,
    target_root_token: Optional[str],
    tag: Dict,
) -> Optional[str]:
    """根据已有分类结果执行复制与打标，成功时返回新节点的 node_token。"""

    print(f"\n{'='*60}")
    print(f"📄 处理文档: {doc_title}")
    print(f"🔑 node_token: {node_token} | obj_token: {obj_token}")
    print(f"🏷️ 分类结果: {json.dumps(tag, ensure_ascii=False)}")
    print(f"{'='*60}")

    try:
        tag_count = len(tag)
        
        if tag_count == 1:
            copied_node_token = process_single_level_tag(
                node_token, doc_title, tag, creator,
                name_checker, SPACE_ID, target_root_token,
                token_manager
            )
        elif tag_count == 2:
            copied_node_token = process_two_level_tag(
                node_token, doc_title, tag, creator,
                name_checker, SPACE_ID, target_root_token,
                token_manager
            )
        elif tag_count >= 3:
            copied_node_token = process_three_level_tag(
                node_token, doc_title, tag, creator,
                name_checker, SPACE_ID, target_root_token,
                token_manager
            )
        else:
            print(f"❌ 未知的标签格式: {tag}")
            return None
        
        if ENABLE_TAG_ADD and copied_node_token:
            tag_message = format_tag_message(tag)
            if tag_adder.add_tag_block(obj_token, tag_message):
                print("🏷️ 已添加标签块到原文档")
            else:
                print("⚠️ 标签块添加失败（复制已成功）")
        
        return copied_node_token
        
    except Exception as e:
        print(f"❌ 处理文档失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def format_tag_message(tag: Dict) -> str:
    """格式化标签消息"""
    parts = []
    for i in range(1, len(tag) + 1):
        tag_key = f"tag{i}"
        if tag_key in tag:
            parts.append(f"Tag{i}: {tag[tag_key][0]}")
    return "\n | " + " | ".join(parts)

def _ensure_child_folder(
    creator: FeishuNodeCreator,
    name_checker: FolderNameChecker,
    space_id: str,
    parent_token: Optional[str],
    folder_name: str,
    *,
    max_retries: int = 3,
) -> Optional[str]:
    """在父节点下获取或创建同名文件夹，返回 node_token（含并发重试）。"""
    for attempt in range(max_retries):
        dup = name_checker.check_duplicate(space_id, folder_name, parent_token)
        if dup["is_duplicate"]:
            token = dup.get("node_token")
            if token:
                print(f"✅ 找到已存在的节点: {folder_name}")
                return token
            return None

        _, token, new_title = creator.create_lark_node(parent_token or "", folder_name)
        if token:
            name_checker.invalidate_children(space_id, parent_token)
            print(f"✅ 创建新节点: {new_title}")
            return token

        name_checker.invalidate_children(space_id, parent_token)
        if attempt < max_retries - 1:
            print(f"⚠️ 创建文件夹失败，重试 ({attempt + 2}/{max_retries}): {folder_name}")

    return None


def process_single_level_tag(doc_token, doc_title, tag, creator,
                            name_checker, space_id, parent_token,
                            token_manager):
    """处理单级标签"""
    level1tag = tag["tag1"][0]
    target_token = _ensure_child_folder(
        creator, name_checker, space_id, parent_token, level1tag
    )
    if not target_token:
        return None
    return copy_document(
        doc_token, doc_title, target_token, token_manager, name_checker, space_id
    )


def process_two_level_tag(doc_token, doc_title, tag, creator,
                         name_checker, space_id, parent_token,
                         token_manager):
    """处理二级标签"""
    level1tag = tag["tag1"][0]
    level2tag = tag["tag2"][0]

    level1_token = _ensure_child_folder(
        creator, name_checker, space_id, parent_token, level1tag
    )
    if not level1_token:
        return None

    target_token = _ensure_child_folder(
        creator, name_checker, space_id, level1_token, level2tag
    )
    if not target_token:
        return None
    return copy_document(
        doc_token, doc_title, target_token, token_manager, name_checker, space_id
    )


def process_three_level_tag(doc_token, doc_title, tag, creator,
                           name_checker, space_id, parent_token,
                           token_manager):
    """处理三级标签"""
    level1tag = tag["tag1"][0]
    level2tag = tag["tag2"][0]
    level3tag = tag["tag3"][0]

    level1_token = _ensure_child_folder(
        creator, name_checker, space_id, parent_token, level1tag
    )
    if not level1_token:
        return None

    level2_token = _ensure_child_folder(
        creator, name_checker, space_id, level1_token, level2tag
    )
    if not level2_token:
        return None

    target_token = _ensure_child_folder(
        creator, name_checker, space_id, level2_token, level3tag
    )
    if not target_token:
        return None
    return copy_document(
        doc_token, doc_title, target_token, token_manager, name_checker, space_id
    )

def copy_document(
    doc_token: str,
    doc_title: str,
    target_folder_token: str,
    token_manager: TokenManager,
    name_checker: FolderNameChecker,
    space_id: str,
) -> Optional[str]:
    """复制文档到目标文件夹，成功时返回新节点 node_token。"""
    try:
        unique_title = name_checker.resolve_unique_child_title(
            space_id, target_folder_token, doc_title
        )
        if unique_title != doc_title:
            print(f"📝 目标子目录已有同名文档，使用标题: {unique_title}")

        copier = FeishuWikiCopier(
            token_manager=token_manager,
            node_token=doc_token,
            target_folder_token=target_folder_token,
            new_file_name=unique_title,
            source_space_id=SPACE_ID,
            target_space_id=SPACE_ID,
        )
        copied_node_token = copier.copy_document_by_node_token()

        if copied_node_token:
            print(f"✅ 文档复制成功: {unique_title}")
        else:
            print(f"❌ 文档复制失败: {unique_title}")

        return copied_node_token
    except Exception as e:
        print(f"❌ 复制文档异常: {e}")
        return None

def save_excluded_reports(
    excluded_by_category: Dict[str, List[str]],
    log_dir: str,
) -> Optional[str]:
    """Write excluded report document names to logs/excluded_reports.json."""
    total = sum(len(titles) for titles in excluded_by_category.values())
    if total == 0:
        return None

    import os

    os.makedirs(log_dir, exist_ok=True)
    out_path = os.path.join(log_dir, "excluded_reports.json")
    payload = {
        "run_at": datetime.now().isoformat(),
        "total": total,
        "by_category": {
            cat: {"count": len(excluded_by_category.get(cat, [])), "titles": excluded_by_category.get(cat, [])}
            for cat in EXCLUDED_REPORT_TYPES
            if excluded_by_category.get(cat)
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path

def print_excluded_reports_summary(excluded_by_category: Dict[str, List[str]]) -> int:
    """Print excluded report counts and titles; return total excluded."""
    total = sum(len(titles) for titles in excluded_by_category.values())
    if total == 0:
        return 0

    print(f"\n📋 排除类文档（不分类、不复制）: 共 {total} 个")
    for category in EXCLUDED_REPORT_TYPES:
        titles = excluded_by_category.get(category, [])
        if not titles:
            continue
        print(f"\n   【{category}】 {len(titles)} 个:")
        for name in titles:
            print(f"      - {name}")
    return total

# ============================================================
# 主函数
# ============================================================

def main():
    """主函数"""
    start_time = datetime.now()
    print("="*60)
    print("🚀 飞书文档自动分类系统启动")
    print(f"⏰ 开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    print("\n📋 配置信息:")
    print(f"   - 扫描目录token: {SCAN_ROOT_TOKEN}")
    target_label = TARGET_ROOT_NAME or TARGET_PARENT_TOKEN or "(未配置)"
    print(f"   - 目标目录: {target_label}")
    print(f"   - 使用缓存: {USE_CACHE}")
    print(f"   - 最大文档数: {MAX_DOCUMENTS if MAX_DOCUMENTS else '无限制'}")
    print(f"   - 并行读取: {READ_WORKERS} | 并行分类: {CLASSIFY_WORKERS} | LLM重试: {LLM_MAX_RETRIES}")
    print(f"   - LLM 模型: {LLM_MODEL} | 网关: {LLM_BASE_URL}")
    print(f"   - 分类正文上限: {CLASSIFY_MAX_CHARS} 字符 | 分类缓存: {USE_CLASSIFY_CACHE}")
    print(f"   - 多人并行去重: {ENABLE_SHARED_DEDUP}")
    if ENABLE_SCAN_SNAPSHOT:
        print(
            f"   - 扫描快照增量: 开启 | 校准周期: "
            f"{FULL_SCAN_CALIBRATION_DAYS} 天 | DB: {SCAN_SNAPSHOT_DB}"
        )
    if ENABLE_SHARED_DEDUP:
        print(f"   - 共享状态库: {SHARED_STATE_DB}")
        print(f"   - Worker ID: {WORKER_ID or '(自动生成)'}")
    
    # 1. 创建 TokenManager
    token_manager = TokenManager(FEISHU_APP_ID, FEISHU_APP_SECRET)
    try:
        # 验证 token 是否可获取
        test_token = token_manager.get_token()
        if not test_token:
            print("❌ 无法获取有效的 tenant_access_token, 程序退出")
            return
        print("✅ TokenManager 创建成功，token 获取正常")
    except Exception as e:
        print(f"❌ TokenManager 初始化失败: {e}")
        return
    
    # 2. 初始化组件
    print("\n🔧 步骤2: 初始化组件...")
    reader = FeishuDocumentReader(token_manager)
    classify_cache = ClassifyCache() if USE_CLASSIFY_CACHE else None
    classifier = LLMTreeClassifier(
        LLM_API_KEY,
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        max_content_chars=CLASSIFY_MAX_CHARS,
        verbose=CLASSIFY_VERBOSE,
        cache=classify_cache,
        max_retries=LLM_MAX_RETRIES,
        request_timeout=LLM_REQUEST_TIMEOUT,
    )
    creator = FeishuNodeCreator(token_manager, SPACE_ID)
    name_checker = FolderNameChecker(token_manager)
    tag_adder = FeishuDocumentTagAdder(token_manager)
    print("✅ 组件初始化完成")

    shared_state: Optional[SharedCopyState] = None
    worker_label = WORKER_ID or default_worker_id()
    if ENABLE_SHARED_DEDUP:
        shared_state = SharedCopyState(
            db_path=SHARED_STATE_DB,
            worker_id=worker_label,
            claim_timeout_minutes=CLAIM_TIMEOUT_MINUTES,
        )
        print(
            f"👥 多人并行去重已启用 | worker={worker_label} | "
            f"共享库={SHARED_STATE_DB}"
        )
    else:
        print("👥 多人并行去重未启用（ENABLE_SHARED_DEDUP=false）")
    
    # 3. 确定扫描范围和目标目录（传入 token_manager）
    print("\n📂 步骤3: 确定扫描范围...")
    
    scan_root_token = get_scan_root_token(token_manager)
    target_root_token = get_target_root_token(token_manager)
    
    if not scan_root_token:
        print("❌ 未找到扫描目录，程序退出")
        return
    
    if not target_root_token:
        print("⚠️ 未找到目标节点，将使用知识库根目录")
    
    print(f"\n✅ 扫描范围 token: {scan_root_token}")
    print(f"✅ 目标目录 token: {target_root_token if target_root_token else '知识库根目录'}")

    scanner = SimpleWikiScanner(token_manager, enable_db_cache=USE_CACHE)

    print("\n📂 统计目标目录当前文档数（处理前）...")
    target_count_before = count_target_leaf_documents(
        scanner,
        SPACE_ID,
        target_root_token,
        use_cache=False,
    )
    print(f"📊 目标目录当前叶子文档数: {target_count_before}")
    
    # 4. 扫描叶子文档（仅 has_child=false 的 docx）
    print("\n📂 步骤4: 扫描叶子文档...")
    all_documents = scanner.scan_space(
        space_id=SPACE_ID,
        root_token=scan_root_token,
        use_cache=USE_CACHE
    )
    
    print(f"\n✅ 扫描完成！在指定目录下找到 {len(all_documents)} 个叶子文档")
    non_leaf_skipped = scanner.stats.get("non_leaf_docx_skipped", 0)
    if non_leaf_skipped:
        print(f"⏭️ 已跳过 {non_leaf_skipped} 个非叶子 docx（目录/索引页）")
    
    if all_documents:
        print("\n找到的叶子文档列表:")
        for idx, doc in enumerate(all_documents[:20], 1):
            print(f"  {idx}. {doc.get('title')}")
        if len(all_documents) > 20:
            print(f"  ... 还有 {len(all_documents) - 20} 个文档")
    
    if MAX_DOCUMENTS:
        all_documents = all_documents[:MAX_DOCUMENTS]
        print(f"⚠️ 测试模式：只处理前 {MAX_DOCUMENTS} 个文档")

    scan_snapshot: Optional[ScanSnapshot] = None
    snapshot_delta_tokens: Set[str] = set()
    snapshot_calibration = False
    if ENABLE_SCAN_SNAPSHOT and scan_root_token:
        scan_snapshot = ScanSnapshot(
            SCAN_SNAPSHOT_DB,
            space_id=SPACE_ID,
            scan_root=scan_root_token,
        )
        snapshot_calibration = (
            FORCE_RESCAN
            or not scan_snapshot.has_baseline()
            or scan_snapshot.needs_full_calibration(FULL_SCAN_CALIBRATION_DAYS)
        )
        if snapshot_calibration:
            reason = "FORCE_RESCAN" if FORCE_RESCAN else (
                "首次基线" if not scan_snapshot.has_baseline()
                else f"超过 {FULL_SCAN_CALIBRATION_DAYS} 天未全量校准"
            )
            print(f"\n📸 扫描快照: 全量校准模式（{reason}）")
        else:
            snapshot_delta_tokens = scan_snapshot.delta_node_tokens(all_documents)
            last_scan, last_cal, known = scan_snapshot.summary()
            print(f"\n📸 扫描快照: 增量模式")
            print(f"   - 快照已知叶子: {known} | 上次扫描: {last_scan or '无'}")
            print(f"   - 上次全量校准: {last_cal or '无'}")
            print(f"   - 本次新增叶子: {len(snapshot_delta_tokens)} 个")
    
    # 5. 加载处理进度
    processed_tokens = load_processing_progress()
    print(f"📊 已处理文档数: {len(processed_tokens)}")
    
    # 6. 批量读取 + 并行分类，再串行复制/打标
    print("\n🔄 步骤5: 开始处理文档...")
    new_copy_count = 0
    fail_count = 0
    skip_count = 0
    empty_content_skip = 0
    excluded_report_skip = 0
    excluded_by_category: Dict[str, List[str]] = defaultdict(list)
    duplicate_skip = 0
    claim_busy_skip = 0
    local_resume_skip = 0

    global_copied: Set[str] = (
        shared_state.copied_obj_tokens() if shared_state else set()
    )

    use_snapshot_filter = (
        ENABLE_SCAN_SNAPSHOT
        and scan_snapshot is not None
        and not snapshot_calibration
    )

    pending_docs: List[Dict] = []
    for doc in all_documents:
        node_token = doc["node_token"]
        if node_token in processed_tokens:
            if not use_snapshot_filter or node_token not in snapshot_delta_tokens:
                local_resume_skip += 1
                continue
        obj_token = doc.get("obj_token") or doc["node_token"]
        if obj_token in global_copied:
            duplicate_skip += 1
            processed_tokens.add(node_token)
            continue
        pending_docs.append(doc)

    skip_count = local_resume_skip + duplicate_skip
    if use_snapshot_filter:
        print(f"   - 待处理（含新增与失败重试）: {len(pending_docs)} 个")
    if local_resume_skip:
        print(f"⏭️ 跳过本地已处理节点: {local_resume_skip} 个")
    if duplicate_skip:
        print(f"⏭️ 跳过全局已复制文档（obj_token）: {duplicate_skip} 个")

    obj_groups = group_docs_by_obj_token(pending_docs)
    unique_docs: List[Dict] = [docs[0] for docs in obj_groups.values()]
    intra_scan_dedup = len(pending_docs) - len(unique_docs)
    if intra_scan_dedup:
        print(
            f"⏭️ 本次扫描内 obj_token 去重: {intra_scan_dedup} 个重复引用"
        )
        skip_count += intra_scan_dedup

    read_results: Dict[str, Tuple[str, Optional[str], str]] = {}
    classify_results: Dict[str, Optional[Dict]] = {}

    docs_to_read: List[Dict] = []
    for doc in unique_docs:
        title = doc.get("title") or ""
        obj_token = doc.get("obj_token") or doc["node_token"]
        source_path = doc.get("source_path") or ""
        skip_cat = classifier.detect_excluded_report(title=title, content=None)
        if skip_cat:
            read_results[obj_token] = (title, "", source_path)
            classify_results[obj_token] = classifier.make_excluded_tag(skip_cat)
        else:
            docs_to_read.append(doc)

    title_excluded_count = len(read_results)
    if title_excluded_count:
        print(
            f"\n⏭️ 标题预检排除类文档: {title_excluded_count} 个"
            f"（跳过读取与 LLM 分类）"
        )
        by_cat: Dict[str, int] = defaultdict(int)
        for tag in classify_results.values():
            if is_excluded_report_tag(tag):
                by_cat[excluded_report_category(tag)] += 1
        for cat in EXCLUDED_REPORT_TYPES:
            if by_cat.get(cat):
                print(f"   - {cat}: {by_cat[cat]} 个")

    if docs_to_read:
        print(
            f"\n📖 并行读取 {len(docs_to_read)} 个唯一文档 "
            f"(workers={READ_WORKERS})..."
        )
        t_read = datetime.now()
        fetched = batch_read_contents(docs_to_read, reader, READ_WORKERS)
        read_results.update(fetched)
        print(f"✅ 读取完成，耗时 {(datetime.now() - t_read).total_seconds():.1f}s")

        print(f"\n🤖 并行 AI 分类 (workers={CLASSIFY_WORKERS})...")
        t_cls = datetime.now()
        classify_results.update(
            batch_classify_documents(fetched, classifier, CLASSIFY_WORKERS)
        )
        print(f"✅ 分类完成，耗时 {(datetime.now() - t_cls).total_seconds():.1f}s")

    total_unique = len(read_results)
    processed_in_run = 0

    for obj_token, (doc_title, content, source_path) in read_results.items():
        docs = obj_groups.get(obj_token, [])
        if not docs:
            continue
        representative = docs[0]
        node_token = representative["node_token"]
        node_tokens = {doc["node_token"] for doc in docs}
        processed_in_run += 1
        idx = processed_in_run

        tag = classify_results.get(obj_token)
        if is_excluded_report_tag(tag):
            category = excluded_report_category(tag)
            excluded_by_category[category].append(doc_title)
            excluded_report_skip += 1
            skip_count += 1
            print(
                f"\n[{idx}/{total_unique}] ⏭️ 排除类（{category}），跳过: {doc_title}"
            )
            processed_tokens.update(node_tokens)
            continue

        if not has_body_content(content):
            print(
                f"\n[{idx}/{total_unique}] ⏭️ 正文为空，跳过（不论标题）: {doc_title}"
            )
            empty_content_skip += 1
            skip_count += 1
            processed_tokens.update(node_tokens)
            continue

        if not tag:
            print(f"\n[{idx}/{total_unique}] ❌ 分类失败，跳过: {doc_title}")
            fail_count += 1
            continue

        if shared_state and shared_state.is_copied(obj_token):
            print(
                f"\n[{idx}/{total_unique}] ⏭️ 其他同事已复制，跳过: {doc_title}"
            )
            duplicate_skip += 1
            skip_count += 1
            processed_tokens.update(node_tokens)
            continue

        claimed = True
        if shared_state:
            claimed = shared_state.try_claim(obj_token)
            if not claimed:
                print(
                    f"\n[{idx}/{total_unique}] ⏭️ 文档正在被其他进程处理，跳过: {doc_title}"
                )
                claim_busy_skip += 1
                skip_count += 1
                continue

        copied_node_token = process_single_document(
            node_token, obj_token, doc_title, creator,
            name_checker, tag_adder, token_manager, target_root_token, tag
        )

        if copied_node_token:
            new_copy_count += 1
            processed_tokens.update(node_tokens)
            if shared_state:
                if not shared_state.mark_copied(
                    obj_token,
                    title=doc_title,
                    source_node_token=node_token,
                    copied_node_token=copied_node_token,
                    target_parent_token=target_root_token or "",
                    target_folder_token="",
                    scan_root=SCAN_ROOT_TOKEN,
                ):
                    print(
                        "⚠️ 共享去重库写入失败（文档已复制成功，"
                        "本地进度已保存，请检查 SHARED_STATE_DB）"
                    )
        else:
            fail_count += 1
            if shared_state:
                shared_state.release_claim(obj_token)

        if processed_in_run % 5 == 0:
            save_processing_progress(processed_tokens)

        elapsed = (datetime.now() - start_time).total_seconds()
        avg_time = elapsed / processed_in_run if processed_in_run > 0 else 0
        remaining = (total_unique - processed_in_run) * avg_time
        print(
            f"\n📈 进度: {processed_in_run}/{total_unique} | "
            f"本次新复制: {new_copy_count} | 失败: {fail_count} | "
            f"跳过: {skip_count}（含正文空 {empty_content_skip}、"
            f"排除类 {excluded_report_skip}、"
            f"全局去重 {duplicate_skip}、并发占用 {claim_busy_skip}）"
        )
        if remaining > 0:
            print(f"⏱️ 预计剩余时间: {remaining/60:.1f} 分钟")
    
    # 7. 最终统计（以目标目录实际扫描为准）
    print("\n📂 验证目标目录文档数量（处理后）...")
    target_count_after = count_target_leaf_documents(
        scanner,
        SPACE_ID,
        target_root_token,
        use_cache=False,
    )
    target_net_gain = target_count_after - target_count_before

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()
    
    print("\n" + "="*60)
    print("🎉 处理完成！")
    print("="*60)
    print(f"📊 统计信息:")
    print(f"   - 执行 worker: {worker_label}")
    print(f"   - 扫描目录: {SCAN_ROOT_TOKEN}")
    print(f"   - 目标目录 token: {target_root_token}")
    print(f"   - 找到叶子文档（扫描）: {len(all_documents)}")
    if non_leaf_skipped:
        print(f"   - 跳过非叶子 docx: {non_leaf_skipped}")
    print(f"   - 成功处理（目标目录实际叶子文档数）: {target_count_after}")
    print(f"   - 本次净增（验证）: {target_net_gain}")
    print(f"   - 本次新复制（本 worker）: {new_copy_count}")
    print(f"   - 失败: {fail_count}")
    print(f"   - 跳过: {skip_count}")
    if duplicate_skip:
        print(f"   - 其中全局去重跳过: {duplicate_skip}")
    if claim_busy_skip:
        print(f"   - 其中并发占用跳过: {claim_busy_skip}")
    if empty_content_skip:
        print(f"   - 其中正文为空跳过: {empty_content_skip}")
    if excluded_report_skip:
        print(f"   - 其中排除类跳过: {excluded_report_skip}")
        for category in EXCLUDED_REPORT_TYPES:
            n = len(excluded_by_category.get(category, []))
            if n:
                print(f"      · {category}: {n} 个")
    if new_copy_count + fail_count > 0:
        print(
            f"   - 本次复制成功率: "
            f"{new_copy_count/(new_copy_count+fail_count)*100:.1f}%"
        )
    if shared_state:
        registry = shared_state.worker_stats()
        print(
            f"   - 共享库累计已复制（全 worker）: {registry['total_copied']}"
        )
        print(
            f"   - 共享库本 worker 累计: {registry['worker_copied']}"
        )
    print(f"   - 总耗时: {elapsed/60:.1f} 分钟")
    print("="*60)
    
    save_processing_progress(processed_tokens)

    print_excluded_reports_summary(excluded_by_category)
    excluded_path = save_excluded_reports(excluded_by_category, LOG_DIR)
    if excluded_path:
        print(f"📄 排除类文档清单已保存: {excluded_path}")

    if scan_snapshot and all_documents:
        scan_snapshot.save_scan(
            all_documents,
            full_calibration=snapshot_calibration,
        )

if __name__ == "__main__":
    try:
        config.validate()
    except ValueError as exc:
        print(f"❌ 配置错误: {exc}")
        sys.exit(1)

    log_paths = None
    if SAVE_RUN_LOG:
        log_paths = setup_run_log(LOG_DIR)
    try:
        if log_paths:
            print(f"📝 实时日志: {log_paths['latest']}")
            print(f"📝 归档日志: {log_paths['stamped']}")
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断程序")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)