# AI DocClassifier

飞书知识库文档自动分类工具：扫描指定目录下的叶子文档，用 LLM 按标签树分类，并复制到目标目录的分类文件夹中。

支持**多人并行**、**扫描快照增量**、**附件提取转文本**，通过共享去重库避免重复复制，结束时以目标目录实际扫描结果作为统计口径。

详细说明见 [docs/AI_DocClassifier说明文档.md](docs/AI_DocClassifier说明文档.md)。  
分支变更见 [docs/BRANCHES.md](docs/BRANCHES.md)。

## 快速开始

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# 编辑 .env 填入飞书与 LLM 配置
python main.py
```

## 主要能力

- 仅处理叶子 `docx`（跳过目录/索引页）
- **可选附件提取**：PDF / Word / PPT → 文本写回源文档（`ENABLE_ATTACHMENT_EXTRACT`）
- 并行读取与 AI 分类，串行复制到飞书
- 本机断点续跑 + 扫描快照增量 + 全局 `obj_token` 去重（多人并行）
- 排除周报/日报/会议纪要/重点客户跟踪等非技术文档
- 结束时扫描目标目录，统计实际文档数
- 飞书/LLM 限流保护，共享库与扫描缓存容错

## 文档

| 文档 | 内容 |
|------|------|
| [说明文档](docs/AI_DocClassifier说明文档.md) | 配置、流程、多人协作、排障 |
| [分支记录](docs/BRANCHES.md) | 各分支重要变化与选用建议 |
| [增量方案对比](docs/增量更新方案对比.md) | Plan B 扫描快照方案讨论稿 |

## 分支概览

| 分支 | 要点 |
|------|------|
| `master` | 早期单机版 |
| `feature/multi-worker-parallel` | 多人并行 + 共享去重 |
| `feature/scan-snapshot-plan-b` | 扫描快照增量 + 排除类规则 |
| **`feature/attachment-extract`** | **附件提取合入（当前推荐）** |

```powershell
git checkout feature/attachment-extract
git pull origin feature/attachment-extract
```
