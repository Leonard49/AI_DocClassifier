# 分支变更记录

> 记录各功能分支相对 `master` 的重要变化，便于选型与合并。  
> **当前推荐落地分支：`feature/arch-data-dir-cleanup`**（持续迭代中 · 见下方优化日志）  
> **架构边界（Core vs Tools）**：[ARCHITECTURE.md](ARCHITECTURE.md) · **控制台**：[CONSOLE.md](CONSOLE.md)

### 如何维护本文件（必读）

代码体量变大后，**每次有意义的代码/产品优化都要在本文件「当前推荐分支」的「迭代优化日志」里追加一行**（日期 + 一句话 + 关键提交/文件）。不要只改功能代码却不记账。

| 要记 | 可省略 |
|------|--------|
| 新工具 / 新控制台能力 / 行为语义变更 / 重要 bugfix | 纯 typo、仅格式化、临时调试 |
| 配置项增删、账本 op 增删 | 与功能无关的文档微调（可并入同一次日志） |

追加位置：下文 **`feature/arch-data-dir-cleanup` → 迭代优化日志**（**新记录写在表格最上方**）。

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
| 字段 | 产品线(tag1)、模块型号、文档类型、作者、**分类路径**、**源路径** |
| 路径语义 | 源路径=SCAN；分类路径=分类结果 / TARGET 目录（回填） |
| 开关 | `ENABLE_METADATA_TABLE`（默认 true）；`METADATA_TABLE_FETCH_AUTHOR` 控制作者解析 |

**关联文件：** `classify/doc_metadata.py`、`feishu/metadata_table.py`、`feishu/wiki_meta.py`、`main.py`

---

## `feature/doc-metadata-bitable`

**基于：** `feature/scan-folders-batch`

**方案：** 独立侧工具把文档元数据写入飞书多维表格（与 inline-table 互为替代/可并存）。后续已合入 `feature/console-ui` 任务列表。

**主要变化：**

| 能力 | 说明 |
|------|------|
| 多维表格导出 | `tools/export_doc_metadata_bitable.py`：汇总表 / 按 token 分表 / both |
| 三人并行 | 常用 per-token 分表，避免同时写同一汇总表 |
| 跳过已写 | ledger / 索引记录 `record_id`（后续收敛进 `tool_ops.db`） |

**关联文件：** `tools/export_doc_metadata_bitable.py`、`state/metadata_bitable.py`、`feishu/bitable.py`

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

> 后续控制台增强（任务分组、增量/全量、清单可视化加 token 等）记在 **`arch-data-dir-cleanup` 迭代日志**，不再开新分支名。

---

## `feature/doc-enrichment`（文档增强管道）

**基于：** `feature/console-ui`

**主要变化：**

| 能力 | 说明 |
|------|------|
| enrichment 插件 | `enrichment/`：复制后 / 回填可插拔步骤 |
| 默认步骤 | 贴元数据表、附件分隔符（均幂等） |
| 旧副本回填 | `tools/enrich_copied_docs.py`（默认 TARGET） |
| 字段语义（后续纠偏） | 作者/源路径←SCAN；分类路径←tag 或 TARGET 面包屑；见 arch 迭代日志 |
| 开关 | `ENABLE_METADATA_TABLE` / `ENABLE_ATTACHMENT_SEPARATOR` |

**关联文件：** `enrichment/`、`tools/enrich_copied_docs.py`、`main.py`（`enrich_after_copy`）

---

## `feature/tool-ops-target-scope`（工具只处理 TARGET + 统一操作账本）

**基于：** `feature/doc-enrichment`

**主要变化：**

| 能力 | 说明 |
|------|------|
| 工具文档宇宙 | 默认只扫 `TARGET_PARENT_TOKEN`；未分类复制的源文档不进工具 |
| 统一账本 | `tool_ops.db`（`OperationLedger`）：按 `(文档, op)` 独立记录 |
| 操作互不影响 | 各 Tools op 独立 skip（完整列表见 arch 迭代日志） |
| 主流程不变 | `shared_copy_state` / `scan_snapshot` 仍只服务分类复制 |
| 兼容 | `--scope scan` 可恢复扫源清单 |

**关联文件：** `state/operation_ledger.py`、`state/target_docs.py`、`tools/_tool_scope.py`、各 `tools/export_*` / `enrich_copied_docs`

---

## `feature/arch-data-dir-cleanup`（当前推荐 · 持续迭代）

**基于：** `feature/tool-ops-target-scope`

本分支是**生产落地点**：在 TARGET 工具 + `tool_ops` 之上，收敛 `data/` 布局，并持续叠加控制台、贴表语义、展示标题、源刷新等优化。  
**不要只看「主要能力」摘要——以「迭代优化日志」为准。**

### 主要能力（基线，`d19d7c1` 起）

| 能力 | 说明 |
|------|------|
| `DATA_DIR` | 默认 `data/`；Core → `data/core/`，Tools → `data/tools/tool_ops.db` |
| 旧库迁移 | 根目录 `*.db` 可自动迁入 `data/`（`AUTO_MIGRATE_DATA_DIR`） |
| 账本唯一 | bitable `record_id` 写入 `operations.result_ref`；废弃独立 `*_index.db` |
| ToolJob | `tools/runner.py` 统一 scope / skip / 报告 |
| 文档边界 | Core vs Tools；根 shim / `attachment_extractors/` 标明遗留 |

### 迭代优化日志（新 → 旧）

> 约定：日期为大致落地日；SHA 为该能力对应的主要提交（可 `git show <sha>`）。

| 日期 | 优化内容 | 提交 / 关键 |
|------|----------|-------------|
| 2026-08-19 | **附件提取图片可显示**：上传补 `extra.drive_route_token`，PDF/Word 非 JPEG/PNG 先转码；复制后重绑 TARGET 图块。存量用 `python -m tools.repair_extracted_images`（空图块加 `--reextract`） | `5c35684` · `attachment/images.py` · `attachment/extractors/base.py` · `tools/repair_extracted_images.py` |
| 2026-08-13 | **展示标题/贴表共用 LLM 归纳主题+主型号**：正则 PN 优先，否则 LLM 给模组或产品名，再否则 TARGET 一级\|二级；元数据表补 **文章主题**，作者与标题同一套中英文人名 | 待提交 · `classify/display_llm.py` · `classify/display_title.py` · `classify/doc_metadata.py` |
| 2026-08-13 | **展示标题作者保留中英文名**；无模组 PN 时中间段用 TARGET 一级\|二级目录，不再写「未知型号」 | 待提交 · `classify/display_title.py` |
| 2026-08-13 | **展示标题改为「主题-模组型号-作者」**：主题按正文归纳禁止日期开头；通讯录 41050 时用 SCAN 源路径人名文件夹回退作者 | 待提交 · `classify/display_title.py` · `feishu/wiki_meta.py` · `tools/rename_target_display_titles.py` |
| 2026-08-13 | **元数据表补齐源数据**：贴表/多维表含 **原文档名称、源文档路径、作者、产品线、源文档创建时间**（取 SCAN 源节点，不随 TARGET 改名）；旧贴表需 `--force-metadata` | 待提交 · `classify/doc_metadata.py` · `tools/enrich_copied_docs.py` · `tools/export_doc_metadata_bitable.py` |
| 2026-08-13 | **展示标题主题不再用日期开头**：去掉原标题流水号/日期前缀；LLM 按正文归纳主题；日期开头的 TARGET 标题即使 ledger 已写也会重命名 | 待提交 · `classify/display_title.py` · `tools/rename_target_display_titles.py` |
| 2026-08-12 | **归纳新标题日志卡在「读取正文」**：并行读/生成阶段补进度行（`util/progress.py`，`flush=True`，间隔 `PROGRESS_INTERVAL`）；同样修元数据 bitable 工具 | 待提交 · `tools/export_display_title_bitable.py` · `tools/rename_target_display_titles.py` · `tools/export_doc_metadata_bitable.py` |
| 2026-08-12 | **贴表列宽加宽**：docx 元数据表 `column_width` 默认 `160,560` px（可配 `METADATA_TABLE_COLUMN_WIDTHS`），减轻值列挤换行；旧表需 `--force-metadata` 重贴 | `e888213` · `feishu/metadata_table.py` · `config.py` |
| 2026-08-12 | **控制台清单可视化添加 SCAN token**：粘贴 wiki token（或 URL）→ 可选飞书解析 name/id →「添加并保存」写入 `scan_folders.json`；行可移除后再保存。不再必须手改 JSON。API：`POST /api/folders/preview`、`POST /api/folders/add`。同步建立 BRANCHES「迭代优化日志」记账约定 | `a56bb5c` · `console/app.py` · `console/static/*` · `state/scan_folders.py` · [CONSOLE.md](CONSOLE.md) · [BRANCHES.md](BRANCHES.md) |
| 2026-08-12 | **文档同步**：贴表双路径、展示标题、源刷新、作者排障等写回 README / QUICK_START / CONSOLE / 分类准则 / 说明文档 / 增量方案对比 | `844ee66` |
| 2026-08-12 | **贴表「分类路径」回填**：enrichment 无 `tag` 时用 TARGET 面包屑 `target_path`；产品线可回退路径第一段；`--force-metadata` 重贴 | `1f94b61` · `enrichment/*` · `classify/doc_metadata.py` · `tools/enrich_copied_docs.py` |
| 2026-08-12 | **归纳新标题格式**改为 **主题-产品线-作者**；新增 `rename_target_display_titles`（只改 TARGET）；**源→TARGET 单向内容刷新** `refresh_target_from_source`（保留整理标题，旧副本进 `_已废弃_源刷新`）；ops：`display_title_rename` / `target_content_refresh` | `d8c03cd` · `classify/display_title.py` · `tools/rename_*` · `tools/refresh_*` · `feishu/wiki_meta.py` |
| 2026-08-12 | **控制台任务分组对齐**流程：主流程 / 副本增强 / 文档元数据表 / 归纳新标题 / 运维纠偏；文档与文案统一 | `39c9d55` |
| 2026-08-12 | **BRANCHES 谱系补全**：列出全部 feature 分支与选用建议 | `5de0146` |
| 2026-08-11 | **贴表作者/源路径纠偏**：经 `SHARED_STATE_DB` 还原 SCAN 源；作者取源 `creator`（需通讯录只读）；禁止把 TARGET 枢纽路径当源路径；`--force-metadata` | `38f1040` · `tools/enrich_copied_docs.py` · `feishu/wiki_meta.py` |
| 2026-08-11 | **工具运行日志 + 控制台日志不断流**：`maybe_setup_run_log`；ring buffer 用绝对 `log_seq`，避免 UI「卡住」 | `c5d0831` · `tools/runner.py` · `console/jobs.py` |
| 2026-08-11 | **主流程任务标注【增量更新】/【全量重扫】**；全量经 `FORCE_RESCAN` env override | `de02426` · `console/jobs.py` |
| 2026-08-11 | **控制台按 Core/Tools 工作流重排任务**；配置保存反馈修复 | `d10ec8e` |
| 2026-08-07 | **流程图与说明文档**端到端同步 Core/Tools 协作 | `8c832a2` |
| 2026-08-07 | **架构文档**：Core vs Tools；控制台「归纳新标题」任务说明 | `1a3c77a` · [ARCHITECTURE.md](ARCHITECTURE.md) |
| 2026-08-07 | **基线落地**：`DATA_DIR` + `tool_ops` 收敛 + ToolJob | `d19d7c1` · `util/paths.py` · `config.py` · `tools/runner.py` |

### 当前 Tools 账本 op（互不影响）

| op | 工具 / 场景 |
|----|-------------|
| `metadata_table` | enrichment 贴「文档元数据」表 |
| `attachment_separator` | enrichment 附件分隔符 |
| `metadata_bitable` | `export_doc_metadata_bitable` |
| `display_title_bitable` | `export_display_title_bitable`（写表，不改 wiki） |
| `display_title_rename` | `rename_target_display_titles`（改 TARGET 标题） |
| `target_content_refresh` | `refresh_target_from_source`（源→TARGET 重拷） |

### 贴表字段语义（现行）

| 字段 | 来源 |
|------|------|
| 作者 | SCAN 源 `creator` → 通讯录；失败则源路径人名文件夹 |
| 原文档名称 | SCAN 源标题（共享库 / 源节点；非 TARGET 展示标题） |
| 源路径 / 源文档路径 | SCAN 目录 breadcrumb（`SHARED_STATE_DB`） |
| 源文档创建时间 | SCAN 源 `obj_create_time` |
| 分类路径 | 复制时用分类 `tag`；回填用 TARGET `target_path` |

### 关联文件（本分支累计）

`util/paths.py`、`config.py`、`tools/runner.py`、`console/`、`enrichment/`、`classify/display_title.py`、`classify/doc_metadata.py`、`tools/enrich_copied_docs.py`、`tools/export_display_title_bitable.py`、`tools/rename_target_display_titles.py`、`tools/refresh_target_from_source.py`、`state/scan_folders.py`、`state/operation_ledger.py`、`docs/*`

---

## 分支关系

```
master
  └── feature/multi-worker-parallel
        └── feature/scan-snapshot-plan-b
              └── feature/attachment-extract
                    └── feature/classify-quality-restructure
                          └── feature/scan-folders-batch
                                ├── feature/doc-metadata-bitable          （独立多维表格工具，与贴表方案并行）
                                └── feature/doc-metadata-inline-table     （复制后贴「文档元数据」表）
                                      └── feature/console-ui              （可视化控制台；并合入 bitable 导出）
                                            └── feature/doc-enrichment    （enrichment 插件 + 旧副本回填）
                                                  └── feature/tool-ops-target-scope   （工具默认 TARGET + tool_ops 账本）
                                                        └── feature/arch-data-dir-cleanup  ← 当前推荐（持续迭代）
                                                              · data/ + tool_ops 收敛
                                                              · 控制台分组 / 增量·全量 / 清单加 token
                                                              · 贴表作者·双路径纠偏
                                                              · 展示标题重命名 + 源→TARGET 刷新
```

## 选用建议

| 场景 | 推荐分支 |
|------|----------|
| **生产推荐（持续更新看本文件迭代日志）** | **`feature/arch-data-dir-cleanup`** |
| 上一版（TARGET 工具，根目录 .db） | `feature/tool-ops-target-scope` |
| 图形化配置 + enrichment（较旧） | `feature/doc-enrichment` |

## 切换与更新

```powershell
git fetch origin
git checkout feature/arch-data-dir-cleanup
git pull origin feature/arch-data-dir-cleanup
```

拉完后建议打开本文件「迭代优化日志」顶部几行，确认本地已知最新能力。
