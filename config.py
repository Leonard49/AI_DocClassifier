"""Application configuration loaded from environment variables."""

import os
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from util.paths import (
    default_data_dir,
    leftover_legacy_hints,
    migrate_legacy_local_files,
    resolve_configurable_path,
)


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(key, default)
    if value is not None and value.strip() == "":
        return default
    return value


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


# Feishu app credentials
FEISHU_APP_ID = _env("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = _env("FEISHU_APP_SECRET", "")

# Wiki space and scan targets
SPACE_ID = _env("SPACE_ID", "")
SCAN_ROOT_TOKEN = _env("SCAN_ROOT_TOKEN")
SCAN_FOLDER_NAME = _env("SCAN_FOLDER_NAME")
# Shared registry of source folders (tokens + assignees). See scan_folders.example.json
SCAN_FOLDERS_FILE = _env("SCAN_FOLDERS_FILE") or "scan_folders.json"

# Destination folder for classified copies
TARGET_PARENT_TOKEN = _env("TARGET_PARENT_TOKEN")
TARGET_ROOT_NAME = _env("TARGET_ROOT_NAME")
FALLBACK_PARENT_TOKEN = _env("FALLBACK_PARENT_TOKEN")

# Local runtime data root (core + tools). Shared UNC paths stay in their own env vars.
DATA_DIR = _env("DATA_DIR") or default_data_dir()
AUTO_MIGRATE_DATA_DIR = _env_bool("AUTO_MIGRATE_DATA_DIR", True)

# Processing behavior
USE_CACHE = _env_bool("USE_CACHE", False)
MAX_DOCUMENTS = _env_int("MAX_DOCUMENTS", 0) or None
ENABLE_TAG_ADD = _env_bool("ENABLE_TAG_ADD", True)
# After copy: insert metadata key/value table at the top of the *target* Docx
ENABLE_METADATA_TABLE = _env_bool("ENABLE_METADATA_TABLE", True)
METADATA_TABLE_FETCH_AUTHOR = _env_bool("METADATA_TABLE_FETCH_AUTHOR", True)
# Backfill / after-copy: insert eye-catching separator before `附件：` headings
ENABLE_ATTACHMENT_SEPARATOR = _env_bool("ENABLE_ATTACHMENT_SEPARATOR", True)
ENABLE_ATTACHMENT_EXTRACT = _env_bool("ENABLE_ATTACHMENT_EXTRACT", False)
SAVE_PROGRESS = _env_bool("SAVE_PROGRESS", True)
FORCE_RESCAN = _env_bool("FORCE_RESCAN", False)
ENABLE_SCAN_SNAPSHOT = _env_bool("ENABLE_SCAN_SNAPSHOT", True)
SCAN_SNAPSHOT_DB = resolve_configurable_path(
    _env("SCAN_SNAPSHOT_DB"),
    data_dir=DATA_DIR,
    default_relative="core/scan_snapshot.db",
)
FULL_SCAN_CALIBRATION_DAYS = _env_int("FULL_SCAN_CALIBRATION_DAYS", 7)
SAVE_RUN_LOG = _env_bool("SAVE_RUN_LOG", True)
LOG_DIR = _env("LOG_DIR", "logs") or "logs"
PROCESSING_PROGRESS_FILE = resolve_configurable_path(
    _env("PROCESSING_PROGRESS_FILE"),
    data_dir=DATA_DIR,
    default_relative="core/processing_progress.json",
)
CLASSIFY_CACHE_DB = resolve_configurable_path(
    _env("CLASSIFY_CACHE_DB"),
    data_dir=DATA_DIR,
    default_relative="core/classify_cache.db",
)
WIKI_SCAN_CACHE_DB = resolve_configurable_path(
    _env("WIKI_SCAN_CACHE_DB"),
    data_dir=DATA_DIR,
    default_relative="core/wiki_scan_cache.db",
)

# Performance tuning
READ_WORKERS = _env_int("READ_WORKERS", 2)
CLASSIFY_WORKERS = _env_int("CLASSIFY_WORKERS", 4)
CLASSIFY_MAX_CHARS = _env_int("CLASSIFY_MAX_CHARS", 3000)
USE_CLASSIFY_CACHE = _env_bool("USE_CLASSIFY_CACHE", True)
CLASSIFY_VERBOSE = _env_bool("CLASSIFY_VERBOSE", False)
# Warn when Others share among classified docs exceeds this ratio (0 disables warning).
# Exceeding the threshold no longer aborts classify/copy; a report is written instead.
OTHERS_RATIO_FAIL_THRESHOLD = _env_float("OTHERS_RATIO_FAIL_THRESHOLD", 0.15)
ENABLE_FOLDER_ROLLOVER = _env_bool("ENABLE_FOLDER_ROLLOVER", True)
FOLDER_ROLLOVER_DB = _env("FOLDER_ROLLOVER_DB")
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 6)
LLM_REQUEST_TIMEOUT = _env_float("LLM_REQUEST_TIMEOUT", 120.0)
PROGRESS_INTERVAL = _env_int("PROGRESS_INTERVAL", 10)

# LLM (OpenAI-compatible gateway)
LLM_API_KEY = _env("LLM_API_KEY") or _env("QWEN_API_KEY", "")
LLM_BASE_URL = _env("LLM_BASE_URL") or "https://qlitellm.phicotek.com/v1"
LLM_MODEL = _env("LLM_MODEL") or "deepseek-v4-flash"

# Multi-worker parallel processing (shared folder on network drive recommended)
ENABLE_SHARED_DEDUP = _env_bool("ENABLE_SHARED_DEDUP", True)
# Default local copy under data/core; production should set UNC SHARED_STATE_DB
SHARED_STATE_DB = resolve_configurable_path(
    _env("SHARED_STATE_DB"),
    data_dir=DATA_DIR,
    default_relative="core/shared_copy_state.db",
)
WORKER_ID = _env("WORKER_ID")
CLAIM_TIMEOUT_MINUTES = _env_int("CLAIM_TIMEOUT_MINUTES", 30)

# Feishu API resilience (multi-worker attachment extract)
ENABLE_CROSS_PROCESS_FEISHU_LIMIT = _env_bool("ENABLE_CROSS_PROCESS_FEISHU_LIMIT", True)
FEISHU_RATE_LIMIT_DB = _env("FEISHU_RATE_LIMIT_DB")
FEISHU_GLOBAL_MAX_PER_SECOND = _env_float("FEISHU_GLOBAL_MAX_PER_SECOND", 2.0)
FEISHU_LOCAL_MAX_PER_SECOND = _env_float("FEISHU_LOCAL_MAX_PER_SECOND", 4.0)
FEISHU_API_MAX_RETRIES = _env_int("FEISHU_API_MAX_RETRIES", 5)
FEISHU_API_TIMEOUT = _env_float("FEISHU_API_TIMEOUT", 90.0)
FEISHU_DOWNLOAD_TIMEOUT = _env_float("FEISHU_DOWNLOAD_TIMEOUT", 180.0)

# Document metadata → Feishu bitable (standalone tool)
METADATA_BITABLE_TITLE = _env("METADATA_BITABLE_TITLE") or "文档元数据汇总"
METADATA_BITABLE_APP_TOKEN = _env("METADATA_BITABLE_APP_TOKEN")
# Deprecated: bitable record ids live in TOOL_OPS_DB; kept for one-release compat migrate
METADATA_BITABLE_INDEX_DB = resolve_configurable_path(
    _env("METADATA_BITABLE_INDEX_DB"),
    data_dir=DATA_DIR,
    default_relative="tools/metadata_bitable_index.db",
)
METADATA_BITABLE_PER_TOKEN_TITLE_TMPL = (
    _env("METADATA_BITABLE_PER_TOKEN_TITLE_TMPL") or "文档元数据-{id}"
)
METADATA_BITABLE_MODE = (_env("METADATA_BITABLE_MODE") or "both").strip().lower()
METADATA_BITABLE_PER_TOKEN_PARENT = (
    _env("METADATA_BITABLE_PER_TOKEN_PARENT") or "target"
).strip().lower()
METADATA_USE_LLM_DOC_TYPE = _env_bool("METADATA_USE_LLM_DOC_TYPE", True)
METADATA_BITABLE_SKIP_EXISTING = _env_bool("METADATA_BITABLE_SKIP_EXISTING", False)

# Side tools: document universe + unified operation ledger
TOOL_DOC_SCOPE = (_env("TOOL_DOC_SCOPE") or "target").strip().lower()
TOOL_OPS_DB = resolve_configurable_path(
    _env("TOOL_OPS_DB"),
    data_dir=DATA_DIR,
    default_relative="tools/tool_ops.db",
)

# Display titles → Feishu bitable (standalone; does NOT rename wiki titles)
DISPLAY_TITLE_BITABLE_TITLE = _env("DISPLAY_TITLE_BITABLE_TITLE") or "文档展示标题"
DISPLAY_TITLE_BITABLE_APP_TOKEN = _env("DISPLAY_TITLE_BITABLE_APP_TOKEN")
DISPLAY_TITLE_BITABLE_INDEX_DB = resolve_configurable_path(
    _env("DISPLAY_TITLE_BITABLE_INDEX_DB"),
    data_dir=DATA_DIR,
    default_relative="tools/display_title_bitable_index.db",
)
DISPLAY_TITLE_BITABLE_PER_TOKEN_TITLE_TMPL = (
    _env("DISPLAY_TITLE_BITABLE_PER_TOKEN_TITLE_TMPL") or "展示标题-{id}"
)
DISPLAY_TITLE_BITABLE_MODE = (
    _env("DISPLAY_TITLE_BITABLE_MODE") or "aggregated"
).strip().lower()
DISPLAY_TITLE_BITABLE_PER_TOKEN_PARENT = (
    _env("DISPLAY_TITLE_BITABLE_PER_TOKEN_PARENT") or "target"
).strip().lower()
DISPLAY_TITLE_USE_LLM_PURPOSE = _env_bool("DISPLAY_TITLE_USE_LLM_PURPOSE", True)
DISPLAY_TITLE_SKIP_EXISTING = _env_bool("DISPLAY_TITLE_SKIP_EXISTING", False)
# Rename TARGET wiki titles to display-title format (never touches SCAN source)
DISPLAY_TITLE_RENAME_SKIP_EXISTING = _env_bool(
    "DISPLAY_TITLE_RENAME_SKIP_EXISTING", False
)

# Enrichment backfill skip (per-op in TOOL_OPS_DB)
ENRICHMENT_SKIP_EXISTING = _env_bool("ENRICHMENT_SKIP_EXISTING", False)

# Source → TARGET content refresh (retire old copy under obsolete folder)
REFRESH_TARGET_SKIP_UNCHANGED = _env_bool("REFRESH_TARGET_SKIP_UNCHANGED", True)
REFRESH_TARGET_OBSOLETE_FOLDER = (
    _env("REFRESH_TARGET_OBSOLETE_FOLDER") or "_已废弃_源刷新"
)

_MIGRATION_DONE = False


def ensure_runtime_layout(*, quiet: bool = False) -> None:
    """Create data dirs and optionally migrate legacy root-level local files once."""
    global _MIGRATION_DONE
    if _MIGRATION_DONE:
        return
    _MIGRATION_DONE = True
    os.makedirs(os.path.join(DATA_DIR, "core"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "tools"), exist_ok=True)
    if AUTO_MIGRATE_DATA_DIR:
        messages = migrate_legacy_local_files(DATA_DIR)
        if messages and not quiet:
            print("📁 本地数据目录迁移:")
            for msg in messages:
                print(f"   - {msg}")
    leftover = leftover_legacy_hints(DATA_DIR)
    if leftover and not quiet:
        print("💡 本地数据目录提示:")
        for msg in leftover:
            print(f"   - {msg}")


def validate(
    *,
    require_scan_source: bool = True,
    require_llm: bool = True,
    require_target: bool = True,
) -> None:
    """Raise ValueError when required settings are missing."""
    ensure_runtime_layout()
    missing = []
    if not FEISHU_APP_ID:
        missing.append("FEISHU_APP_ID")
    if not FEISHU_APP_SECRET:
        missing.append("FEISHU_APP_SECRET")
    if not SPACE_ID:
        missing.append("SPACE_ID")
    if require_llm and not LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if require_scan_source and not SCAN_ROOT_TOKEN and not SCAN_FOLDER_NAME:
        has_registry = bool(SCAN_FOLDERS_FILE and os.path.isfile(SCAN_FOLDERS_FILE))
        if not has_registry:
            missing.append(
                "SCAN_ROOT_TOKEN / SCAN_FOLDER_NAME / scan_folders.json "
                f"(SCAN_FOLDERS_FILE={SCAN_FOLDERS_FILE})"
            )
    if require_target and not TARGET_PARENT_TOKEN and not TARGET_ROOT_NAME:
        missing.append("TARGET_PARENT_TOKEN or TARGET_ROOT_NAME")

    if missing:
        raise ValueError(
            "Missing required configuration: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill in values."
        )
