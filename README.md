# AI DocClassifier

飞书知识库文档自动分类工具：扫描指定目录下的叶子文档，用 LLM 按标签树分类，并复制到目标目录的分类文件夹中。

支持**多人并行**、**扫描快照增量**、**附件提取**、**文档增强**（贴表 / 附件分隔 / 可扩展回填）、**多维表格元数据**、**归纳新标题**（写表或重命名 TARGET）、**源→TARGET 按需刷新**，以及**本地 Web 控制台**配置与一键跑任务。

## 文档

| 文档 | 内容 |
|------|------|
| **[快速上手指南](docs/QUICK_START.md)** | **落地操作、控制台、检查清单、排障** |
| **[控制台使用说明](docs/CONSOLE.md)** | **本地 Web 控制台：安装、页签、运行任务** |
| [项目结构](docs/PROJECT_STRUCTURE.md) | 包划分与入口命令 |
| [分类准则说明](docs/分类准则说明.md) | 产品线判定、Others、元数据 |
| [系统说明文档](docs/AI_DocClassifier说明文档.md) | 架构、配置、流程、详细排障 |
| [分支记录](docs/BRANCHES.md) | **每次代码优化的迭代日志**（必看）+ 各分支变化与选用建议 |
| [增量方案对比](docs/增量更新方案对比.md) | Plan B 扫描快照方案讨论稿 |

## 快速开始（推荐：控制台）

```powershell
git checkout feature/arch-data-dir-cleanup
git pull origin feature/arch-data-dir-cleanup

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# 编辑 .env：WORKER_ID、飞书 App、TARGET、LLM_API_KEY

# 双击 启动控制台.bat  或:
python run_console.py
# 浏览器打开 http://127.0.0.1:8787
```

也可命令行：`python main.py --all-assigned`。详见 **[docs/QUICK_START.md](docs/QUICK_START.md)**。

## 主要能力

- 仅处理叶子 `docx`（跳过目录/索引页）
- **本地 Web 控制台**：配置 `.env`、清单分工（可可视化添加 SCAN token）；运行页按「主流程 / 副本增强 / 文档元数据表 / 归纳新标题 / 运维纠偏」分组一键跑任务
- **附件提取**：PDF / Word / PPT → 文本写回源文档
- 并行读取与 AI 分类，串行复制到飞书
- 本机断点续跑 + 扫描快照增量 + 全局 `obj_token` 去重（多人并行）
- 跨进程飞书 API 限速与自动重试
- 基于 QT-SOP-PM-048E 的模组→产品线判定，降低 Others
- Others 占比超告警阈值时写报告，仍继续复制；超限自动分卷
- **文档增强**：复制后贴元数据表 + 附件分隔；作者/源路径取 SCAN，分类路径取 TARGET；旧副本可用回填 / `--force-metadata` 纠偏
- **归纳新标题**：格式 **主题-产品线-作者**；可写飞书多维表格，或直接重命名 TARGET 副本标题（不改源）
- **源→TARGET 刷新**：按需单向重拷源正文，保留整理标题；旧副本进废弃夹（不做双向同步）
- **多维表格**：独立工具写入飞书 bitable（汇总 / 按 token）
- 存量 `Others` 纠偏 / 主题归档 / 附件失败重试（`tools/`）

## 分支概览

| 分支 | 要点 |
|------|------|
| `master` | 早期单机版 |
| `feature/multi-worker-parallel` | 多人并行 + 共享去重 |
| `feature/scan-snapshot-plan-b` | 扫描快照增量 + 排除类规则 |
| `feature/attachment-extract` | 附件提取 + 跨进程限速 |
| `feature/classify-quality-restructure` | 包结构 + 分类质量/分卷 |
| `feature/scan-folders-batch` | 清单批量增量 |
| `feature/doc-metadata-bitable` | 元数据 → 多维表格（独立工具） |
| `feature/doc-metadata-inline-table` | 元数据贴目标文档开头 |
| `feature/console-ui` | 本地 Web 控制台 |
| `feature/doc-enrichment` | enrichment 管道 + 旧副本回填 |
| `feature/tool-ops-target-scope` | 工具默认 TARGET + tool_ops 账本 |
| **`feature/arch-data-dir-cleanup`** | **data/ + 账本收敛 + 展示标题/源刷新/贴表纠偏（当前推荐）** |

```powershell
git checkout feature/arch-data-dir-cleanup
git pull origin feature/arch-data-dir-cleanup
```

## 作者

- 作者：Hydrew
- 项目负责人：Jamie
