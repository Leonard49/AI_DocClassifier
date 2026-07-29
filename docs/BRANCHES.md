# 分支变更记录

> 记录各功能分支相对 `master` 的重要变化，便于选型与合并。  
> **当前推荐落地分支：`feature/console-ui`**（2026-07-29）

---

## `master`

- 早期单机版飞书文档自动分类
- 基础流程：扫描 → 读取 → LLM 分类 → 复制
- 系统说明文档与流程图

---

## `feature/multi-worker-parallel`

**基于：** `master`

**主要变化：**

| 能力 | 说明 |
|------|------|
| 多人并行 | 不同 worker 扫描不同源目录，共享同一目标目录 |
| 全局去重 | `shared_copy_state.db` 按 `obj_token` 去重，避免重复复制 |
| 目标目录验证 | 结束时扫描目标目录，以实际叶子文档数作为成功口径 |
| 共享库容错 | 网络盘 SQLite 禁用 WAL、损坏自动重建 |
| 通用 LLM 分类器 | `classify/llm_tree_classifier.py`，`LLM_MODEL` / `LLM_BASE_URL` 可配置 |
| 飞书/LLM 限流 | `READ_WORKERS=2` 建议值，LLM 全局并发≤2 |
| 同名标题处理 | 目标子目录自动重命名为 `标题 (2)` 等 |

**关联文件：** `state/shared_state.py`、`config.py` 并行配置

---

## `feature/scan-snapshot-plan-b`

**基于：** `feature/multi-worker-parallel`

**主要变化：**

| 能力 | 说明 |
|------|------|
| 扫描快照（Plan B） | `scan_snapshot.db` 记录已知叶子，增量模式只处理新增与失败重试 |
| 周期性全量校准 | `FULL_SCAN_CALIBRATION_DAYS` 定期刷新快照基线 |
| 排除类文档 | 周报/日报/会议纪要/客户问题跟踪（含**重点客户跟踪**）跳过分类与复制 |
| 来源路径优先 | `source_path` 面包屑用于域提示（ShortRange / Automotive / GNSS） |
| 分类失败清单 | `logs/classification_failures.json` 记录标题与 wiki 路径 |
| 排除类清单 | `logs/excluded_reports.json` |

**关联文件：** `state/scan_snapshot.py`、`classify/llm_tree_classifier.py`（排除规则）

---

## `feature/attachment-extract`

**基于：** `feature/scan-snapshot-plan-b`

**主要变化：**

| 能力 | 说明 |
|------|------|
| 附件提取合入 | PDF / Word / PPT 附件下载并转文本写回源 docx |
| 功能开关 | `ENABLE_ATTACHMENT_EXTRACT=true/false` |
| 防重复 | 已有 `附件：{文件名}` 标题则跳过 |
| 可视化统计 | 进度条、阶段汇总、终局统计、失败列表 |
| 运行清单 | `logs/attachment_extract.json` |
| 失败重试 | `tools/retry_attachment_extract.py` |
| 依赖 | `PyMuPDF`、`python-docx`、`lxml`、`python-pptx`；旧版 `.doc`/`.ppt` 需 LibreOffice 或 Word |
| 跨进程飞书限速 | `feishu/http.py` + `FEISHU_RATE_LIMIT_DB` |

**移除：** 独立子项目 `PDF2Feishu/`（逻辑已迁入主仓库）

---

## `feature/classify-quality-restructure`

**基于：** `feature/attachment-extract`

**主要变化：**

| 能力 | 说明 |
|------|------|
| 包结构重组 | 代码按 `feishu/`、`classify/`、`state/`、`attachment/`、`tools/`、`util/` 划分 |
| 产品线判定 | QT-SOP-PM-048E 模组/项目名 → 产品线（`classify/module_product_map.py`） |
| Others 占比告警 | `OTHERS_RATIO_FAIL_THRESHOLD`（默认 0.15）超限写报告，仍继续复制 |
| 单层超限分卷 | Feishu 131003 时创建同级 `名称 (2)` 分卷；共享 `folder_rollover_state.db` |
| Others 存量纠偏 | `tools/reclassify_others_move.py` 重分类后 **move**（非 copy） |
| 文档 | `docs/分类准则说明.md`、`docs/PROJECT_STRUCTURE.md` |

**关联文件：** `attachment/`、`classify/`、`state/`、`tools/`、`docs/分类准则说明.md`、`docs/PROJECT_STRUCTURE.md`

**兼容：** 根目录保留 `retry_attachment_extract.py`、`reclassify_others_move.py` 薄入口

---

## `feature/scan-folders-batch`

**基于：** `feature/classify-quality-restructure`

**主要变化：**

| 能力 | 说明 |
|------|------|
| 源文件夹清单 | `scan_folders.json` 集中记录全部 `SCAN_ROOT` token、名称、`assignee` |
| 一人批量增量 | `python main.py --all-assigned`（或未设 `SCAN_ROOT_TOKEN` 时直接 `python main.py`）按人跑完全部负责目录 |
| CLI | `--list-folders` / `--folder ID` / `--all-assigned` / `--all-enabled` / `--folders-file` |
| Others 主题归档 | `tools/others_theme_classify_move.py`：主题子夹只挂主 Others，并尽量清空 Others (2) |
| 配置 | `SCAN_FOLDERS_FILE`；`.env.example` 更新 |

**关联文件：** `state/scan_folders.py`、`scan_folders.json`、`scan_folders.example.json`、`main.py`、`classify/others_theme.py`、`tools/others_theme_classify_move.py`

**兼容：** 仍可用 `.env` 的单个 `SCAN_ROOT_TOKEN` 单次运行

---

## `feature/doc-metadata-inline-table`

**基于：** `feature/scan-folders-batch`

**方案：** 1A（随 `main.py`）+ 2B（产品线=分类 tag1）；与 `feature/doc-metadata-bitable`（独立多维表格工具）互为替代实现。

**主要变化：**

| 能力 | 说明 |
|------|------|
| 复制后写元数据表 | 复制成功后在**目标文档**开头插入「文档元数据」二级标题 + 两列表格 |
| 字段 | 产品线(tag1)、模块型号、文档类型、作者、分类路径、源路径 |
| 开关 | `ENABLE_METADATA_TABLE`（默认 true）；`METADATA_TABLE_FETCH_AUTHOR` 控制作者解析 |

**关联文件：** `classify/doc_metadata.py`、`feishu/metadata_table.py`、`feishu/wiki_meta.py`、`main.py`

---

## `feature/console-ui`（可视化控制台）

**基于：** `feature/doc-metadata-inline-table`（并合入多维表格导出工具）

**主要变化：**

| 能力 | 说明 |
|------|------|
| 本地 Web 控制台 | `http://127.0.0.1:8787`：配置 `.env`、编辑清单分工、一键跑任务看日志 |
| 分类任务 | `main.py --all-assigned` / `--folder` / `--list-folders` 等 |
| 元数据任务 | 多维表格导出（per-token / both / aggregated）+ main 复制后贴表（配置开关） |
| 启动 | 双击 `启动控制台.bat` 或 `python run_console.py` |

**使用说明：** [docs/CONSOLE.md](CONSOLE.md)

**关联文件：** `console/`、`run_console.py`、`启动控制台.bat`

---

## 分支关系

```
master
  └── feature/multi-worker-parallel
        └── feature/scan-snapshot-plan-b
              └── feature/attachment-extract
                    └── feature/classify-quality-restructure
                          └── feature/scan-folders-batch
                                ├── feature/doc-metadata-bitable
                                └── feature/doc-metadata-inline-table
                                      └── feature/console-ui  ← 本地 Web 控制台
```

## 选用建议

| 场景 | 推荐分支 |
|------|----------|
| 单人、小目录、快速试用 | `feature/multi-worker-parallel` |
| 大目录增量跑、排除周报日报 | `feature/scan-snapshot-plan-b` |
| 仅需附件提取 + 跨进程限速 | `feature/attachment-extract` |
| 分类质量 + 分卷 + 包结构 | `feature/classify-quality-restructure` |
| 生产落地（清单批量增量） | `feature/scan-folders-batch` |
| 元数据写入多维表格（独立工具） | `feature/doc-metadata-bitable` |
| 元数据贴到目标文档开头（随 main） | `feature/doc-metadata-inline-table` |
| **图形化配置 + 跑分类/元数据** | **`feature/console-ui`** |

## 切换与更新

```powershell
git fetch origin
git checkout feature/console-ui
git pull origin feature/console-ui
copy .env.example .env
pip install -r requirements.txt
# 双击 启动控制台.bat  或:
python run_console.py
```