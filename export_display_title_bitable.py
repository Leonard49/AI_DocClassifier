#!/usr/bin/env python3
"""Compat shim: python export_display_title_bitable.py → tools.export_display_title_bitable."""
from tools.export_display_title_bitable import main

if __name__ == "__main__":
    raise SystemExit(main())
