# 项目结构

```text
AI_DocClassifier/
├── scan_folders.json
├── scan_folders.example.json
├── main.py
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
│   ├── metadata_bitable.py
│   └── …
├── attachment/
├── tools/
│   ├── export_doc_metadata_bitable.py
│   └── …
├── util/
└── docs/
```

## 常用命令

```powershell
# 本地 Web 控制台（配置 + 跑分类/元数据）
python run_console.py
# 或双击 启动控制台.bat → http://127.0.0.1:8787

python main.py --list-folders
python main.py --all-assigned
python main.py --folder 25.Smart-FAE

python -m tools.export_doc_metadata_bitable --all-assigned --mode per-token
python -m tools.retry_attachment_extract
python -m tools.reclassify_others_move --dry-run
python -m tools.others_theme_classify_move --dry-run
```
