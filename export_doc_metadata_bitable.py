#!/usr/bin/env python3
"""Compat shim (legacy root entry). Prefer: python -m tools.export_doc_metadata_bitable"""
from tools.export_doc_metadata_bitable import main

if __name__ == "__main__":
    raise SystemExit(main())
