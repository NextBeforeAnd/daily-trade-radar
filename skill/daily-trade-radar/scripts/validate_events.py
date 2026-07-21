#!/usr/bin/env python3
"""Validate Daily Trade Radar event JSON using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT_FIELDS = {
    "report_date": str,
    "timezone": str,
    "cutoff": str,
    "language": str,
    "scope": list,
    "coverage_gaps": list,
    "events": list,
}
EVENT_FIELDS = {
    "id": str,
    "title": str,
    "status": str,
    "level": str,
    "score": int,
    "jurisdiction": str,
    "authority": str,
    "published_date": (str, type(None)),
    "effective_date": (str, type(None)),
    "deadline": (str, type(None)),
    "products_or_channels": list,
    "summary": str,
    "impact": str,
    "action": str,
    "rationale": str,
    "source_title": str,
    "source_url": str,
    "retrieved_date": str,
}
STATUSES = {"new", "effective", "deadline", "ongoing", "unconfirmed"}
LEVELS = {"high", "medium", "low", "watch"}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("root must be a JSON object")
    return value


def valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    for key, expected in ROOT_FIELDS.items():
        if key not in data:
            errors.append(f"root: missing {key}")
        elif not isinstance(data[key], expected):
            errors.append(f"root.{key}: wrong type")

    if isinstance(data.get("report_date"), str) and not valid_date(data["report_date"]):
        errors.append("root.report_date: use YYYY-MM-DD")
    if isinstance(data.get("cutoff"), str):
        try:
            parsed = datetime.fromisoformat(data["cutoff"])
            if parsed.tzinfo is None:
                errors.append("root.cutoff: include a UTC offset")
        except ValueError:
            errors.append("root.cutoff: use ISO 8601 date-time")

    seen_ids: set[str] = set()
    for index, event in enumerate(data.get("events", [])):
        label = f"events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{label}: must be an object")
            continue
        for key, expected in EVENT_FIELDS.items():
            if key not in event:
                errors.append(f"{label}: missing {key}")
            elif not isinstance(event[key], expected):
                errors.append(f"{label}.{key}: wrong type")
        event_id = event.get("id")
        if isinstance(event_id, str):
            if not event_id.strip():
                errors.append(f"{label}.id: must not be blank")
            elif event_id in seen_ids:
                errors.append(f"{label}.id: duplicate {event_id}")
            seen_ids.add(event_id)
        if event.get("status") not in STATUSES:
            errors.append(f"{label}.status: invalid value")
        if event.get("level") not in LEVELS:
            errors.append(f"{label}.level: invalid value")
        score = event.get("score")
        if isinstance(score, int) and not 0 <= score <= 10:
            errors.append(f"{label}.score: must be 0..10")
        if event.get("status") == "unconfirmed" and event.get("level") != "watch":
            errors.append(f"{label}: unconfirmed events must use watch level")
        for field in ("published_date", "effective_date", "deadline", "retrieved_date"):
            value = event.get(field)
            if isinstance(value, str) and not valid_date(value):
                errors.append(f"{label}.{field}: use YYYY-MM-DD")
        url = event.get("source_url")
        if isinstance(url, str):
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"{label}.source_url: use a direct http(s) URL")
        if event.get("level") != "watch" and not event.get("source_title", "").strip():
            errors.append(f"{label}.source_title: required for main-table events")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        data = load_json(args.input)
        errors = validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {len(data['events'])} events validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

