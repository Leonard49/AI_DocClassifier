#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书文档分类 - 指定子目录扫描版本（集成 TokenManager）
"""

import json
import time
import sys
import requests
from datetime import datetime
from typing import Optional, List, Dict

# 导入原有模块
from TokenManager import TokenManager
from CreateFeishuNode import FeishuNodeCreator
from Copydoc import FeishuWikiCopier
from ReadFeishuRaw import FeishuDocumentReader
from AddTagBlockV2 import FeishuDocumentTagAdder
from QwenAI_new import QwenTreeClassifier
from FindNodeByName import FeishuWikiNodeFinder
from FeishuTitleCheck import FolderNameChecker
from SimpleWikiScanner import SimpleWikiScanner

# ============================================================
# 配置部分
# ============================================================

FEISHU_APP_ID = "cli_a93910bbc5f95cc2"
FEISHU_APP_SECRET = "srbaL4nDLMAoEa9jYFQMrhtipJv2ZfvD"

# 知识库配置
SPACE_ID = "7595802147485141976"  # 新的空间ID

# ========== 指定要扫描的子目录 ==========
SCAN_ROOT_TOKEN = "F2NEwKAuGiKA7GkCEVncVIYanwh"  # 填充需要遍历的根目录的token
SCAN_FOLDER_NAME = None  # 如果设置了 SCAN_ROOT_TOKEN，这个设为 None

# ========== 目标根节点配置（文档复制到这里）==========
TARGET_PARENT_TOKEN = "FgkMwaZizi5xVukAz0pcVzrlnTg"
TARGET_ROOT_NAME = "Label scanner test"
FALLBACK_PARENT_TOKEN = None

# ========== 处理配置 ==========
USE_CACHE = False
MAX_DOCUMENTS = None
ENABLE_TAG_ADD = True
SAVE_PROGRESS = True
FORCE_RESCAN = False

# AI 配置
Qwen_AI_KEY = "sk-9neu2wGxtXiOb9EcBDlL6g"

# ============================================================
# 辅助函数（使用 TokenManager 统一 token 管理）
# ============================================================

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

def process_single_document(
    node_token: str,
    obj_token: str,
    doc_title: str,
    reader: FeishuDocumentReader,
    classifier: QwenTreeClassifier,
    creator: FeishuNodeCreator,
    name_checker: FolderNameChecker,
    node_finder: FeishuWikiNodeFinder,
    tag_adder: FeishuDocumentTagAdder,
    token_manager: TokenManager,
    processed_tokens: set,
    target_root_token: str
) -> bool:
    """处理单个文档"""
    
    print(f"\n{'='*60}")
    print(f"📄 处理文档: {doc_title}")
    print(f"🔑 node_token: {node_token} | obj_token: {obj_token}")
    print(f"{'='*60}")
    
    try:
        print("📖 正在读取文档内容...")
        content = reader.get_raw_content(obj_token)
        if not content:
            print("⚠️ 文档内容为空，跳过")
            return False
        
        print(f"✅ 文档内容读取成功，长度: {len(content)} 字符")
        
        print("🤖 正在进行AI分类...")
        tag = classifier.classify(content)
        print(f"🏷️ 分类结果: {json.dumps(tag, ensure_ascii=False)}")
        
        tag_count = len(tag)
        
        if tag_count == 1:
            success = process_single_level_tag(
                node_token, doc_title, tag, creator,
                name_checker, node_finder, SPACE_ID, target_root_token,
                token_manager
            )
        elif tag_count == 2:
            success = process_two_level_tag(
                node_token, doc_title, tag, creator,
                name_checker, node_finder, SPACE_ID, target_root_token,
                token_manager
            )
        elif tag_count >= 3:
            success = process_three_level_tag(
                node_token, doc_title, tag, creator,
                name_checker, node_finder, SPACE_ID, target_root_token,
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

def process_single_level_tag(doc_token, doc_title, tag, creator,
                            name_checker, node_finder, space_id, parent_token,
                            token_manager):
    """处理单级标签"""
    level1tag = tag["tag1"][0]
    
    is_duplicate = name_checker.check_duplicate(
        space_id, level1tag, parent_token
    )['is_duplicate']
    
    if is_duplicate:
        result = node_finder.get_parent_token_by_node_name(
            space_id, level1tag, parent_token
        )
        if result.get("found"):
            target_token = result["node_token"]
            print(f"✅ 找到已存在的节点: {level1tag}")
        else:
            return False
    else:
        _, target_token, new_title = creator.create_lark_node(parent_token, level1tag)
        if not target_token:
            return False
        print(f"✅ 创建新节点: {new_title}")
    
    return copy_document(doc_token, doc_title, target_token, token_manager)

def process_two_level_tag(doc_token, doc_title, tag, creator,
                         name_checker, node_finder, space_id, parent_token,
                         token_manager):
    """处理二级标签"""
    level1tag = tag["tag1"][0]
    level2tag = tag["tag2"][0]
    
    level1_exists = name_checker.check_duplicate(
        space_id, level1tag, parent_token
    )['is_duplicate']
    
    if level1_exists:
        result = node_finder.get_parent_token_by_node_name(
            space_id, level1tag, parent_token
        )
        if not result.get("found"):
            return False
        level1_token = result["node_token"]
        
        level2_exists = name_checker.check_duplicate(
            space_id, level2tag, level1_token
        )['is_duplicate']
        
        if level2_exists:
            result2 = node_finder.get_parent_token_by_node_name(
                space_id, level2tag, level1_token
            )
            if result2.get("found"):
                target_token = result2["node_token"]
                print(f"✅ 找到已存在的二级节点: {level2tag}")
            else:
                return False
        else:
            _, target_token, new_title = creator.create_lark_node(level1_token, level2tag)
            if not target_token:
                return False
            print(f"✅ 创建新二级节点: {new_title}")
    else:
        _, level1_token, _ = creator.create_lark_node(parent_token, level1tag)
        if not level1_token:
            return False
        _, target_token, new_title = creator.create_lark_node(level1_token, level2tag)
        if not target_token:
            return False
        print(f"✅ 创建新节点: {level1tag} -> {new_title}")
    
    return copy_document(doc_token, doc_title, target_token, token_manager)

def process_three_level_tag(doc_token, doc_title, tag, creator,
                           name_checker, node_finder, space_id, parent_token,
                           token_manager):
    """处理三级标签"""
    level1tag = tag["tag1"][0]
    level2tag = tag["tag2"][0]
    level3tag = tag["tag3"][0]
    
    level1_exists = name_checker.check_duplicate(
        space_id, level1tag, parent_token
    )['is_duplicate']
    
    if level1_exists:
        result1 = node_finder.get_parent_token_by_node_name(space_id, level1tag, parent_token)
        if not result1.get("found"):
            return False
        level1_token = result1["node_token"]
        
        level2_exists = name_checker.check_duplicate(space_id, level2tag, level1_token)['is_duplicate']
        
        if level2_exists:
            result2 = node_finder.get_parent_token_by_node_name(space_id, level2tag, level1_token)
            if not result2.get("found"):
                return False
            level2_token = result2["node_token"]
            
            level3_exists = name_checker.check_duplicate(space_id, level3tag, level2_token)['is_duplicate']
            
            if level3_exists:
                result3 = node_finder.get_parent_token_by_node_name(space_id, level3tag, level2_token)
                if result3.get("found"):
                    target_token = result3["node_token"]
                else:
                    return False
            else:
                _, target_token, _ = creator.create_lark_node(level2_token, level3tag)
                if not target_token:
                    return False
        else:
            _, level2_token, _ = creator.create_lark_node(level1_token, level2tag)
            if not level2_token:
                return False
            _, target_token, _ = creator.create_lark_node(level2_token, level3tag)
            if not target_token:
                return False
    else:
        _, level1_token, _ = creator.create_lark_node(parent_token, level1tag)
        if not level1_token:
            return False
        _, level2_token, _ = creator.create_lark_node(level1_token, level2tag)
        if not level2_token:
            return False
        _, target_token, _ = creator.create_lark_node(level2_token, level3tag)
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
    classifier = QwenTreeClassifier(Qwen_AI_KEY)
    creator = FeishuNodeCreator(token_manager, SPACE_ID)
    name_checker = FolderNameChecker(token_manager)
    node_finder = FeishuWikiNodeFinder(token_manager)
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
    
    # 6. 处理每个文档
    print("\n🔄 步骤5: 开始处理文档...")
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    for idx, doc in enumerate(all_documents, 1):
        node_token = doc["node_token"]
        obj_token = doc.get("obj_token") or node_token
        doc_title = doc["title"]
        
        if node_token in processed_tokens:
            print(f"\n[{idx}/{len(all_documents)}] ⏭️ 跳过已处理文档: {doc_title}")
            skip_count += 1
            continue
        
        success = process_single_document(
            node_token, obj_token, doc_title, reader, classifier, creator,
            name_checker, node_finder, tag_adder, token_manager, processed_tokens,
            target_root_token
        )
        
        if success:
            success_count += 1
            processed_tokens.add(node_token)
        else:
            fail_count += 1
        
        if idx % 5 == 0:
            save_processing_progress(processed_tokens)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        avg_time = elapsed / idx if idx > 0 else 0
        remaining = (len(all_documents) - idx) * avg_time
        print(f"\n📈 进度: {idx}/{len(all_documents)} | 成功: {success_count} | 失败: {fail_count} | 跳过: {skip_count}")
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
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断程序")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)