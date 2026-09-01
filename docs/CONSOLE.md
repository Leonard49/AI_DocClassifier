# AI DocClassifier — 本地 Web 控制台使用说明

> 分支：`feature/arch-data-dir-cleanup`  
> 更新日期：2026-08-12  
> 地址：http://127.0.0.1:8787（仅本机）  
> 启动：双击 `启动控制台.bat`，或 `python run_console.py`  
> 架构（主流程 vs 侧工具）：[ARCHITECTURE.md](ARCHITECTURE.md) · **迭代优化日志**：[BRANCHES.md](BRANCHES.md)

控制台用于：**改配置、改清单分工、按分组一键跑主流程 / 副本增强 / 文档元数据表 / 归纳新标题 / 运维纠偏并看实时日志**。不替代飞书权限与 `.env` 必填项。

---

## 1. 首次安装（每人一次）

```powershell
git clone https://github.com/Leonard49/AI_DocClassifier.git
cd AI_DocClassifier
git checkout feature/arch-data-dir-cleanup
git pull origin feature/arch-data-dir-cleanup

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

1. `git pull origin feature/arch-data-dir-cleanup`
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

左侧按**分组卡片**选任务，右侧看实时输出。筛选：`全部 | 主流程 | 副本增强 | 文档元数据表 | 归纳新标题 | 运维纠偏`。

「全部」时分组顺序固定为：主流程 → 副本增强 → 文档元数据表 → 归纳新标题 → 运维纠偏。组内正式任务在上、试跑（虚线按钮）在下；扫源任务带 `扫源` 标签。

| 筛选 | 典型任务 | 作用 |
|------|----------|------|
| 主流程 | 列出清单分工 | 确认 assignee / enabled |
| 主流程 | **【增量更新】分类复制 · 我的文件夹** | **日常首选**：快照跳过已成功；已 copied 不重复复制 |
| 主流程 | **【全量重扫】分类复制 · 我的文件夹** | `FORCE_RESCAN`：强制全量扫描校准；已 copied 仍跳过复制 |
| 主流程 | 【增量/全量】指定 folder | 先在下方下拉框选 id |
| 主流程 | 【增量/全量】清单全部 enabled | **慎用** |
| 副本增强 | 回填正式 / 试跑 | TARGET：贴元数据表（原名/源路径/作者/产品线/创建时间）+ 附件分隔 |
| 副本增强 | **强制重贴元数据表** | 删除错误旧表后重贴；需 `SHARED_STATE_DB` |
| 文档元数据表 | 汇总 / 汇总+分表（TARGET） | 写文档元数据多维表格（含原文档名称、源路径、创建时间） |
| 文档元数据表 | **[扫源] 按 token 分表** / 指定 folder | 三人并行常用；扫源清单 |
| 文档元数据表 | 试跑 20 篇 | 不写表 |
| **归纳新标题** | 写入汇总表 / 试跑 | TARGET；格式 **主题-模组型号-作者**（**不改 wiki**） |
| **归纳新标题** | **重命名 TARGET 副本标题** / 试跑 | 按**正文**归纳主题（去掉日期/流水号开头），格式**主题-模组型号-作者**；**不改 SCAN 源** |
| 运维纠偏 | **源 → TARGET 内容刷新** / 试跑 / 强制全量 | 源有更新时重拷；保留整理标题；旧副本进 `_已废弃_源刷新` |
| 运维纠偏 | Others 纠偏 / 主题归档 / 附件重试 / **修复附件提取图片** | 运维专项 |

操作要点：

1. **一次只能跑一个任务**；跑完或点「停止任务」后再开下一个。  
2. 需要指定文件夹的任务：先在「指定 folder id」里选好再点任务。  
3. 「停止任务」会尝试中断子进程；复制到一半时飞书侧可能已有部分结果，属正常。  
4. 关浏览器 **不会** 停任务；要用「停止任务」，或结束黑窗口（会连控制台一起停）。

分类复制成功后，会跑 `enrichment` 管道（默认：贴元数据表 + **归纳新标题并重命名 TARGET** + 附件分隔符 + 重绑附件提取区图片，均幂等）。历史副本仍用任务「副本增强回填」/「重命名 TARGET 副本标题」，或：

```bash
python -m tools.enrich_copied_docs --dry-run --limit 20
python -m tools.enrich_copied_docs
# 修正错误的作者/源路径/分类路径（先删旧表再贴）：
python -m tools.enrich_copied_docs --force-metadata --steps metadata_table
```

附件提取后 TARGET 副本里图片裂开时：

```bash
python -m tools.repair_extracted_images --dry-run --limit 20
python -m tools.repair_extracted_images
# 图块是空的、重绑无效时，删「附件：」提取区后重新提取：
python -m tools.repair_extracted_images --reextract --limit 20
```

回填时作者取源文档 `creator`，源路径取 SCAN 目录 breadcrumb（经 `SHARED_STATE_DB` 的 `copied_node → source_node` 映射）；**分类路径**取 TARGET 目录面包屑（`target_path`）。**不要**把知识枢纽路径误当作源路径。

作者为空常见原因：应用缺**通讯录/联系人只读**或用户不在通讯录可见范围（飞书 `41050 no user authority`）。此时会回退 **SCAN 源路径**中的人名文件夹（如 `Fei Xie`、`吴恩荣_Natalie.Wu`）。文件夹同时有中英文名时标题和元数据表里都会带上（`吴恩荣·Natalie.Wu`、`梁波·Edwin Liang`）。

新标题中间段：正文/标题正则扫到模组 PN 则用 PN；否则 LLM 归纳本文主要针对的模组或产品名；再没有则用 TARGET 一级|二级目录。贴表里的 **文章主题 / 作者 / 模块型号** 与展示标题共用同一套归纳。

源与 TARGET **不做双向同步**。需要跟进源正文变更时，用「源 → TARGET 内容刷新」（单向）：

```bash
python -m tools.refresh_target_from_source --dry-run --limit 20
python -m tools.refresh_target_from_source
# 忽略变更检测、全部重拷：
python -m tools.refresh_target_from_source --force
```

策略：重拷源到同一父目录 → 恢复当前 TARGET 标题 → 旧副本移入 `TARGET/_已废弃_源刷新` → 更新共享库映射 → 可选 enrichment。配置：`REFRESH_TARGET_SKIP_UNCHANGED`、`REFRESH_TARGET_OBSOLETE_FOLDER`。

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
| `METADATA_TABLE_COLUMN_WIDTHS` | 贴表列宽 px，如 `160,560`（标签,值） |
| `ENABLE_ATTACHMENT_SEPARATOR` | 复制后/回填是否加附件分隔符（默认开） |
| `METADATA_TABLE_FETCH_AUTHOR` | 贴表/回填解析作者（需联系人只读） |
| `REFRESH_TARGET_SKIP_UNCHANGED` | 源刷新默认只处理源有更新的映射（默认开） |
| `REFRESH_TARGET_OBSOLETE_FOLDER` | 旧副本废弃目录名（默认 `_已废弃_源刷新`） |
| `DISPLAY_TITLE_*` / `DISPLAY_TITLE_RENAME_SKIP_EXISTING` | 归纳新标题写表 / 重命名 TARGET |
| `MAX_DOCUMENTS` | 试跑时设 `10`；全量设 `0` |
| `METADATA_BITABLE_MODE` | 命令行默认；控制台任务按钮已带 `--mode` |
| `ENABLE_ATTACHMENT_EXTRACT` | 附件提取，耗时长 |

### 3.3 清单分工

编辑 `scan_folders.json`（路径以配置里 `SCAN_FOLDERS_FILE` 为准），**推荐在控制台「清单分工」页操作**，不必手改 JSON。

#### 添加新的 SCAN 目录（token）

1. 打开飞书知识库目标文件夹，从 URL 复制节点 token（`…/wiki/` 后面一段；也可直接粘贴整段 URL）  
2. 「清单分工」→ **添加 SCAN 目录** → 粘贴 token  
3. （可选）点 **从飞书解析**：自动填 `name` / 建议 `id` / `priority`  
4. 填 `assignee`（须与对方 `WORKER_ID` 一致；默认可为当前 worker）  
5. 点 **添加并保存** → 立刻写入清单文件  

同一 token / id 不可重复。解析需 `.env` 中飞书 App 可用，且对节点有读权限。

#### 改现有条目

可改：

- `enabled`：是否参与跑  
- `assignee`：负责人（须与对方 `WORKER_ID` 一致）  
- `priority`：排序  
- `token` / `name` / `id`：一般不要乱改 token  

改完点 **保存清单**。行末「移除」只从表格删掉，需再保存才落盘。

当前仓库示例分工：

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
3. 日常点 **【增量更新】分类复制 · 我的文件夹**  
4. 只有怀疑扫描漏了 / 要强制重新校准源目录时，才点 **【全量重扫】**（已 copied 的仍不会重复复制）

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
| `logs/latest.log` | 最近一次运行完整终端日志（`SAVE_RUN_LOG=true`；主流程与各 tools 均写入） |
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
