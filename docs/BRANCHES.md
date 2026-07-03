# 分支变更记录

> 记录各功能分支相对 `master` 的重要变化，便于选型与合并。

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
| 通用 LLM 分类器 | `llm_tree_classifier.py`，`LLM_MODEL` / `LLM_BASE_URL` 可配置 |
| 飞书/LLM 限流 | `READ_WORKERS=2` 建议值，LLM 全局并发≤2 |
| 同名标题处理 | 目标子目录自动重命名为 `标题 (2)` 等 |

**关键文件：** `shared_state.py`、`config.py` 并行配置

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

**关键文件：** `scan_snapshot.py`、`llm_tree_classifier.py`（排除规则）

---

## `feature/attachment-extract`（当前推荐）

**基于：** `feature/scan-snapshot-plan-b`

**主要变化：**

| 能力 | 说明 |
|------|------|
| 附件提取合入 | PDF / Word / PPT 附件下载并转文本写回源 docx |
| 功能开关 | `ENABLE_ATTACHMENT_EXTRACT=true/false` |
| 防重复 | 已有 `附件：{文件名}` 标题则跳过 |
| 可视化统计 | 进度条、阶段汇总、终局统计、失败列表 |
| 运行清单 | `logs/attachment_extract.json` |
| 依赖 | `PyMuPDF`、`python-docx`、`lxml`、`python-pptx` |

**关键文件：** `attachment_extractor.py`、`attachment_extractors/`

**移除：** 独立子项目 `PDF2Feishu/`（逻辑已迁入主仓库）

---

## 分支关系

```
master
  └── feature/multi-worker-parallel
        └── feature/scan-snapshot-plan-b
              └── feature/attachment-extract  ← 当前推荐
```

## 选用建议

| 场景 | 推荐分支 |
|------|----------|
| 单人、小目录、快速试用 | `feature/multi-worker-parallel` |
| 大目录增量跑、排除周报日报 | `feature/scan-snapshot-plan-b` |
| 分享以附件为主、需提取正文再分类 | **`feature/attachment-extract`** |

## 切换与更新

```powershell
git fetch origin
git checkout feature/attachment-extract
git pull origin feature/attachment-extract
copy .env.example .env
# 编辑 .env 后
pip install -r requirements.txt
python main.py
```
