"""Aggregate multiple independently reviewed radar evaluations by run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from .evaluation import evaluate
from .snapshots.filesystem import atomic_write_text


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0


def _run_name(label_filename: str) -> str:
    suffix = ".labels.json"
    if not label_filename.endswith(suffix):
        raise ValueError(f"manifest label file must end with {suffix}: {label_filename}")
    return label_filename[:-len(suffix)]


def evaluate_history(manifest: dict, labels_directory: Path, reports_directory: Path, *,
                     minimum_positive_events: int = 20, min_precision: float = 0.9,
                     min_recall: float = 0.9, min_primary_source_rate: float = 0.95,
                     min_date_accuracy: float = 0.98,
                     min_deduplication_accuracy: float = 0.9,
                     max_unsupported_sources: int = 0) -> dict:
    """Evaluate every manifest run and return micro-aggregated benchmark metrics."""
    files = manifest.get("files")
    if not isinstance(files, list) or not files or any(not isinstance(item, str) for item in files):
        raise ValueError("manifest.files must be a non-empty string array")
    if len(files) != len(set(files)):
        raise ValueError("manifest.files must not contain duplicates")

    totals = {
        "candidates": 0, "positives": 0, "negatives": 0, "predicted": 0,
        "true_positive": 0, "false_positive": 0, "false_negative": 0,
        "source_correct": 0, "date_correct": 0, "date_total": 0,
        "status_correct": 0, "level_correct": 0, "dedup_correct": 0, "dedup_total": 0,
    }
    independently_reviewed = True
    unsupported: list[str] = []
    field_errors = {name: [] for name in (
        "source", "published_date", "effective_date", "deadline", "status", "level"
    )}
    dedup_errors: list[str] = []
    false_positives: list[str] = []
    false_negatives: list[str] = []
    run_results: list[dict] = []

    for label_filename in files:
        run = _run_name(label_filename)
        label_path = labels_directory / label_filename
        report_path = reports_directory / run / "deduplicated.json"
        labels = json.loads(label_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(labels, dict) or not isinstance(report, dict):
            raise ValueError(f"{run}: report and labels roots must be objects")
        result = evaluate(
            report, labels, minimum_positive_events=1, min_precision=0,
            min_recall=0, min_primary_source_rate=0, min_date_accuracy=0,
            min_deduplication_accuracy=0, max_unsupported_sources=10**9,
        )
        sample = result["sample"]
        detection = result["detection"]
        factual = result["factual"]
        deduplication = result["deduplication"]
        independently_reviewed &= result["review_status"] == "independently_reviewed"
        totals["candidates"] += sample["labeled_candidate_count"]
        totals["positives"] += sample["positive_event_count"]
        totals["negatives"] += sample["negative_event_count"]
        totals["predicted"] += sample["predicted_event_count"]
        totals["true_positive"] += detection["true_positive_count"]
        totals["false_positive"] += detection["false_positive_count"]
        totals["false_negative"] += detection["false_negative_count"]
        totals["source_correct"] += detection["true_positive_count"] - len(factual["field_error_ids"]["source"])
        totals["date_total"] += detection["true_positive_count"] * 3
        totals["date_correct"] += detection["true_positive_count"] * 3 - sum(
            len(factual["field_error_ids"][field])
            for field in ("published_date", "effective_date", "deadline")
        )
        totals["status_correct"] += detection["true_positive_count"] - len(factual["field_error_ids"]["status"])
        totals["level_correct"] += detection["true_positive_count"] - len(factual["field_error_ids"]["level"])
        totals["dedup_total"] += sample["deduplication_case_count"]
        totals["dedup_correct"] += deduplication["correct_count"]

        prefix = f"{run}:"
        false_positives.extend(prefix + item for item in detection["false_positive_ids"])
        false_negatives.extend(prefix + item for item in detection["false_negative_ids"])
        unsupported.extend(prefix + item for item in factual["unsupported_source_ids"])
        dedup_errors.extend(prefix + item for item in deduplication["error_ids"])
        for field, identifiers in factual["field_error_ids"].items():
            field_errors[field].extend(prefix + item for item in identifiers)
        run_results.append({
            "run": run,
            "labels_hash": result["labels_hash"],
            "report_hash": result["report_hash"],
            "sample": sample,
            "detection": detection,
            "factual": factual,
            "deduplication": deduplication,
        })

    precision = _ratio(totals["true_positive"], totals["predicted"])
    recall = _ratio(totals["true_positive"], totals["positives"])
    primary_source_rate = _ratio(totals["source_correct"], totals["true_positive"])
    date_accuracy = _ratio(totals["date_correct"], totals["date_total"])
    status_accuracy = _ratio(totals["status_correct"], totals["true_positive"])
    level_accuracy = _ratio(totals["level_correct"], totals["true_positive"])
    deduplication_accuracy = _ratio(totals["dedup_correct"], totals["dedup_total"])
    checks = {
        "independently_reviewed": independently_reviewed,
        "minimum_positive_events": totals["positives"] >= minimum_positive_events,
        "precision": precision is not None and precision >= min_precision,
        "recall": recall is not None and recall >= min_recall,
        "primary_source_rate": primary_source_rate is not None and primary_source_rate >= min_primary_source_rate,
        "date_accuracy": date_accuracy is not None and date_accuracy >= min_date_accuracy,
        "deduplication_accuracy": (
            deduplication_accuracy is not None and deduplication_accuracy >= min_deduplication_accuracy
        ),
        "unsupported_sources": len(unsupported) <= max_unsupported_sources,
    }
    hashes = "".join(item["labels_hash"] + item["report_hash"] for item in run_results)
    return {
        "history_evaluation_version": 1,
        "dataset_name": manifest.get("dataset_name", "daily-trade-radar-history"),
        "dataset_hash": hashlib.sha256(hashes.encode("ascii")).hexdigest(),
        "run_count": len(run_results),
        "sample": {
            "labeled_candidate_count": totals["candidates"],
            "positive_event_count": totals["positives"],
            "negative_event_count": totals["negatives"],
            "predicted_event_count": totals["predicted"],
            "deduplication_case_count": totals["dedup_total"],
        },
        "detection": {
            "true_positive_count": totals["true_positive"],
            "false_positive_count": totals["false_positive"],
            "false_negative_count": totals["false_negative"],
            "precision": precision, "recall": recall, "f1": _f1(precision, recall),
            "false_positive_ids": false_positives, "false_negative_ids": false_negatives,
        },
        "factual": {
            "primary_source_rate": primary_source_rate, "date_accuracy": date_accuracy,
            "status_accuracy": status_accuracy, "level_accuracy": level_accuracy,
            "unsupported_source_count": len(unsupported), "unsupported_source_ids": unsupported,
            "field_error_ids": field_errors,
        },
        "deduplication": {
            "accuracy": deduplication_accuracy, "correct_count": totals["dedup_correct"],
            "error_ids": dedup_errors,
        },
        "quality_gate": {
            "passed": all(checks.values()), "checks": checks,
            "thresholds": {
                "minimum_positive_events": minimum_positive_events,
                "min_precision": min_precision, "min_recall": min_recall,
                "min_primary_source_rate": min_primary_source_rate,
                "min_date_accuracy": min_date_accuracy,
                "min_deduplication_accuracy": min_deduplication_accuracy,
                "max_unsupported_sources": max_unsupported_sources,
            },
        },
        "runs": run_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Manifest containing label filenames")
    parser.add_argument("reports_directory", type=Path, help="Directory containing one run directory per label set")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-positive-events", type=int, default=20)
    parser.add_argument("--min-precision", type=float, default=0.9)
    parser.add_argument("--min-recall", type=float, default=0.9)
    parser.add_argument("--min-primary-source-rate", type=float, default=0.95)
    parser.add_argument("--min-date-accuracy", type=float, default=0.98)
    parser.add_argument("--min-deduplication-accuracy", type=float, default=0.9)
    parser.add_argument("--max-unsupported-sources", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest root must be an object")
        result = evaluate_history(
            manifest, args.manifest.parent, args.reports_directory,
            minimum_positive_events=args.minimum_positive_events,
            min_precision=args.min_precision, min_recall=args.min_recall,
            min_primary_source_rate=args.min_primary_source_rate,
            min_date_accuracy=args.min_date_accuracy,
            min_deduplication_accuracy=args.min_deduplication_accuracy,
            max_unsupported_sources=args.max_unsupported_sources,
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
