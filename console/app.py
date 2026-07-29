# -*- coding: utf-8 -*-
"""Local web console for AI_DocClassifier."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from console.env_io import (  # noqa: E402
    env_path,
    mask_secrets,
    read_env_map,
    schema_for_api,
    write_env_updates,
)
from console.jobs import JOB_MANAGER  # noqa: E402
from state.scan_folders import (  # noqa: E402
    default_scan_folders_path,
    load_scan_folders,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="AI DocClassifier Console", version="1.0.0")


class EnvSaveRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)
    reveal_secrets: bool = False


class FoldersSaveRequest(BaseModel):
    notes: Optional[str] = None
    folders: List[Dict[str, Any]]


class JobStartRequest(BaseModel):
    job_id: str
    folder_id: Optional[str] = None
    extra_args: Optional[List[str]] = None


def _scan_folders_path() -> str:
    values = read_env_map()
    path = (values.get("SCAN_FOLDERS_FILE") or "").strip() or default_scan_folders_path()
    if not os.path.isabs(path):
        path = os.path.join(_ROOT, path)
    return path


def _git_branch() -> str:
    try:
        out = subprocess.check_output(
            ["git", "branch", "--show-current"],
            cwd=_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        return out.strip() or "(unknown)"
    except Exception:
        return "(unknown)"


def _validate_config() -> Dict[str, Any]:
    # Reload config module so .env edits take effect after save + restart note
    try:
        import config as cfg

        importlib.reload(cfg)
        cfg.validate(require_scan_source=False)
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/health")
def health():
    return {"ok": True, "root": _ROOT}


@app.get("/api/status")
def status():
    values = read_env_map()
    validation = _validate_config()
    return {
        "branch": _git_branch(),
        "worker_id": values.get("WORKER_ID") or "",
        "env_path": env_path(),
        "scan_folders_path": _scan_folders_path(),
        "validation": validation,
        "job": JOB_MANAGER.status(),
    }


@app.get("/api/config/schema")
def config_schema():
    return {"schema": schema_for_api()}


@app.get("/api/config")
def get_config(reveal: bool = False):
    values = read_env_map()
    return {
        "path": env_path(),
        "exists": os.path.isfile(env_path()),
        "values": mask_secrets(values, reveal=reveal),
        "schema": schema_for_api(),
    }


@app.put("/api/config")
def put_config(body: EnvSaveRequest):
    # Coerce values to strings for .env
    updates = {k: "" if v is None else str(v) for k, v in body.values.items()}
    # Normalize bools
    for k, v in list(updates.items()):
        if v.lower() in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            if v.lower() in {"1", "yes", "on"}:
                updates[k] = "true"
            elif v.lower() in {"0", "no", "off"}:
                updates[k] = "false"
            else:
                updates[k] = v.lower()
    path = write_env_updates(updates)
    return {
        "ok": True,
        "path": path,
        "note": "已写入 .env。正在运行的任务仍使用旧环境；新任务会读到新配置。",
        "validation": _validate_config(),
    }


@app.get("/api/folders")
def get_folders():
    path = _scan_folders_path()
    if not os.path.isfile(path):
        return {"path": path, "version": 1, "notes": "", "folders": []}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "path": path,
        "version": data.get("version", 1),
        "notes": data.get("notes") or "",
        "folders": data.get("folders") or [],
    }


@app.put("/api/folders")
def put_folders(body: FoldersSaveRequest):
    path = _scan_folders_path()
    existing: Dict[str, Any] = {"version": 1, "notes": "", "folders": []}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing["notes"] = body.notes if body.notes is not None else existing.get("notes", "")
    # Preserve unknown fields on each folder by merging on id
    by_id = {f.get("id"): f for f in (existing.get("folders") or []) if f.get("id")}
    merged = []
    for item in body.folders:
        fid = item.get("id")
        base = dict(by_id.get(fid) or {})
        for k in ("id", "name", "token", "assignee", "enabled", "priority", "notes"):
            if k in item:
                base[k] = item[k]
        if "enabled" in base:
            base["enabled"] = bool(base["enabled"])
        if "priority" in base:
            try:
                base["priority"] = int(base["priority"])
            except Exception:
                base["priority"] = 0
        merged.append(base)
    existing["folders"] = merged
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
        f.write("\n")
    # sanity load
    try:
        load_scan_folders(path)
    except Exception as exc:
        raise HTTPException(400, f"清单校验失败: {exc}") from exc
    return {"ok": True, "path": path, "count": len(merged)}


@app.get("/api/jobs/catalog")
def jobs_catalog():
    return {
        "jobs": JOB_MANAGER.catalog()
        + [
            {
                "id": "classify_folder",
                "title": "分类复制（指定 folder id）",
                "category": "classify",
                "description": "需要 folder_id",
                "needs_folder": True,
            },
            {
                "id": "metadata_folder",
                "title": "元数据分表（指定 folder id）",
                "category": "metadata",
                "description": "需要 folder_id",
                "needs_folder": True,
            },
        ]
    }


@app.get("/api/jobs/status")
def jobs_status():
    return JOB_MANAGER.status()


@app.post("/api/jobs/start")
def jobs_start(body: JobStartRequest):
    try:
        return JOB_MANAGER.start(
            body.job_id,
            folder_id=body.folder_id,
            extra_args=body.extra_args,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/jobs/stop")
def jobs_stop():
    return JOB_MANAGER.stop()


@app.get("/api/jobs/logs")
def jobs_logs(offset: int = 0):
    return JOB_MANAGER.logs_since(offset)


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import uvicorn

    host = os.environ.get("CONSOLE_HOST", "127.0.0.1")
    port = int(os.environ.get("CONSOLE_PORT", "8787"))
    print(f"AI DocClassifier Console → http://{host}:{port}")
    uvicorn.run(
        "console.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
