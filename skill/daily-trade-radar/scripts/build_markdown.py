#!/usr/bin/env python3
"""Backward-compatible entry point for Markdown rendering."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from daily_trade_radar.renderers.markdown import main


if __name__ == "__main__":
    raise SystemExit(main())
