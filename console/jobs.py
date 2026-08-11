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
    scope: str = ""  # target | scan | ""
    dry_run: bool = False
    danger: bool = False
    needs_folder: bool = False
    env_overrides: Dict[str, str] = field(default_factory=dict)


# Filter chip order for console "全部" grouping
JOB_CATEGORY_META: List[Dict[str, str]] = [
    {
        "id": "core",
        "label": "主流程",
        "hint": "日常点「增量更新」；只有要强制重扫源目录时才点「全量重扫」",
    },
    {"id": "enrich", "label": "副本增强", "hint": "只处理 TARGET 已复制文档（贴表 / 附件分隔）"},
    {
        "id": "bitable_meta",
        "label": "文档元数据表",
        "hint": "文档元数据 → 飞书多维表格（默认 TARGET）",
    },
    {
        "id": "bitable_title",
        "label": "归纳新标题",
        "hint": "展示标题 → 多维表格（TARGET，不改 wiki 原标题）",
    },
    {"id": "ops", "label": "运维纠偏", "hint": "Others 纠偏 / 主题归档 / 附件重试"},
]


JOB_CATALOG: List[JobSpec] = [
    # --- core ---
    JobSpec(
        "list_folders",
        "列出清单分工",
        "core",
        "先看清 assignee / enabled，再决定跑哪些夹",
        [sys.executable, "main.py", "--list-folders"],
    ),
    JobSpec(
        "classify_assigned",
        "【增量更新】分类复制 · 我的文件夹",
        "core",
        "日常首选：快照跳过已成功叶子；共享库已 copied 的不重复复制",
        [sys.executable, "main.py", "--all-assigned"],
        scope="scan",
    ),
    JobSpec(
        "classify_assigned_full",
        "【全量重扫】分类复制 · 我的文件夹",
        "core",
        "FORCE_RESCAN：忽略本机断点并全量校准扫描；已 copied 的仍跳过复制",
        [sys.executable, "main.py", "--all-assigned"],
        scope="scan",
        danger=True,
        env_overrides={"FORCE_RESCAN": "true"},
    ),
    JobSpec(
        "classify_all_enabled",
        "【增量更新】分类复制 · 清单全部 enabled",
        "core",
        "会跑清单内全部 enabled 文件夹，慎用（仍走增量跳过逻辑）",
        [sys.executable, "main.py", "--all-enabled"],
        scope="scan",
        danger=True,
    ),
    JobSpec(
        "classify_all_enabled_full",
        "【全量重扫】分类复制 · 清单全部 enabled",
        "core",
        "FORCE_RESCAN + 全部 enabled，慎用",
        [sys.executable, "main.py", "--all-enabled"],
        scope="scan",
        danger=True,
        env_overrides={"FORCE_RESCAN": "true"},
    ),
    # --- enrich ---
    JobSpec(
        "enrich_backfill",
        "副本增强回填（正式）",
        "enrich",
        "TARGET：贴元数据表 + 附件分隔符（作者/源路径取自源文档）",
        [
            sys.executable,
            "-m",
            "tools.enrich_copied_docs",
            "--scope",
            "target",
        ],
        scope="target",
    ),
    JobSpec(
        "enrich_backfill_force_meta",
        "副本增强 · 强制重贴元数据表",
        "enrich",
        "删除错误旧表后重贴（修正作者/源路径）；需 SHARED_STATE_DB",
        [
            sys.executable,
            "-m",
            "tools.enrich_copied_docs",
            "--scope",
            "target",
            "--force-metadata",
            "--steps",
            "metadata_table",
        ],
        scope="target",
        danger=True,
    ),
    JobSpec(
        "enrich_backfill_dry",
        "副本增强回填（试跑 · 最多 20 篇 · 不写飞书）",
        "enrich",
        "tools.enrich_copied_docs --dry-run --limit 20",
        [
            sys.executable,
            "-m",
            "tools.enrich_copied_docs",
            "--scope",
            "target",
            "--dry-run",
            "--limit",
            "20",
        ],
        scope="target",
        dry_run=True,
    ),
    # --- bitable_meta ---
    JobSpec(
        "metadata_aggregated",
        "文档元数据 → 仅汇总表（TARGET）",
        "bitable_meta",
        "export_doc_metadata_bitable --scope target --mode aggregated",
        [
            sys.executable,
            "-m",
            "tools.export_doc_metadata_bitable",
            "--scope",
            "target",
            "--mode",
            "aggregated",
        ],
        scope="target",
    ),
    JobSpec(
        "metadata_both",
        "文档元数据 → 汇总+分表（TARGET）",
        "bitable_meta",
        "export_doc_metadata_bitable --scope target --mode both",
        [
            sys.executable,
            "-m",
            "tools.export_doc_metadata_bitable",
            "--scope",
            "target",
            "--mode",
            "both",
        ],
        scope="target",
    ),
    JobSpec(
        "metadata_per_token",
        "[扫源] 文档元数据 → 按 token 分表",
        "bitable_meta",
        "扫源清单 --all-assigned --mode per-token（三人并行常用）",
        [
            sys.executable,
            "-m",
            "tools.export_doc_metadata_bitable",
            "--scope",
            "scan",
            "--all-assigned",
            "--mode",
            "per-token",
        ],
        scope="scan",
    ),
    JobSpec(
        "metadata_dry",
        "文档元数据（试跑 · 最多 20 篇 · 不写飞书）",
        "bitable_meta",
        "TARGET aggregated dry-run",
        [
            sys.executable,
            "-m",
            "tools.export_doc_metadata_bitable",
            "--scope",
            "target",
            "--mode",
            "aggregated",
            "--dry-run",
            "--max-documents",
            "20",
        ],
        scope="target",
        dry_run=True,
    ),
    # --- bitable_title ---
    JobSpec(
        "display_title_agg",
        "归纳新标题 → 写入汇总表（TARGET，不改 wiki 原标题）",
        "bitable_title",
        "日期-型号或路径-作用 + Wiki 链接",
        [
            sys.executable,
            "-m",
            "tools.export_display_title_bitable",
            "--scope",
            "target",
        ],
        scope="target",
    ),
    JobSpec(
        "display_title_dry",
        "归纳新标题（试跑 · 最多 20 篇 · 不写飞书）",
        "bitable_title",
        "不改 wiki 原标题",
        [
            sys.executable,
            "-m",
            "tools.export_display_title_bitable",
            "--scope",
            "target",
            "--dry-run",
            "--max-documents",
            "20",
        ],
        scope="target",
        dry_run=True,
    ),
    # --- ops ---
    JobSpec(
        "reclassify_others",
        "Others 产品线纠偏",
        "ops",
        "tools.reclassify_others_move",
        [sys.executable, "-m", "tools.reclassify_others_move"],
    ),
    JobSpec(
        "others_theme",
        "Others 主题归档",
        "ops",
        "tools.others_theme_classify_move",
        [sys.executable, "-m", "tools.others_theme_classify_move"],
    ),
    JobSpec(
        "retry_attachments",
        "附件提取失败重试",
        "ops",
        "tools.retry_attachment_extract",
        [sys.executable, "-m", "tools.retry_attachment_extract"],
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
    # Ring buffer of recent lines; log_seq is absolute line count ever appended.
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=20000))
    log_seq: int = 0
    proc: Optional[subprocess.Popen] = None

    def append_log(self, line: str) -> None:
        self.logs.append(line)
        self.log_seq += 1


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
                "scope": j.scope,
                "dry_run": j.dry_run,
                "danger": j.danger,
                "needs_folder": j.needs_folder,
                "force_rescan": bool(j.env_overrides.get("FORCE_RESCAN")),
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
                    "log_lines": cur.log_seq,
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
        env_overrides: Dict[str, str] = {}
        if not spec:
            if job_id == "classify_folder":
                if not folder_id:
                    raise ValueError("classify_folder 需要 folder_id")
                argv = [sys.executable, "main.py", "--folder", folder_id]
                title = f"【增量更新】分类复制 --folder {folder_id}"
            elif job_id == "classify_folder_full":
                if not folder_id:
                    raise ValueError("classify_folder_full 需要 folder_id")
                argv = [sys.executable, "main.py", "--folder", folder_id]
                title = f"【全量重扫】分类复制 --folder {folder_id}"
                env_overrides = {"FORCE_RESCAN": "true"}
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
                title = f"[扫源] 元数据分表 --folder {folder_id}"
            else:
                raise ValueError(f"未知任务: {job_id}")
        else:
            argv = list(spec.argv)
            title = spec.title
            env_overrides = dict(spec.env_overrides or {})

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
        env.update(env_overrides)

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
        state.append_log(f"$ {' '.join(argv)}\n")
        if env_overrides:
            ov = " ".join(f"{k}={v}" for k, v in sorted(env_overrides.items()))
            state.append_log(f"# env overrides: {ov}\n")

        t = threading.Thread(target=self._pump, args=(state,), daemon=True)
        t.start()
        return self.status()

    def _pump(self, state: JobState) -> None:
        assert state.proc is not None
        try:
            assert state.proc.stdout is not None
            for line in state.proc.stdout:
                state.append_log(line)
            code = state.proc.wait()
            state.exit_code = code
            state.status = "succeeded" if code == 0 else "failed"
        except Exception as exc:
            state.append_log(f"\n[console] pump error: {exc}\n")
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
            cur.append_log(f"\n[console] stop error: {exc}\n")
            try:
                proc.kill()
            except Exception:
                pass
        cur.status = "stopped"
        cur.finished_at = time.time()
        return self.status()

    def logs_since(self, offset: int = 0) -> dict:
        """
        offset is an absolute line sequence (0-based), not an index into the ring buffer.

        When the ring drops old lines, clients whose offset is behind the buffer head
        receive a truncated notice and continue from the oldest retained line.
        """
        with self._lock:
            cur = self._current
            if not cur:
                return {
                    "offset": 0,
                    "lines": [],
                    "status": None,
                    "truncated": False,
                    "total": 0,
                }
            buf = list(cur.logs)
            seq = cur.log_seq
            retained = len(buf)
            head = seq - retained  # absolute index of buf[0]
            truncated = False
            if offset < head:
                truncated = True
                notice = (
                    f"\n[console] 日志缓冲已滚动：跳过前 {head - offset} 行"
                    f"（仅保留最近 {retained} 行）\n"
                )
                chunk = [notice] + buf
                new_offset = seq
            else:
                local = offset - head
                chunk = buf[local:]
                new_offset = offset + len(chunk)
            return {
                "offset": new_offset,
                "total": seq,
                "retained": retained,
                "lines": chunk,
                "status": cur.status,
                "run_id": cur.run_id,
                "exit_code": cur.exit_code,
                "truncated": truncated,
            }


JOB_MANAGER = JobManager()
