"""Detect report-language mismatches without silently translating factual content."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from .snapshots.filesystem import atomic_write_text


TEXT_FIELDS = ("title", "summary", "impact", "action", "rationale")


def _family(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    return "unknown"


def _event_text(event: dict[str, Any]) -> str:
    values = [str(event.get(field, "")) for field in TEXT_FIELDS]
    values.extend(str(item) for item in event.get("products_or_channels", []))
    for item in event.get("action_items", []):
        if isinstance(item, dict):
            values.extend(str(item.get(field, "")) for field in ("owner", "action", "deadline", "completion_evidence"))
    return " ".join(values)


def _counts(text: str) -> tuple[int, int]:
    han = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return han, latin


def assess_language(report: dict[str, Any], *, require_language: str | None = None) -> dict[str, Any]:
    declared = str(report.get("language", ""))
    target = require_language or declared
    target_family = _family(target)
    issues: list[dict[str, Any]] = []
    if target_family == "unknown":
        issues.append({
            "location": "root.language", "code": "unsupported_target_language",
            "message": f"Only zh-* and en-* consistency checks are supported, got {target!r}.",
        })
    elif require_language and _family(declared) != target_family:
        issues.append({
            "location": "root.language", "code": "declared_language_mismatch",
            "message": f"Report declares {declared!r}, but {require_language!r} is required.",
        })
    checked = 0
    for index, event in enumerate(report.get("events", [])):
        if not isinstance(event, dict):
            continue
        text = _event_text(event)
        han, latin = _counts(text)
        total = han + latin
        if total < 20 or target_family == "unknown":
            continue
        checked += 1
        mismatch = (
            target_family == "zh" and latin / total >= 0.75 and han < 8
        ) or (
            target_family == "en" and han / total >= 0.35 and han >= 8
        )
        if mismatch:
            issues.append({
                "location": f"events[{index}]", "event_id": event.get("id"),
                "code": "content_language_mismatch",
                "message": (
                    f"Content appears inconsistent with {target}: han={han}, latin={latin}. "
                    "Translate during reviewed research; do not silently machine-rewrite high-risk facts."
                ),
            })
    return {
        "schema_version": "1.0", "declared_language": declared,
        "required_language": require_language, "target_language": target,
        "status": "pass" if not issues else "review_required",
        "checked_event_count": checked, "issue_count": len(issues), "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--require-language")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("report must be a JSON object")
        result = assess_language(report, require_language=args.require_language)
        content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            atomic_write_text(args.output, content)
            print(f"WROTE: {args.output}")
        else:
            print(content, end="")
        return 1 if args.strict and result["issues"] else 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
