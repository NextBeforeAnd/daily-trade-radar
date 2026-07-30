"""Create a draft evaluation-label file from candidate and final radar reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .snapshots.filesystem import atomic_write_text


def _events_by_id(report: dict, label: str) -> dict[str, dict]:
    events = report.get("events")
    if not isinstance(events, list):
        raise ValueError(f"{label}.events must be an array")
    result: dict[str, dict] = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"{label}.events[{index}] must be an object")
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError(f"{label}.events[{index}].id must be a nonblank string")
        if event_id in result:
            raise ValueError(f"duplicate {label} event id: {event_id}")
        result[event_id] = event
    return result


def _review_context(event: dict) -> dict:
    return {
        "title": event.get("title"),
        "jurisdiction": event.get("jurisdiction"),
        "authority": event.get("authority"),
        "source_title": event.get("source_title"),
        "source_url": event.get("source_url"),
    }


def scaffold_labels(candidate_report: dict, final_report: dict, dataset_name: str) -> dict:
    """Build review-ready draft labels without claiming independent ground truth."""
    if not isinstance(dataset_name, str) or not dataset_name.strip():
        raise ValueError("dataset_name must be a nonblank string")
    candidates = _events_by_id(candidate_report, "candidate_report")
    final = _events_by_id(final_report, "final_report")

    records: list[dict] = []
    for event_id in sorted(candidates):
        candidate = candidates[event_id]
        accepted = final.get(event_id)
        if accepted is None:
            records.append({
                "event_id": event_id,
                "should_include": False,
                "review_context": _review_context(candidate),
            })
            continue
        source_url = accepted.get("source_url")
        if not isinstance(source_url, str) or not source_url.strip():
            raise ValueError(f"final event {event_id} must have a source_url")
        records.append({
            "event_id": event_id,
            "should_include": True,
            "accepted_primary_source_urls": [source_url],
            "published_date": accepted.get("published_date"),
            "effective_date": accepted.get("effective_date"),
            "deadline": accepted.get("deadline"),
            "status": accepted.get("status"),
            "level": accepted.get("level"),
            "review_context": _review_context(accepted),
        })

    for event_id in sorted(set(final) - set(candidates)):
        accepted = final[event_id]
        source_url = accepted.get("source_url")
        if not isinstance(source_url, str) or not source_url.strip():
            raise ValueError(f"final event {event_id} must have a source_url")
        records.append({
            "event_id": event_id,
            "should_include": True,
            "accepted_primary_source_urls": [source_url],
            "published_date": accepted.get("published_date"),
            "effective_date": accepted.get("effective_date"),
            "deadline": accepted.get("deadline"),
            "status": accepted.get("status"),
            "level": accepted.get("level"),
            "review_context": _review_context(accepted),
            "review_note": "Present in final report but absent from candidate report; verify provenance.",
        })

    deduplication = final_report.get("deduplication", {})
    matches = deduplication.get("matches", []) if isinstance(deduplication, dict) else []
    if not isinstance(matches, list):
        raise ValueError("final_report.deduplication.matches must be an array")
    deduplication_cases: list[dict] = []
    seen_current_ids: set[str] = set()
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            raise ValueError(f"final_report.deduplication.matches[{index}] must be an object")
        current_id = match.get("current_id")
        previous_id = match.get("previous_id")
        disposition = match.get("disposition")
        if not all(isinstance(value, str) and value.strip() for value in (current_id, previous_id, disposition)):
            continue
        if current_id in seen_current_ids:
            raise ValueError(f"duplicate deduplication current_id: {current_id}")
        seen_current_ids.add(current_id)
        deduplication_cases.append({
            "current_id": current_id,
            "previous_id": previous_id,
            "expected_disposition": disposition,
            "review_context": {
                "similarity": match.get("similarity"),
                "match_method": match.get("match_method"),
                "review_required": match.get("review_required"),
                "change_reasons": match.get("change_reasons", []),
            },
        })

    return {
        "dataset_version": 1,
        "dataset_name": dataset_name.strip(),
        "review_status": "draft",
        "draft_warning": (
            "Generated from the radar's own candidate and final outputs. "
            "An independent reviewer must verify every decision before this becomes ground truth."
        ),
        "source_report_date": final_report.get("report_date"),
        "records": records,
        "deduplication_cases": deduplication_cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_report", type=Path, help="Pre-deduplication candidate JSON")
    parser.add_argument("final_report", type=Path, help="Validated deduplicated radar JSON")
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        candidate = json.loads(args.candidate_report.read_text(encoding="utf-8"))
        final = json.loads(args.final_report.read_text(encoding="utf-8"))
        if not isinstance(candidate, dict) or not isinstance(final, dict):
            raise ValueError("candidate and final report roots must be objects")
        result = scaffold_labels(candidate, final, args.dataset_name)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    atomic_write_text(args.output, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    positives = sum(record["should_include"] for record in result["records"])
    print(
        f"WROTE: {args.output} | candidates={len(result['records'])} "
        f"positives={positives} deduplication_cases={len(result['deduplication_cases'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
