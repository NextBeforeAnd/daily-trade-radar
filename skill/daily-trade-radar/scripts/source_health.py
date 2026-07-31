#!/usr/bin/env python3
"""Compatibility entry point for source-health inventory and postmortems."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from daily_trade_radar.source_health import main


if __name__ == "__main__":
    raise SystemExit(main())
