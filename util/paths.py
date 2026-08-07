# -*- coding: utf-8 -*-
"""Project data directory helpers (local runtime state under data/)."""

from __future__ import annotations

import os
import shutil
from typing import Iterable, List, Optional, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Legacy root-level files → new relative locations under DATA_DIR
_LEGACY_MOVES: Tuple[Tuple[str, str], ...] = (
    ("scan_snapshot.db", "core/scan_snapshot.db"),
    ("classify_cache.db", "core/classify_cache.db"),
    ("processing_progress.json", "core/processing_progress.json"),
    ("wiki_scan_cache.db", "core/wiki_scan_cache.db"),
    ("tool_ops.db", "tools/tool_ops.db"),
    ("metadata_bitable_index.db", "tools/metadata_bitable_index.db"),
    ("display_title_bitable_index.db", "tools/display_title_bitable_index.db"),
    ("enrichment_backfill_index.db", "tools/enrichment_backfill_index.db"),
    # Local-only shared_copy_state (UNC/shared paths are never auto-moved)
    ("shared_copy_state.db", "core/shared_copy_state.db"),
)


def project_root() -> str:
    return _PROJECT_ROOT


def default_data_dir() -> str:
    return os.path.join(_PROJECT_ROOT, "data")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def is_absolute_or_unc(path: str) -> bool:
    if not path:
        return False
    if path.startswith("\\\\") or path.startswith("//"):
        return True
    return os.path.isabs(path)


def resolve_under_data(data_dir: str, *parts: str) -> str:
    """Join under data_dir; create parent dirs."""
    path = os.path.join(data_dir, *parts)
    parent = os.path.dirname(path)
    if parent:
        ensure_dir(parent)
    return path


# Bare filenames from older .env → data/ layout (UNC/abs paths never remapped)
_LEGACY_BASENAME_TO_REL = {src: dest for src, dest in _LEGACY_MOVES}


def resolve_configurable_path(
    configured: Optional[str],
    *,
    data_dir: str,
    default_relative: str,
) -> str:
    """
    If configured is absolute/UNC, use as-is.
    Bare legacy basenames (e.g. scan_snapshot.db) map under data_dir.
    Other relative paths stay relative for back-compat.
    Empty → default_relative under data_dir.
    """
    raw = (configured or "").strip()
    if not raw:
        return resolve_under_data(
            data_dir, *default_relative.replace("\\", "/").split("/")
        )
    if is_absolute_or_unc(raw):
        return raw
    normalized = raw.replace("\\", "/")
    base = os.path.basename(normalized)
    if normalized == base and base in _LEGACY_BASENAME_TO_REL:
        return resolve_under_data(
            data_dir, *_LEGACY_BASENAME_TO_REL[base].split("/")
        )
    return raw


def leftover_legacy_hints(
    data_dir: str,
    *,
    project_root_dir: Optional[str] = None,
) -> List[str]:
    """Warn when root still has legacy DBs that were not migrated."""
    root = project_root_dir or _PROJECT_ROOT
    hints: List[str] = []
    for src_name, dest_rel in _LEGACY_MOVES:
        src = os.path.join(root, src_name)
        if not os.path.isfile(src):
            continue
        hints.append(
            f"根目录仍有 {src_name}；可删或移到 data/{dest_rel} "
            f"（DATA_DIR={data_dir}，AUTO_MIGRATE_DATA_DIR=true 可自动迁移）"
        )
    return hints

def migrate_legacy_local_files(
    data_dir: str,
    *,
    project_root_dir: Optional[str] = None,
    moves: Optional[Iterable[Tuple[str, str]]] = None,
) -> List[str]:
    """
    Move legacy root-level local DBs into data/. Skip if destination exists.
    Returns human-readable messages (moved / skipped).
    """
    root = project_root_dir or _PROJECT_ROOT
    ensure_dir(data_dir)
    ensure_dir(os.path.join(data_dir, "core"))
    ensure_dir(os.path.join(data_dir, "tools"))
    messages: List[str] = []
    for src_name, dest_rel in moves or _LEGACY_MOVES:
        src = os.path.join(root, src_name)
        dest = resolve_under_data(data_dir, *dest_rel.split("/"))
        if not os.path.isfile(src):
            continue
        if os.path.abspath(src) == os.path.abspath(dest):
            continue
        if os.path.exists(dest):
            messages.append(f"保留旧文件 {src_name}（目标已存在: {dest_rel}）")
            continue
        try:
            shutil.move(src, dest)
            # Move sqlite sidecars if present
            for suffix in ("-wal", "-shm", "-journal"):
                side = src + suffix
                if os.path.isfile(side):
                    shutil.move(side, dest + suffix)
            messages.append(f"已迁移 {src_name} → data/{dest_rel}")
        except OSError as exc:
            messages.append(f"迁移失败 {src_name}: {exc}")
    return messages


__all__ = [
    "project_root",
    "default_data_dir",
    "ensure_dir",
    "is_absolute_or_unc",
    "resolve_under_data",
    "resolve_configurable_path",
    "migrate_legacy_local_files",
    "leftover_legacy_hints",
]