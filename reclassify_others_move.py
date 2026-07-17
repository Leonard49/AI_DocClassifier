#!/usr/bin/env python3
""" Backward-compatible entry: prefer `python -m tools.reclassify_others_move`. """
from tools.reclassify_others_move import main

if __name__ == "__main__":
    raise SystemExit(main())
