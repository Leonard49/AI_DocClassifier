# 项目结构

```text
AI_DocClassifier/
├── scan_folders.json          # 源文件夹 token 清单
├── scan_folders.example.json  # 清单模板
├── main.py                 # 主流程入口（支持 --all-assigned 批量）
├── config.py               # 环境变量配置
├── retry_attachment_extract.py
├── reclassify_others_move.py
├── others_theme_classify_move.py
├── export_doc_metadata_bitable.py
├── feishu/
│   ├── http.py
│   ├── token_manager.py
│   ├── wiki_scanner.py
│   ├── read_doc.py
│   ├── copy_doc.py
│   ├── wiki_move.py
│   ├── create_feishu_node.py   # 支持 obj_type=bitable
│   ├── bitable.py              # 多维表格 API
│   ├── wiki_meta.py            # 节点作者解析
│   ├── title_check.py
│   └── add_tag_block.py
├── classify/
│   ├── llm_tree_classifier.py
│   ├── module_product_map.py
│   ├── doc_metadata.py         # 产品线/型号/文档类型提取
│   ├── others_theme.py
│   ├── classify_cache.py
│   └── llm_rate_limit.py
├── state/
│   ├── shared_state.py
│   ├── scan_folders.py
│   ├── metadata_bitable.py     # 确保表格 + 幂等写入索引
│   └── …
├── attachment/
├── tools/
│   ├── retry_attachment_extract.py
│   ├── reclassify_others_move.py
│   ├── others_theme_classify_move.py
│   └── export_doc_metadata_bitable.py
├── util/
└── docs/
```

## 常用命令

```powershell
# 清单批量分类复制
python main.py --list-folders
python main.py --all-assigned

# 文档元数据 → 多维表格（独立工具；汇总 + 按 token 分表）
python -m tools.export_doc_metadata_bitable --dry-run --max-documents 20
python -m tools.export_doc_metadata_bitable --all-enabled --mode both
python -m tools.export_doc_metadata_bitable --folder 25.Smart-FAE --mode per-token
python -m tools.export_doc_metadata_bitable --scan-token <wiki_token> --mode aggregated

python -m tools.retry_attachment_extract
python -m tools.reclassify_others_move --dry-run
python -m tools.others_theme_classify_move --dry-run
```
