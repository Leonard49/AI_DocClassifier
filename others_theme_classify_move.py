#!/usr/bin/env python3
""" Backward-compatible entry: prefer `python -m tools.others_theme_classify_move`. """
from tools.others_theme_classify_move import main

if __name__ == "__main__":
    raise SystemExit(main())
