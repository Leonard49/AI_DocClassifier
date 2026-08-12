# -*- coding: utf-8 -*-
"""Read/write .env while preserving unknown keys and blank lines where possible."""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENV_PATH = os.path.join(_ROOT, ".env")
DEFAULT_EXAMPLE_PATH = os.path.join(_ROOT, ".env.example")

SECRET_KEYS = {
    "FEISHU_APP_SECRET",
    "LLM_API_KEY",
    "QWEN_API_KEY",
}

# UI schema: (key, label, group, type) type in {str,bool,int,float,path}
CONFIG_SCHEMA: List[Tuple[str, str, str, str]] = [
    ("WORKER_ID", "Worker ID", "identity", "str"),
    ("FEISHU_APP_ID", "飞书 App ID", "feishu", "str"),
    ("FEISHU_APP_SECRET", "飞书 App Secret", "feishu", "secret"),
    ("SPACE_ID", "知识空间 SPACE_ID", "feishu", "str"),
    ("TARGET_PARENT_TOKEN", "目标目录 token", "feishu", "str"),
    ("TARGET_ROOT_NAME", "目标目录名称（可选）", "feishu", "str"),
    ("SCAN_FOLDERS_FILE", "清单文件路径", "scan", "path"),
    ("SCAN_ROOT_TOKEN", "单次扫描 token（可选）", "scan", "str"),
    ("LLM_API_KEY", "LLM API Key", "llm", "secret"),
    ("LLM_MODEL", "LLM 模型", "llm", "str"),
    ("LLM_BASE_URL", "LLM 网关", "llm", "str"),
    ("ENABLE_SHARED_DEDUP", "多人共享去重", "parallel", "bool"),
    ("SHARED_STATE_DB", "共享去重库路径", "parallel", "path"),
    ("ENABLE_CROSS_PROCESS_FEISHU_LIMIT", "跨进程飞书限速", "parallel", "bool"),
    ("FEISHU_RATE_LIMIT_DB", "飞书限速库路径", "parallel", "path"),
    ("FEISHU_GLOBAL_MAX_PER_SECOND", "全局飞书 QPS", "parallel", "float"),
    ("FEISHU_LOCAL_MAX_PER_SECOND", "本机飞书 QPS", "parallel", "float"),
    ("ENABLE_ATTACHMENT_EXTRACT", "附件提取", "classify", "bool"),
    ("ENABLE_METADATA_TABLE", "复制后贴元数据表", "classify", "bool"),
    ("ENABLE_ATTACHMENT_SEPARATOR", "附件提取分隔符", "classify", "bool"),
    ("METADATA_TABLE_FETCH_AUTHOR", "贴表时解析作者", "classify", "bool"),
    ("ENABLE_TAG_ADD", "源文档打标签块", "classify", "bool"),
    ("ENABLE_SCAN_SNAPSHOT", "扫描快照增量", "classify", "bool"),
    ("FORCE_RESCAN", "强制全量重扫", "classify", "bool"),
    ("ENABLE_FOLDER_ROLLOVER", "超限自动分卷", "classify", "bool"),
    ("OTHERS_RATIO_FAIL_THRESHOLD", "Others 告警阈值", "classify", "float"),
    ("MAX_DOCUMENTS", "最多处理文档数(0=不限)", "classify", "int"),
    ("READ_WORKERS", "读取并发", "perf", "int"),
    ("CLASSIFY_WORKERS", "分类并发", "perf", "int"),
    ("CLASSIFY_MAX_CHARS", "分类正文上限", "perf", "int"),
    ("USE_CLASSIFY_CACHE", "分类缓存", "perf", "bool"),
    ("DATA_DIR", "本地数据目录", "perf", "path"),
    ("AUTO_MIGRATE_DATA_DIR", "自动迁移根目录旧库到 data/", "perf", "bool"),
    ("METADATA_BITABLE_MODE", "多维表格模式", "metadata", "str"),
    ("METADATA_BITABLE_TITLE", "汇总表标题", "metadata", "str"),
    ("METADATA_BITABLE_APP_TOKEN", "已有汇总 app_token", "metadata", "str"),
    ("METADATA_BITABLE_PER_TOKEN_TITLE_TMPL", "分表标题模板", "metadata", "str"),
    ("METADATA_BITABLE_PER_TOKEN_PARENT", "分表挂载位置", "metadata", "str"),
    ("METADATA_USE_LLM_DOC_TYPE", "文档类型用 LLM", "metadata", "bool"),
    ("METADATA_BITABLE_SKIP_EXISTING", "元数据表已写跳过", "metadata", "bool"),
    ("TOOL_DOC_SCOPE", "工具文档范围(target/scan)", "metadata", "str"),
    ("TOOL_OPS_DB", "工具操作账本路径", "metadata", "path"),
    ("DISPLAY_TITLE_BITABLE_MODE", "展示标题表模式", "metadata", "str"),
    ("DISPLAY_TITLE_BITABLE_TITLE", "展示标题汇总表名", "metadata", "str"),
    ("DISPLAY_TITLE_BITABLE_APP_TOKEN", "已有展示标题 app_token", "metadata", "str"),
    ("DISPLAY_TITLE_USE_LLM_PURPOSE", "展示标题文章主题用 LLM", "metadata", "bool"),
    ("DISPLAY_TITLE_SKIP_EXISTING", "展示标题多维表已写跳过", "metadata", "bool"),
    ("DISPLAY_TITLE_RENAME_SKIP_EXISTING", "TARGET 改标题已写跳过", "metadata", "bool"),
    ("REFRESH_TARGET_SKIP_UNCHANGED", "源刷新仅处理有变更", "classify", "bool"),
    ("REFRESH_TARGET_OBSOLETE_FOLDER", "源刷新废弃目录名", "classify", "str"),
    ("ENRICHMENT_SKIP_EXISTING", "副本增强已写跳过", "classify", "bool"),
]

GROUP_LABELS = {
    "identity": "身份",
    "feishu": "飞书",
    "scan": "扫描清单",
    "llm": "LLM",
    "parallel": "多人并行",
    "classify": "分类复制",
    "metadata": "元数据多维表格",
    "perf": "性能",
}


def env_path() -> str:
    return DEFAULT_ENV_PATH


def _parse_line(line: str) -> Tuple[Optional[str], Optional[str], str]:
    """Return (key, value, kind) where kind is comment|blank|kv|other."""
    raw = line.rstrip("\n\r")
    stripped = raw.strip()
    if not stripped:
        return None, None, "blank"
    if stripped.startswith("#"):
        return None, None, "comment"
    if "=" not in stripped:
        return None, None, "other"
    key, _, val = stripped.partition("=")
    key = key.strip()
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    return key, val, "kv"


def read_env_map(path: Optional[str] = None) -> Dict[str, str]:
    path = path or env_path()
    result: Dict[str, str] = {}
    if not os.path.isfile(path):
        # Seed from example keys if .env missing
        example = DEFAULT_EXAMPLE_PATH
        if os.path.isfile(example):
            path = example
        else:
            return result
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            key, val, kind = _parse_line(line)
            if kind == "kv" and key:
                result[key] = val if val is not None else ""
    return result


def mask_secrets(values: Dict[str, str], *, reveal: bool = False) -> Dict[str, str]:
    out = dict(values)
    if reveal:
        return out
    for k in SECRET_KEYS:
        if k in out and out[k]:
            out[k] = "••••••••"
    return out


def write_env_updates(updates: Dict[str, str], path: Optional[str] = None) -> str:
    """
    Merge updates into .env. Preserve comments/order for existing keys;
    append new keys at end. Secret placeholders (••••) are ignored.
    """
    path = path or env_path()
    lines: List[str] = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
    elif os.path.isfile(DEFAULT_EXAMPLE_PATH):
        with open(DEFAULT_EXAMPLE_PATH, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()

    clean_updates: Dict[str, str] = {}
    for k, v in updates.items():
        if v is None:
            continue
        s = str(v)
        if k in SECRET_KEYS and (s.startswith("••") or s == ""):
            continue
        clean_updates[k] = s

    seen = set()
    new_lines: List[str] = []
    for line in lines:
        key, _val, kind = _parse_line(line)
        if kind == "kv" and key in clean_updates:
            new_lines.append(f"{key}={clean_updates[key]}\n")
            seen.add(key)
        else:
            new_lines.append(line if line.endswith("\n") else line + "\n")

    missing = [k for k in clean_updates if k not in seen]
    if missing:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        if new_lines and new_lines[-1].strip():
            new_lines.append("\n")
        new_lines.append("# --- updated by console ---\n")
        for k in missing:
            new_lines.append(f"{k}={clean_updates[k]}\n")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(new_lines)
    return path


def schema_for_api() -> List[dict]:
    return [
        {
            "key": key,
            "label": label,
            "group": group,
            "group_label": GROUP_LABELS.get(group, group),
            "type": typ,
            "secret": typ == "secret" or key in SECRET_KEYS,
        }
        for key, label, group, typ in CONFIG_SCHEMA
    ]
