"""Command-line tools for acquisition manifests, receipts, XML discovery, and coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..snapshots.filesystem import atomic_write_text
from .adapters.http import HttpAdapter
from .adapters.xmlfeeds import parse_feed, parse_sitemap
from .cache import AcquisitionCache
from .coverage import build_coverage_ledger
from .manifest import AcquisitionManifest, build_platform_manifest
from .models import AcquisitionReceipt
from .receipts import create_receipt


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write(value: object, output: Path | None) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        print(content, end="")
    else:
        atomic_write_text(output, content)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser("manifest", help="build tasks from registered platform routes")
    manifest.add_argument("--platform", action="append", required=True)
    manifest.add_argument("--seller-market", required=True)
    manifest.add_argument("--program", required=True)
    manifest.add_argument("--window-start", required=True)
    manifest.add_argument("--cutoff", required=True)
    manifest.add_argument("--created-at")
    manifest.add_argument("--output", type=Path)

    receipt = commands.add_parser("receipt", help="record a manual/public acquisition result")
    receipt.add_argument("--manifest", type=Path, required=True)
    receipt.add_argument("--task-id", required=True)
    receipt.add_argument("--checked-at", required=True)
    receipt.add_argument("--result", required=True)
    receipt.add_argument("--method", choices=("manual", "browser_public"), default="manual")
    receipt.add_argument("--notes", required=True)
    receipt.add_argument("--content-file", type=Path)
    receipt.add_argument("--final-url")
    receipt.add_argument("--cache", type=Path)
    receipt.add_argument("--snapshot", type=Path)
    receipt.add_argument("--route-verified", action="store_true")
    receipt.add_argument("--output", type=Path)

    coverage = commands.add_parser("coverage", help="convert manifests and receipts to ledger rows")
    coverage.add_argument("--manifest", type=Path, required=True)
    coverage.add_argument("--receipt", type=Path, action="append", default=[])
    coverage.add_argument("--output", type=Path)

    fetch = commands.add_parser("fetch", help="retrieve one public task with bounded HTTP")
    fetch.add_argument("--manifest", type=Path, required=True)
    fetch.add_argument("--task-id", required=True)
    fetch.add_argument("--checked-at", required=True)
    fetch.add_argument("--cache", type=Path, required=True)
    fetch.add_argument("--cache-ttl", type=float, default=24 * 60 * 60, help="reusable receipt TTL in seconds")
    fetch.add_argument("--refresh", action="store_true", help="ignore a reusable cached receipt")
    fetch.add_argument("--timeout", type=float, default=20.0)
    fetch.add_argument("--max-attempts", type=int, default=3)
    fetch.add_argument("--output", type=Path)

    xml = commands.add_parser("xml", help="parse a supplied RSS, Atom, or sitemap file")
    xml.add_argument("--input", type=Path, required=True)
    xml.add_argument("--kind", choices=("auto", "feed", "sitemap"), default="auto")
    xml.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "manifest":
            value = build_platform_manifest(
                args.platform, args.seller_market, args.program, args.window_start,
                args.cutoff, args.created_at,
            ).to_dict()
        elif args.command == "receipt":
            manifest = AcquisitionManifest.from_dict(_load(args.manifest))
            task = next((item for item in manifest.tasks if item.task_id == args.task_id), None)
            if task is None:
                raise ValueError(f"task id not found in manifest: {args.task_id}")
            content = args.content_file.read_text(encoding="utf-8") if args.content_file else None
            snapshot = _load(args.snapshot) if args.snapshot else None
            receipt = create_receipt(
                task, args.checked_at, args.result, args.method, args.notes, content=content,
                final_url=args.final_url, cache=AcquisitionCache(args.cache) if args.cache else None,
                snapshot=snapshot, route_verified=args.route_verified,
            )
            value = receipt.to_dict()
        elif args.command == "coverage":
            manifest = AcquisitionManifest.from_dict(_load(args.manifest))
            receipts = [AcquisitionReceipt.from_dict(_load(path)) for path in args.receipt]
            value = build_coverage_ledger(manifest, receipts)
        elif args.command == "fetch":
            manifest = AcquisitionManifest.from_dict(_load(args.manifest))
            task = next((item for item in manifest.tasks if item.task_id == args.task_id), None)
            if task is None:
                raise ValueError(f"task id not found in manifest: {args.task_id}")
            if task.requires_auth:
                raise ValueError("authenticated tasks must use the read-only browser adapter")
            adapter = HttpAdapter(
                cache=AcquisitionCache(args.cache), timeout=args.timeout,
                max_attempts=args.max_attempts, cache_ttl_seconds=args.cache_ttl,
            )
            value = adapter.acquire(task, args.checked_at, refresh=args.refresh).to_dict()
        else:
            content = args.input.read_text(encoding="utf-8")
            if args.kind == "sitemap":
                kind, entries = "sitemap", parse_sitemap(content)
            elif args.kind == "feed":
                kind, entries = parse_feed(content)
            else:
                try:
                    kind, entries = parse_feed(content)
                except ValueError:
                    kind, entries = "sitemap", parse_sitemap(content)
            value = {"kind": kind, "entries": [item.to_dict() for item in entries]}
        _write(value, args.output)
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser = _parser()
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
