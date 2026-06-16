# AI DocClassifier 系统说明文档

> 飞书知识库文档自动分类系统 — 机制说明、配置参数与流程图  
> 整理日期：2026-06-16（含多人并行与共享去重）

---

## 目录

1. [系统目标](#一系统目标)
2. [整体架构](#二整体架构)
3. [运行流程](#三运行流程)
4. [分类机制](#四分类机制)
5. [配置参数说明](#五配置参数说明)
6. [运行时生成的文件](#六运行时生成的文件)
7. [常见运维场景](#七常见运维场景)
8. [并发模型总结](#八并发模型总结)
9. [多人并行协作](#九多人并行协作)
10. [流程框图](#十流程框图)
11. [附录：跳过/失败分支汇总](#十一附录跳过失败分支汇总)

---

## 一、系统目标

本系统用于**自动整理飞书知识库文档**：

1. 在指定源目录下扫描**叶子 docx 文档**（`has_child=false`）
2. 读取正文，调用 **Qwen LLM** 按预定义标签树分类
3. 在目标目录下按分类结果**创建文件夹层级并复制文档**
4. 可选：在**原文档**中插入分类标签块
5. 支持**多人并行**：各人扫描不同源目录，共享同一目标目录，按 `obj_token` 全局去重

整体采用「**扫描 → 批量读 → 批量分类 → 串行写回 → 目标目录验证**」的流水线架构。

---

## 二、整体架构

| 模块 | 文件 | 职责 |
|------|------|------|
| 入口编排 | `main.py` | 流程控制、并行调度、进度统计 |
| 配置 | `config.py` | 从 `.env` 加载环境变量 |
| Token | `token_manager.py` | 飞书 `tenant_access_token` 自动刷新（默认 30 分钟） |
| 扫描 | `wiki_scanner.py` | BFS 遍历 wiki 节点树，只收集叶子 docx |
| 读文档 | `read_feishu_doc.py` | 调用 docx API 获取 raw_content |
| 分类 | `qwen_classifier.py` | 标签树 + Qwen API 分类 |
| 分类缓存 | `classify_cache.py` | SQLite 缓存分类结果 |
| 文件夹 | `create_feishu_node.py` / `feishu_title_check.py` | 创建/查找目标文件夹 |
| 复制 | `copy_doc.py` | 将文档复制到目标文件夹 |
| 打标 | `add_tag_block.py` | 在原文档插入标签块 |
| 共享去重 | `shared_state.py` | 跨进程/跨 worker 的 `obj_token` 复制注册表（SQLite） |
| 限流 | `feishu_rate_limit.py` / `llm_rate_limit.py` | 飞书读文档 & LLM 调用限速 |
| 日志 | `run_logging.py` | 终端输出同步写入 `logs/` |

---

## 三、运行流程

### 步骤 1：配置校验与 Token 初始化

- 启动时执行 `config.validate()`，检查必填项
- 创建 `TokenManager`，向飞书申请 `tenant_access_token`
- 后续所有飞书 API 调用统一通过 `token_manager.get_token()` 取 token

### 步骤 2：组件初始化

- `FeishuDocumentReader`：读文档正文
- `QwenTreeClassifier`：LLM 分类器（内置标签树 `LABEL_TREE`）
- `ClassifyCache`：可选，SQLite 分类结果缓存
- `FeishuNodeCreator` / `FolderNameChecker`：目标目录管理
- `FeishuDocumentTagAdder`：原文档打标
- `SharedCopyState`（`ENABLE_SHARED_DEDUP=true` 时）：多人并行共享去重库

### 步骤 3：确定扫描源与复制目标

**扫描源（二选一）：**

- `SCAN_ROOT_TOKEN`：直接指定 wiki 节点 token
- `SCAN_FOLDER_NAME`：按文件夹名称在知识库根层查找

**复制目标（优先级递减）：**

1. `TARGET_PARENT_TOKEN`
2. `TARGET_ROOT_NAME`（按名称查找）
3. `FALLBACK_PARENT_TOKEN`（备选）
4. 都找不到 → 使用知识库根目录

**目标目录基线统计：** 解析目标 token 后，先递归扫描目标目录，记录处理前的叶子 docx 数量（`target_count_before`）。

### 步骤 4：扫描叶子文档（`wiki_scanner.py`）

采用 **BFS（广度优先）** 遍历 wiki 节点树：

```
扫描根节点
  └─ 获取子节点列表（分页，每页 50）
       ├─ 若 obj_type == "docx" 且 has_child == false → 加入待处理列表（叶子文档）
       ├─ 若 has_child == true → 加入待扫描队列（继续向下）
       └─ 非 docx 但有子节点 → 仅遍历，不收集
```

**关键过滤规则：**

| 类型 | 处理方式 |
|------|----------|
| 叶子 docx（`has_child=false`） | ✅ 收集，进入后续流程 |
| 非叶子 docx（目录/索引页，有子节点） | ❌ 跳过，不读、不分类 |
| 正文为空的叶子 docx | ⏭️ 读取后跳过，不调 LLM |
| 已在 `processing_progress.json` 中的 node | ⏭️ 跳过（本机断点续跑） |
| 已在共享库中复制的 `obj_token` | ⏭️ 跳过（全局去重，多人并行） |
| 同一扫描内重复 `obj_token`（快捷方式等） | ⏭️ 合并为一次读取/复制 |

**扫描缓存**（`USE_CACHE=true` 时）：

- SQLite：`wiki_scan_cache.db`（节点缓存 + 扫描进度）
- JSON：`scanned_documents_{cache_key}.json`
- 缓存 key 带 `_leaf` 后缀，与旧版全量扫描区分

### 步骤 5：加载处理进度与全局去重过滤

- 读取 `processing_progress.json` 中已成功的 `node_token` 集合（按 `SCAN_ROOT_TOKEN` 区分）
- 若 `FORCE_RESCAN=true` → 忽略进度，全部重跑
- 若 `scan_root` 与当前 `SCAN_ROOT_TOKEN` 不一致 → 清空本地进度
- 若启用共享去重：跳过 `SHARED_STATE_DB` 中状态为 `copied` 的 `obj_token`
- 对待处理列表按 `obj_token` 分组，同一文档只读取和分类一次

### 步骤 6：批量读取 + 并行分类

**6a. 并行读取（`READ_WORKERS` 线程）**

- 调用飞书 `docx/v1/documents/{id}/raw_content` 获取纯文本
- 全局限速：`DOCX_READ_LIMITER` = **4 次/秒**（飞书上限 5 次/秒）
- 遇限流错误 `99991400` 自动重试（最多 5 次）

**6b. 并行 AI 分类（`CLASSIFY_WORKERS` 线程）**

- 正文为空 → 直接跳过，不调 LLM
- 有正文 → 构造 prompt（标题 + 正文前 `CLASSIFY_MAX_CHARS` 字符）
- LLM 返回标签路径，如 `Cellular -> 固件升级`
- 转换为 JSON：`{"tag1": ["Cellular"], "tag2": ["固件升级"]}`
- 路径校验：必须在预定义 `LABEL_TREE` 中，否则回退为 `Others`
- 分类缓存：同一 `obj_token` + 相同内容 hash → 直接命中缓存，不调 LLM

**LLM 调用保护：**

- 并发上限：2（`LLM_CONCURRENCY`）
- 速率：1.2 次/秒（`LLM_RATE_LIMITER`）
- 失败重试：最多 `LLM_MAX_RETRIES` 次，指数退避

### 步骤 7：串行复制 + 打标

对每个分类成功的文档**串行**执行（避免飞书写操作冲突）：

1. **全局占位**：`try_claim(obj_token)`，防止多 worker 同时复制同一文档
2. 根据 tag 层级（1～3 级）在目标目录下**查找或创建**文件夹链（并发创建失败时自动重试）
3. 若目标子目录已有同名文档，自动重命名为 `标题 (2)`、`标题 (3)` …
4. 调用 wiki copy API 将文档复制到最深层文件夹
5. 若 `ENABLE_SHARED_DEDUP=true`，复制成功后写入共享库；失败则 `release_claim`
6. 若 `ENABLE_TAG_ADD=true`，在**原文档**插入分类标签块

每处理 5 个文档自动保存一次 `processing_progress.json`。

### 步骤 8：目标目录验证与统计

结束时再次递归扫描 `TARGET_PARENT_TOKEN`，统计叶子 docx 数量（`target_count_after`）。

**主要统计口径：**

| 指标 | 含义 |
|------|------|
| **成功处理（目标目录实际叶子文档数）** | 结束时扫描目标目录的叶子 docx 总数，与飞书实际一致 |
| **本次净增（验证）** | `target_count_after - target_count_before` |
| **本次新复制（本 worker）** | 本进程本次成功复制且全局去重后的篇数 |
| **全局去重跳过** | 其他同事或前序运行已复制过的 `obj_token` |

---

## 四、分类机制

### 4.1 标签树

分类依据是代码中硬编码的 `LABEL_TREE`（见 `qwen_classifier.py`），顶层标签包括：

- `Cellular`（蜂窝模组相关）
- `Automotive`（车载相关）
- `Smart`（智能设备/BSP 相关）
- 等

树最深 3 级，LLM 必须从树中选择路径，不能自由发明标签。

### 4.2 分类输出格式

```json
{"tag1": ["Smart"], "tag2": ["BSP"], "tag3": ["I2C/UART/SPI/CAN"]}
```

- 1 级标签 → 在目标根下建 1 层文件夹
- 2 级标签 → 建 2 层
- 3 级标签 → 建 3 层

### 4.3 空文档处理（三层防护）

1. **扫描层**：非叶子 docx 不进入列表
2. **分类层**：`has_body_content()` 为 false 不调 LLM
3. **分类器层**：`classify()` 内再次检查正文为空返回 `None`

---

## 五、配置参数说明

所有配置通过项目根目录的 **`.env`** 文件设置，由 `config.py` 加载。

### 5.1 必填参数

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `FEISHU_APP_ID` | 字符串 | 飞书开放平台应用 App ID | `cli_xxxxxxxx` |
| `FEISHU_APP_SECRET` | 字符串 | 飞书应用 App Secret | `xxxxxxxx` |
| `SPACE_ID` | 字符串 | 知识库空间 ID | `7595802147485141976` |
| `QWEN_API_KEY` | 字符串 | 通义千问 / LiteLLM 网关 API Key | `sk-xxxxxxxx` |
| `SCAN_ROOT_TOKEN` | 字符串 | 扫描源目录的 wiki node token | 与 `SCAN_FOLDER_NAME` 二选一 |
| `SCAN_FOLDER_NAME` | 字符串 | 扫描源目录名称（在知识库根层查找） | 与 `SCAN_ROOT_TOKEN` 二选一 |
| `TARGET_PARENT_TOKEN` | 字符串 | 复制目标根目录 token | 与 `TARGET_ROOT_NAME` 二选一 |
| `TARGET_ROOT_NAME` | 字符串 | 复制目标根目录名称 | 与 `TARGET_PARENT_TOKEN` 二选一 |

### 5.2 可选参数 — 目录与行为

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `FALLBACK_PARENT_TOKEN` | 无 | 目标目录查找失败时的备选 token/名称 |
| `USE_CACHE` | `false` | 是否启用 wiki 扫描 SQLite 缓存（`wiki_scan_cache.db`），中断后可恢复扫描进度 |
| `MAX_DOCUMENTS` | `0`（无限制） | 测试用：只处理前 N 个文档 |
| `ENABLE_TAG_ADD` | `true` | 复制成功后是否在原文档插入分类标签块 |
| `SAVE_PROGRESS` | `true` | 是否保存处理进度到 `processing_progress.json` |
| `FORCE_RESCAN` | `false` | 设为 `true` 时忽略进度文件，重新处理所有文档 |
| `SAVE_RUN_LOG` | `true` | 是否将终端输出同步写入日志文件 |
| `LOG_DIR` | `logs` | 日志目录，生成 `latest.log` 和带时间戳的归档日志 |

### 5.3 可选参数 — 性能调优

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `READ_WORKERS` | `3` | 并行读取文档的线程数。过高易触发飞书限流（HTTP 400, code `99991400`），建议 2～3 |
| `CLASSIFY_WORKERS` | `4` | 并行 AI 分类的线程数。实际 LLM 并发被全局限制为 2，过高无益 |
| `CLASSIFY_MAX_CHARS` | `3000` | 送入 LLM 的正文最大字符数（标题另附） |
| `USE_CLASSIFY_CACHE` | `true` | 是否启用分类结果 SQLite 缓存（`classify_cache.db`）。内容变更后 hash 不同会自动重分类 |
| `CLASSIFY_VERBOSE` | `false` | 设为 `true` 时打印 LLM 原始返回和缓存命中详情 |
| `LLM_MAX_RETRIES` | `6` | LLM 调用失败时的最大重试次数（429/5xx 等可重试错误） |
| `LLM_REQUEST_TIMEOUT` | `120` | 单次 LLM 请求超时（秒） |
| `PROGRESS_INTERVAL` | `10` | 批量读取/分类时每处理 N 个文档打印一次进度 |

### 5.4 可选参数 — 多人并行

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_SHARED_DEDUP` | `true` | 是否启用跨 worker 的 `obj_token` 去重 |
| `SHARED_STATE_DB` | `shared_copy_state.db` | 共享 SQLite 路径；多人协作时放在共享盘，所有人指向同一文件 |
| `WORKER_ID` | `主机名-PID` | 当前执行者标识，每人应不同 |
| `CLAIM_TIMEOUT_MINUTES` | `30` | 复制占位超时（分钟），超时后允许其他 worker 重新抢占 |

**多人并行时必须一致：** `SPACE_ID`、`TARGET_PARENT_TOKEN`、`SHARED_STATE_DB`（同一租户下）。

**可以不同：** `FEISHU_APP_ID` / `FEISHU_APP_SECRET`、`SCAN_ROOT_TOKEN`、`WORKER_ID`、`QWEN_API_KEY`。

### 5.5 布尔值写法

以下值均视为 `true`：`1`、`true`、`yes`、`on`（不区分大小写）。  
未设置或非上述值时使用默认值。

### 5.6 配置示例（单人）

```env
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxx
SPACE_ID=7595802147485141976
SCAN_ROOT_TOKEN=JUWxwwvfJiLWQvk9HLHc3b24nie
TARGET_PARENT_TOKEN=GPFewOUJ1iGBrGks7R7cB137nDh
QWEN_API_KEY=sk-xxxxxxxx

ENABLE_SHARED_DEDUP=true
SHARED_STATE_DB=shared_copy_state.db
WORKER_ID=alice

READ_WORKERS=3
CLASSIFY_WORKERS=4
USE_CLASSIFY_CACHE=true
SAVE_PROGRESS=true
```

### 5.7 配置示例（多人并行）

**主机（共享盘在本机）：**

```env
WORKER_ID=hydrew
SCAN_ROOT_TOKEN=token_A
TARGET_PARENT_TOKEN=GPFewOUJ1iGBrGks7R7cB137nDh
SHARED_STATE_DB=F:\shared_db\shared_copy_state.db
ENABLE_SHARED_DEDUP=true
```

**同事（通过 UNC 访问共享盘）：**

```env
WORKER_ID=bob
SCAN_ROOT_TOKEN=token_B
TARGET_PARENT_TOKEN=GPFewOUJ1iGBrGks7R7cB137nDh
SHARED_STATE_DB=\\HOSTNAME\shared_db\shared_copy_state.db
ENABLE_SHARED_DEDUP=true
```

### 5.8 同事如何生成本地 `.env`

1. 克隆项目后，在项目根目录执行：

   ```powershell
   copy .env.example .env
   ```

2. 用编辑器打开 `.env`，填入真实值（**不要**提交到 Git）
3. 验证配置：

   ```powershell
   .venv\Scripts\python.exe -c "import config; config.validate(); print('OK')"
   ```

4. 密钥/token 通过团队文档或私下传递，不要写入 `.env.example`

---

## 六、运行时生成的文件

| 文件 | 触发条件 | 用途 |
|------|----------|------|
| `processing_progress.json` | `SAVE_PROGRESS=true` | 本机已成功处理的 `node_token`（按 `SCAN_ROOT_TOKEN` 断点续跑） |
| `shared_copy_state.db` | `ENABLE_SHARED_DEDUP=true` | 跨 worker 已复制 `obj_token` 注册表（建议放共享盘） |
| `classify_cache.db` | `USE_CLASSIFY_CACHE=true` | AI 分类结果缓存 |
| `wiki_scan_cache.db` | `USE_CACHE=true` | wiki 节点扫描缓存 |
| `scanned_documents_*.json` | `USE_CACHE=true` | 扫描到的文档列表快照 |
| `logs/latest.log` | `SAVE_RUN_LOG=true` | 实时日志 |
| `logs/run_YYYYMMDD_HHMMSS.log` | `SAVE_RUN_LOG=true` | 单次运行归档日志 |

以上文件均在 `.gitignore` 中，不会提交到 Git。

---

## 七、常见运维场景

| 场景 | 操作 |
|------|------|
| 中断后续跑 | 直接重新运行 `main.py`，读取 `processing_progress.json` 跳过已完成项 |
| 全部重跑 | 删除 `processing_progress.json`，或设 `FORCE_RESCAN=true` |
| 换扫描目录 | 修改 `SCAN_ROOT_TOKEN`，本地进度文件会因 `scan_root` 不匹配自动清空 |
| 多人并行分工 | 每人不同 `SCAN_ROOT_TOKEN` + `WORKER_ID`，共用 `TARGET_PARENT_TOKEN` 与 `SHARED_STATE_DB` |
| 关闭全局去重 | 设 `ENABLE_SHARED_DEDUP=false`（仅适合单人调试） |
| 共享库锁冲突 | 降低并行 worker 数量；确认共享文件夹为「修改」权限；避免过多机器同时写 SQLite |
| 强制重新分类 | 设 `USE_CLASSIFY_CACHE=false`，或删除 `classify_cache.db` |
| 飞书限流 | 降低 `READ_WORKERS` 到 2 |
| LLM 502/503 | 降低 `CLASSIFY_WORKERS`，或调整 `llm_rate_limit.py` 中的并发/QPS |
| 测试小批量 | 设 `MAX_DOCUMENTS=10` |
| 中断程序 | 终端 `Ctrl+C`，或在任务管理器中结束 `python.exe main.py` 进程 |

---

## 八、并发模型总结

```
扫描阶段       → 单线程 BFS + 分页 API
读取阶段       → READ_WORKERS 并行，全局 4 req/s 限速
分类阶段       → CLASSIFY_WORKERS 并行，实际 LLM 并发 ≤ 2，1.2 req/s
复制/打标阶段   → 严格串行（避免飞书 wiki 写冲突）
多人协调       → SHARED_STATE_DB 原子 claim + obj_token 去重
统计验证       → 处理前后各扫描一次 TARGET_PARENT_TOKEN
```

读和算阶段最大化吞吐，写阶段保证飞书 API 操作稳定性；共享库保证多人不会重复复制同一文档。

---

## 九、多人并行协作

### 9.1 分工方式

```
同事 A ── SCAN_ROOT_A ──┐
同事 B ── SCAN_ROOT_B ──┼──► 同一 TARGET_PARENT_TOKEN
同事 C ── SCAN_ROOT_C ──┘         ▲
                                  │
                         SHARED_STATE_DB（共享去重）
```

- 源目录**并列**即可，不要求互不包含
- 同一 `obj_token` 无论出现在哪个源目录，只会复制一次
- 各人的 `processing_progress.json` 保留在本地，仅记录本机已处理的 `node_token`

### 9.2 共享文件夹设置（Windows 示例）

1. 在主机创建 `F:\shared_db` 并开启文件夹共享（同事需**修改**权限）
2. 主机 `.env`：`SHARED_STATE_DB=F:\shared_db\shared_copy_state.db`
3. 同事 `.env`：`SHARED_STATE_DB=\\主机名\shared_db\shared_copy_state.db`
4. 同事先执行 `dir \\主机名\shared_db` 验证可读写

### 9.3 飞书应用是否必须相同

**不必。** 不同 `FEISHU_APP_ID` 也可并行，但须满足：

- 同一飞书租户（企业）
- 各应用均具备知识库与文档读写权限
- 应用可访问同一 `SPACE_ID` 与目标目录

不同应用还有助于分摊 API 限流配额。

### 9.4 统计对账

全部 worker 完成后：

- 各 worker「本次新复制」之和 ≈ 目标目录总净增（若开始时目标为空）
- 任一 worker 结束时的「目标目录实际叶子文档数」为**全量**计数（含其他人已写入的文档）
- 以**最后一次**全量扫描结果为准

---

## 十、流程框图

> 以下框图使用 Mermaid 语法，可在 VS Code、GitHub、Typora 等支持 Mermaid 的编辑器中渲染。

### 10.1 系统总览（启动 → 结束）

```mermaid
flowchart TB
    subgraph INIT["阶段 0：启动与初始化"]
        A0([运行 main.py]) --> A1{config.validate<br/>必填项齐全?}
        A1 -->|否| A1E[❌ 打印配置错误并退出]
        A1 -->|是| A2{SAVE_RUN_LOG?}
        A2 -->|是| A3[setup_run_log<br/>终端输出 → logs/]
        A2 -->|否| A4
        A3 --> A4[TokenManager 获取 tenant_access_token<br/>每 30 分钟自动刷新]
        A4 --> A5[初始化组件<br/>Reader / Classifier / Creator / Checker / TagAdder]
        A5 --> A5B{ENABLE_SHARED_DEDUP?}
        A5B -->|是| A5C[SharedCopyState 连接 SHARED_STATE_DB]
        A5B -->|否| A6
        A5C --> A6
    end

    subgraph RESOLVE["阶段 1：解析目录"]
        B1[解析扫描源<br/>SCAN_ROOT_TOKEN 或 SCAN_FOLDER_NAME]
        B2[解析复制目标<br/>TARGET_PARENT_TOKEN / TARGET_ROOT_NAME / FALLBACK]
        B1 --> B3{scan_root_token 存在?}
        B3 -->|否| B3E[❌ 退出]
        B3 -->|是| B2
        B2 --> B2A[扫描目标目录 baseline<br/>target_count_before]
    end

    subgraph SCAN["阶段 2：扫描"]
        C1[SimpleWikiScanner BFS 遍历<br/>仅收集叶子 docx]
        C1 --> C2{MAX_DOCUMENTS > 0?}
        C2 -->|是| C3[截取前 N 篇]
        C2 -->|否| C4
        C3 --> C4
    end

    subgraph PROGRESS["阶段 3：断点"]
        D1[load_processing_progress]
        D1 --> D2{FORCE_RESCAN<br/>或 scan_root 变更?}
        D2 -->|是| D3[processed_tokens = 空集]
        D2 -->|否| D4[从 processing_progress.json 恢复]
        D3 --> D5[过滤 pending_docs<br/>排除已处理 node_token<br/>排除共享库已复制 obj_token]
        D4 --> D5
        D5 --> D5A[按 obj_token 分组去重]
    end

    subgraph BATCH["阶段 4：批量读 + 分类"]
        E1[ThreadPool 并行读取唯一 obj_token<br/>READ_WORKERS + 飞书 4 req/s 限速]
        E2[ThreadPool 并行分类<br/>CLASSIFY_WORKERS + LLM 并发≤2]
        E1 --> E2
    end

    subgraph SERIAL["阶段 5：串行写回"]
        F1[逐篇遍历 read_results]
        F2{正文为空?}
        F3{分类成功?}
        F1 --> F2
        F2 -->|是| F2S[⏭️ 跳过]
        F2 -->|否| F3
        F3 -->|否| F3F[❌ 失败计数]
        F3 -->|是| F4[try_claim obj_token]
        F4 --> F4A{占位成功?}
        F4A -->|否| F4S[⏭️ 并发占用跳过]
        F4A -->|是| F4B[文件夹链 + 唯一标题复制 + 可选打标]
        F4B --> F5{复制成功?}
        F5 -->|是| F6[mark_copied + processed_tokens<br/>每 5 篇保存进度]
        F5 -->|否| F5R[release_claim → 失败计数]
    end

    subgraph END["阶段 6：收尾"]
        G0[扫描目标目录 target_count_after]
        G1[打印统计<br/>成功处理 = 目标目录实际叶子文档数]
        G2[save_processing_progress 最终保存]
        G3([结束])
        G0 --> G1 --> G2 --> G3
    end

    INIT --> RESOLVE --> SCAN --> PROGRESS --> BATCH --> SERIAL --> END
```

### 10.2 Wiki 扫描阶段（叶子节点过滤）

```mermaid
flowchart TD
    S0([scan_space 开始]) --> S1{验证 SPACE_ID 可访问?}
    S1 -->|否| S1E[返回空列表]
    S1 -->|是| S2{USE_CACHE=true?}
    S2 -->|是| S3[从 wiki_scan_cache.db 恢复<br/>scanned_nodes / pending_nodes / 文档列表]
    S2 -->|否| S4
    S3 --> S4[初始化 BFS 队列<br/>起点 = SCAN_ROOT_TOKEN]

    S4 --> S5{队列 pending_nodes<br/>非空?}
    S5 -->|否| S5D([扫描完成])
    S5 -->|是| S6[取出 current_parent]
    S6 --> S7{已扫描过?}
    S7 -->|是| S5
    S7 -->|否| S8[调用 wiki/v2/spaces/.../nodes<br/>分页 page_size=50]

    S8 --> S9{API 成功?}
    S9 -->|否| S9E[记录错误，继续下一节点]
    S9 -->|是| S10[遍历当前页每个 node]

    S10 --> S11{obj_type == docx?}
    S11 -->|是| S12{has_child == false?<br/>叶子节点}
    S11 -->|否| S14
    S12 -->|是| S13[✅ 加入 all_documents]
    S12 -->|否| S12S[⏭️ 跳过非叶子 docx<br/>目录/索引页]

    S13 --> S14
    S12S --> S14
    S14{has_child == true?}
    S14 -->|是| S15[加入 pending_nodes<br/>继续向下遍历]
    S14 -->|否| S16
    S15 --> S16[标记 current_parent 已扫描<br/>sleep 0.1s 防限流]
    S16 --> S5

    S5D --> S19[返回叶子 docx 列表]
```

### 10.3 并行读取阶段

```mermaid
flowchart TD
    R0([batch_read_contents]) --> R1[输入 pending_docs 列表]
    R1 --> R2[ThreadPoolExecutor<br/>max_workers = READ_WORKERS]

    R2 --> R3[每个 doc 提交 _read_one 任务]

    subgraph READ_ONE["单文档读取"]
        R4[取 obj_token / node_token / title]
        R4 --> R5[DOCX_READ_LIMITER.wait<br/>全局 4 req/s]
        R5 --> R6[GET docx/v1/documents/id/raw_content]
        R6 --> R7{code == 0?}
        R7 -->|是| R8[返回 content]
        R7 -->|限流 99991400| R9[指数退避重试 最多 5 次]
        R9 --> R6
        R7 -->|其他失败| R10[尝试 wiki get_node 重新解析 obj_token]
        R10 --> R6
    end

    R3 --> READ_ONE
    READ_ONE --> R11[写入 results<br/>obj_token → title, content]
    R11 --> R14([返回 read_results])
```

### 10.4 并行 AI 分类阶段

```mermaid
flowchart TD
    C0([batch_classify_documents]) --> C1[遍历 read_results]

    C1 --> C2{has_body_content?<br/>正文非空白}
    C2 -->|否| C2S[tags = None<br/>不调 LLM]
    C2 -->|是| C3[加入 to_classify 队列]

    C2S --> C1
    C3 --> C1
    C1 --> C4{to_classify 为空?}
    C4 -->|是| C4S[无需 AI 分类]
    C4 -->|否| C5[ThreadPoolExecutor<br/>max_workers = CLASSIFY_WORKERS]

    subgraph CLASSIFY_ONE["单文档分类 classify"]
        C6{USE_CLASSIFY_CACHE<br/>且缓存命中?}
        C6 -->|是| C6H[返回缓存 tag]
        C6 -->|否| C7[截取正文 CLASSIFY_MAX_CHARS<br/>拼接标题构造 prompt]
        C7 --> C8[LLM 并发 ≤2 + 1.2 req/s]
        C8 --> C10[调用 Qwen API]
        C10 --> C11{成功?}
        C11 -->|429/5xx| C12[指数退避重试<br/>最多 LLM_MAX_RETRIES 次]
        C12 --> C10
        C11 -->|是| C13[解析路径 → JSON tag1/tag2/tag3]
        C13 --> C14[_validate_path<br/>不在树中则回退 Others]
        C14 --> C18[写入 classify_cache.db]
        C11 -->|不可重试| C11F[返回 None]
    end

    C5 --> CLASSIFY_ONE
    CLASSIFY_ONE --> C21([返回 classify_results])
```

### 10.5 串行复制与打标阶段

```mermaid
flowchart TD
    P0([process_single_document]) --> P1[打印文档信息 + 分类 tag]
    P1 --> P2{tag 层级数}

    P2 -->|1 级| P3A[目标根 → tag1 文件夹]
    P2 -->|2 级| P3B[目标根 → tag1 → tag2]
    P2 -->|3 级| P3C[目标根 → tag1 → tag2 → tag3]
    P2 -->|异常| P2E[❌ 返回 None]

    subgraph ENSURE["文件夹 _ensure_child_folder（含并发重试）"]
        E1[check_duplicate 查同名子节点]
        E1 --> E2{已存在?}
        E2 -->|是| E3[复用已有 node_token]
        E2 -->|否| E4[create_lark_node 创建新文件夹]
        E4 --> E5{创建成功?}
        E5 -->|否| E1
    end

    P3A --> ENSURE
    P3B --> ENSURE
    P3C --> ENSURE

    ENSURE --> P3D[resolve_unique_child_title<br/>避免同名覆盖]
    P3D --> P4[FeishuWikiCopier 复制文档]
    P4 --> P5{复制成功?}
    P5 -->|否| P5F[❌ 返回 None]
    P5 -->|是| P6{ENABLE_TAG_ADD?}
    P6 -->|否| P7[✅ 返回 copied_node_token]
    P6 -->|是| P8[add_tag_block 原文档打标]
    P8 --> P7
```

### 10.6 配置解析与断点续跑决策

```mermaid
flowchart LR
    subgraph SCAN_SRC["扫描源解析"]
        SS1{SCAN_ROOT_TOKEN?}
        SS1 -->|是| SS2[直接使用 token]
        SS1 -->|否| SS3{SCAN_FOLDER_NAME?}
        SS3 -->|是| SS4[API 按名称查找]
        SS3 -->|否| SS5[扫描整个知识库]
    end

    subgraph TARGET["复制目标解析"]
        TT1{TARGET_PARENT_TOKEN?}
        TT1 -->|是| TT2[直接使用]
        TT1 -->|否| TT3{TARGET_ROOT_NAME?}
        TT3 -->|是| TT4[按名称查找]
        TT3 -->|否| TT5{FALLBACK?}
        TT5 -->|是| TT6[使用备选]
        TT5 -->|否| TT7[知识库根目录]
    end

    subgraph RESUME["断点续跑"]
        RP1{SAVE_PROGRESS?}
        RP1 -->|否| RP2[不加载进度]
        RP1 -->|是| RP3{FORCE_RESCAN?}
        RP3 -->|是| RP4[忽略 progress 文件]
        RP3 -->|否| RP5{scan_root 匹配?}
        RP5 -->|否| RP6[清空进度]
        RP5 -->|是| RP7[加载 processed_tokens]
    end
    subgraph DEDUP["全局去重（多人并行）"]
        DD1{ENABLE_SHARED_DEDUP?}
        DD1 -->|是| DD2[跳过 SHARED_STATE_DB 已复制 obj_token]
        DD1 -->|否| DD3[仅本地 progress 过滤]
    end
```

### 10.7 数据流与缓存层

```mermaid
flowchart LR
    subgraph INPUT["输入"]
        ENV[".env 配置"]
        WIKI["飞书 Wiki API"]
        LLM["Qwen LiteLLM 网关"]
    end

    subgraph MEMORY["运行时内存"]
        DOCS["all_documents"]
        READ["read_results"]
        TAGS["classify_results"]
    end

    subgraph PERSIST["持久化"]
        PP["processing_progress.json<br/>（本机）"]
        SS["shared_copy_state.db<br/>（共享盘，多人）"]
        CC["classify_cache.db"]
        WS["wiki_scan_cache.db"]
        LOG["logs/latest.log"]
    end

    ENV --> DOCS
    WIKI --> DOCS
    WS -.-> DOCS
    SS -.-> DOCS
    DOCS --> READ
    WIKI --> READ
    PP -.-> DOCS
    READ --> TAGS
    CC -.-> TAGS
    LLM --> TAGS
    TAGS --> WIKI
    TAGS --> PP
    TAGS --> SS
```

### 10.8 单篇文档端到端时序

```mermaid
sequenceDiagram
    participant M as main.py
    participant SS as SharedCopyState
    participant S as WikiScanner
    participant R as DocumentReader
    participant C as QwenClassifier
    participant F as FolderCreator
    participant CP as WikiCopier
    participant T as TagAdder

    M->>S: scan_space(TARGET) 统计 baseline
    M->>S: scan_space(SCAN_ROOT_TOKEN)
    S-->>M: 叶子 docx 列表

    M->>M: 过滤 progress + 共享库已复制 obj_token
    M->>M: 按 obj_token 分组去重

    par 并行读取
        M->>R: get_raw_content(obj_token)
        R-->>M: title + content
    end

    alt 正文为空
        M->>M: 跳过，不调 LLM
    else 正文有内容
        par 并行分类
            M->>C: classify(content, title)
            C-->>M: tag JSON
        end
    end

    loop 串行处理每篇
        M->>SS: try_claim(obj_token)
        alt 占位失败或已复制
            M->>M: 跳过
        else 占位成功
            M->>F: 创建 tag1→tag2→tag3 文件夹链
            M->>CP: copy_document（唯一标题）
            M->>SS: mark_copied / release_claim
            opt ENABLE_TAG_ADD
                M->>T: add_tag_block(原文档)
            end
        end
        M->>M: 保存进度
    end

    M->>S: scan_space(TARGET) 验证 target_count_after
```

---

## 十一、附录：跳过/失败分支汇总

```mermaid
flowchart TD
    subgraph SKIP["⏭️ 跳过（不计失败）"]
        SK1[非叶子 docx<br/>has_child=true]
        SK2[正文空白]
        SK3[已在 processing_progress.json]
        SK4[共享库已复制 obj_token<br/>全局去重]
        SK5[try_claim 失败<br/>其他 worker 正在处理]
        SK6[同一扫描内重复 obj_token]
        SK7[MAX_DOCUMENTS 截断后的文档]
    end

    subgraph FAIL["❌ 失败计数"]
        F1[LLM 分类返回 None]
        F2[标签格式无法解析]
        F3[文件夹创建失败]
        F4[文档复制 API 失败]
    end

    subgraph WARN["⚠️ 警告但不中断"]
        W1[标签块写入失败<br/>复制已成功]
        W2[LLM 路径模糊匹配 / 回退 Others]
    end
```

---

## 快速启动

```powershell
# 1. 环境准备
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
# 编辑 .env 填入配置

# 2. 验证配置
.venv\Scripts\python.exe -c "import config; config.validate(); print('OK')"

# 3. 运行
.venv\Scripts\python.exe main.py
```

---

*文档对应代码仓库：AI_DocClassifier（`feature/multi-worker-parallel` 分支，含多人并行与共享去重）*
