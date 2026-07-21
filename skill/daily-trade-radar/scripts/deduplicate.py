#!/usr/bin/env python3
"""Compare current radar events with a previous JSON report."""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError(f"{path}: expected an object with an events array")
    return data


def normalized(value: object) -> str:
    text = str(value or "").casefold()
    return " ".join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def signature(event: dict) -> str:
    parts = [
        event.get("jurisdiction"),
        event.get("authority"),
        event.get("title"),
        " ".join(event.get("products_or_channels", [])),
    ]
    return normalized(" ".join(str(part or "") for part in parts))


def similarity(left: dict, right: dict) -> float:
    if left.get("id") and left.get("id") == right.get("id"):
        return 1.0
    if left.get("source_url") and left.get("source_url") == right.get("source_url"):
        return 0.99
    return SequenceMatcher(None, signature(left), signature(right)).ratio()


def materially_changed(current: dict, previous: dict) -> bool:
    fields = (
        "status",
        "level",
        "score",
        "effective_date",
        "deadline",
        "summary",
        "impact",
        "action",
        "source_url",
    )
    return any(normalized(current.get(field)) != normalized(previous.get(field)) for field in fields)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("current", type=Path)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.82)
    args = parser.parse_args()

    current = load(args.current)
    previous = load(args.previous)
    kept: list[dict] = []
    matches: list[dict] = []

    for event in current["events"]:
        candidates = [(similarity(event, old), old) for old in previous["events"]]
        score, old = max(candidates, default=(0.0, {}), key=lambda pair: pair[0])
        if score < args.threshold:
            kept.append(event)
            continue
        changed = materially_changed(event, old)
        disposition = "possible_update" if changed else "duplicate_removed"
        matches.append({
            "current_id": event.get("id"),
            "previous_id": old.get("id"),
            "similarity": round(score, 3),
            "disposition": disposition,
        })
        if changed:
            copy = dict(event)
            copy["deduplication_review"] = disposition
            copy["matched_previous_id"] = old.get("id")
            kept.append(copy)

    current["events"] = kept
    current["deduplication"] = {
        "previous_report": str(args.previous),
        "threshold": args.threshold,
        "matches": matches,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(current, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    removed = sum(item["disposition"] == "duplicate_removed" for item in matches)
    review = sum(item["disposition"] == "possible_update" for item in matches)
    print(f"WROTE: {args.output} ({removed} duplicates removed, {review} updates to review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
