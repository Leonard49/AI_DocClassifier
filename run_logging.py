#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mirror stdout/stderr and logging to UTF-8 log files (terminal + logs/latest.log)."""

import atexit
import logging
import os
import signal
import sys
from datetime import datetime
from typing import Dict, IO, List, Optional, TextIO


class _MultiFileWriter:
    """Write the same bytes to multiple open log files."""

    def __init__(self, files: List[IO[str]]):
        self.files = files

    def write(self, data: str) -> int:
        if not data:
            return 0
        for f in self.files:
            f.write(data)
        return len(data)

    def flush(self) -> None:
        for f in self.files:
            f.flush()


class _TeeStream:
    """Terminal output + log files; normalizes \\r progress lines for the log."""

    def __init__(self, terminal: TextIO, log_sink: _MultiFileWriter):
        self.terminal = terminal
        self.log_sink = log_sink
        self._log_line_open = False

    def write(self, data: str) -> int:
        if not data:
            return 0

        self.terminal.write(data)
        self.terminal.flush()

        if "\r" in data and not data.endswith("\n"):
            if self._log_line_open:
                self.log_sink.write("\n")
            line = data.replace("\r", "").lstrip()
            if line:
                self.log_sink.write(line + "\n")
            self._log_line_open = False
        else:
            self.log_sink.write(data)
            self._log_line_open = not data.endswith("\n")

        self.log_sink.flush()
        return len(data)

    def flush(self) -> None:
        self.terminal.flush()
        self.log_sink.flush()

    def isatty(self) -> bool:
        return getattr(self.terminal, "isatty", lambda: False)()


_log_files: List[IO[str]] = []
_orig_stdout: Optional[TextIO] = None
_orig_stderr: Optional[TextIO] = None


def _reconfigure_logging(log_sink: _MultiFileWriter, console_stderr: TextIO) -> None:
    """Route logging (scanner, httpx, openai) to log files and the real terminal."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    class _LoggingMultiHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                msg = self.format(record) + "\n"
                log_sink.write(msg)
                console_stderr.write(msg)
                log_sink.flush()
                console_stderr.flush()
            except Exception:
                self.handleError(record)

    log_handler = _LoggingMultiHandler()
    log_handler.setFormatter(formatter)
    root.setLevel(logging.INFO)
    root.addHandler(log_handler)

    for name in ("openai", "httpx", "httpcore", "urllib3"):
        child = logging.getLogger(name)
        child.handlers.clear()
        child.propagate = True


def _flush_and_close() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    for f in _log_files:
        try:
            if not f.closed:
                f.flush()
                f.close()
        except Exception:
            pass
    _log_files.clear()


def setup_run_log(log_dir: str = "logs") -> Dict[str, str]:
    """
    Capture print() and logging into:
      - logs/latest.log   (always overwritten each run — easy to find)
      - logs/run_YYYYMMDD_HHMMSS.log  (archive)
    """
    global _log_files, _orig_stdout, _orig_stderr

    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_path = os.path.join(log_dir, f"run_{stamp}.log")
    latest_path = os.path.join(log_dir, "latest.log")

    stamped_f = open(stamped_path, "w", encoding="utf-8", buffering=1)
    latest_f = open(latest_path, "w", encoding="utf-8", buffering=1)
    _log_files = [stamped_f, latest_f]

    header = (
        f"=== AI_DocMover run log ===\n"
        f"Started: {datetime.now().isoformat()}\n"
        f"CWD: {os.getcwd()}\n"
        f"{'=' * 40}\n"
    )
    for f in _log_files:
        f.write(header)
        f.flush()

    log_sink = _MultiFileWriter(_log_files)

    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr
    sys.stdout = _TeeStream(_orig_stdout, log_sink)
    sys.stderr = _TeeStream(_orig_stderr, log_sink)

    _reconfigure_logging(log_sink, _orig_stderr)

    atexit.register(_flush_and_close)
    try:
        signal.signal(signal.SIGINT, _signal_flush)
    except (ValueError, OSError):
        pass

    return {
        "latest": os.path.abspath(latest_path),
        "stamped": os.path.abspath(stamped_path),
    }


def _signal_flush(signum, frame) -> None:
    _flush_and_close()
    raise KeyboardInterrupt
