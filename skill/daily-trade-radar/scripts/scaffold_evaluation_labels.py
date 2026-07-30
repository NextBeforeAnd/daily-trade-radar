#!/usr/bin/env python3
"""Backward-compatible entry point for draft evaluation-label scaffolding."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from daily_trade_radar.evaluation_scaffold import main


if __name__ == "__main__":
    raise SystemExit(main())
