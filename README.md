# AI DocClassifier

飞书知识库文档自动分类工具：扫描指定目录下的叶子文档，用 LLM 按标签树分类，并复制到目标目录的分类文件夹中。

支持**多人并行**、**扫描快照增量**、**附件提取转文本**，通过共享去重库避免重复复制，结束时以目标目录实际扫描结果作为统计口径。

## 文档

| 文档 | 内容 |
|------|------|
| **[快速上手指南](docs/QUICK_START.md)** | **周五落地操作步骤、检查清单、排障速查** |
| [项目结构](docs/PROJECT_STRUCTURE.md) | 包划分与入口命令 |
| [分类准则说明](docs/分类准则说明.md) | 产品线判定、Others 门禁、超限分卷 |
| [系统说明文档](docs/AI_DocClassifier说明文档.md) | 架构、配置、流程、多人协作、详细排障 |
| [分支记录](docs/BRANCHES.md) | 各分支变化与选用建议 |
| [增量方案对比](docs/增量更新方案对比.md) | Plan B 扫描快照方案讨论稿 |

## 快速开始

```powershell
git checkout feature/classify-quality-restructure
git pull origin feature/classify-quality-restructure

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# 编辑 .env：WORKER_ID、飞书 App、SCAN/TARGET token、LLM_API_KEY
python main.py
```

多人并行请直接跟随 **[docs/QUICK_START.md](docs/QUICK_START.md)**。

## 主要能力

- 仅处理叶子 `docx`（跳过目录/索引页）
- **附件提取**：PDF / Word / PPT → 文本写回源文档（`ENABLE_ATTACHMENT_EXTRACT`）
- 并行读取与 AI 分类，串行复制到飞书
- 本机断点续跑 + 扫描快照增量 + 全局 `obj_token` 去重（多人并行）
- 跨进程飞书 API 限速与自动重试（`feishu/http.py`）
- 基于 QT-SOP-PM-048E 的模组→产品线判定，降低 Others
- Others 占比超阈值（默认 15%）则整批分类失败并中止复制
- 目标文件夹单层节点超限（131003）时自动创建 `名称 (2)` 分卷（共享库同步）
- 存量 `Others` 纠偏：`python -m tools.reclassify_others_move`（重分类后 **move**）
- 排除周报/日报/会议纪要/重点客户跟踪等非技术文档
- 结束时扫描目标目录，统计实际文档数
- 附件失败重试：`python -m tools.retry_attachment_extract`

## 分支概览

| 分支 | 要点 |
|------|------|
| `master` | 早期单机版 |
| `feature/multi-worker-parallel` | 多人并行 + 共享去重 |
| `feature/scan-snapshot-plan-b` | 扫描快照增量 + 排除类规则 |
| `feature/attachment-extract` | 附件提取 + 跨进程限速 |
| **`feature/classify-quality-restructure`** | **包结构 + 分类质量/分卷/Others 纠偏（当前推荐）** |

```powershell
git checkout feature/classify-quality-restructure
git pull origin feature/classify-quality-restructure
```
