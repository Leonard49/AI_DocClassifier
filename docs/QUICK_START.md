# AI DocClassifier — 快速上手指南

> 面向周五批量落地 · 多人并行操作手册  
> 当前推荐分支：`feature/classify-quality-restructure`

---

## 一、你需要准备什么

| 项目 | 说明 |
|------|------|
| Python 3.10+ | 建议 3.11 |
| Git | 拉取代码 |
| 飞书应用 | **每人独立 App**（`FEISHU_APP_ID` / `FEISHU_APP_SECRET`） |
| LLM Key | 每人独立或团队分配 |
| 共享网络盘 | `\\HF-D-006494B\shared_db\` 需有**读写**权限 |
| 分工 | 每人负责不同的 `SCAN_ROOT_TOKEN`，共用同一 `TARGET_PARENT_TOKEN` |

---

## 二、首次安装（每人执行一次）

```powershell
# 1. 克隆 / 更新代码
git clone https://github.com/Leonard49/AI_DocClassifier.git
cd AI_DocClassifier
git checkout feature/classify-quality-restructure
git pull origin feature/classify-quality-restructure

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
WORKER_ID=你的名字          # 如 Hydrew、Hayes、Jamie，必须唯一
FEISHU_APP_ID=cli_xxx       # 你的飞书 App
FEISHU_APP_SECRET=xxx
SCAN_ROOT_TOKEN=xxx         # 你负责的源目录 token
TARGET_PARENT_TOKEN=xxx     # 团队统一的目标目录 token
LLM_API_KEY=sk-xxx
```

其余项已在 `.env.example` 中按 **3～5 人并行** 预设好，一般无需修改。

### 校验配置

```powershell
.venv\Scripts\python.exe -c "import config; config.validate(); print('配置 OK')"
```

---

## 三、正式批量跑

```powershell
cd AI_DocClassifier
.venv\Scripts\activate
python main.py
```

程序会自动：

1. 扫描你负责的源目录（仅叶子 `docx`）
2. 提取 PDF/Word/PPT 附件正文写回源文档（已开启）
3. 并行读取 + AI 分类
4. 串行复制到目标目录（共享去重，不会重复复制）
5. 结束时扫描目标目录，输出统计

### 运行时长参考（单 worker，约 1400 篇）

| 阶段 | 耗时 |
|------|------|
| 扫描 | 4～6 分钟 |
| 附件提取 | 视附件数量，可能数小时 |
| 读取 + 分类 | 数小时 |
| 复制 | 数小时（串行） |

**建议：** 周五开始前先用 `MAX_DOCUMENTS=10` 试跑，确认配置无误后再全量。

```env
MAX_DOCUMENTS=10
```

---

## 四、多人并行规则

```
同事 A ── SCAN_ROOT_A ──┐
同事 B ── SCAN_ROOT_B ──┼──► 同一 TARGET_PARENT_TOKEN
同事 C ── SCAN_ROOT_C ──┘
              │
    \\HF-D-006494B\shared_db\
      ├── shared_copy_state.db   ← 去重（必须共用）
      └── feishu_rate_limit.db   ← 飞书限速（必须共用）
```

| 必须一致 | 每人不同 |
|----------|----------|
| `SPACE_ID` | `WORKER_ID` |
| `TARGET_PARENT_TOKEN` | `FEISHU_APP_ID` / `SECRET` |
| `SHARED_STATE_DB` 路径 | `SCAN_ROOT_TOKEN` |
| `FEISHU_RATE_LIMIT_DB` 路径 | `LLM_API_KEY` |

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
git checkout feature/classify-quality-restructure
git pull origin feature/classify-quality-restructure
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

### 存量 Others 纠偏（移动到正确分类）

```powershell
python -m tools.reclassify_others_move --dry-run --max-documents 20
python -m tools.reclassify_others_move --skip-others-ratio-check
```

详见 [分类准则说明.md](分类准则说明.md)。项目包结构见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。

---

## 六、中断与续跑

| 操作 | 方法 |
|------|------|
| 正常中断 | 终端 `Ctrl+C` |
| 续跑 | 直接再次 `python main.py`（自动跳过已复制文档） |
| 强制全量重跑 | `.env` 设 `FORCE_RESCAN=true` 或删除 `processing_progress.json` |
| 只测少量 | `MAX_DOCUMENTS=10` |

> 复制阶段每 5 篇保存进度；读取/分类阶段中断后下次会重新读取（不会重复复制已完成的）。

---

## 七、落地前检查清单

**环境**

- [ ] Python 虚拟环境已创建，`pip install -r requirements.txt` 成功
- [ ] `config.validate()` 通过
- [ ] 共享盘 `\\HF-D-006494B\shared_db\` 可读写

**配置**

- [ ] `WORKER_ID` 唯一，不与同事重复
- [ ] 每人使用**不同**飞书 App
- [ ] `SCAN_ROOT_TOKEN` 已分配，无重叠
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
| 飞书 `99991400` / ReadTimeout | 正常现象，程序会自动重试；若频繁出现，确认不同 App + 共享限速库可用 |
| `database disk image is malformed` | 删共享库 `.db` 及 `-wal`/`-shm`，重跑；保留本地 `processing_progress.json` |
| 附件 `.doc` 失败 | 需本机安装 LibreOffice 或 Word（自动转换） |
| 附件提取失败 | `python -m tools.retry_attachment_extract` |
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
| `processing_progress.json` | 本机断点续跑（勿手动改） |
| `scan_snapshot.db` | 本机扫描快照（增量用） |
