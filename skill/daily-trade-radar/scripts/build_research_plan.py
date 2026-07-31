#!/usr/bin/env python3
"""Compatibility entry point for research-plan generation and validation."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from daily_trade_radar.planning import main


if __name__ == "__main__":
    raise SystemExit(main())
