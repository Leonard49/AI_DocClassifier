# 项目结构

> 对应分支：`feature/doc-enrichment` · 更新 2026-07-31

```text
AI_DocClassifier/
├── scan_folders.json
├── scan_folders.example.json
├── main.py                     # 流程编排；复制后调用 enrichment 钩子
├── config.py
├── run_console.py              # 本地 Web 控制台
├── 启动控制台.bat
├── console/                    # FastAPI + 静态前端
│   ├── app.py
│   ├── env_io.py
│   ├── jobs.py
│   └── static/
├── export_doc_metadata_bitable.py
├── retry_attachment_extract.py
├── reclassify_others_move.py
├── others_theme_classify_move.py
├── enrichment/                 # 文档增强插件（复制后 + 回填）
│   ├── __init__.py
│   ├── base.py                 # EnrichmentContext / Pipeline / Step
│   ├── markers.py              # 共享横幅文案与块结构
│   ├── detect.py               # 幂等检测与按索引插入
│   ├── steps.py                # metadata_table / attachment_separator
│   └── hooks.py                # enrich_after_copy（供 main 调用）
├── feishu/
│   ├── bitable.py
│   ├── metadata_table.py
│   ├── wiki_meta.py
│   └── …
├── classify/
│   ├── doc_metadata.py
│   └── …
├── state/
│   ├── scan_folders.py
│   ├── shared_state.py         # 含 list_copied（回填用）
│   ├── metadata_bitable.py
│   └── …
├── attachment/                 # 附件提取；分隔符块复用 enrichment.markers
├── tools/
│   ├── export_doc_metadata_bitable.py
│   ├── enrich_copied_docs.py   # 已复制文档增强回填
│   └── …
├── util/
└── docs/
```

## 常用命令

```powershell
# 本地 Web 控制台（配置 + 跑分类/元数据/回填）
python run_console.py
# 或双击 启动控制台.bat → http://127.0.0.1:8787

python main.py --list-folders
python main.py --all-assigned
python main.py --folder 25.Smart-FAE

python -m tools.export_doc_metadata_bitable --all-assigned --mode per-token
python -m tools.enrich_copied_docs --dry-run --limit 20
python -m tools.enrich_copied_docs
python -m tools.retry_attachment_extract
python -m tools.reclassify_others_move --dry-run
python -m tools.others_theme_classify_move --dry-run
```
