# AI DocClassifier

飞书知识库文档自动分类工具：扫描指定目录下的叶子文档，用 LLM 按标签树分类，并复制到目标目录的分类文件夹中。

支持**多人并行**处理不同源目录，通过共享去重库避免重复复制，结束时以目标目录实际扫描结果作为统计口径。

详细说明见 [docs/AI_DocClassifier说明文档.md](docs/AI_DocClassifier说明文档.md)。

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
- 并行读取与 AI 分类，串行复制到飞书
- 本机断点续跑 + 全局 `obj_token` 去重（多人并行）
- 结束时扫描目标目录，统计实际文档数
- 飞书/LLM 限流保护，共享库与扫描缓存容错

## 文档

完整说明（配置、多人协作、增量更新、排障）：[docs/AI_DocClassifier说明文档.md](docs/AI_DocClassifier说明文档.md)

## 当前分支

主开发分支：`feature/multi-worker-parallel`
