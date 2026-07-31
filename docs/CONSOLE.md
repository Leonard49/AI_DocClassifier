# AI DocClassifier — 本地 Web 控制台使用说明

> 分支：`feature/doc-enrichment`  
> 更新日期：2026-07-31  
> 地址：http://127.0.0.1:8787（仅本机）  
> 启动：双击 `启动控制台.bat`，或 `python run_console.py`

控制台用于：**改配置、改清单分工、一键跑分类/元数据/副本增强回填并看实时日志**。不替代飞书权限与 `.env` 必填项。

---

## 1. 首次安装（每人一次）

```powershell
git clone https://github.com/Leonard49/AI_DocClassifier.git
cd AI_DocClassifier
git checkout feature/doc-enrichment
git pull origin feature/doc-enrichment

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
notepad .env
```

### `.env` 必填（每人不同）

| 变量 | 说明 |
|------|------|
| `WORKER_ID` | 你的名字，须与 `scan_folders.json` 里 `assignee` **完全一致**（如 `Hydrew` / `Jamie` / `Hayes`） |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | **每人独立**飞书应用 |
| `SPACE_ID` | 团队统一知识空间 ID |
| `TARGET_PARENT_TOKEN` | 团队统一目标目录 token |
| `LLM_API_KEY` | 分类 / 文档类型 LLM 用 |

### 建议与团队一致

- `SCAN_FOLDERS_FILE=scan_folders.json`
- `SHARED_STATE_DB`、`FEISHU_RATE_LIMIT_DB` 等共享盘路径（多人并行时）
- 清单模式下可清空 `SCAN_ROOT_TOKEN`

飞书 App 权限（按任务）：

- 分类复制：`wiki` 读写、文档复制相关权限  
- 元数据多维表格：另需 `bitable:app`；解析作者需联系人只读  

更完整的落地说明见 [QUICK_START.md](QUICK_START.md)。

---

## 2. 日常启动

1. `git pull origin feature/doc-enrichment`
2. 双击项目根目录 **`启动控制台.bat`**  
   - 或：`.venv\Scripts\activate` 后执行 `python run_console.py`
3. 浏览器应自动打开 http://127.0.0.1:8787  
   若未打开，请手动访问该地址

**黑窗口不要关**：那是控制台服务进程。关掉后网页会失效。

顶部状态条含义：

- **分支**：当前 git 分支  
- **WORKER**：当前 `.env` 里的 `WORKER_ID`  
- **配置 OK / 配置缺项**：必填项是否齐全  

---

## 3. 三个页签

### 3.1 运行

左侧选任务，右侧看实时输出。

| 筛选 | 典型任务 | 作用 |
|------|----------|------|
| 分类 | 列出清单分工 | 确认 assignee / 自己名下文件夹 |
| 分类 | 分类复制（我的文件夹） | `main.py --all-assigned` |
| 分类 | 分类复制（清单全部 enabled） | 慎用，会跑所有 enabled |
| 分类 | 分类复制（指定 folder id） | 先在下方下拉框选 id |
| 元数据 | 元数据 → 按 token 分表 | **三人并行推荐** |
| 元数据 | 元数据 → 汇总+分表 (both) | 自己名下；可能与同事抢写汇总表 |
| 元数据 | 元数据 → 仅汇总表（全清单） | **建议全部人分表跑完后，由一人执行** |
| 元数据 | 元数据试跑（20 篇 dry-run） | 不写表，先看提取结果 |
| 元数据 | 元数据分表（指定 folder id） | 单夹验证 |
| 工具 | Others 纠偏 / 主题归档 / 附件重试 | 运维专项 |

操作要点：

1. **一次只能跑一个任务**；跑完或点「停止任务」后再开下一个。  
2. 需要指定文件夹的任务：先在「指定 folder id」里选好再点任务。  
3. 「停止任务」会尝试中断子进程；复制到一半时飞书侧可能已有部分结果，属正常。  
4. 关浏览器 **不会** 停任务；要用「停止任务」，或结束黑窗口（会连控制台一起停）。

分类复制成功后，会跑 `enrichment` 管道（默认：贴元数据表 + 附件分隔符，均幂等）。已复制的旧文档可用任务「副本增强回填」或：

```bash
python -m tools.enrich_copied_docs --dry-run --limit 20
python -m tools.enrich_copied_docs
```

### 3.2 配置

对应编辑项目根目录 `.env`。

- 按分组修改（身份 / 飞书 / LLM / 并行 / 分类 / 元数据 / 性能）  
- 密钥默认隐藏；勾选「显示密钥」再查看  
- 点 **保存** 写入磁盘  
- **正在跑的任务仍用启动时的旧环境**；改完后请停掉任务再新开，新任务才会读到新配置  

常用开关：

| 配置 | 建议 |
|------|------|
| `ENABLE_METADATA_TABLE` | 分类复制后是否贴表（默认开） |
| `ENABLE_ATTACHMENT_SEPARATOR` | 复制后/回填是否加附件分隔符（默认开） |
| `MAX_DOCUMENTS` | 试跑时设 `10`；全量设 `0` |
| `METADATA_BITABLE_MODE` | 命令行默认；控制台任务按钮已带 `--mode` |
| `ENABLE_ATTACHMENT_EXTRACT` | 附件提取，耗时长 |

### 3.3 清单分工

编辑 `scan_folders.json`（路径以配置里 `SCAN_FOLDERS_FILE` 为准）。

可改：

- `enabled`：是否参与跑  
- `assignee`：负责人（须与对方 `WORKER_ID` 一致）  
- `priority`：排序  
- `token` / `name` / `id`：一般不要乱改 token  

改完点 **保存清单**。当前仓库示例分工：

| 人 | 范围（约） |
|----|------------|
| Hydrew | 8～14（国内大区等） |
| Jamie | 15～20（福建、海外等） |
| Hayes | 21～29（台湾、Smart、GNSS 等） |

先点「运行 → 列出清单分工」，确认自己名下带 `*` 的条目无误。

---

## 4. 推荐工作流

### 4.1 分类复制（日常增量）

1. 配置页确认 `WORKER_ID`、飞书、TARGET、LLM  
2. 运行 → **列出清单分工**  
3. 可选：配置里 `MAX_DOCUMENTS=10` 试跑 → **分类复制（我的文件夹）**  
4. 确认无误后 `MAX_DOCUMENTS=0`，再全量跑 **分类复制（我的文件夹）**

### 4.2 全量元数据归纳（三人并行）

1. 每人只跑：**元数据 → 按 token 分表**（不要同时多人写汇总表）  
2. 全部完成后，**任一人**再跑：**元数据 → 仅汇总表（全清单）**  
3. 在飞书 `TARGET_PARENT_TOKEN` 下查看 `文档元数据-{id}` 分表与「文档元数据汇总」

试跑可用：**元数据试跑（20 篇 dry-run）**。

---

## 5. 产出与日志

| 位置 | 说明 |
|------|------|
| 控制台右侧「输出」 | 当前任务实时日志 |
| `logs/` | `main` / 工具的运行与报告 JSON |
| `logs/doc_metadata_bitable.json` | 最近一次元数据导出报告 |
| 飞书 TARGET 目录 | 分类结果、贴表文档、多维表格 |

---

## 6. 常见问题

**双击 bat 一闪而过 / 报错找不到 python**  
- 安装 Python 3.10+ 并勾选「Add to PATH」  
- 或先建好 `.venv`（见上文「首次安装」）

**网页打不开**  
- 看黑窗口是否还在、是否提示 `http://127.0.0.1:8787`  
- 确认没有别的程序占用 8787；可用环境变量 `CONSOLE_PORT=8790` 后 `python run_console.py`

**配置缺项**  
- 到「配置」页补全红色提示相关项并保存  

**列出清单是空的 / 没有我的文件夹**  
- `WORKER_ID` 与 `assignee` 拼写、大小写一致  
- 「清单分工」里对应条目 `enabled` 为勾选  

**任务点了没反应 / 提示已有任务在运行**  
- 先「停止任务」，或等当前任务结束  

**多人同时写汇总表重复/错乱**  
- 并行阶段只用「按 token 分表」；汇总表最后一人跑  

**保存配置后好像没生效**  
- 停掉当前任务再重新启动任务（不必重启控制台，但重启更稳妥）

---

## 7. 与命令行的关系

控制台只是把常用命令变成按钮，等价于例如：

```powershell
python main.py --all-assigned
python -m tools.export_doc_metadata_bitable --all-assigned --mode per-token
```

高级参数、排障仍可直接用命令行；系统细节见 [AI_DocClassifier说明文档.md](AI_DocClassifier说明文档.md)、分支说明见 [BRANCHES.md](BRANCHES.md)。
