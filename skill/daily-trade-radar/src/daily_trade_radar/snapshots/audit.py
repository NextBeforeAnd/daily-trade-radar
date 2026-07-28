"""Audit a version-controlled snapshot store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .git import GitSnapshotStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a Daily Trade Radar Git snapshot store.")
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = GitSnapshotStore(args.store).audit()
    except (OSError, ValueError) as exc:
        result = {
            "valid": False,
            "storage_backend": "git",
            "repository": str(args.store.resolve()),
            "errors": [str(exc)],
        }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"WROTE: {args.output}")
    else:
        print(rendered, end="")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
