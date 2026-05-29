#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书文档分类 - 指定子目录扫描版本（集成 TokenManager）
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# 导入原有模块
from TokenManager import TokenManager
from CreateFeishuNode import FeishuNodeCreator
from Copydoc import FeishuWikiCopier
from ReadFeishuRaw import FeishuDocumentReader
from AddTagBlockV2 import FeishuDocumentTagAdder
from QwenAI_new import QwenTreeClassifier
from FeishuTitleCheck import FolderNameChecker
from SimpleWikiScanner import SimpleWikiScanner
from classify_cache import ClassifyCache
from run_logging import setup_run_log

# ============================================================
# 配置部分
# ============================================================

FEISHU_APP_ID = "cli_a93910bbc5f95cc2"
FEISHU_APP_SECRET = "srbaL4nDLMAoEa9jYFQMrhtipJv2ZfvD"

# 知识库配置
SPACE_ID = "7595802147485141976"  # 新的空间ID

# ========== 指定要扫描的子目录 ==========
SCAN_ROOT_TOKEN = "JUWxwwvfJiLWQvk9HLHc3b24nie"  # 填充需要遍历的根目录的token
SCAN_FOLDER_NAME = None  # 如果设置了 SCAN_ROOT_TOKEN，这个设为 None

# ========== 目标根节点配置（文档复制到这里）==========
TARGET_PARENT_TOKEN = "GPFewOUJ1iGBrGks7R7cB137nDh"
TARGET_ROOT_NAME = "HyTest"
FALLBACK_PARENT_TOKEN = None

# ========== 处理配置 ==========
USE_CACHE = False
MAX_DOCUMENTS = None
ENABLE_TAG_ADD = True
SAVE_PROGRESS = True
FORCE_RESCAN = False
SAVE_RUN_LOG = True       # 自动保存终端输出到 logs/run_YYYYMMDD_HHMMSS.log
LOG_DIR = "logs"

# ========== 性能优化配置 ==========
READ_WORKERS = 3          # 并行读取（全局限速 4 次/秒，勿超过飞书 docx 5 次/秒上限）
CLASSIFY_WORKERS = 4      # 并行 AI 分类（与 llm_rate_limit 并发上限配合，过大易 502）
CLASSIFY_MAX_CHARS = 3000 # 送入模型的正文字符上限（含标题前缀）
USE_CLASSIFY_CACHE = True # SQLite 分类结果缓存
CLASSIFY_VERBOSE = False  # 批量时关闭逐条 AI 日志
LLM_MAX_RETRIES = 6       # 502/503 等可重试错误的最大次数
LLM_REQUEST_TIMEOUT = 120.0
PROGRESS_INTERVAL = 10    # 每处理 N 个文档打印一次进度

# AI 配置
Qwen_AI_KEY = "sk-9neu2wGxtXiOb9EcBDlL6g"

# ============================================================
# 辅助函数（使用 TokenManager 统一 token 管理）
# ============================================================

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
    if not SAVE_PROGRESS:
        return set()
    
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 如果扫描目录变了，清空进度
            if data.get("scan_root") != SCAN_ROOT_TOKEN:
                print("⚠️ 扫描目录已更改，将重新处理所有文档")
                return set()
            return set(data.get("processed_tokens", []))
    except:
        return set()

# ============================================================
# 文档处理函数
# ============================================================

def batch_read_contents(
    docs: List[Dict],
    reader: FeishuDocumentReader,
    workers: int,
    progress_interval: int = PROGRESS_INTERVAL,
) -> Dict[str, Tuple[str, Optional[str]]]:
    """并行读取文档，返回 obj_token -> (title, content)"""
    results: Dict[str, Tuple[str, Optional[str]]] = {}
    total = len(docs)
    done = 0
    ok = 0
    lock = threading.Lock()
    start_time = datetime.now()

    def _read_one(doc: Dict) -> Tuple[str, str, Optional[str]]:
        obj_token = doc.get("obj_token") or doc["node_token"]
        node_token = doc["node_token"]
        title = doc["title"]
        content = reader.get_raw_content(obj_token, wiki_node_token=node_token)
        return obj_token, title, content

    def _on_done(obj_token: str, title: str, content: Optional[str]) -> None:
        nonlocal done, ok
        results[obj_token] = (title, content)
        with lock:
            done += 1
            if content:
                ok += 1
            if done == 1 or done == total or done % progress_interval == 0:
                _print_batch_progress(
                    "📖 读取进度", done, total, ok, done - ok, start_time
                )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_read_one, doc): doc for doc in docs}
        for future in as_completed(futures):
            obj_token, title, content = future.result()
            _on_done(obj_token, title, content)

    print()
    elapsed = (datetime.now() - start_time).total_seconds()
    print(
        f"📖 读取汇总: {ok}/{total} 有内容 | "
        f"{total - ok} 为空 | 耗时 {elapsed / 60:.1f} 分钟"
    )
    return results


def batch_classify_documents(
    read_results: Dict[str, Tuple[str, Optional[str]]],
    classifier: QwenTreeClassifier,
    workers: int,
    progress_interval: int = PROGRESS_INTERVAL,
) -> Dict[str, Optional[Dict]]:
    """并行 AI 分类，返回 obj_token -> tag（失败或空内容为 None）"""
    tags: Dict[str, Optional[Dict]] = {}
    to_classify: List[Tuple[str, Tuple[str, Optional[str]]]] = []
    empty_skip = 0

    for obj_token, item in read_results.items():
        title, content = item
        if not content:
            tags[obj_token] = None
            empty_skip += 1
        else:
            to_classify.append((obj_token, item))

    total = len(to_classify)
    done = 0
    ok = 0
    cached = 0
    lock = threading.Lock()
    start_time = datetime.now()

    print(
        f"   待 AI 分类: {total} | 内容为空已跳过: {empty_skip} | "
        f"合计: {len(read_results)}"
    )

    def _classify_one(item: Tuple[str, Tuple[str, Optional[str]]]) -> Tuple[str, Optional[Dict], bool]:
        obj_token, (title, content) = item
        from_cache = False
        if classifier.cache and obj_token:
            cached_tag = classifier.cache.get(obj_token, content or "")
            if cached_tag is not None:
                return obj_token, cached_tag, True
        tag = classifier.classify(content, obj_token=obj_token, title=title)
        return obj_token, tag, from_cache

    def _on_done(obj_token: str, tag: Optional[Dict], from_cache: bool) -> None:
        nonlocal done, ok, cached
        tags[obj_token] = tag
        with lock:
            done += 1
            if tag:
                ok += 1
            if from_cache:
                cached += 1
            if done == 1 or done == total or done % progress_interval == 0:
                _print_batch_progress(
                    "🤖 AI 分类进度",
                    done,
                    total,
                    ok,
                    done - ok,
                    start_time,
                    extra=f"缓存命中: {cached}",
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
        f"🤖 分类汇总: 成功 {ok}/{total} | 失败 {total - ok} | "
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
) -> bool:
    """根据已有分类结果执行复制与打标（串行，保证飞书写操作顺序）"""

    print(f"\n{'='*60}")
    print(f"📄 处理文档: {doc_title}")
    print(f"🔑 node_token: {node_token} | obj_token: {obj_token}")
    print(f"🏷️ 分类结果: {json.dumps(tag, ensure_ascii=False)}")
    print(f"{'='*60}")

    try:
        tag_count = len(tag)
        
        if tag_count == 1:
            success = process_single_level_tag(
                node_token, doc_title, tag, creator,
                name_checker, SPACE_ID, target_root_token,
                token_manager
            )
        elif tag_count == 2:
            success = process_two_level_tag(
                node_token, doc_title, tag, creator,
                name_checker, SPACE_ID, target_root_token,
                token_manager
            )
        elif tag_count >= 3:
            success = process_three_level_tag(
                node_token, doc_title, tag, creator,
                name_checker, SPACE_ID, target_root_token,
                token_manager
            )
        else:
            print(f"❌ 未知的标签格式: {tag}")
            return False
        
        if ENABLE_TAG_ADD and success:
            tag_message = format_tag_message(tag)
            if tag_adder.add_tag_block(obj_token, tag_message):
                print("🏷️ 已添加标签块到原文档")
            else:
                print("⚠️ 标签块添加失败（复制已成功）")
        
        return success
        
    except Exception as e:
        print(f"❌ 处理文档失败: {e}")
        import traceback
        traceback.print_exc()
        return False

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
) -> Optional[str]:
    """在父节点下获取或创建同名文件夹，返回 node_token。"""
    dup = name_checker.check_duplicate(space_id, folder_name, parent_token)
    if dup["is_duplicate"]:
        token = dup.get("node_token")
        if token:
            print(f"✅ 找到已存在的节点: {folder_name}")
            return token
        return None
    _, token, new_title = creator.create_lark_node(parent_token or "", folder_name)
    if not token:
        return None
    name_checker.invalidate_children(space_id, parent_token)
    print(f"✅ 创建新节点: {new_title}")
    return token


def process_single_level_tag(doc_token, doc_title, tag, creator,
                            name_checker, space_id, parent_token,
                            token_manager):
    """处理单级标签"""
    level1tag = tag["tag1"][0]
    target_token = _ensure_child_folder(
        creator, name_checker, space_id, parent_token, level1tag
    )
    if not target_token:
        return False
    return copy_document(doc_token, doc_title, target_token, token_manager)


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
        return False

    target_token = _ensure_child_folder(
        creator, name_checker, space_id, level1_token, level2tag
    )
    if not target_token:
        return False
    return copy_document(doc_token, doc_title, target_token, token_manager)


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
        return False

    level2_token = _ensure_child_folder(
        creator, name_checker, space_id, level1_token, level2tag
    )
    if not level2_token:
        return False

    target_token = _ensure_child_folder(
        creator, name_checker, space_id, level2_token, level3tag
    )
    if not target_token:
        return False
    return copy_document(doc_token, doc_title, target_token, token_manager)

def copy_document(doc_token: str, doc_title: str, target_folder_token: str, token_manager: TokenManager) -> bool:
    """复制文档到目标文件夹（使用 TokenManager）"""
    try:
        copier = FeishuWikiCopier(
            token_manager=token_manager,
            node_token=doc_token,
            target_folder_token=target_folder_token,
            new_file_name=doc_title,
            source_space_id=SPACE_ID,
            target_space_id=SPACE_ID,
        )
        success = copier.copy_document_by_node_token()
        
        if success:
            print(f"✅ 文档复制成功: {doc_title}")
        else:
            print(f"❌ 文档复制失败: {doc_title}")
        
        return success
    except Exception as e:
        print(f"❌ 复制文档异常: {e}")
        return False

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
    print(f"   - 目标目录: {TARGET_ROOT_NAME}")
    print(f"   - 使用缓存: {USE_CACHE}")
    print(f"   - 最大文档数: {MAX_DOCUMENTS if MAX_DOCUMENTS else '无限制'}")
    print(f"   - 并行读取: {READ_WORKERS} | 并行分类: {CLASSIFY_WORKERS} | LLM重试: {LLM_MAX_RETRIES}")
    print(f"   - 分类正文上限: {CLASSIFY_MAX_CHARS} 字符 | 分类缓存: {USE_CLASSIFY_CACHE}")
    
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
    classifier = QwenTreeClassifier(
        Qwen_AI_KEY,
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
    
    # 4. 扫描文档
    print("\n📂 步骤4: 扫描文档...")
    scanner = SimpleWikiScanner(token_manager, enable_db_cache=USE_CACHE)
    
    all_documents = scanner.scan_space(
        space_id=SPACE_ID,
        root_token=scan_root_token,
        use_cache=USE_CACHE
    )
    
    print(f"\n✅ 扫描完成！在指定目录下找到 {len(all_documents)} 个文档")
    
    if all_documents:
        print("\n找到的文档列表:")
        for idx, doc in enumerate(all_documents[:20], 1):
            print(f"  {idx}. {doc.get('title')}")
        if len(all_documents) > 20:
            print(f"  ... 还有 {len(all_documents) - 20} 个文档")
    
    if MAX_DOCUMENTS:
        all_documents = all_documents[:MAX_DOCUMENTS]
        print(f"⚠️ 测试模式：只处理前 {MAX_DOCUMENTS} 个文档")
    
    # 5. 加载处理进度
    processed_tokens = load_processing_progress()
    print(f"📊 已处理文档数: {len(processed_tokens)}")
    
    # 6. 批量读取 + 并行分类，再串行复制/打标
    print("\n🔄 步骤5: 开始处理文档...")
    success_count = 0
    fail_count = 0
    skip_count = 0

    pending_docs = [
        doc for doc in all_documents
        if doc["node_token"] not in processed_tokens
    ]
    skip_count = len(all_documents) - len(pending_docs)
    if skip_count:
        print(f"⏭️ 跳过已处理文档: {skip_count} 个")

    read_results: Dict[str, Tuple[str, Optional[str]]] = {}
    classify_results: Dict[str, Optional[Dict]] = {}

    if pending_docs:
        print(f"\n📖 并行读取 {len(pending_docs)} 个文档 (workers={READ_WORKERS})...")
        t_read = datetime.now()
        read_results = batch_read_contents(pending_docs, reader, READ_WORKERS)
        print(f"✅ 读取完成，耗时 {(datetime.now() - t_read).total_seconds():.1f}s")

        print(f"\n🤖 并行 AI 分类 (workers={CLASSIFY_WORKERS})...")
        t_cls = datetime.now()
        classify_results = batch_classify_documents(
            read_results, classifier, CLASSIFY_WORKERS
        )
        print(f"✅ 分类完成，耗时 {(datetime.now() - t_cls).total_seconds():.1f}s")

    doc_by_obj: Dict[str, Dict] = {
        (doc.get("obj_token") or doc["node_token"]): doc
        for doc in pending_docs
    }
    total_pending = len(pending_docs)
    processed_in_run = 0

    for obj_token, (doc_title, content) in read_results.items():
        doc = doc_by_obj[obj_token]
        node_token = doc["node_token"]
        processed_in_run += 1
        idx = processed_in_run

        if not content:
            print(f"\n[{idx}/{total_pending}] ⚠️ 文档内容为空，跳过: {doc_title}")
            fail_count += 1
            continue

        tag = classify_results.get(obj_token)
        if not tag:
            print(f"\n[{idx}/{total_pending}] ❌ 分类失败，跳过: {doc_title}")
            fail_count += 1
            continue

        success = process_single_document(
            node_token, obj_token, doc_title, creator,
            name_checker, tag_adder, token_manager, target_root_token, tag
        )

        if success:
            success_count += 1
            processed_tokens.add(node_token)
        else:
            fail_count += 1

        if processed_in_run % 5 == 0:
            save_processing_progress(processed_tokens)

        elapsed = (datetime.now() - start_time).total_seconds()
        avg_time = elapsed / processed_in_run if processed_in_run > 0 else 0
        remaining = (total_pending - processed_in_run) * avg_time
        print(
            f"\n📈 进度: {processed_in_run}/{total_pending} | "
            f"成功: {success_count} | 失败: {fail_count} | 跳过: {skip_count}"
        )
        if remaining > 0:
            print(f"⏱️ 预计剩余时间: {remaining/60:.1f} 分钟")
    
    # 7. 最终统计
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()
    
    print("\n" + "="*60)
    print("🎉 处理完成！")
    print("="*60)
    print(f"📊 统计信息:")
    print(f"   - 扫描目录: {SCAN_ROOT_TOKEN}")
    print(f"   - 目标目录: {TARGET_ROOT_NAME}")
    print(f"   - 找到文档: {len(all_documents)}")
    print(f"   - 成功处理: {success_count}")
    print(f"   - 失败: {fail_count}")
    print(f"   - 跳过: {skip_count}")
    if success_count + fail_count > 0:
        print(f"   - 成功率: {success_count/(success_count+fail_count)*100:.1f}%")
    print(f"   - 总耗时: {elapsed/60:.1f} 分钟")
    print("="*60)
    
    save_processing_progress(processed_tokens)

if __name__ == "__main__":
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