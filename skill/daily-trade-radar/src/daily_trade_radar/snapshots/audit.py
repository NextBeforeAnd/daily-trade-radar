"""Audit a Git or S3-compatible snapshot store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .store import create_snapshot_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a Daily Trade Radar Git or S3 snapshot store.")
    parser.add_argument("--store", required=True)
    parser.add_argument("--backend", choices=("git", "s3"), default="git")
    parser.add_argument("--s3-endpoint-url")
    parser.add_argument("--s3-region")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        options = {}
        if args.backend == "s3":
            options = {"endpoint_url": args.s3_endpoint_url, "region_name": args.s3_region}
        elif args.s3_endpoint_url or args.s3_region:
            raise ValueError("S3 options require --backend s3")
        result = create_snapshot_store(args.backend, args.store, **options).audit()
    except Exception as exc:
        result = {
            "valid": False,
            "storage_backend": args.backend,
            "store": str(Path(args.store).resolve()) if args.backend == "git" else args.store,
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
