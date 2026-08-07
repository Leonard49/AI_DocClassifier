#!/usr/bin/env python3
"""Compat shim (legacy root entry). Prefer: python -m tools.retry_attachment_extract"""
from tools.retry_attachment_extract import main

if __name__ == "__main__":
    raise SystemExit(main())
