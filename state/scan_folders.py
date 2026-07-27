# -*- coding: utf-8 -*-
"""Load and filter the shared scan-folder token registry."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ScanFolder:
    id: str
    name: str
    token: str
    assignee: str = ""
    assignees: tuple = ()
    enabled: bool = True
    priority: int = 100
    notes: str = ""
    target_parent_token: str = ""

    def owners(self) -> List[str]:
        owners: List[str] = []
        if self.assignee and self.assignee.strip():
            owners.append(self.assignee.strip())
        for a in self.assignees:
            if a and str(a).strip():
                owners.append(str(a).strip())
        seen = set()
        out: List[str] = []
        for o in owners:
            key = o.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(o)
        return out

    def is_assigned_to(self, worker_id: Optional[str]) -> bool:
        if not worker_id or not worker_id.strip():
            return False
        wid = worker_id.strip().lower()
        return any(o.lower() == wid for o in self.owners())


def default_scan_folders_path() -> str:
    return os.getenv("SCAN_FOLDERS_FILE") or "scan_folders.json"


def load_scan_folders(path: Optional[str] = None) -> List[ScanFolder]:
    """Load registry from JSON. Missing file → empty list."""
    path = path or default_scan_folders_path()
    if not path or not os.path.isfile(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_folders = data.get("folders") if isinstance(data, dict) else data
    if not isinstance(raw_folders, list):
        raise ValueError(f"scan folders file must contain a 'folders' list: {path}")

    folders: List[ScanFolder] = []
    seen_ids = set()
    for i, item in enumerate(raw_folders):
        if not isinstance(item, dict):
            raise ValueError(f"folders[{i}] must be an object in {path}")
        fid = str(item.get("id") or "").strip()
        token = str(item.get("token") or "").strip()
        name = str(item.get("name") or fid or token).strip()
        if not fid:
            raise ValueError(f"folders[{i}] missing id in {path}")
        if not token:
            raise ValueError(f"folders[{i}] ({fid}) missing token in {path}")
        if fid in seen_ids:
            raise ValueError(f"duplicate folder id '{fid}' in {path}")
        seen_ids.add(fid)

        assignees_raw = item.get("assignees") or []
        if isinstance(assignees_raw, str):
            assignees_raw = [assignees_raw]
        folders.append(
            ScanFolder(
                id=fid,
                name=name,
                token=token,
                assignee=str(item.get("assignee") or "").strip(),
                assignees=tuple(assignees_raw),
                enabled=bool(item.get("enabled", True)),
                priority=int(item.get("priority", 100)),
                notes=str(item.get("notes") or ""),
                target_parent_token=str(item.get("target_parent_token") or "").strip(),
            )
        )

    folders.sort(key=lambda x: (x.priority, x.id))
    return folders


def filter_folders(
    folders: Sequence[ScanFolder],
    *,
    ids: Optional[Iterable[str]] = None,
    worker_id: Optional[str] = None,
    assigned_only: bool = False,
    enabled_only: bool = True,
) -> List[ScanFolder]:
    out = list(folders)
    if enabled_only:
        out = [f for f in out if f.enabled]
    if ids is not None:
        want = {str(i).strip().lower() for i in ids if str(i).strip()}
        matched = [f for f in out if f.id.lower() in want]
        all_ids = {f.id.lower() for f in folders}
        unknown = want - all_ids
        if unknown:
            raise ValueError("未知文件夹 id: " + ", ".join(sorted(unknown)))
        out = matched
    if assigned_only:
        out = [f for f in out if f.is_assigned_to(worker_id)]
    return out


def format_folder_table(
    folders: Sequence[ScanFolder], worker_id: Optional[str] = None
) -> str:
    if not folders:
        return "(空)"
    lines = [
        f"{'id':<24} {'assignee':<16} {'enabled':<8} {'token':<28} name",
        "-" * 100,
    ]
    for f in folders:
        owners = ",".join(f.owners()) or "-"
        mine = " *" if f.is_assigned_to(worker_id) else ""
        lines.append(
            f"{f.id:<24} {owners:<16} {str(f.enabled):<8} {f.token:<28} {f.name}{mine}"
        )
    if worker_id:
        lines.append(f"\n* = 分配给当前 WORKER_ID ({worker_id})")
    return "\n".join(lines)


__all__ = [
    "ScanFolder",
    "default_scan_folders_path",
    "load_scan_folders",
    "filter_folders",
    "format_folder_table",
]
