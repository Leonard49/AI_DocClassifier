# 项目结构

```text
AI_DocClassifier/
├── scan_folders.json          # 源文件夹 token 清单（可提交；本地也可用 SCAN_FOLDERS_FILE 覆盖）
├── scan_folders.example.json  # 清单模板
├── main.py                 # 主流程入口（支持 --all-assigned 批量）
├── config.py               # 环境变量配置
├── retry_attachment_extract.py   # 兼容入口 → tools/
├── reclassify_others_move.py      # 兼容入口 → tools/
├── others_theme_classify_move.py # 兼容入口 → tools/
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
│   ├── others_theme.py     # Others 主题桶（规则/LLM）
│   ├── classify_cache.py
│   └── llm_rate_limit.py
├── state/                  # 共享去重 / 分卷 / 快照 / 路径
│   ├── shared_state.py
│   ├── shared_folder_rollover.py
│   ├── folder_rollover.py
│   ├── tag_folder_path.py
│   ├── scan_snapshot.py
│   └── scan_folders.py     # 源文件夹 token 清单加载/分工过滤
├── attachment/             # 附件提取
│   ├── extractor.py
│   └── extractors/         # PDF / Word / PPT
├── tools/                  # 运维专项脚本
│   ├── retry_attachment_extract.py
│   ├── reclassify_others_move.py
│   └── others_theme_classify_move.py
├── util/
│   └── run_logging.py
└── docs/
```

## 常用命令

```powershell
# 推荐：维护 scan_folders.json，按人自动批量
python main.py --list-folders                      # 查看清单与分工
python main.py --all-assigned                      # 跑自己名下全部文件夹
python main.py --folder 25.Smart-FAE
python main.py --all-enabled                       # 跑清单内全部（负责人）

# 兼容旧方式：.env 里设 SCAN_ROOT_TOKEN 后直接跑
python main.py

python -m tools.retry_attachment_extract
python -m tools.reclassify_others_move --dry-run
python -m tools.others_theme_classify_move --dry-run
# 旧命令仍可用（根目录薄封装）:
python retry_attachment_extract.py
python reclassify_others_move.py --dry-run
```