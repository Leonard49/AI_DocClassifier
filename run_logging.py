#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mirror stdout/stderr to a UTF-8 log file while keeping terminal output."""

import atexit
import os
import sys
from datetime import datetime
from typing import IO, Optional, TextIO, Tuple


class _TeeStream:
    """Write to terminal and log file; supports progress lines with \\r."""

    def __init__(self, terminal: TextIO, log_file: IO[str]):
        self.terminal = terminal
        self.log_file = log_file

    def write(self, data: str) -> int:
        if not data:
            return 0
        self.terminal.write(data)
        # Progress uses \\r; log file keeps one line per update
        if data.startswith("\r"):
            self.log_file.write(data.lstrip("\r"))
        else:
            self.log_file.write(data)
        return len(data)

    def flush(self) -> None:
        self.terminal.flush()
        self.log_file.flush()

    def isatty(self) -> bool:
        return getattr(self.terminal, "isatty", lambda: False)()


_log_handle: Optional[IO[str]] = None


def setup_run_log(log_dir: str = "logs") -> str:
    """
    Duplicate stdout/stderr into logs/run_YYYYMMDD_HHMMSS.log.
    Returns absolute path to the log file.
    """
    global _log_handle

    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"run_{stamp}.log")
    _log_handle = open(log_path, "a", encoding="utf-8")

    sys.stdout = _TeeStream(sys.stdout, _log_handle)
    sys.stderr = _TeeStream(sys.stderr, _log_handle)

    atexit.register(_close_log)
    return os.path.abspath(log_path)


def _close_log() -> None:
    global _log_handle
    if _log_handle and not _log_handle.closed:
        _log_handle.close()
    _log_handle = None
