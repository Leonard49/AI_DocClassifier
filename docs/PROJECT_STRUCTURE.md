# 项目结构

> 对应分支：`feature/arch-data-dir-cleanup` · 更新 2026-08

## Core vs Tools

| | **Core（主流程）** | **Tools（侧工具）** |
|--|--|--|
| 入口 | `main.py` | `python -m tools.*` |
| 文档宇宙 | `SCAN_*` 源目录 | 默认 `TARGET_PARENT_TOKEN`（`--scope scan` 可选） |
| 状态 | `data/core/*` + 共享 `SHARED_STATE_DB`（UNC） | **唯一**账本 `data/tools/tool_ops.db` |
| 职责 | 扫描 → 附件提取 → 分类 → 复制 | 元数据表/分隔符回填、bitable 导出、展示标题等 |
| 扩展 | 复制后钩子走 `enrichment/` 插件 | 新工具：加 `OP_*` + `ToolJob` + console 挂项；**禁止**再建 `*_index.db` |

```text
AI_DocClassifier/
├── main.py                     # Core：扫描/附件提取/分类复制（本轮不拆）
├── config.py                   # DATA_DIR、路径解析、ensure_runtime_layout
├── util/paths.py               # resolve_configurable_path / 旧库迁移
├── data/                       # 本地运行时（gitignore）
│   ├── core/                   # scan_snapshot、classify_cache、progress…
│   └── tools/                  # tool_ops.db（唯一工具账本）
├── enrichment/                 # 复制后增强步骤
├── feishu/ / classify/ / attachment/
├── attachment_extractors/      # 遗留副本，见其 README；请用 attachment/
├── state/
│   ├── shared_state.py         # Core 去重
│   ├── scan_snapshot.py
│   ├── operation_ledger.py     # Tools 统一账本
│   ├── metadata_bitable.py     # record_id → ledger.result_ref
│   └── target_docs.py
├── tools/
│   ├── runner.py               # ToolJob 基类
│   ├── _tool_scope.py          # 文档宇宙：默认 target
│   ├── enrich_copied_docs.py
│   ├── export_doc_metadata_bitable.py
│   ├── export_display_title_bitable.py
│   └── …
├── export_*.py / retry_*.py    # 根目录兼容 shim → tools.*
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
