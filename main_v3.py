#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书文档分类
"""
import json
import re
from typing import Optional, Dict, List
import requests
from CreateFeishuNode import FeishuNodeCreator
from Copydoc import FeishuWikiCopier
from ReadFeishuRaw import FeishuDocumentReader
from AddTagBlock import FeishuDocumentTagAdder
from deepseekAI import DeepSeekTreeClassifier
from GetTokenFromTable import FeishuBitableExtractor
from FindNodeByName import FeishuWikiNodeFinder
from FeishuTitleCheck import FolderNameChecker
from QwenAI import QwenTreeClassifier
# ============================================================
# 配置部分
# ============================================================

# 飞书应用配置
FEISHU_APP_ID = "cli_a93910bbc5f95cc2"                     # 飞书应用 App ID
FEISHU_APP_SECRET = "srbaL4nDLMAoEa9jYFQMrhtipJv2ZfvD"     # 飞书应用 App Secret
PARENT_NODE_TOKEN = "ZrEOwxMYEiKxNvkmG3ucS0TknFg"                                     # 父节点token，为空则创建父节点
# 父节点token：ZrEOwxMYEiKxNvkmG3ucS0TknFg
# SPACE_ID = "7540196657544347650"                           # 创建节点需要使用
SPACE_ID = "7595802147485141976"  
#测试ID： 7595802147485141976
# APP_TOKEN = "TqVuw4zA5iloCkkhJ58cOxTAn4c"                  # 表格的token
APP_TOKEN = "OZypbpofiaI774szaGlcCVaUnjd"   
# 测试表格token OZypbpofiaI774szaGlcCVaUnjd
# TABLE_ID = "tbl4F1KvMQ7iPpOx"                              # 多维表格ID
TABLE_ID = "tblIX6fxzFKzGe3b"  
# table ID：tblIX6fxzFKzGe3b
#https://quectel.feishu.cn/base/OZypbpofiaI774szaGlcCVaUnjd?table=tblIX6fxzFKzGe3b&view=vew5R4hBp1
Tablename = "文档链接"

# AI 配置
DEEPSEEK_API_KEY = "sk-88e00b5638c542c5a2ea84d64bb1fc24"   # DEEPSEEK AI KEY
Qwen_AI_KEY = "sk-9neu2wGxtXiOb9EcBDlL6g"                  # Qwen AI KEY


# ============================================================
# 飞书 API 辅助函数
# ============================================================

def get_tenant_access_token() -> Optional[str]:
    """
    获取飞书 tenant_access_token
    Returns:
        access_token 或 None
    """
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

#-------------------------------------------------------------------------------------------
# ****************************************入口函数！*****************************************
#-------------------------------------------------------------------------------------------
def main():
    token = get_tenant_access_token()
    if not token:
        print("无法获取飞书 token, 请检查token是否正常，本次退出！！！")
        return        
    creator = FeishuNodeCreator(token,SPACE_ID)                      # 创建实例 -> 创建节点实例
    Rawdata = FeishuDocumentReader(token)                            # 创建实例 -> 创建读取飞书文档内容实例                                     
    TagAdd = FeishuDocumentTagAdder(token)                           # 创建实例 -> 创建打标签实例
#    deepseek = DeepSeekTreeClassifier(DEEPSEEK_API_KEY)             # 创建实例 -> 创建调用Deepseek AI实例
    qwen = QwenTreeClassifier(Qwen_AI_KEY)                           # 创建实例 -> 创建调用Qwen AI实例
    FeishuNodeNameCheck = FolderNameChecker(FEISHU_APP_ID,FEISHU_APP_SECRET)  # 创建实例 -> 判断知识库指定父节点下是否存在同名子节点
    FeishuTableTokne = FeishuBitableExtractor(
        app_id = FEISHU_APP_ID,
        app_secret= FEISHU_APP_SECRET,
        app_token= APP_TOKEN,
        table_id= TABLE_ID
    )        
    FindNodeByname =  FeishuWikiNodeFinder(FEISHU_APP_ID,FEISHU_APP_SECRET)     # 创建实例 -> 根据节点名称查询父节点                                                    # 创建实例 -> 获取多维表格中文档的token
    docx_ids = FeishuTableTokne.get_column_records(Tablename)                   # 根据多维表格列名称或者整列所有token
    print(f"共获取到 {len(docx_ids)} 个文档: {docx_ids}")

    for docx_id in docx_ids:
        print(f"\n>>> 开始遍历处理文档: {docx_id}")
        content = Rawdata.get_raw_content(docx_id)                  # 读取文档并将内容存储在content
        if not content:
            print("文档内容为空，跳过")
            continue
        else:
            Title = Rawdata.get_title(docx_id)                       # 获取文档标题
#            tag = deepseek.classify(content)
            tag = qwen.classify(content)
            print(f"\n>>>>  生成标签: {tag}")
#*********************************************************************************************
#*********************开始处理文档，创建节点，打标签，复制文档等!*********************************
#*********************************************************************************************
            if len(tag) ==1 :
                level1tag = tag["tag1"][0]
                tag_message = f"\n | Tag1: {level1tag}"
                if FeishuNodeNameCheck.check_duplicate(SPACE_ID,level1tag, PARENT_NODE_TOKEN)['is_duplicate'] is True:  # 检查root节点下有无level1tag相同名称的节点，返回Ture or False
                # 如果节点名称已经存在，直接获取名称对应的父节点
                    Parent_token = FindNodeByname.get_parent_token_by_node_name(SPACE_ID,level1tag,PARENT_NODE_TOKEN)
                    if Parent_token:    
                        #获取成功，复制文档
                        copier = FeishuWikiCopier( 
                            app_id=FEISHU_APP_ID,
                            app_secret=FEISHU_APP_SECRET,
                            node_token=docx_id,
                            target_folder_token=Parent_token["node_token"],
                            new_file_name=Title,
                            source_space_id=SPACE_ID,
                            target_space_id=SPACE_ID,   
                            )
                        copy_docx = copier.copy_document_by_node_token()  
                    else:
                        print("异常！没有根据节点名称获取到对应的父节点Token！！！")
                else: 
                    # 如果节点不存在，直接创建新节点
#                   Addtagblock = TagAdd.add_tag_block(docx_id,tag_message)
                    rsp1, level1_node_token, level1_new_title = creator.create_lark_node(PARENT_NODE_TOKEN,level1tag) 
                    copier = FeishuWikiCopier( 
                        app_id=FEISHU_APP_ID,
                        app_secret=FEISHU_APP_SECRET,
                        node_token=docx_id,
                        target_folder_token=level1_node_token,
                        new_file_name=Title,
                        source_space_id=SPACE_ID,
                        target_space_id=SPACE_ID,   
                        )
                    copy_docx = copier.copy_document_by_node_token()  
                print("只有一个标签的文档复制完成！！！！！！")
            if len(tag) == 2:
                level1tag = tag["tag1"][0]   # 获取标签1
                level2tag = tag["tag2"][0]   # 获取标签2
                tag_message = f"\n | Tag1: {level1tag} | Tag1: {level2tag} "
                if FeishuNodeNameCheck.check_duplicate(SPACE_ID,level1tag, PARENT_NODE_TOKEN)['is_duplicate'] is True:   
                    Parent_token = FindNodeByname.get_parent_token_by_node_name(SPACE_ID,level1tag,PARENT_NODE_TOKEN)
                    # 如果标签1名称已存在，检查标签1节点下是否存标签2名称
                    # #*****************************************
                    # s = Parent_token["node_token"]
                    # print("Parent_token; "+ str(s))
                    # #****************************************
                    if FeishuNodeNameCheck.check_duplicate(SPACE_ID,level2tag,Parent_token["node_token"])['is_duplicate'] is True:
                        level2_info = FindNodeByname.get_parent_token_by_node_name(SPACE_ID, level2tag, Parent_token["node_token"])
                        if level2_info and level2_info.get("found"):
                            target_folder_token = level2_info['node_token']
                        else:
                            target_folder_token = Parent_token["node_token"]   # 降级处理，或直接报错
                        copier = FeishuWikiCopier( 
                            app_id=FEISHU_APP_ID,
                            app_secret=FEISHU_APP_SECRET,
                            node_token=docx_id,
                            target_folder_token=target_folder_token,
                            new_file_name=Title,
                            source_space_id=SPACE_ID,
                            target_space_id=SPACE_ID,   
                            )
                        copy_docx = copier.copy_document_by_node_token()  
                        # 如果存在，直接复制文档
                    else:
                        # 如果标签2名称不存在，直接创建
                        rsp2, level2_node_token, level2_new_title = creator.create_lark_node(Parent_token["node_token"],level2tag)
                        copier = FeishuWikiCopier( 
                            app_id=FEISHU_APP_ID,
                            app_secret=FEISHU_APP_SECRET,
                            node_token=docx_id,
                            target_folder_token=level2_node_token,   # 一级存在、二级不存在时，直接复制到创建的2级token下
                            new_file_name=Title,
                            source_space_id=SPACE_ID,
                            target_space_id=SPACE_ID,   
                            )
                        copy_docx = copier.copy_document_by_node_token()      
                else:
                    # 如果标签1不存在，直接在父节点下创建新节点
                    rsp1, level1_node_token, level1_new_title = creator.create_lark_node(PARENT_NODE_TOKEN,level1tag)
                    if level1_node_token:
                        print("level1_node_token: "+str(level1_node_token))
                    # 不需要考虑标签2存在与否，因为父级节点是新创建的，子节点肯定不会重复，则可以直接创建
                        rsp2, level2_node_token, level2_new_title = creator.create_lark_node(level1_node_token,level2tag)
                    # 2节点创建完成后直接复制文档
                        copier = FeishuWikiCopier( 
                            app_id=FEISHU_APP_ID,
                            app_secret=FEISHU_APP_SECRET,
                            node_token=docx_id,
                            target_folder_token=level2_node_token,
                            new_file_name=Title,
                            source_space_id=SPACE_ID,
                            target_space_id=SPACE_ID,   
                            )
                        copy_docx = copier.copy_document_by_node_token()                          
                    else:
                        print("2标签时创建1标签节点失败！！！！")
                #Addtagblock = TagAdd.add_tag_block(docx_id,tag_message)
                print("只有2个标签的文档复制完成！！！！！！")
            if len(tag) == 3:
                level1tag = tag["tag1"][0]
                level2tag = tag["tag2"][0]
                level3tag = tag["tag3"][0]
                tag_message = f"\n | Tag1: {level1tag} | Tag2: {level2tag} | Tag3: {level3tag}"
                #Addtagblock = TagAdd.add_tag_block(docx_id,tag_message)
                if FeishuNodeNameCheck.check_duplicate(SPACE_ID,level1tag,PARENT_NODE_TOKEN)['is_duplicate'] is True: 
                    # 如果一级标签存在，获取一级标签节点token
                    Parent_token = FindNodeByname.get_parent_token_by_node_name(SPACE_ID,level1tag,PARENT_NODE_TOKEN)
                    # 如果二级标签存在，根据一级标签的token获取二级标签token
                    if FeishuNodeNameCheck.check_duplicate(SPACE_ID,level2tag,Parent_token["node_token"])['is_duplicate'] is True: 
                        Parent2_token = FindNodeByname.get_parent_token_by_node_name(SPACE_ID,level2tag,Parent_token["node_token"])
                    # 如果三级标签存在，根据二级标签的token获取三级标签token
                        if FeishuNodeNameCheck.check_duplicate(SPACE_ID,level3tag,Parent2_token["node_token"])['is_duplicate'] is True: 
                            Parent3_token = FindNodeByname.get_parent_token_by_node_name(SPACE_ID,level3tag,Parent2_token["node_token"])
                            #level2_info = FindNodeByname.get_parent_token_by_node_name(SPACE_ID, level2tag, Parent_token["node_token"])
                            if Parent3_token and Parent3_token.get("found"):
                                target_folder_token = Parent3_token['node_token']
                            else:
                                target_folder_token = Parent_token["node_token"]   # 降级处理，或直接报错
                    # 如果3级标签存在，直接复制文档到三级节点
                            copier = FeishuWikiCopier( 
                                app_id=FEISHU_APP_ID,
                                app_secret=FEISHU_APP_SECRET,
                                node_token=docx_id,
                                target_folder_token=target_folder_token,
                                new_file_name=Title,
                                source_space_id=SPACE_ID,
                                target_space_id=SPACE_ID,   
                                )
                            copy_docx = copier.copy_document_by_node_token()  
                           # 如果存在，直接复制文档
                        else:
                    # 如果三级标签不存在，创建新节点再复制文档
                            rsp3, level3_node_token, level3_new_title = creator.create_lark_node(Parent3_token["node_token"],level3tag)
                            if level3_node_token:
                                copier = FeishuWikiCopier( 
                                    app_id=FEISHU_APP_ID,
                                    app_secret=FEISHU_APP_SECRET,
                                    node_token=docx_id,
                                    target_folder_token=level3_node_token,
                                    new_file_name=Title,
                                    source_space_id=SPACE_ID,
                                    target_space_id=SPACE_ID,   
                                    )
                                copy_docx = copier.copy_document_by_node_token()  
                            else:
                                pass
                    
                    else:
                        # 如果二级标签不存在，根据一级标签的token直接创建2级别标签
                        rsp2, level2_node_token, level2_new_title = creator.create_lark_node(Parent_token["node_token"],level2tag)
                        # 二级标签创建完成，直接创建三级标签
                        if level2_node_token:
                            rsp3, level3_node_token, level3_new_title = creator.create_lark_node(level2_node_token,level3tag)
                            if level3_node_token:
                            # 三级创建完成，复制文档
                                copier = FeishuWikiCopier( 
                                    app_id=FEISHU_APP_ID,
                                    app_secret=FEISHU_APP_SECRET,
                                    node_token=docx_id,
                                    target_folder_token=level3_node_token,
                                    new_file_name=Title,
                                    source_space_id=SPACE_ID,
                                    target_space_id=SPACE_ID,   
                                    )
                                copy_docx = copier.copy_document_by_node_token()      
                            else:
                                pass
                        else:
                            pass 
                else:
                    # 如果一级节点不存在，直接新建节点
                    rsp1, level1_node_token, level1_new_title = creator.create_lark_node(PARENT_NODE_TOKEN,level1tag)
                    if level1_node_token:
                        rsp2, level2_node_token, level2_new_title = creator.create_lark_node(level1_node_token,level2tag)
                        if level2_node_token:
                            rsp3, level3_node_token, level3_new_title = creator.create_lark_node(level2_node_token,level3tag)
                            if level3_node_token:
                                copier = FeishuWikiCopier( 
                                    app_id=FEISHU_APP_ID,
                                    app_secret=FEISHU_APP_SECRET,
                                    node_token=docx_id,
                                    target_folder_token=level3_node_token,
                                    new_file_name=Title,
                                    source_space_id=SPACE_ID,
                                    target_space_id=SPACE_ID,   
                                    )
                                copy_docx = copier.copy_document_by_node_token()   
                            else:
                                pass
                        else:
                            pass
                    else:
                        pass
    
if __name__ == "__main__":
    main()
