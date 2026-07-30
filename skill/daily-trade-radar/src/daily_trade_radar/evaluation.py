"""Evaluate a radar report against an independently reviewed label set."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse

from .deduplication import canonical_url
from .snapshots.filesystem import atomic_write_text


LEVELS = {"watch", "low", "medium", "high"}
STATUSES = {"new", "effective", "deadline", "ongoing", "unconfirmed"}
REVIEW_STATUSES = {"draft", "independently_reviewed"}
DATE_FIELDS = ("published_date", "effective_date", "deadline")


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_url(value: Any) -> bool:
    if not _nonblank(value):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _valid_offset_datetime(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def _validate_labels(data: dict) -> tuple[list[dict], list[dict]]:
    if data.get("dataset_version") != 1:
        raise ValueError("dataset_version must be 1")
    if not _nonblank(data.get("dataset_name")):
        raise ValueError("dataset_name must be a nonblank string")
    if data.get("review_status") not in REVIEW_STATUSES:
        raise ValueError("review_status must be draft or independently_reviewed")
    if data.get("review_status") == "independently_reviewed":
        if not _nonblank(data.get("reviewed_by")):
            raise ValueError("reviewed_by is required for independently reviewed labels")
        if not _nonblank(data.get("reviewed_at")) or not _valid_offset_datetime(data["reviewed_at"]):
            raise ValueError("reviewed_at must be an ISO 8601 date-time with a UTC offset")

    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a non-empty array")
    validated: list[dict] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        label = f"records[{index}]"
        if not isinstance(record, dict):
            raise ValueError(f"{label} must be an object")
        event_id = record.get("event_id")
        if not _nonblank(event_id):
            raise ValueError(f"{label}.event_id must be a nonblank string")
        if event_id in seen_ids:
            raise ValueError(f"duplicate event_id: {event_id}")
        seen_ids.add(event_id)
        should_include = record.get("should_include")
        if not isinstance(should_include, bool):
            raise ValueError(f"{label}.should_include must be boolean")

        normalized = {"event_id": event_id, "should_include": should_include}
        if should_include:
            urls = record.get("accepted_primary_source_urls")
            if not isinstance(urls, list) or not urls or any(not _valid_url(url) for url in urls):
                raise ValueError(f"{label}.accepted_primary_source_urls must contain direct http(s) URLs")
            status = record.get("status")
            level = record.get("level")
            if status not in STATUSES:
                raise ValueError(f"{label}.status is invalid")
            if level not in LEVELS:
                raise ValueError(f"{label}.level is invalid")
            normalized.update({
                "accepted_primary_source_urls": sorted({canonical_url(url) for url in urls}),
                "status": status,
                "level": level,
            })
            for field in DATE_FIELDS:
                value = record.get(field)
                if value is not None and (not _nonblank(value) or not _valid_date(value)):
                    raise ValueError(f"{label}.{field} must use YYYY-MM-DD or null")
                normalized[field] = value
        validated.append(normalized)

    deduplication_cases = data.get("deduplication_cases", [])
    if not isinstance(deduplication_cases, list):
        raise ValueError("deduplication_cases must be an array")
    validated_deduplication: list[dict] = []
    seen_current_ids: set[str] = set()
    for index, case in enumerate(deduplication_cases):
        label = f"deduplication_cases[{index}]"
        if not isinstance(case, dict):
            raise ValueError(f"{label} must be an object")
        current_id = case.get("current_id")
        previous_id = case.get("previous_id")
        disposition = case.get("expected_disposition")
        if not _nonblank(current_id) or not _nonblank(previous_id) or not _nonblank(disposition):
            raise ValueError(f"{label} requires nonblank current_id, previous_id, and expected_disposition")
        if current_id in seen_current_ids:
            raise ValueError(f"duplicate deduplication current_id: {current_id}")
        seen_current_ids.add(current_id)
        validated_deduplication.append({
            "current_id": current_id,
            "previous_id": previous_id,
            "expected_disposition": disposition,
        })
    return validated, validated_deduplication


def _validate_report(data: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    events = data.get("events")
    if not isinstance(events, list):
        raise ValueError("report.events must be an array")
    by_id: dict[str, dict] = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict) or not _nonblank(event.get("id")):
            raise ValueError(f"report.events[{index}].id must be a nonblank string")
        if event["id"] in by_id:
            raise ValueError(f"duplicate report event id: {event['id']}")
        by_id[event["id"]] = event

    matches = data.get("deduplication", {}).get("matches", [])
    if not isinstance(matches, list):
        raise ValueError("report.deduplication.matches must be an array")
    matches_by_current: dict[str, dict] = {}
    for index, match in enumerate(matches):
        if not isinstance(match, dict) or not _nonblank(match.get("current_id")):
            raise ValueError(f"report.deduplication.matches[{index}].current_id must be nonblank")
        matches_by_current[match["current_id"]] = match
    return by_id, matches_by_current


def evaluate(report: dict, labels: dict, *, minimum_positive_events: int = 20,
             min_precision: float = 0.9, min_recall: float = 0.9,
             min_primary_source_rate: float = 0.95, min_date_accuracy: float = 0.98,
             min_deduplication_accuracy: float = 0.9, max_unsupported_sources: int = 0,
             require_independently_reviewed: bool = True) -> dict:
    """Return deterministic quality metrics and gate results."""
    if minimum_positive_events < 1:
        raise ValueError("minimum_positive_events must be positive")
    for name, value in {
        "min_precision": min_precision,
        "min_recall": min_recall,
        "min_primary_source_rate": min_primary_source_rate,
        "min_date_accuracy": min_date_accuracy,
        "min_deduplication_accuracy": min_deduplication_accuracy,
    }.items():
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1")
    if max_unsupported_sources < 0:
        raise ValueError("max_unsupported_sources must not be negative")

    records, deduplication_cases = _validate_labels(labels)
    predicted, predicted_matches = _validate_report(report)
    expected = {record["event_id"]: record for record in records if record["should_include"]}
    expected_ids = set(expected)
    predicted_ids = set(predicted)
    matched_ids = expected_ids & predicted_ids
    false_positive_ids = sorted(predicted_ids - expected_ids)
    false_negative_ids = sorted(expected_ids - predicted_ids)

    precision = _ratio(len(matched_ids), len(predicted_ids))
    recall = _ratio(len(matched_ids), len(expected_ids))

    source_correct = 0
    unsupported_source_ids: list[str] = list(false_positive_ids)
    date_correct = 0
    date_total = 0
    status_correct = 0
    level_correct = 0
    field_errors: dict[str, list[str]] = {
        "source": [], "published_date": [], "effective_date": [], "deadline": [],
        "status": [], "level": [],
    }
    for event_id in sorted(matched_ids):
        actual = predicted[event_id]
        gold = expected[event_id]
        actual_source = canonical_url(actual.get("source_url"))
        if actual_source in gold["accepted_primary_source_urls"]:
            source_correct += 1
        else:
            unsupported_source_ids.append(event_id)
            field_errors["source"].append(event_id)
        for field in DATE_FIELDS:
            date_total += 1
            if actual.get(field) == gold[field]:
                date_correct += 1
            else:
                field_errors[field].append(event_id)
        if actual.get("status") == gold["status"]:
            status_correct += 1
        else:
            field_errors["status"].append(event_id)
        if actual.get("level") == gold["level"]:
            level_correct += 1
        else:
            field_errors["level"].append(event_id)

    dedup_correct = 0
    dedup_errors: list[str] = []
    for case in deduplication_cases:
        actual = predicted_matches.get(case["current_id"])
        if actual and actual.get("previous_id") == case["previous_id"] and actual.get("disposition") == case["expected_disposition"]:
            dedup_correct += 1
        else:
            dedup_errors.append(case["current_id"])

    primary_source_rate = _ratio(source_correct, len(matched_ids))
    date_accuracy = _ratio(date_correct, date_total)
    deduplication_accuracy = _ratio(dedup_correct, len(deduplication_cases))
    status_accuracy = _ratio(status_correct, len(matched_ids))
    level_accuracy = _ratio(level_correct, len(matched_ids))
    unsupported_source_ids = sorted(set(unsupported_source_ids))

    checks = {
        "independently_reviewed": (
            labels.get("review_status") == "independently_reviewed"
            if require_independently_reviewed else True
        ),
        "minimum_positive_events": len(expected_ids) >= minimum_positive_events,
        "precision": precision is not None and precision >= min_precision,
        "recall": recall is not None and recall >= min_recall,
        "primary_source_rate": primary_source_rate is not None and primary_source_rate >= min_primary_source_rate,
        "date_accuracy": date_accuracy is not None and date_accuracy >= min_date_accuracy,
        "deduplication_accuracy": (
            (deduplication_accuracy is not None and deduplication_accuracy >= min_deduplication_accuracy)
            or (not deduplication_cases and min_deduplication_accuracy == 0)
        ),
        "unsupported_sources": len(unsupported_source_ids) <= max_unsupported_sources,
    }
    canonical_labels = json.dumps(labels, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    canonical_report = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "evaluation_version": 1,
        "dataset_name": labels["dataset_name"],
        "review_status": labels["review_status"],
        "labels_hash": hashlib.sha256(canonical_labels.encode("utf-8")).hexdigest(),
        "report_hash": hashlib.sha256(canonical_report.encode("utf-8")).hexdigest(),
        "sample": {
            "labeled_candidate_count": len(records),
            "positive_event_count": len(expected_ids),
            "negative_event_count": len(records) - len(expected_ids),
            "predicted_event_count": len(predicted_ids),
            "deduplication_case_count": len(deduplication_cases),
        },
        "detection": {
            "true_positive_count": len(matched_ids),
            "false_positive_count": len(false_positive_ids),
            "false_negative_count": len(false_negative_ids),
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
            "false_positive_ids": false_positive_ids,
            "false_negative_ids": false_negative_ids,
        },
        "factual": {
            "primary_source_rate": primary_source_rate,
            "date_accuracy": date_accuracy,
            "status_accuracy": status_accuracy,
            "level_accuracy": level_accuracy,
            "unsupported_source_count": len(unsupported_source_ids),
            "unsupported_source_ids": unsupported_source_ids,
            "field_error_ids": field_errors,
        },
        "deduplication": {
            "accuracy": deduplication_accuracy,
            "correct_count": dedup_correct,
            "error_ids": dedup_errors,
        },
        "quality_gate": {
            "passed": all(checks.values()),
            "checks": checks,
            "thresholds": {
                "require_independently_reviewed": require_independently_reviewed,
                "minimum_positive_events": minimum_positive_events,
                "min_precision": min_precision,
                "min_recall": min_recall,
                "min_primary_source_rate": min_primary_source_rate,
                "min_date_accuracy": min_date_accuracy,
                "min_deduplication_accuracy": min_deduplication_accuracy,
                "max_unsupported_sources": max_unsupported_sources,
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Generated radar JSON to evaluate")
    parser.add_argument("labels", type=Path, help="Independently reviewed evaluation labels")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-positive-events", type=int, default=20)
    parser.add_argument("--min-precision", type=float, default=0.9)
    parser.add_argument("--min-recall", type=float, default=0.9)
    parser.add_argument("--min-primary-source-rate", type=float, default=0.95)
    parser.add_argument("--min-date-accuracy", type=float, default=0.98)
    parser.add_argument("--min-deduplication-accuracy", type=float, default=0.9)
    parser.add_argument("--max-unsupported-sources", type=int, default=0)
    parser.add_argument("--allow-draft", action="store_true", help="Do not require independent-review metadata")
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(labels, dict):
            raise ValueError("report and labels roots must be objects")
        result = evaluate(
            report,
            labels,
            minimum_positive_events=args.minimum_positive_events,
            min_precision=args.min_precision,
            min_recall=args.min_recall,
            min_primary_source_rate=args.min_primary_source_rate,
            min_date_accuracy=args.min_date_accuracy,
            min_deduplication_accuracy=args.min_deduplication_accuracy,
            max_unsupported_sources=args.max_unsupported_sources,
            require_independently_reviewed=not args.allow_draft,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        atomic_write_text(args.output, rendered)
        print(f"WROTE: {args.output}")
    else:
        print(rendered, end="")
    if not result["quality_gate"]["passed"]:
        failed = [name for name, passed in result["quality_gate"]["checks"].items() if not passed]
        print(f"QUALITY GATE FAILED: {', '.join(failed)}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
