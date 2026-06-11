# AI DocClassifier

Automatically scan Feishu wiki documents, classify them with an LLM (Qwen), and copy each document into a folder hierarchy that matches the classification tags.

Originally based on code from LinKin Wang; optimized by Hydrew Wang with parallel processing, SQLite caching, and rate limiting.

## Project layout

| File | Purpose |
|------|---------|
| `main.py` | Entry point and orchestration pipeline |
| `config.py` | Settings loaded from environment / `.env` |
| `token_manager.py` | Feishu tenant access token refresh |
| `wiki_scanner.py` | Scan wiki nodes under a folder |
| `read_feishu_doc.py` | Read document raw content (rate-limited) |
| `qwen_classifier.py` | LLM classification against a label tree |
| `classify_cache.py` | SQLite cache for classification results |
| `feishu_title_check.py` | Folder lookup and duplicate checks |
| `create_feishu_node.py` | Create wiki folder nodes |
| `copy_doc.py` | Copy documents into target folders |
| `add_tag_block.py` | Insert classification tag block in source doc |
| `feishu_rate_limit.py` | Global Feishu API rate limiter |
| `llm_rate_limit.py` | Global LLM concurrency / rate limiter |
| `run_logging.py` | Mirror stdout/stderr to `logs/` |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env            # then edit .env with your values
```

Required environment variables:

- `FEISHU_APP_ID`, `FEISHU_APP_SECRET` — Feishu app credentials
- `SPACE_ID` — wiki space ID
- `SCAN_ROOT_TOKEN` or `SCAN_FOLDER_NAME` — source folder to scan
- `TARGET_PARENT_TOKEN` or `TARGET_ROOT_NAME` — destination root for copies
- `QWEN_API_KEY` — LLM API key

## Run

```bash
python main.py
```

Logs are written to `logs/latest.log` and `logs/run_YYYYMMDD_HHMMSS.log` when `SAVE_RUN_LOG=true` (default).

## Pipeline

1. **Scan** — list documents under the configured source folder
2. **Read** — fetch document bodies in parallel (`READ_WORKERS`, Feishu rate-limited)
3. **Classify** — LLM assigns 1–3 level tags in parallel (`CLASSIFY_WORKERS`)
4. **Copy / tag** — create folder path, copy document, optionally add tag block (serial)

Documents with empty body text are skipped. Progress is saved to `processing_progress.json` when `SAVE_PROGRESS=true`.

## Tuning

If you see Feishu HTTP 400 with code `99991400` (rate limit), lower `READ_WORKERS` (default 3).

If the LLM gateway returns 502/503, lower `CLASSIFY_WORKERS` or adjust limits in `llm_rate_limit.py`.

Classification results are cached in `classify_cache.db`; set `USE_CLASSIFY_CACHE=false` to force re-classification.

## Generated / ignored files

- `classify_cache.db` — classification cache
- `wiki_scan_cache.db` — scan cache (when `USE_CACHE=true`)
- `processing_progress.json` — resume checkpoint
- `logs/` — run logs
