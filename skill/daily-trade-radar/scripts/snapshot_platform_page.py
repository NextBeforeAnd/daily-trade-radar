#!/usr/bin/env python3
"""Store normalized marketplace page text and compare it with the prior snapshot."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_KEYS = {"from", "source", "ref", "ref_", "spm", "scm"}
SNAPSHOT_VERSION = 1


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be a direct http(s) URL")
    query = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in TRACKING_KEYS:
            continue
        query.append((key, item))
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path or "/", urlencode(sorted(query)), ""))


def normalize_content(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    lines: list[str] = []
    for raw in value.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "platform"


def timestamp_slug(value: str) -> str:
    return re.sub(r"[^0-9]", "", value)[:14]


def load_latest(index_path: Path) -> dict | None:
    if not index_path.exists():
        return None
    data = json.loads(index_path.read_text(encoding="utf-8"))
    latest_path = data.get("latest_snapshot_path")
    if not isinstance(latest_path, str):
        return None
    snapshot_path = Path(latest_path)
    if not snapshot_path.is_absolute():
        snapshot_path = index_path.parent / snapshot_path
    if not snapshot_path.exists():
        return None
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def diff_details(previous: str, current: str) -> tuple[str, str]:
    before = previous.splitlines()
    after = current.splitlines()
    diff = list(difflib.unified_diff(before, after, fromfile="previous", tofile="current", lineterm=""))
    added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]
    examples = [f"+ {line}" for line in added[:3]] + [f"- {line}" for line in removed[:3]]
    summary = f"Normalized page text changed: +{len(added)} / -{len(removed)} lines."
    if examples:
        summary += " " + " | ".join(examples)
    return summary[:800], "\n".join(diff) + "\n"


def capture(platform: str, url: str, content: str, store: Path, captured_at: str) -> dict:
    try:
        parsed_time = datetime.fromisoformat(captured_at)
    except ValueError as exc:
        raise ValueError("captured_at must be ISO 8601") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise ValueError("captured_at must include a UTC offset")

    canonical = canonical_url(url)
    normalized = normalize_content(content)
    if not normalized:
        raise ValueError("captured content is empty after normalization")
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    page_key = hashlib.sha256(f"{platform.casefold()}\n{canonical}".encode("utf-8")).hexdigest()[:20]
    page_dir = store / safe_slug(platform) / page_key
    page_dir.mkdir(parents=True, exist_ok=True)
    index_path = page_dir / "index.json"
    previous = load_latest(index_path)

    previous_id = previous.get("snapshot_id") if previous else None
    if previous is None:
        change_status = "first_seen"
        diff_summary = "First captured snapshot; no historical baseline is available."
        diff_text = ""
    elif previous.get("content_hash") == content_hash:
        change_status = "unchanged"
        diff_summary = "No normalized page-text change from the previous snapshot."
        diff_text = ""
    else:
        change_status = "changed"
        diff_summary, diff_text = diff_details(str(previous.get("content", "")), normalized)

    snapshot_id = f"{timestamp_slug(captured_at)}-{content_hash[:12]}"
    snapshot_path = page_dir / f"{snapshot_id}.json"
    snapshot_record = {
        "schema_version": SNAPSHOT_VERSION,
        "snapshot_id": snapshot_id,
        "platform": platform,
        "url": canonical,
        "captured_at": captured_at,
        "content_hash": content_hash,
        "previous_snapshot_id": previous_id,
        "change_status": change_status,
        "diff_summary": diff_summary,
        "content": normalized,
    }
    snapshot_path.write_text(json.dumps(snapshot_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diff_path = None
    if diff_text:
        diff_path = snapshot_path.with_suffix(".diff.txt")
        diff_path.write_text(diff_text, encoding="utf-8")

    index = {
        "schema_version": SNAPSHOT_VERSION,
        "platform": platform,
        "url": canonical,
        "latest_snapshot_id": snapshot_id,
        "latest_snapshot_path": snapshot_path.name,
        "updated_at": captured_at,
    }
    temp_index = index_path.with_suffix(".tmp")
    temp_index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_index.replace(index_path)

    return {
        "snapshot_id": snapshot_id,
        "captured_at": captured_at,
        "content_hash": content_hash,
        "previous_snapshot_id": previous_id,
        "change_status": change_status,
        "diff_summary": diff_summary,
        "snapshot_path": str(snapshot_path.resolve()),
        "diff_path": str(diff_path.resolve()) if diff_path else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--content-file", required=True, help="UTF-8 text file, or - for stdin")
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--captured-at", default=datetime.now().astimezone().isoformat(timespec="seconds"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    content = sys.stdin.read() if args.content_file == "-" else Path(args.content_file).read_text(encoding="utf-8")
    try:
        result = capture(args.platform, args.url, content, args.store, args.captured_at)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"WROTE: {args.output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
