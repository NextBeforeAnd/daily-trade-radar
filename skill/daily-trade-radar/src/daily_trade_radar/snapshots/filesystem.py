#!/usr/bin/env python3
"""Capture normalized marketplace page text in a filesystem snapshot store."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_KEYS = {"from", "source", "ref", "ref_", "spm", "scm"}
SNAPSHOT_VERSION = 2
LOCK_TIMEOUT_SECONDS = 5.0
STALE_LOCK_SECONDS = 60.0


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


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


class FileLock:
    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT_SECONDS, stale_after: float = STALE_LOCK_SECONDS):
        self.path = path
        self.timeout = timeout
        self.stale_after = stale_after
        self.acquired = False

    def __enter__(self) -> "FileLock":
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale_after:
                        self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"snapshot page is locked: {self.path}")
                time.sleep(0.05)
                continue
            try:
                os.write(descriptor, f"pid={os.getpid()} acquired_at={datetime.now().astimezone().isoformat()}\n".encode())
            finally:
                os.close(descriptor)
            self.acquired = True
            return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


def _read_snapshot(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("snapshot_id"), str):
        return None
    return value


def _scan_latest(page_dir: Path) -> dict | None:
    candidates: list[tuple[datetime, str, dict]] = []
    for path in page_dir.glob("*.json"):
        if path.name == "index.json":
            continue
        record = _read_snapshot(path)
        if record is None:
            continue
        try:
            captured = datetime.fromisoformat(str(record.get("captured_at", "")))
        except ValueError:
            continue
        if captured.tzinfo is None or captured.utcoffset() is None:
            continue
        candidates.append((captured, path.name, record))
    return max(candidates, default=None, key=lambda item: (item[0], item[1]))[2] if candidates else None


def _load_latest(page_dir: Path) -> tuple[dict | None, bool]:
    index_path = page_dir / "index.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            latest_path = index.get("latest_snapshot_path")
            if isinstance(latest_path, str):
                candidate = Path(latest_path)
                if not candidate.is_absolute():
                    candidate = page_dir / candidate
                record = _read_snapshot(candidate)
                if record is not None:
                    return record, False
        except (OSError, json.JSONDecodeError):
            pass
    recovered = _scan_latest(page_dir)
    return recovered, recovered is not None


def load_latest(index_path: Path) -> dict | None:
    """Backward-compatible index loader with scan-based recovery."""
    return _load_latest(index_path.parent)[0]


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


class FilesystemSnapshotStore:
    backend_name = "filesystem"

    def __init__(self, root: Path, lock_timeout: float = LOCK_TIMEOUT_SECONDS):
        self.root = Path(root).resolve()
        self.lock_timeout = lock_timeout

    def _page_dir(self, platform: str, canonical: str) -> Path:
        page_key = hashlib.sha256(f"{platform.casefold()}\n{canonical}".encode("utf-8")).hexdigest()[:20]
        return self.root / safe_slug(platform) / page_key

    def load_latest(self, platform: str, url: str) -> dict | None:
        canonical = canonical_url(url)
        return _load_latest(self._page_dir(platform, canonical))[0]

    def _metadata(
        self,
        record: dict,
        snapshot_path: Path,
        diff_path: Path | None,
        index_recovered: bool,
    ) -> dict:
        return {
            "snapshot_id": record["snapshot_id"],
            "captured_at": record["captured_at"],
            "content_hash": record["content_hash"],
            "previous_snapshot_id": record.get("previous_snapshot_id"),
            "change_status": record["change_status"],
            "diff_summary": record["diff_summary"],
            "snapshot_path": str(snapshot_path.resolve()),
            "diff_path": str(diff_path.resolve()) if diff_path else None,
            "storage_backend": self.backend_name,
            "snapshot_ref": snapshot_path.relative_to(self.root).as_posix(),
            "diff_ref": diff_path.relative_to(self.root).as_posix() if diff_path else None,
            "index_recovered": index_recovered,
        }

    def capture(self, platform: str, url: str, content: str, captured_at: str) -> dict:
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
        page_dir = self._page_dir(platform, canonical)
        page_dir.mkdir(parents=True, exist_ok=True)
        index_path = page_dir / "index.json"

        with FileLock(page_dir / ".capture.lock", timeout=self.lock_timeout):
            previous, index_recovered = _load_latest(page_dir)
            previous_id = previous.get("snapshot_id") if previous else None
            snapshot_id = f"{timestamp_slug(captured_at)}-{content_hash[:12]}"
            snapshot_path = page_dir / f"{snapshot_id}.json"

            if previous and previous_id == snapshot_id and previous.get("content_hash") == content_hash:
                diff_candidate = snapshot_path.with_suffix(".diff.txt")
                return self._metadata(
                    previous,
                    snapshot_path,
                    diff_candidate if diff_candidate.exists() else None,
                    index_recovered,
                )

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
            atomic_write_text(
                snapshot_path,
                json.dumps(snapshot_record, ensure_ascii=False, indent=2) + "\n",
            )
            diff_path = None
            if diff_text:
                diff_path = snapshot_path.with_suffix(".diff.txt")
                atomic_write_text(diff_path, diff_text)

            index = {
                "schema_version": SNAPSHOT_VERSION,
                "storage_backend": self.backend_name,
                "platform": platform,
                "url": canonical,
                "latest_snapshot_id": snapshot_id,
                "latest_snapshot_path": snapshot_path.name,
                "latest_snapshot_ref": snapshot_path.relative_to(self.root).as_posix(),
                "updated_at": captured_at,
            }
            atomic_write_text(index_path, json.dumps(index, ensure_ascii=False, indent=2) + "\n")
            return self._metadata(snapshot_record, snapshot_path, diff_path, index_recovered)


def capture(platform: str, url: str, content: str, store: Path, captured_at: str) -> dict:
    """Backward-compatible functional API for the filesystem backend."""
    return FilesystemSnapshotStore(store).capture(platform, url, content, captured_at)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--content-file", required=True, help="UTF-8 text file, or - for stdin")
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--backend", default="filesystem")
    parser.add_argument("--captured-at", default=datetime.now().astimezone().isoformat(timespec="seconds"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    content = sys.stdin.read() if args.content_file == "-" else Path(args.content_file).read_text(encoding="utf-8")
    try:
        from .store import create_snapshot_store

        snapshot_store = create_snapshot_store(args.backend, args.store)
        result = snapshot_store.capture(args.platform, args.url, content, args.captured_at)
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.DatabaseError) as exc:
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
