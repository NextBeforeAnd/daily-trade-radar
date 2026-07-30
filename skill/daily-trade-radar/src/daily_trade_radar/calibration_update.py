"""Run fail-closed incremental scoring and calibration as one atomic workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

from .calibration import LEVEL_ORDER, calibrate
from .calibration_scaffold import (
    format_incremental_diff_summary,
    merge_existing_scaffold,
    scaffold_calibration,
)
from .snapshots.filesystem import atomic_write_text


ARTIFACT_NAMES = {
    "scaffold": "calibration-review-scaffold.json",
    "diff": "calibration-diff.json",
    "calibration": "calibration-report.json",
    "update": "calibration-update.json",
}


def _read_object(path: Path, label: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} root must be an object")
    return data


def _metric_snapshot(report: dict | None) -> dict | None:
    if not isinstance(report, dict):
        return None
    current = report.get("current_rules")
    current = current if isinstance(current, dict) else {}
    candidate = report.get("recommended_candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    label_counts = report.get("label_counts")
    label_counts = label_counts if isinstance(label_counts, dict) else {}
    return {
        "consensus_event_count": report.get("consensus_event_count"),
        "label_counts": {level: label_counts.get(level, 0) for level in LEVEL_ORDER},
        "current_thresholds": current.get("thresholds"),
        "current_accuracy": current.get("accuracy"),
        "current_macro_f1": current.get("macro_f1"),
        "current_disagreement_count": current.get("disagreement_count"),
        "recommendation_status": report.get("recommendation_status"),
        "candidate_thresholds": candidate.get("thresholds"),
        "candidate_accuracy": candidate.get("accuracy"),
        "candidate_macro_f1": candidate.get("macro_f1"),
    }


def _numeric_delta(current: object, previous: object) -> float | int | None:
    if isinstance(current, bool) or isinstance(previous, bool):
        return None
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)):
        return None
    value = current - previous
    return round(value, 4) if isinstance(value, float) else value


def compare_calibration_reports(current: dict, previous: dict | None) -> dict:
    """Compare decision-relevant calibration outputs while ignoring metadata-only hash changes."""
    current_snapshot = _metric_snapshot(current)
    previous_snapshot = _metric_snapshot(previous)
    if previous_snapshot is None:
        return {
            "previous_report_supplied": False,
            "decision_relevant_change": None,
            "current": current_snapshot,
            "previous": None,
            "delta": None,
        }
    delta = {
        "consensus_event_count": _numeric_delta(
            current_snapshot["consensus_event_count"],
            previous_snapshot["consensus_event_count"],
        ),
        "label_counts": {
            level: _numeric_delta(
                current_snapshot["label_counts"][level],
                previous_snapshot["label_counts"][level],
            )
            for level in LEVEL_ORDER
        },
        "current_accuracy": _numeric_delta(
            current_snapshot["current_accuracy"], previous_snapshot["current_accuracy"]
        ),
        "current_macro_f1": _numeric_delta(
            current_snapshot["current_macro_f1"], previous_snapshot["current_macro_f1"]
        ),
        "current_disagreement_count": _numeric_delta(
            current_snapshot["current_disagreement_count"],
            previous_snapshot["current_disagreement_count"],
        ),
        "candidate_accuracy": _numeric_delta(
            current_snapshot["candidate_accuracy"], previous_snapshot["candidate_accuracy"]
        ),
        "candidate_macro_f1": _numeric_delta(
            current_snapshot["candidate_macro_f1"], previous_snapshot["candidate_macro_f1"]
        ),
    }
    return {
        "previous_report_supplied": True,
        "decision_relevant_change": current_snapshot != previous_snapshot,
        "current": current_snapshot,
        "previous": previous_snapshot,
        "delta": delta,
    }


def build_update_report(
    scaffold: dict,
    calibration_report: dict | None,
    previous_calibration: dict | None,
    decision_record: dict | None,
) -> dict:
    diff = scaffold["incremental_diff"]
    incremental_ready = diff["calibration_gate"]["ready"]
    comparison = (
        compare_calibration_reports(calibration_report, previous_calibration)
        if calibration_report is not None
        else None
    )
    prior_decision = None
    if isinstance(decision_record, dict):
        candidate = decision_record.get("calibration_decision")
        if isinstance(candidate, dict):
            prior_decision = candidate

    if not incremental_ready:
        status = "human_review_required"
        exit_code = 3
        threshold_status = "not_evaluated"
    elif not calibration_report["sample_gate"]["sufficient"]:
        status = "insufficient_calibration_sample"
        exit_code = 4
        threshold_status = "insufficient_data"
    else:
        status = "calibration_complete"
        exit_code = 0
        if calibration_report["recommendation_status"] == "current_rules_supported":
            threshold_status = "current_rules_supported"
        elif (
            prior_decision is not None
            and comparison is not None
            and comparison["decision_relevant_change"] is False
        ):
            threshold_status = "previous_human_decision_retained"
        else:
            threshold_status = "fresh_human_decision_required"

    return {
        "calibration_update_version": 1,
        "status": status,
        "exit_code": exit_code,
        "artifacts": {
            "scaffold": ARTIFACT_NAMES["scaffold"],
            "diff": ARTIFACT_NAMES["diff"],
            "calibration": ARTIFACT_NAMES["calibration"] if calibration_report else None,
            "update": ARTIFACT_NAMES["update"],
        },
        "incremental_diff_summary": diff["summary"],
        "calibration_gate": diff["calibration_gate"],
        "sample_gate": calibration_report.get("sample_gate") if calibration_report else None,
        "calibration_comparison": comparison,
        "threshold_control": {
            "status": threshold_status,
            "previous_human_decision": prior_decision,
            "automatic_threshold_change_allowed": False,
        },
    }


def run_update(
    manifest: dict,
    labels_directory: Path,
    existing: dict,
    *,
    minimum_samples: int = 20,
    minimum_per_level: int = 3,
    previous_calibration: dict | None = None,
    decision_record: dict | None = None,
) -> tuple[dict, dict | None, dict]:
    if minimum_samples < 1 or minimum_per_level < 1:
        raise ValueError("minimum sample limits must be positive")
    fresh = scaffold_calibration(manifest, labels_directory)
    scaffold = merge_existing_scaffold(fresh, existing)
    calibration_report = None
    if scaffold["incremental_diff"]["calibration_gate"]["ready"]:
        calibration_report = calibrate(scaffold, minimum_samples, minimum_per_level)
    update_report = build_update_report(
        scaffold, calibration_report, previous_calibration, decision_record
    )
    return scaffold, calibration_report, update_report


def _write_bundle(
    output_directory: Path,
    scaffold: dict,
    calibration_report: dict | None,
    update_report: dict,
) -> None:
    parent = output_directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_directory.name}.", dir=parent))
    try:
        artifacts = {
            ARTIFACT_NAMES["scaffold"]: scaffold,
            ARTIFACT_NAMES["diff"]: scaffold["incremental_diff"],
            ARTIFACT_NAMES["update"]: update_report,
        }
        if calibration_report is not None:
            artifacts[ARTIFACT_NAMES["calibration"]] = calibration_report
        for filename, data in artifacts.items():
            atomic_write_text(
                staging / filename,
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            )
        staging.replace(output_directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--existing", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--previous-calibration", type=Path)
    parser.add_argument("--decision-record", type=Path)
    parser.add_argument("--minimum-samples", type=int, default=20)
    parser.add_argument("--minimum-per-level", type=int, default=3)
    args = parser.parse_args(argv)

    if args.output_dir.exists():
        print(f"ERROR: output directory already exists: {args.output_dir}", file=sys.stderr)
        return 1
    input_paths = [args.manifest, args.existing, args.previous_calibration, args.decision_record]
    if any(
        path is not None and path.resolve() == args.output_dir.resolve()
        for path in input_paths
    ):
        print("ERROR: output directory must not be an input path", file=sys.stderr)
        return 2
    try:
        manifest = _read_object(args.manifest, "manifest")
        existing = _read_object(args.existing, "existing calibration scaffold")
        previous = (
            _read_object(args.previous_calibration, "previous calibration report")
            if args.previous_calibration else None
        )
        decision = (
            _read_object(args.decision_record, "calibration decision record")
            if args.decision_record else None
        )
        scaffold, calibration_report, update_report = run_update(
            manifest,
            args.manifest.parent,
            existing,
            minimum_samples=args.minimum_samples,
            minimum_per_level=args.minimum_per_level,
            previous_calibration=previous,
            decision_record=decision,
        )
        _write_bundle(args.output_dir, scaffold, calibration_report, update_report)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"WROTE UPDATE: {args.output_dir}")
    print(format_incremental_diff_summary(scaffold["incremental_diff"]))
    if calibration_report is not None:
        snapshot = update_report["calibration_comparison"]["current"]
        print(
            f"CALIBRATION: {calibration_report['recommendation_status']}"
            f" | samples={snapshot['consensus_event_count']}"
            f" | accuracy={snapshot['current_accuracy']}"
            f" | macro_f1={snapshot['current_macro_f1']}"
        )
    print(f"THRESHOLD CONTROL: {update_report['threshold_control']['status']}")
    return update_report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
