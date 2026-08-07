# 项目结构

> 对应分支：`feature/tool-ops-target-scope` · 更新 2026-08-07

```text
AI_DocClassifier/
├── main.py                     # 主流程：扫描/附件提取/分类复制
├── config.py
├── run_console.py
├── enrichment/                 # 复制后增强步骤（贴表/附件分隔）
├── feishu/ / classify/ / attachment/
├── state/
│   ├── shared_state.py         # 主流程去重（分类复制）
│   ├── scan_snapshot.py        # 主流程扫描增量
│   ├── operation_ledger.py     # 工具统一操作账本 tool_ops.db
│   ├── target_docs.py          # 列出 TARGET 叶子文档
│   └── …
├── tools/
│   ├── _tool_scope.py          # 文档宇宙：默认 target，可选 scan
│   ├── enrich_copied_docs.py   # 增强回填（默认 TARGET）
│   ├── export_doc_metadata_bitable.py
│   ├── export_display_title_bitable.py
│   └── …
├── console/
└── docs/
```

## 常用命令

```powershell
# 主流程
python main.py --all-assigned

# 工具（默认只处理 TARGET 下文档）
python -m tools.enrich_copied_docs --dry-run --limit 20
python -m tools.export_display_title_bitable --dry-run --max-documents 20
python -m tools.export_doc_metadata_bitable --mode aggregated --dry-run --max-documents 20

# 显式扫源（旧行为）
python -m tools.export_doc_metadata_bitable --scope scan --all-assigned --mode per-token
```
