#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书文档分类 - 指定子目录扫描版本
"""

import json
import time
import sys
import requests
from datetime import datetime
from typing import Optional, List, Dict

# 导入原有模块
from CreateFeishuNode import FeishuNodeCreator
from Copydoc import FeishuWikiCopier
from ReadFeishuRaw import FeishuDocumentReader
from AddTagBlock import FeishuDocumentTagAdder
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
# 方式1：直接指定节点token（推荐，最快）
SCAN_ROOT_TOKEN = "VtQbwy9toiH9rrkpXHycsGMLnNb"  # 8.level2 AE Team 的 token

# 方式2：指定文件夹名称（程序会自动查找，但会消耗一些时间）
SCAN_FOLDER_NAME = None  # 如果设置了 SCAN_ROOT_TOKEN，这个设为 None

# ========== 目标根节点配置（文档复制到这里）==========
TARGET_PARENT_TOKEN = None
TARGET_ROOT_NAME = "Kline label test"  # 文档将被复制到这个文件夹
FALLBACK_PARENT_TOKEN = None  # 备选

# ========== 处理配置 ==========
USE_CACHE = False                   # 首次扫描不使用缓存
MAX_DOCUMENTS = None                # 限制处理文档数量
ENABLE_TAG_ADD = False              # 是否在原文档添加标签块
SAVE_PROGRESS = True                # 是否保存处理进度
FORCE_RESCAN = False                # 是否强制重新扫描

# AI 配置
Qwen_AI_KEY = "sk-9neu2wGxtXiOb9EcBDlL6g"

# ============================================================
# 辅助函数
# ============================================================

def get_tenant_access_token() -> Optional[str]:
    """获取飞书 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == 0:
            return data.get("tenant_access_token")
        else:
            print(f"获取 tenant_access_token 失败: {data}")
            return None
    except Exception as e:
        print(f"获取 tenant_access_token 异常: {e}")
        return None

def find_node_by_name_direct(space_id: str, node_name: str) -> Optional[str]:
    """直接通过API查找节点（不扫描整个知识库）"""
    print(f"\n🔍 正在查找节点: {node_name}")
    
    token = get_tenant_access_token()
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

def get_scan_root_token() -> Optional[str]:
    """获取要扫描的根目录token"""
    if SCAN_ROOT_TOKEN:
        print(f"📁 使用指定的扫描根节点token: {SCAN_ROOT_TOKEN}")
        return SCAN_ROOT_TOKEN
    
    if SCAN_FOLDER_NAME:
        token = find_node_by_name_direct(SPACE_ID, SCAN_FOLDER_NAME)
        if token:
            print(f"📁 将只扫描文件夹: {SCAN_FOLDER_NAME}")
            return token
    
    print(f"📁 未指定扫描范围，将扫描整个知识库")
    return None

def get_target_root_token() -> Optional[str]:
    """获取目标根节点token（文档复制到这里）"""
    if TARGET_PARENT_TOKEN:
        print(f"📁 使用指定的目标根节点token: {TARGET_PARENT_TOKEN}")
        return TARGET_PARENT_TOKEN
    
    if TARGET_ROOT_NAME:
        token = find_node_by_name_direct(SPACE_ID, TARGET_ROOT_NAME)
        if token:
            print(f"📁 文档将复制到: {TARGET_ROOT_NAME}")
            return token
    
    if FALLBACK_PARENT_TOKEN:
        print(f"📁 使用备选根节点: {FALLBACK_PARENT_TOKEN}")
        # 如果备选是字符串，尝试查找
        if isinstance(FALLBACK_PARENT_TOKEN, str) and not FALLBACK_PARENT_TOKEN.startswith("VtQb"):
            token = find_node_by_name_direct(SPACE_ID, FALLBACK_PARENT_TOKEN)
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
    doc_token: str,
    doc_title: str,
    reader: FeishuDocumentReader,
    classifier: QwenTreeClassifier,
    creator: FeishuNodeCreator,
    name_checker: FolderNameChecker,
    node_finder: FeishuWikiNodeFinder,
    tag_adder: FeishuDocumentTagAdder,
    processed_tokens: set,
    target_root_token: str
) -> bool:
    """处理单个文档"""
    
    print(f"\n{'='*60}")
    print(f"📄 处理文档: {doc_title}")
    print(f"🔑 Token: {doc_token}")
    print(f"{'='*60}")
    
    try:
        print("📖 正在读取文档内容...")
        content = reader.get_raw_content(doc_token)
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
                doc_token, doc_title, tag, creator,
                name_checker, node_finder, SPACE_ID, target_root_token
            )
        elif tag_count == 2:
            success = process_two_level_tag(
                doc_token, doc_title, tag, creator,
                name_checker, node_finder, SPACE_ID, target_root_token
            )
        elif tag_count >= 3:
            success = process_three_level_tag(
                doc_token, doc_title, tag, creator,
                name_checker, node_finder, SPACE_ID, target_root_token
            )
        else:
            print(f"❌ 未知的标签格式: {tag}")
            return False
        
        if ENABLE_TAG_ADD and success:
            tag_message = format_tag_message(tag)
            tag_adder.add_tag_block(doc_token, tag_message)
            print("🏷️ 已添加标签块到原文档")
        
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
                            name_checker, node_finder, space_id, parent_token):
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
    
    return copy_document(doc_token, doc_title, target_token)

def process_two_level_tag(doc_token, doc_title, tag, creator,
                         name_checker, node_finder, space_id, parent_token):
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
    
    return copy_document(doc_token, doc_title, target_token)

def process_three_level_tag(doc_token, doc_title, tag, creator,
                           name_checker, node_finder, space_id, parent_token):
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
    
    return copy_document(doc_token, doc_title, target_token)

def copy_document(doc_token: str, doc_title: str, target_folder_token: str) -> bool:
    """复制文档到目标文件夹"""
    try:
        copier = FeishuWikiCopier(
            app_id=FEISHU_APP_ID,
            app_secret=FEISHU_APP_SECRET,
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
    
    # 1. 获取飞书token
    print("\n🔑 步骤1: 获取飞书访问令牌...")
    token = get_tenant_access_token()
    if not token:
        print("❌ 无法获取飞书token, 程序退出")
        return
    
    print("✅ 飞书token获取成功")
    
    # 2. 初始化组件
    print("\n🔧 步骤2: 初始化组件...")
    reader = FeishuDocumentReader(token)
    classifier = QwenTreeClassifier(Qwen_AI_KEY)
    creator = FeishuNodeCreator(token, SPACE_ID)
    name_checker = FolderNameChecker(FEISHU_APP_ID, FEISHU_APP_SECRET)
    node_finder = FeishuWikiNodeFinder(FEISHU_APP_ID, FEISHU_APP_SECRET)
    tag_adder = FeishuDocumentTagAdder(token)
    print("✅ 组件初始化完成")
    
    # 3. 确定扫描范围和目标目录
    print("\n📂 步骤3: 确定扫描范围...")
    
    scan_root_token = get_scan_root_token()
    target_root_token = get_target_root_token()
    
    if not scan_root_token:
        print("❌ 未找到扫描目录，程序退出")
        return
    
    if not target_root_token:
        print("⚠️ 未找到目标节点，将使用知识库根目录")
    
    print(f"\n✅ 扫描范围 token: {scan_root_token}")
    print(f"✅ 目标目录 token: {target_root_token if target_root_token else '知识库根目录'}")
    
    # 4. 扫描文档
    print("\n📂 步骤4: 扫描文档...")
    scanner = SimpleWikiScanner(FEISHU_APP_ID, FEISHU_APP_SECRET)
    
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
        doc_token = doc["node_token"]
        doc_title = doc["title"]
        
        if doc_token in processed_tokens:
            print(f"\n[{idx}/{len(all_documents)}] ⏭️ 跳过已处理文档: {doc_title}")
            skip_count += 1
            continue
        
        success = process_single_document(
            doc_token, doc_title, reader, classifier, creator,
            name_checker, node_finder, tag_adder, processed_tokens,
            target_root_token
        )
        
        if success:
            success_count += 1
            processed_tokens.add(doc_token)
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