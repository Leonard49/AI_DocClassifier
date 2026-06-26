"""Application configuration loaded from environment variables."""

import os
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


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

# Destination folder for classified copies
TARGET_PARENT_TOKEN = _env("TARGET_PARENT_TOKEN")
TARGET_ROOT_NAME = _env("TARGET_ROOT_NAME")
FALLBACK_PARENT_TOKEN = _env("FALLBACK_PARENT_TOKEN")

# Processing behavior
USE_CACHE = _env_bool("USE_CACHE", False)
MAX_DOCUMENTS = _env_int("MAX_DOCUMENTS", 0) or None
ENABLE_TAG_ADD = _env_bool("ENABLE_TAG_ADD", True)
SAVE_PROGRESS = _env_bool("SAVE_PROGRESS", True)
FORCE_RESCAN = _env_bool("FORCE_RESCAN", False)
ENABLE_SCAN_SNAPSHOT = _env_bool("ENABLE_SCAN_SNAPSHOT", True)
SCAN_SNAPSHOT_DB = _env("SCAN_SNAPSHOT_DB") or "scan_snapshot.db"
FULL_SCAN_CALIBRATION_DAYS = _env_int("FULL_SCAN_CALIBRATION_DAYS", 7)
SAVE_RUN_LOG = _env_bool("SAVE_RUN_LOG", True)
LOG_DIR = _env("LOG_DIR", "logs") or "logs"

# Performance tuning
READ_WORKERS = _env_int("READ_WORKERS", 2)
CLASSIFY_WORKERS = _env_int("CLASSIFY_WORKERS", 4)
CLASSIFY_MAX_CHARS = _env_int("CLASSIFY_MAX_CHARS", 3000)
USE_CLASSIFY_CACHE = _env_bool("USE_CLASSIFY_CACHE", True)
CLASSIFY_VERBOSE = _env_bool("CLASSIFY_VERBOSE", False)
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 6)
LLM_REQUEST_TIMEOUT = _env_float("LLM_REQUEST_TIMEOUT", 120.0)
PROGRESS_INTERVAL = _env_int("PROGRESS_INTERVAL", 10)

# LLM (OpenAI-compatible gateway)
LLM_API_KEY = _env("LLM_API_KEY") or _env("QWEN_API_KEY", "")
LLM_BASE_URL = _env("LLM_BASE_URL") or "https://qlitellm.phicotek.com/v1"
LLM_MODEL = _env("LLM_MODEL") or "deepseek-v4-flash"

# Multi-worker parallel processing (shared folder on network drive recommended)
ENABLE_SHARED_DEDUP = _env_bool("ENABLE_SHARED_DEDUP", True)
SHARED_STATE_DB = _env("SHARED_STATE_DB") or "shared_copy_state.db"
WORKER_ID = _env("WORKER_ID")
CLAIM_TIMEOUT_MINUTES = _env_int("CLAIM_TIMEOUT_MINUTES", 30)


def validate() -> None:
    """Raise ValueError when required settings are missing."""
    missing = []
    if not FEISHU_APP_ID:
        missing.append("FEISHU_APP_ID")
    if not FEISHU_APP_SECRET:
        missing.append("FEISHU_APP_SECRET")
    if not SPACE_ID:
        missing.append("SPACE_ID")
    if not LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if not SCAN_ROOT_TOKEN and not SCAN_FOLDER_NAME:
        missing.append("SCAN_ROOT_TOKEN or SCAN_FOLDER_NAME")
    if not TARGET_PARENT_TOKEN and not TARGET_ROOT_NAME:
        missing.append("TARGET_PARENT_TOKEN or TARGET_ROOT_NAME")

    if missing:
        raise ValueError(
            "Missing required configuration: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill in values."
        )
