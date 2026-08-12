# AI DocClassifier — 快速上手指南

> 面向批量落地 · 多人并行 / 一人清单增量操作手册  
> **当前推荐分支：`feature/arch-data-dir-cleanup`**（控制台 + TARGET 侧工具 + 展示标题/源刷新/贴表纠偏）  
> 控制台：[CONSOLE.md](CONSOLE.md) · 架构：[ARCHITECTURE.md](ARCHITECTURE.md) · **优化日志**：[BRANCHES.md](BRANCHES.md)

---

## 零、本地 Web 控制台（推荐）

```powershell
git checkout feature/arch-data-dir-cleanup
git pull origin feature/arch-data-dir-cleanup
pip install -r requirements.txt
# 双击 启动控制台.bat
# 或: python run_console.py
```

浏览器打开 http://127.0.0.1:8787 ：

- **配置**：编辑 `.env`（飞书 / LLM / 并行 / 元数据开关）
- **清单分工**：改 assignee / enabled；**可直接粘贴 scan token 添加新目录**（不必手改 JSON）
- **运行**：分组卡片（主流程 / 副本增强 / 文档元数据表 / 归纳新标题 / 运维纠偏），右侧看实时日志

完整说明见 **[控制台使用说明](CONSOLE.md)**。主程序与侧工具边界见 **[ARCHITECTURE.md](ARCHITECTURE.md)**。

---

## 一、你需要准备什么

| 项目 | 说明 |
|------|------|
| Python 3.10+ | 建议 3.11 |
| Git | 拉取代码 |
| 飞书应用 | **每人独立 App**（`FEISHU_APP_ID` / `FEISHU_APP_SECRET`） |
| LLM Key | 每人独立或团队分配 |
| 共享网络盘 | `\\HF-D-006494B\shared_db\` 需有**读写**权限 |
| 分工 | 推荐用 `scan_folders.json` 的 `assignee`；共用同一 `TARGET_PARENT_TOKEN` |

---

## 二、首次安装（每人执行一次）

```powershell
# 1. 克隆 / 更新代码
git clone https://github.com/Leonard49/AI_DocClassifier.git
cd AI_DocClassifier
git checkout feature/arch-data-dir-cleanup
git pull origin feature/arch-data-dir-cleanup

# 2. Python 环境
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置文件
copy .env.example .env
notepad .env
```

### 必填项（每人不同）

编辑 `.env`，填写以下字段：

```env
WORKER_ID=你的名字          # 如 Hydrew，须与 scan_folders.json 的 assignee 一致
FEISHU_APP_ID=cli_xxx       # 你的飞书 App
FEISHU_APP_SECRET=xxx
# SCAN_ROOT_TOKEN=          # 清单模式下可留空
SCAN_FOLDERS_FILE=scan_folders.json
TARGET_PARENT_TOKEN=xxx     # 团队统一的目标目录 token
LLM_API_KEY=sk-xxx
```

仓库已带 `scan_folders.json`（源目录 token + 三人分工示例：Hydrew / Jamie / Hayes）。将 `WORKER_ID` 设为自己的名字即可只跑自己的文件夹。新增源目录：控制台「清单分工」→ 粘贴 wiki token →「添加并保存」。

其余项已在 `.env.example` 中按 **3～5 人并行** 预设好，一般无需修改。配置也可用控制台「配置」页编辑并保存。

### 校验配置

```powershell
.venv\Scripts\python.exe -c "import config; config.validate(require_scan_source=False); print('配置 OK')"
python main.py --list-folders
```

---

## 三、正式批量跑

```powershell
cd AI_DocClassifier
.venv\Scripts\activate
python main.py --all-assigned
# 未设 SCAN_ROOT_TOKEN 时，直接 python main.py 等同 --all-assigned
```

程序会按清单顺序：

1. 扫描你负责的每个源目录（仅叶子 `docx`）
2. 提取 PDF/Word/PPT 附件正文写回源文档（已开启）
3. 并行读取 + AI 分类
4. 串行复制到目标目录（共享去重，不会重复复制）
5. 复制成功后跑文档增强管道（`ENABLE_METADATA_TABLE` 贴表；`ENABLE_ATTACHMENT_SEPARATOR` 附件分隔）。旧副本用 `python -m tools.enrich_copied_docs` 回填；路径/作者错误时加 `--force-metadata`
6. 结束时扫描目标目录，输出统计

### 常用清单命令

```powershell
python main.py --list-folders
python main.py --folder 25.Smart-FAE
python main.py --all-enabled          # 清单内全部（负责人）
```

### 侧工具速查（默认 TARGET）

```powershell
# 副本增强回填 / 强制重贴元数据表
python -m tools.enrich_copied_docs --dry-run --limit 20
python -m tools.enrich_copied_docs --force-metadata --steps metadata_table

# 文档元数据 → 多维表格
python -m tools.export_doc_metadata_bitable --scope target --mode aggregated --dry-run --max-documents 20

# 归纳新标题：写表 或 重命名 TARGET（主题-产品线-作者）
python -m tools.export_display_title_bitable --dry-run --max-documents 20
python -m tools.rename_target_display_titles --dry-run --max-documents 20

# 源有更新 → 单向刷新 TARGET（保留整理标题）
python -m tools.refresh_target_from_source --dry-run --limit 20
```

也可在控制台「运行」页按分组点击对应任务。

### 元数据多维表格（全量归纳）

```powershell
# 并行推荐：每人只写自己的分表
python -m tools.export_doc_metadata_bitable --all-assigned --mode per-token
# 全部完成后，任一人写汇总表
python -m tools.export_doc_metadata_bitable --all-enabled --mode aggregated
```

也可在控制台「运行」页点击对应任务。

### 运行时长参考（单 worker，约 1400 篇）

| 阶段 | 耗时 |
|------|------|
| 扫描 | 4～6 分钟 |
| 附件提取 | 视附件数量，可能数小时 |
| 读取 + 分类 | 数小时 |
| 复制 | 数小时（串行） |

**建议：** 开始前先用 `MAX_DOCUMENTS=10` 试跑，确认配置无误后再全量。

```env
MAX_DOCUMENTS=10
```

---

## 四、多人并行规则

```
scan_folders.json (assignee=各人 WORKER_ID)
        │
        ▼
同一 TARGET_PARENT_TOKEN
        │
\\HF-D-006494B\shared_db\
  ├── shared_copy_state.db   ← 去重（必须共用）
  └── feishu_rate_limit.db   ← 飞书限速（必须共用）
```

| 必须一致 | 每人不同 |
|----------|----------|
| `SPACE_ID` | `WORKER_ID` |
| `TARGET_PARENT_TOKEN` | `FEISHU_APP_ID` / `SECRET` |
| `SHARED_STATE_DB` 路径 | 清单中的负责文件夹 |
| `FEISHU_RATE_LIMIT_DB` 路径 | `LLM_API_KEY` |
| `scan_folders.json`（或共享盘同一份） | |

### 并行人数与限速

| 并行人数 | 建议 `FEISHU_GLOBAL_MAX_PER_SECOND` |
|----------|-------------------------------------|
| 3 人 | 6 |
| 4 人 | 8 |
| 5 人 | 10（模板默认值） |

人数少于 5 时可直接用模板默认值，更保守、更稳。

---

## 五、日常协作命令

### 拉取最新代码

```powershell
git fetch origin
git checkout feature/arch-data-dir-cleanup
git pull origin feature/arch-data-dir-cleanup
pip install -r requirements.txt   # 依赖有变时执行
```

### 查看日志

```powershell
# 最新一次运行
type logs\latest.log

# 带 worker 标识的日志（若配置了 SAVE_RUN_LOG）
type logs\latest_Hydrew.log
```

### 重试失败的附件提取

```powershell
python -m tools.retry_attachment_extract
python -m tools.retry_attachment_extract --dry-run
```

### 存量 Others 纠偏 / 主题归档

```powershell
python -m tools.reclassify_others_move --dry-run --max-documents 20
python -m tools.reclassify_others_move --skip-others-ratio-check

python -m tools.others_theme_classify_move --dry-run
python -m tools.others_theme_classify_move
```

详见 [分类准则说明.md](分类准则说明.md)。项目包结构见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。

---

## 六、中断与续跑

| 操作 | 方法 |
|------|------|
| 正常中断 | 终端 `Ctrl+C` |
| 续跑 | 直接再次 `python main.py --all-assigned`（自动跳过已复制文档） |
| 强制全量重跑 | `.env` 设 `FORCE_RESCAN=true` 或删除 `processing_progress.json` |
| 只测少量 | `MAX_DOCUMENTS=10` |

> 复制阶段每 5 篇保存进度；读取/分类阶段中断后下次会重新读取（不会重复复制已完成的）。

---

## 七、落地前检查清单

**环境**

- [ ] Python 虚拟环境已创建，`pip install -r requirements.txt` 成功
- [ ] `python main.py --list-folders` 能列出你的文件夹
- [ ] 共享盘 `\\HF-D-006494B\shared_db\` 可读写

**配置**

- [ ] `WORKER_ID` 唯一，并与清单 `assignee` 一致
- [ ] 每人使用**不同**飞书 App
- [ ] `scan_folders.json` 已就绪（或 `SCAN_FOLDERS_FILE` 指向共享盘）
- [ ] `TARGET_PARENT_TOKEN` 全组一致
- [ ] `SHARED_STATE_DB` 和 `FEISHU_RATE_LIMIT_DB` 指向共享盘

**试跑**

- [ ] `MAX_DOCUMENTS=10` 试跑成功
- [ ] 目标目录出现分类副本
- [ ] `logs/` 无大量连续报错

**正式跑**

- [ ] 去掉 `MAX_DOCUMENTS` 限制（或设为 `0`）
- [ ] 确认同事启动时间错开 5～10 分钟（降低同时扫描峰值）
- [ ] 约定跑完后在群里报 `WORKER_ID` + 终局统计

---

## 八、常见问题速查

| 现象 | 处理 |
|------|------|
| 很快结束但目标目录为空 | 查 `processing_progress.json` 是否已有记录；设 `FORCE_RESCAN=true` |
| 提示没有分配给 WORKER_ID 的文件夹 | 检查清单 `assignee` 是否与 `WORKER_ID` 一致、`enabled=true` |
| 飞书 `99991400` / ReadTimeout | 正常现象，程序会自动重试；若频繁出现，确认不同 App + 共享限速库可用 |
| `database disk image is malformed` | 删共享库 `.db` 及 `-wal`/`-shm`，重跑；保留本地 `processing_progress.json` |
| 附件 `.doc` 失败 | 需本机安装 LibreOffice 或 Word（自动转换） |
| 附件提取失败 | `python -m tools.retry_attachment_extract` |
| 旧副本缺元数据表/附件分隔 | `python -m tools.enrich_copied_docs`（先 `--dry-run`） |
| 贴表作者为空 / 分类路径为 `-` | 开联系人只读；确认 `SHARED_STATE_DB`；`--force-metadata` 重贴（分类路径取 TARGET 面包屑） |
| 源改正文后 TARGET 未更新 | 正常（不同步）；跑 `refresh_target_from_source` 或控制台「源→TARGET 内容刷新」 |
| 各 worker 成功数之和不等于目标总数 | 正常；以**全部跑完后**目标目录实际扫描数为准 |

更多细节见 [AI_DocClassifier说明文档.md](AI_DocClassifier说明文档.md)。

---

## 九、产出文件说明

| 文件 | 用途 |
|------|------|
| `logs/latest.log` | 本次运行完整日志 |
| `logs/attachment_extract.json` | 附件提取结果与失败清单 |
| `logs/classification_failures.json` | 分类失败清单 |
| `logs/excluded_reports.json` | 被排除的周报/日报等 |
| `logs/others_reclassify_move.json` | Others 产品线纠偏报告 |
| `logs/others_theme_classify_move.json` | Others 主题归档报告 |
| `logs/doc_metadata_bitable.json` | 元数据写入多维表格报告 |
| `logs/display_title_bitable.json` | 归纳新标题→多维表报告 |
| `logs/display_title_rename.json` | TARGET 标题重命名报告 |
| `logs/refresh_target_from_source.json` | 源→TARGET 内容刷新报告 |
| `data/core/processing_progress.json` | 本机断点续跑（勿手动改） |
| `data/core/scan_snapshot.db` | 本机扫描快照（增量用） |
| `data/tools/tool_ops.db` | 侧工具操作账本（含 bitable record_id） |
| `scan_folders.json` | 源文件夹 token 清单 |
