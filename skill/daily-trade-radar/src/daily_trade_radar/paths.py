"""Filesystem locations bundled with the installable skill."""

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = SKILL_ROOT / "assets"
REFERENCES_DIR = SKILL_ROOT / "references"
