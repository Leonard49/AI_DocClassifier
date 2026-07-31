# -*- coding: utf-8 -*-
"""Background job runner for console (subprocess + ring buffer logs)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class JobSpec:
    id: str
    title: str
    category: str
    description: str
    argv: List[str]


JOB_CATALOG: List[JobSpec] = [
    JobSpec(
        "list_folders",
        "列出清单分工",
        "classify",
        "python main.py --list-folders",
        [sys.executable, "main.py", "--list-folders"],
    ),
    JobSpec(
        "classify_assigned",
        "分类复制（我的文件夹）",
        "classify",
        "python main.py --all-assigned",
        [sys.executable, "main.py", "--all-assigned"],
    ),
    JobSpec(
        "classify_all_enabled",
        "分类复制（清单全部 enabled）",
        "classify",
        "python main.py --all-enabled",
        [sys.executable, "main.py", "--all-enabled"],
    ),
    JobSpec(
        "metadata_per_token",
        "元数据 → 按 token 分表",
        "metadata",
        "export_doc_metadata_bitable --all-assigned --mode per-token",
        [
            sys.executable,
            "-m",
            "tools.export_doc_metadata_bitable",
            "--all-assigned",
            "--mode",
            "per-token",
        ],
    ),
    JobSpec(
        "metadata_both",
        "元数据 → 汇总+分表 (both)",
        "metadata",
        "export_doc_metadata_bitable --all-assigned --mode both",
        [
            sys.executable,
            "-m",
            "tools.export_doc_metadata_bitable",
            "--all-assigned",
            "--mode",
            "both",
        ],
    ),
    JobSpec(
        "metadata_aggregated",
        "元数据 → 仅汇总表（全清单）",
        "metadata",
        "export_doc_metadata_bitable --all-enabled --mode aggregated",
        [
            sys.executable,
            "-m",
            "tools.export_doc_metadata_bitable",
            "--all-enabled",
            "--mode",
            "aggregated",
        ],
    ),
    JobSpec(
        "metadata_dry",
        "元数据试跑（20 篇 dry-run）",
        "metadata",
        "dry-run --max-documents 20",
        [
            sys.executable,
            "-m",
            "tools.export_doc_metadata_bitable",
            "--all-assigned",
            "--mode",
            "per-token",
            "--dry-run",
            "--max-documents",
            "20",
        ],
    ),
    JobSpec(
        "reclassify_others",
        "Others 纠偏 move",
        "tools",
        "tools.reclassify_others_move",
        [sys.executable, "-m", "tools.reclassify_others_move"],
    ),
    JobSpec(
        "others_theme",
        "Others 主题归档",
        "tools",
        "tools.others_theme_classify_move",
        [sys.executable, "-m", "tools.others_theme_classify_move"],
    ),
    JobSpec(
        "retry_attachments",
        "附件提取失败重试",
        "tools",
        "tools.retry_attachment_extract",
        [sys.executable, "-m", "tools.retry_attachment_extract"],
    ),
    JobSpec(
        "enrich_backfill",
        "副本增强回填（元数据表+附件分隔）",
        "tools",
        "tools.enrich_copied_docs",
        [sys.executable, "-m", "tools.enrich_copied_docs"],
    ),
    JobSpec(
        "enrich_backfill_dry",
        "副本增强回填试跑（20 篇 dry-run）",
        "tools",
        "enrich_copied_docs --dry-run --limit 20",
        [
            sys.executable,
            "-m",
            "tools.enrich_copied_docs",
            "--dry-run",
            "--limit",
            "20",
        ],
    ),
]


@dataclass
class JobState:
    run_id: str
    job_id: str
    title: str
    argv: List[str]
    status: str = "running"  # running|succeeded|failed|stopped
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=8000))
    proc: Optional[subprocess.Popen] = None


class JobManager:
    def __init__(self, cwd: str = _ROOT):
        self.cwd = cwd
        self._lock = threading.Lock()
        self._current: Optional[JobState] = None

    def catalog(self) -> List[dict]:
        return [
            {
                "id": j.id,
                "title": j.title,
                "category": j.category,
                "description": j.description,
            }
            for j in JOB_CATALOG
        ]

    def status(self) -> dict:
        with self._lock:
            cur = self._current
            if not cur:
                return {"running": False, "job": None}
            return {
                "running": cur.status == "running",
                "job": {
                    "run_id": cur.run_id,
                    "job_id": cur.job_id,
                    "title": cur.title,
                    "status": cur.status,
                    "started_at": cur.started_at,
                    "finished_at": cur.finished_at,
                    "exit_code": cur.exit_code,
                    "log_lines": len(cur.logs),
                },
            }

    def start(
        self,
        job_id: str,
        *,
        extra_args: Optional[List[str]] = None,
        folder_id: Optional[str] = None,
    ) -> dict:
        spec = next((j for j in JOB_CATALOG if j.id == job_id), None)
        if not spec:
            if job_id == "classify_folder":
                if not folder_id:
                    raise ValueError("classify_folder 需要 folder_id")
                argv = [sys.executable, "main.py", "--folder", folder_id]
                title = f"分类复制 --folder {folder_id}"
            elif job_id == "metadata_folder":
                if not folder_id:
                    raise ValueError("metadata_folder 需要 folder_id")
                argv = [
                    sys.executable,
                    "-m",
                    "tools.export_doc_metadata_bitable",
                    "--folder",
                    folder_id,
                    "--mode",
                    "per-token",
                ]
                title = f"元数据分表 --folder {folder_id}"
            else:
                raise ValueError(f"未知任务: {job_id}")
        else:
            argv = list(spec.argv)
            title = spec.title

        if extra_args:
            argv.extend(extra_args)

        with self._lock:
            if self._current and self._current.status == "running":
                raise RuntimeError("已有任务在运行，请先停止")
            run_id = uuid.uuid4().hex[:10]
            state = JobState(run_id=run_id, job_id=job_id, title=title, argv=argv)
            self._current = state

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        proc = subprocess.Popen(
            argv,
            cwd=self.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        state.proc = proc
        state.logs.append(f"$ {' '.join(argv)}\n")

        t = threading.Thread(target=self._pump, args=(state,), daemon=True)
        t.start()
        return self.status()

    def _pump(self, state: JobState) -> None:
        assert state.proc is not None
        try:
            assert state.proc.stdout is not None
            for line in state.proc.stdout:
                state.logs.append(line)
            code = state.proc.wait()
            state.exit_code = code
            state.status = "succeeded" if code == 0 else "failed"
        except Exception as exc:
            state.logs.append(f"\n[console] pump error: {exc}\n")
            state.status = "failed"
            state.exit_code = -1
        finally:
            state.finished_at = time.time()

    def stop(self) -> dict:
        with self._lock:
            cur = self._current
            if not cur or cur.status != "running" or not cur.proc:
                return self.status()
            proc = cur.proc
        try:
            if sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception as exc:
            cur.logs.append(f"\n[console] stop error: {exc}\n")
            try:
                proc.kill()
            except Exception:
                pass
        cur.status = "stopped"
        cur.finished_at = time.time()
        return self.status()

    def logs_since(self, offset: int = 0) -> dict:
        with self._lock:
            cur = self._current
            if not cur:
                return {"offset": 0, "lines": [], "status": None}
            lines = list(cur.logs)
            chunk = lines[offset:]
            return {
                "offset": offset + len(chunk),
                "total": len(lines),
                "lines": chunk,
                "status": cur.status,
                "run_id": cur.run_id,
                "exit_code": cur.exit_code,
            }


JOB_MANAGER = JobManager()
