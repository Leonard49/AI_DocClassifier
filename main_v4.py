#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书文档分类 - 使用知识库扫描器版本
替换原有的多维表格数据源
"""

import json
import time
import sys
from datetime import datetime
from typing import Optional, List, Dict

# 导入原有模块
from CreateFeishuNode import FeishuNodeCreator
from Copydoc import FeishuWikiCopier
from ReadFeishuRaw import FeishuDocumentReader
from AddTagBlock import FeishuDocumentTagAdder
from QwenAI import QwenTreeClassifier
from FindNodeByName import FeishuWikiNodeFinder
from FeishuTitleCheck import FolderNameChecker

# 导入新的扫描器
from SimpleWikiScanner import SimpleWikiScanner

# ============================================================
# 配置部分
# ============================================================

# 飞书应用配置
FEISHU_APP_ID = "cli_a93910bbc5f95cc2"
FEISHU_APP_SECRET = "srbaL4nDLMAoEa9jYFQMrhtipJv2ZfvD"

# 知识库配置
SPACE_ID = "7555708594691178498"  # NA FAQ&Demo 空间
PARENT_NODE_TOKEN = None  # None 表示从根节点开始扫描

# AI 配置
Qwen_AI_KEY = "sk-9neu2wGxtXiOb9EcBDlL6g"

# 处理配置
USE_CACHE = False  # 使用缓存加速扫描（首次扫描建议False，后续True）
MAX_DOCUMENTS = 10  # 限制处理文档数量，None表示全部，用于测试时可设为10
ENABLE_TAG_ADD = False  # 是否在原文档添加标签块（默认False）
SAVE_PROGRESS = True  # 是否保存处理进度（断点续传）

# ============================================================
# 辅助函数
# ============================================================

def get_tenant_access_token() -> Optional[str]:
    """获取飞书 tenant_access_token"""
    import requests
    
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

def save_processing_progress(processed_tokens: set, filename: str = "processing_progress.json"):
    """保存处理进度"""
    if not SAVE_PROGRESS:
        return
    
    progress_data = {
        "processed_tokens": list(processed_tokens),
        "total_processed": len(processed_tokens),
        "last_update": datetime.now().isoformat()
    }
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, ensure_ascii=False, indent=2)
    print(f"💾 进度已保存: 已处理 {len(processed_tokens)} 个文档")

def load_processing_progress(filename: str = "processing_progress.json") -> set:
    """加载处理进度"""
    if not SAVE_PROGRESS:
        return set()
    
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("processed_tokens", []))
    except:
        return set()

def process_single_document(
    doc_token: str,
    doc_title: str,
    reader: FeishuDocumentReader,
    classifier: QwenTreeClassifier,
    creator: FeishuNodeCreator,
    copier_helper,
    name_checker: FolderNameChecker,
    node_finder: FeishuWikiNodeFinder,
    tag_adder: FeishuDocumentTagAdder,
    processed_tokens: set
) -> bool:
    """
    处理单个文档
    
    Returns:
        bool: 处理成功返回True，失败返回False
    """
    print(f"\n{'='*60}")
    print(f"📄 处理文档: {doc_title}")
    print(f"🔑 Token: {doc_token}")
    print(f"{'='*60}")
    
    try:
        # 1. 读取文档内容
        print("📖 正在读取文档内容...")
        content = reader.get_raw_content(doc_token)
        if not content:
            print("⚠️ 文档内容为空，跳过")
            return False
        
        print(f"✅ 文档内容读取成功，长度: {len(content)} 字符")
        
        # 2. AI分类
        print("🤖 正在进行AI分类...")
        tag = classifier.classify(content)
        print(f"🏷️ 分类结果: {json.dumps(tag, ensure_ascii=False)}")
        
        # 3. 根据标签层级处理
        tag_count = len(tag)
        
        if tag_count == 1:
            # 单级标签处理
            success = process_single_level_tag(
                doc_token, doc_title, tag, creator, copier_helper,
                name_checker, node_finder, SPACE_ID, PARENT_NODE_TOKEN
            )
            
        elif tag_count == 2:
            # 二级标签处理
            success = process_two_level_tag(
                doc_token, doc_title, tag, creator, copier_helper,
                name_checker, node_finder, SPACE_ID, PARENT_NODE_TOKEN
            )
            
        elif tag_count >= 3:
            # 三级标签处理
            success = process_three_level_tag(
                doc_token, doc_title, tag, creator, copier_helper,
                name_checker, node_finder, SPACE_ID, PARENT_NODE_TOKEN
            )
        else:
            print(f"❌ 未知的标签格式: {tag}")
            return False
        
        # 4. 可选：在原文档添加标签块
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

def process_single_level_tag(doc_token, doc_title, tag, creator, copier_helper, 
                            name_checker, node_finder, space_id, parent_token):
    """处理单级标签"""
    level1tag = tag["tag1"][0]
    
    # 检查节点是否存在
    is_duplicate = name_checker.check_duplicate(
        space_id, level1tag, parent_token
    )['is_duplicate']
    
    if is_duplicate:
        # 节点已存在，获取其token
        result = node_finder.get_parent_token_by_node_name(
            space_id, level1tag, parent_token
        )
        if result.get("found"):
            target_token = result["node_token"]
            print(f"✅ 找到已存在的节点: {level1tag} (Token: {target_token})")
        else:
            print(f"❌ 未找到节点: {level1tag}")
            return False
    else:
        # 创建新节点
        _, target_token, new_title = creator.create_lark_node(parent_token, level1tag)
        if not target_token:
            print(f"❌ 创建节点失败: {level1tag}")
            return False
        print(f"✅ 创建新节点: {new_title} (Token: {target_token})")
    
    # 复制文档到目标节点
    return copy_document(doc_token, doc_title, target_token, copier_helper)

def process_two_level_tag(doc_token, doc_title, tag, creator, copier_helper,
                         name_checker, node_finder, space_id, parent_token):
    """处理二级标签"""
    level1tag = tag["tag1"][0]
    level2tag = tag["tag2"][0]
    
    # 检查一级节点
    level1_exists = name_checker.check_duplicate(
        space_id, level1tag, parent_token
    )['is_duplicate']
    
    if level1_exists:
        # 获取一级节点token
        result = node_finder.get_parent_token_by_node_name(
            space_id, level1tag, parent_token
        )
        if not result.get("found"):
            print(f"❌ 未找到一级节点: {level1tag}")
            return False
        level1_token = result["node_token"]
        
        # 检查二级节点
        level2_exists = name_checker.check_duplicate(
            space_id, level2tag, level1_token
        )['is_duplicate']
        
        if level2_exists:
            # 获取二级节点token
            result2 = node_finder.get_parent_token_by_node_name(
                space_id, level2tag, level1_token
            )
            if result2.get("found"):
                target_token = result2["node_token"]
                print(f"✅ 找到已存在的二级节点: {level2tag}")
            else:
                return False
        else:
            # 创建二级节点
            _, target_token, new_title = creator.create_lark_node(level1_token, level2tag)
            if not target_token:
                print(f"❌ 创建二级节点失败: {level2tag}")
                return False
            print(f"✅ 创建新二级节点: {new_title}")
    else:
        # 创建一级节点
        _, level1_token, _ = creator.create_lark_node(parent_token, level1tag)
        if not level1_token:
            print(f"❌ 创建一级节点失败: {level1tag}")
            return False
        
        # 创建二级节点
        _, target_token, new_title = creator.create_lark_node(level1_token, level2tag)
        if not target_token:
            print(f"❌ 创建二级节点失败: {level2tag}")
            return False
        print(f"✅ 创建新节点: {level1tag} -> {new_title}")
    
    # 复制文档
    return copy_document(doc_token, doc_title, target_token, copier_helper)

def process_three_level_tag(doc_token, doc_title, tag, creator, copier_helper,
                           name_checker, node_finder, space_id, parent_token):
    """处理三级标签"""
    level1tag = tag["tag1"][0]
    level2tag = tag["tag2"][0]
    level3tag = tag["tag3"][0]
    
    # 检查一级节点
    level1_exists = name_checker.check_duplicate(
        space_id, level1tag, parent_token
    )['is_duplicate']
    
    if level1_exists:
        result1 = node_finder.get_parent_token_by_node_name(space_id, level1tag, parent_token)
        if not result1.get("found"):
            return False
        level1_token = result1["node_token"]
        
        # 检查二级节点
        level2_exists = name_checker.check_duplicate(space_id, level2tag, level1_token)['is_duplicate']
        
        if level2_exists:
            result2 = node_finder.get_parent_token_by_node_name(space_id, level2tag, level1_token)
            if not result2.get("found"):
                return False
            level2_token = result2["node_token"]
            
            # 检查三级节点
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
        # 创建完整的三级结构
        _, level1_token, _ = creator.create_lark_node(parent_token, level1tag)
        if not level1_token:
            return False
        _, level2_token, _ = creator.create_lark_node(level1_token, level2tag)
        if not level2_token:
            return False
        _, target_token, _ = creator.create_lark_node(level2_token, level3tag)
        if not target_token:
            return False
    
    return copy_document(doc_token, doc_title, target_token, copier_helper)

def copy_document(doc_token: str, doc_title: str, target_folder_token: str, copier_helper) -> bool:
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
    
    # 1. 获取飞书token
    print("\n🔑 步骤1: 获取飞书访问令牌...")
    token = get_tenant_access_token()
    if not token:
        print("❌ 无法获取飞书token, 程序退出")
        return
    
    print("✅ 飞书token获取成功")
    
    # 2. 初始化各个组件
    print("\n🔧 步骤2: 初始化组件...")
    reader = FeishuDocumentReader(token)
    classifier = QwenTreeClassifier(Qwen_AI_KEY)
    creator = FeishuNodeCreator(token, SPACE_ID)
    name_checker = FolderNameChecker(FEISHU_APP_ID, FEISHU_APP_SECRET)
    node_finder = FeishuWikiNodeFinder(FEISHU_APP_ID, FEISHU_APP_SECRET)
    tag_adder = FeishuDocumentTagAdder(token)
    print("✅ 组件初始化完成")
    
    # 3. 扫描知识库获取所有文档（替代多维表格）
    print("\n📂 步骤3: 扫描知识库获取文档列表...")
    scanner = SimpleWikiScanner(FEISHU_APP_ID, FEISHU_APP_SECRET)
    
    all_documents = scanner.scan_space(
        space_id=SPACE_ID,
        root_token=PARENT_NODE_TOKEN,
        use_cache=USE_CACHE
    )
    
    print(f"✅ 扫描完成！共找到 {len(all_documents)} 个文档")
    
    # 限制处理数量（用于测试）
    if MAX_DOCUMENTS:
        all_documents = all_documents[:MAX_DOCUMENTS]
        print(f"⚠️ 测试模式：只处理前 {MAX_DOCUMENTS} 个文档")
    
    # 4. 加载处理进度（断点续传）
    processed_tokens = load_processing_progress()
    print(f"📊 已处理文档数: {len(processed_tokens)}")
    
    # 5. 处理每个文档
    print("\n🔄 步骤4: 开始处理文档...")
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    for idx, doc in enumerate(all_documents, 1):
        doc_token = doc["node_token"]
        doc_title = doc["title"]
        
        # 跳过已处理的文档
        if doc_token in processed_tokens:
            print(f"\n[{idx}/{len(all_documents)}] ⏭️ 跳过已处理文档: {doc_title}")
            skip_count += 1
            continue
        
        # 处理文档
        success = process_single_document(
            doc_token, doc_title, reader, classifier, creator, None,
            name_checker, node_finder, tag_adder, processed_tokens
        )
        
        if success:
            success_count += 1
            processed_tokens.add(doc_token)
        else:
            fail_count += 1
        
        # 每处理10个文档保存一次进度
        if idx % 10 == 0:
            save_processing_progress(processed_tokens)
        
        # 显示进度
        elapsed = (datetime.now() - start_time).total_seconds()
        avg_time = elapsed / idx
        remaining = (len(all_documents) - idx) * avg_time
        print(f"\n📈 进度: {idx}/{len(all_documents)} | 成功: {success_count} | 失败: {fail_count} | 跳过: {skip_count}")
        print(f"⏱️ 预计剩余时间: {remaining/60:.1f} 分钟")
    
    # 6. 最终统计
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()
    
    print("\n" + "="*60)
    print("🎉 处理完成！")
    print("="*60)
    print(f"📊 统计信息:")
    print(f"   - 总文档数: {len(all_documents)}")
    print(f"   - 成功: {success_count}")
    print(f"   - 失败: {fail_count}")
    print(f"   - 跳过: {skip_count}")
    print(f"   - 成功率: {success_count/(success_count+fail_count)*100:.1f}%")
    print(f"   - 总耗时: {elapsed/60:.1f} 分钟")
    print(f"   - 平均每文档: {elapsed/len(all_documents):.2f} 秒")
    print("="*60)
    
    # 保存最终进度
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