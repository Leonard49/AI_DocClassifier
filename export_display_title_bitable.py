#!/usr/bin/env python3
"""Compat shim (legacy root entry). Prefer: python -m tools.export_display_title_bitable"""
from tools.export_display_title_bitable import main

if __name__ == "__main__":
    raise SystemExit(main())
