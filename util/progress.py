# -*- coding: utf-8 -*-
"""Shared progress printers for long tool batches (console-friendly, flushed)."""

from __future__ import annotations

from concurrent.futures import Future, as_completed
from datetime import datetime
from typing import Callable, Iterable, List, Optional, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def print_progress(
    label: str,
    done: int,
    total: int,
    *,
    start: Optional[datetime] = None,
    ok: Optional[int] = None,
    fail: Optional[int] = None,
    extra: str = "",
) -> None:
    total = max(int(total), 0)
    done = max(int(done), 0)
    pct = (100.0 * done / total) if total else 100.0
    parts = [f"{label}: {done}/{total} ({pct:.0f}%)"]
    if ok is not None:
        parts.append(f"ok={ok}")
    if fail is not None:
        parts.append(f"fail={fail}")
    if start is not None and done > 0:
        elapsed = max((datetime.now() - start).total_seconds(), 0.001)
        rate = done / elapsed
        eta = (total - done) / rate if rate > 0 and total > done else 0.0
        parts.append(f"{elapsed:.0f}s")
        if eta > 0:
            parts.append(f"ETA {eta:.0f}s")
    if extra:
        parts.append(extra)
    print("  · " + " | ".join(parts), flush=True)


def should_print_progress(done: int, total: int, interval: int) -> bool:
    interval = max(1, int(interval or 1))
    return done == 1 or done == total or done % interval == 0


def map_parallel_with_progress(
    items: Sequence[T],
    worker: Callable[[T], R],
    *,
    workers: int,
    label: str,
    progress_interval: int = 10,
    is_ok: Optional[Callable[[R], bool]] = None,
) -> List[R]:
    """
    Run worker over items in a thread pool; print flushed progress so console
    logs keep moving during long Feishu reads.
    """
    total = len(items)
    if total == 0:
        return []
    workers = max(1, int(workers or 1))
    interval = max(1, int(progress_interval or 10))
    print(f"{label}（共 {total} 篇，workers={workers}）…", flush=True)
    start = datetime.now()
    done = 0
    ok = 0
    fail = 0
    results: List[R] = []

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs: List[Future] = [pool.submit(worker, item) for item in items]
        for fut in as_completed(futs):
            try:
                value = fut.result()
                results.append(value)
                if is_ok is None or is_ok(value):
                    ok += 1
                else:
                    fail += 1
            except Exception as exc:
                fail += 1
                print(f"  ⚠️ {label} 任务失败: {exc}", flush=True)
            done += 1
            if should_print_progress(done, total, interval):
                print_progress(label, done, total, start=start, ok=ok, fail=fail)
    return results


def iter_with_progress(
    items: Iterable[T],
    *,
    total: int,
    label: str,
    progress_interval: int = 10,
) -> Iterable[T]:
    """Yield items while printing progress (for sequential LLM / rename loops)."""
    interval = max(1, int(progress_interval or 10))
    start = datetime.now()
    done = 0
    print(f"{label}（共 {total} 篇）…", flush=True)
    for item in items:
        yield item
        done += 1
        if should_print_progress(done, total, interval):
            print_progress(label, done, total, start=start)
