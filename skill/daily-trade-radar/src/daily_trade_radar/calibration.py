"""Audit historical human labels against deterministic Daily Trade Radar scoring."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
from pathlib import Path
from statistics import mean
import sys

from .scoring import SCORE_DIMENSIONS
from .snapshots.filesystem import atomic_write_text


LEVEL_ORDER = ("watch", "low", "medium", "high")
CURRENT_THRESHOLDS = (1, 4, 7)


def _require_incremental_calibration_gate(data: dict) -> None:
    """Prevent an incremental worksheet with unresolved changes from being calibrated."""
    if "incremental_merge" not in data:
        return
    report = data.get("incremental_diff")
    if not isinstance(report, dict):
        raise ValueError("incremental calibration input is missing incremental_diff")
    gate = report.get("calibration_gate")
    if not isinstance(gate, dict) or not isinstance(gate.get("ready"), bool):
        raise ValueError("incremental calibration input has an invalid calibration_gate")
    if not gate["ready"]:
        blockers = gate.get("blockers")
        blocker_types = [
            item.get("type")
            for item in blockers if isinstance(item, dict) and isinstance(item.get("type"), str)
        ] if isinstance(blockers, list) else []
        detail = ", ".join(blocker_types) or "unresolved incremental changes"
        raise ValueError(f"incremental calibration gate blocked: {detail}")


def _level_with_thresholds(score: int, thresholds: tuple[int, int, int]) -> str:
    watch_max, low_max, medium_max = thresholds
    if score <= watch_max:
        return "watch"
    if score <= low_max:
        return "low"
    if score <= medium_max:
        return "medium"
    return "high"


def _validated_records(data: dict) -> list[dict]:
    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a non-empty array")
    validated: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for index, record in enumerate(records):
        label = f"records[{index}]"
        if not isinstance(record, dict):
            raise ValueError(f"{label} must be an object")
        event_id = record.get("event_id")
        reviewer = record.get("reviewer")
        reviewed_level = record.get("reviewed_level")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError(f"{label}.event_id must be a nonblank string")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError(f"{label}.reviewer must be a nonblank string")
        if reviewed_level not in LEVEL_ORDER:
            raise ValueError(f"{label}.reviewed_level is invalid")
        key = (event_id, reviewer)
        if key in seen:
            raise ValueError(f"duplicate review for event/reviewer: {event_id} / {reviewer}")
        seen.add(key)
        breakdown = record.get("score_breakdown")
        if not isinstance(breakdown, dict) or set(breakdown) != set(SCORE_DIMENSIONS):
            raise ValueError(f"{label}.score_breakdown must contain exactly the five score dimensions")
        normalized_breakdown: dict[str, int] = {}
        for dimension in sorted(SCORE_DIMENSIONS):
            value = breakdown[dimension]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2:
                raise ValueError(f"{label}.score_breakdown.{dimension} must be an integer 0..2")
            normalized_breakdown[dimension] = value
        score = sum(normalized_breakdown.values())
        if "score" in record and record["score"] != score:
            raise ValueError(f"{label}.score must equal score_breakdown total {score}")
        validated.append({
            "event_id": event_id,
            "reviewer": reviewer,
            "reviewed_level": reviewed_level,
            "score": score,
            "score_breakdown": normalized_breakdown,
        })
    return validated


def _consensus(records: list[dict]) -> tuple[list[dict], list[str], dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record["event_id"]].append(record)
    consensus: list[dict] = []
    conflicts: list[str] = []
    pair_total = 0
    exact_total = 0
    weighted_total = 0.0
    for event_id, reviews in sorted(grouped.items()):
        breakdowns = {json.dumps(item["score_breakdown"], sort_keys=True) for item in reviews}
        if len(breakdowns) != 1:
            raise ValueError(f"reviewers supplied different score_breakdown values for event: {event_id}")
        for left, right in itertools.combinations(reviews, 2):
            pair_total += 1
            left_index = LEVEL_ORDER.index(left["reviewed_level"])
            right_index = LEVEL_ORDER.index(right["reviewed_level"])
            exact_total += left_index == right_index
            weighted_total += 1 - abs(left_index - right_index) / (len(LEVEL_ORDER) - 1)
        counts = Counter(item["reviewed_level"] for item in reviews)
        highest = max(counts.values())
        winners = [level for level, count in counts.items() if count == highest]
        if len(winners) != 1:
            conflicts.append(event_id)
            continue
        first = reviews[0]
        consensus.append({
            "event_id": event_id,
            "score": first["score"],
            "score_breakdown": first["score_breakdown"],
            "reviewed_level": winners[0],
            "review_count": len(reviews),
        })
    agreement = {
        "reviewed_event_count": sum(len(items) > 1 for items in grouped.values()),
        "review_pair_count": pair_total,
        "exact_pair_agreement": round(exact_total / pair_total, 4) if pair_total else None,
        "distance_weighted_pair_agreement": round(weighted_total / pair_total, 4) if pair_total else None,
        "consensus_conflict_event_ids": conflicts,
    }
    return consensus, conflicts, agreement


def _metrics(events: list[dict], thresholds: tuple[int, int, int]) -> dict:
    matrix = {actual: {predicted: 0 for predicted in LEVEL_ORDER} for actual in LEVEL_ORDER}
    for event in events:
        predicted = _level_with_thresholds(event["score"], thresholds)
        matrix[event["reviewed_level"]][predicted] += 1
    total = len(events)
    correct = sum(matrix[level][level] for level in LEVEL_ORDER)
    f1_values: list[float] = []
    for level in LEVEL_ORDER:
        true_positive = matrix[level][level]
        false_positive = sum(matrix[actual][level] for actual in LEVEL_ORDER if actual != level)
        false_negative = sum(matrix[level][predicted] for predicted in LEVEL_ORDER if predicted != level)
        denominator = 2 * true_positive + false_positive + false_negative
        f1_values.append((2 * true_positive / denominator) if denominator else 0.0)
    return {
        "thresholds": {"watch_max": thresholds[0], "low_max": thresholds[1], "medium_max": thresholds[2]},
        "accuracy": round(correct / total, 4) if total else 0.0,
        "macro_f1": round(mean(f1_values), 4),
        "confusion_matrix": matrix,
        "disagreement_count": total - correct,
    }


def calibrate(data: dict, minimum_samples: int = 20, minimum_per_level: int = 3) -> dict:
    if minimum_samples < 1 or minimum_per_level < 1:
        raise ValueError("minimum sample limits must be positive")
    _require_incremental_calibration_gate(data)
    records = _validated_records(data)
    events, conflicts, agreement = _consensus(records)
    label_counts = Counter(event["reviewed_level"] for event in events)
    sufficient = len(events) >= minimum_samples and all(label_counts[level] >= minimum_per_level for level in LEVEL_ORDER)
    current = _metrics(events, CURRENT_THRESHOLDS)
    recommendation = None
    status = "insufficient_data"
    if sufficient:
        candidates = [_metrics(events, thresholds) for thresholds in itertools.combinations(range(10), 3)]
        candidates.sort(key=lambda item: (
            -item["macro_f1"],
            -item["accuracy"],
            sum(abs(item["thresholds"][name] - value) for name, value in zip(
                ("watch_max", "low_max", "medium_max"), CURRENT_THRESHOLDS
            )),
            tuple(item["thresholds"].values()),
        ))
        recommendation = candidates[0]
        status = "current_rules_supported" if recommendation["thresholds"] == current["thresholds"] else "candidate_change_requires_review"

    dimension_means: dict[str, dict[str, float | None]] = {}
    for level in LEVEL_ORDER:
        level_events = [event for event in events if event["reviewed_level"] == level]
        dimension_means[level] = {
            dimension: round(mean(event["score_breakdown"][dimension] for event in level_events), 3)
            if level_events else None
            for dimension in sorted(SCORE_DIMENSIONS)
        }
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "calibration_version": 1,
        "dataset_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "review_record_count": len(records),
        "consensus_event_count": len(events),
        "excluded_conflict_count": len(conflicts),
        "label_counts": {level: label_counts[level] for level in LEVEL_ORDER},
        "sample_gate": {
            "minimum_samples": minimum_samples,
            "minimum_per_level": minimum_per_level,
            "sufficient": sufficient,
        },
        "reviewer_agreement": agreement,
        "current_rules": current,
        "recommendation_status": status,
        "recommended_candidate": recommendation,
        "dimension_means_by_reviewed_level": dimension_means,
        "automatic_rule_change_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--minimum-samples", type=int, default=20)
    parser.add_argument("--minimum-per-level", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("calibration input root must be an object")
        result = calibrate(data, args.minimum_samples, args.minimum_per_level)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        atomic_write_text(args.output, rendered)
        print(f"WROTE: {args.output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
