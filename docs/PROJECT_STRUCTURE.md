# 项目结构

```text
AI_DocClassifier/
├── main.py                 # 主流程入口
├── config.py               # 环境变量配置
├── retry_attachment_extract.py   # 兼容入口 → tools/
├── reclassify_others_move.py      # 兼容入口 → tools/
├── feishu/                 # 飞书 API 与 wiki 操作
│   ├── http.py             # 限速 + 重试 HTTP
│   ├── rate_limit.py
│   ├── token_manager.py
│   ├── wiki_scanner.py
│   ├── read_doc.py
│   ├── copy_doc.py
│   ├── wiki_move.py
│   ├── create_feishu_node.py
│   ├── title_check.py
│   └── add_tag_block.py
├── classify/               # LLM 分类
│   ├── llm_tree_classifier.py
│   ├── module_product_map.py
│   ├── classify_cache.py
│   └── llm_rate_limit.py
├── state/                  # 共享去重 / 分卷 / 快照 / 路径
│   ├── shared_state.py
│   ├── shared_folder_rollover.py
│   ├── folder_rollover.py
│   ├── tag_folder_path.py
│   └── scan_snapshot.py
├── attachment/             # 附件提取
│   ├── extractor.py
│   └── extractors/         # PDF / Word / PPT
├── tools/                  # 运维专项脚本
│   ├── retry_attachment_extract.py
│   └── reclassify_others_move.py
├── util/
│   └── run_logging.py
└── docs/
```

## 常用命令

```powershell
python main.py
python -m tools.retry_attachment_extract
python -m tools.reclassify_others_move --dry-run
# 旧命令仍可用（根目录薄封装）:
python retry_attachment_extract.py
python reclassify_others_move.py --dry-run
```
