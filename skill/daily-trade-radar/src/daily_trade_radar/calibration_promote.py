"""Promote an approved calibration-update bundle into a recoverable formal baseline."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

from .calibration import CURRENT_THRESHOLDS, calibrate
from .calibration_update import ARTIFACT_NAMES
from .snapshots.filesystem import FileLock, atomic_write_bytes, atomic_write_text


BASELINE_NAMES = {
    "scaffold": "calibration-review-scaffold.json",
    "calibration": "calibration-report.json",
    "readiness": "calibration-readiness.json",
}
DECISIONS = {
    "retain_current_thresholds",
    "accept_candidate_thresholds",
    "defer",
}


def _read_object(path: Path, label: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} root must be an object")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _threshold_dict(values: tuple[int, int, int]) -> dict[str, int]:
    return dict(zip(("watch_max", "low_max", "medium_max"), values))


def _validated_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("--promoted-at must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--promoted-at must include a UTC offset")
    return parsed.isoformat()


def validate_candidate_bundle(update_directory: Path) -> tuple[dict, dict, dict, dict]:
    """Validate cross-artifact identity and independently recompute calibration."""
    paths = {name: update_directory / filename for name, filename in ARTIFACT_NAMES.items()}
    missing = [path.name for path in paths.values() if not path.is_file()]
    if missing:
        raise ValueError(f"candidate update bundle is incomplete: {', '.join(sorted(missing))}")
    scaffold = _read_object(paths["scaffold"], "candidate scaffold")
    diff = _read_object(paths["diff"], "candidate diff")
    calibration = _read_object(paths["calibration"], "candidate calibration report")
    update = _read_object(paths["update"], "candidate update report")

    if update.get("status") != "calibration_complete" or update.get("exit_code") != 0:
        raise ValueError("candidate update status is not calibration_complete")
    artifacts = update.get("artifacts")
    expected_artifacts = {
        "scaffold": ARTIFACT_NAMES["scaffold"],
        "diff": ARTIFACT_NAMES["diff"],
        "calibration": ARTIFACT_NAMES["calibration"],
        "update": ARTIFACT_NAMES["update"],
    }
    if artifacts != expected_artifacts:
        raise ValueError("candidate update artifact manifest does not match the required bundle")
    if scaffold.get("incremental_diff") != diff:
        raise ValueError("candidate scaffold and diff report do not match")
    gate = diff.get("calibration_gate")
    if not isinstance(gate, dict) or gate.get("ready") is not True:
        raise ValueError("candidate incremental calibration gate is not ready")
    sample_gate = calibration.get("sample_gate")
    if not isinstance(sample_gate, dict) or sample_gate.get("sufficient") is not True:
        raise ValueError("candidate calibration sample gate is not sufficient")
    if calibration.get("automatic_rule_change_allowed") is not False:
        raise ValueError("candidate calibration must prohibit automatic rule changes")
    threshold_control = update.get("threshold_control")
    if (
        not isinstance(threshold_control, dict)
        or threshold_control.get("automatic_threshold_change_allowed") is not False
    ):
        raise ValueError("candidate threshold control must prohibit automatic changes")
    minimum_samples = sample_gate.get("minimum_samples")
    minimum_per_level = sample_gate.get("minimum_per_level")
    recomputed = calibrate(scaffold, minimum_samples, minimum_per_level)
    if recomputed != calibration:
        raise ValueError("candidate calibration report does not match an independent recomputation")
    if update.get("calibration_gate") != gate or update.get("sample_gate") != sample_gate:
        raise ValueError("candidate update summary does not match its gate reports")
    return scaffold, diff, calibration, update


def _validate_decision(decision: str, calibration: dict) -> None:
    if decision == "retain_current_thresholds":
        return
    if decision == "defer":
        return
    candidate = calibration.get("recommended_candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    candidate_thresholds = candidate.get("thresholds")
    if not isinstance(candidate_thresholds, dict):
        raise ValueError("no candidate thresholds are available to accept")
    runtime_thresholds = _threshold_dict(CURRENT_THRESHOLDS)
    if candidate_thresholds != runtime_thresholds:
        raise ValueError(
            "accepted candidate thresholds are not implemented in the runtime rules; "
            "update and test the scoring rules separately, then rerun calibration-update"
        )


def build_readiness_record(
    scaffold: dict,
    calibration: dict,
    *,
    decision: str,
    reviewed_by: str,
    reason: str,
    promoted_at: str,
) -> dict:
    current = calibration["current_rules"]
    candidate = calibration.get("recommended_candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    accepted = decision == "accept_candidate_thresholds"
    return {
        "calibration_readiness_version": 2,
        "assessed_at": promoted_at,
        "eligible": True,
        "thresholds_changed": accepted and candidate.get("thresholds") != current.get("thresholds"),
        "review_scaffold": BASELINE_NAMES["scaffold"],
        "sample": scaffold.get("sample"),
        "default_gate": {
            "minimum_consensus_events": calibration["sample_gate"]["minimum_samples"],
            "minimum_events_per_reviewed_level": calibration["sample_gate"]["minimum_per_level"],
            "requires_independent_full_five_dimension_score_breakdown": True,
        },
        "checks": {
            "incremental_gate_ready": True,
            "sample_gate_sufficient": True,
            "independent_full_score_breakdowns_available": True,
        },
        "blockers": [],
        "calibration_run": {
            "report": BASELINE_NAMES["calibration"],
            "dataset_hash": calibration.get("dataset_hash"),
            "recommendation_status": calibration.get("recommendation_status"),
            "current_thresholds": current.get("thresholds"),
            "candidate_thresholds": candidate.get("thresholds"),
            "current_accuracy": current.get("accuracy"),
            "candidate_accuracy": candidate.get("accuracy"),
            "current_macro_f1": current.get("macro_f1"),
            "candidate_macro_f1": candidate.get("macro_f1"),
            "automatic_rule_change_allowed": False,
        },
        "calibration_decision": {
            "decision": decision,
            "decided_by": reviewed_by,
            "decided_at": promoted_at,
            "candidate_adopted": accepted,
            "reason": reason,
        },
        "next_action": (
            "Collect additional independent boundary samples and rerun calibration-update."
            if decision == "retain_current_thresholds"
            else "Monitor the explicitly approved thresholds against new independent samples."
        ),
    }


def _publish_backup(
    backup_directory: Path,
    baseline_paths: dict[str, Path],
    manifest: dict,
) -> None:
    backup_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(
        prefix=f".{backup_directory.name}.", dir=backup_directory.parent
    ))
    try:
        for path in baseline_paths.values():
            shutil.copy2(path, staging / path.name)
            if _sha256(staging / path.name) != _sha256(path):
                raise OSError(f"backup verification failed for {path.name}")
        atomic_write_text(
            staging / "promotion-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
        staging.replace(backup_directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def promote(
    update_directory: Path,
    baseline_directory: Path,
    backup_directory: Path,
    *,
    decision: str,
    reviewed_by: str,
    reason: str,
    promoted_at: str,
) -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(sorted(DECISIONS))}")
    if not reviewed_by.strip():
        raise ValueError("reviewed_by must be nonblank")
    if not reason.strip():
        raise ValueError("reason must be nonblank")
    promoted_at = _validated_time(promoted_at)
    scaffold, _diff, calibration, _update = validate_candidate_bundle(update_directory)
    _validate_decision(decision, calibration)
    if decision == "defer":
        return {
            "promotion_version": 1,
            "status": "deferred",
            "decision": decision,
            "reviewed_by": reviewed_by,
            "reason": reason,
            "promoted_at": promoted_at,
            "baseline_changed": False,
        }
    if not baseline_directory.is_dir():
        raise ValueError("baseline directory must already exist")
    if backup_directory.exists():
        raise ValueError("backup directory already exists")
    resolved = {
        "update": update_directory.resolve(),
        "baseline": baseline_directory.resolve(),
        "backup": backup_directory.resolve(),
    }
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("update, baseline, and backup directories must be distinct")
    if resolved["backup"].is_relative_to(resolved["update"]):
        raise ValueError("backup directory must not be inside the candidate update directory")
    if resolved["baseline"].is_relative_to(resolved["update"]):
        raise ValueError("formal baseline must not be inside the candidate update directory")

    baseline_paths = {
        name: baseline_directory / filename for name, filename in BASELINE_NAMES.items()
    }
    missing = [path.name for path in baseline_paths.values() if not path.is_file()]
    if missing:
        raise ValueError(f"formal baseline is incomplete: {', '.join(sorted(missing))}")
    readiness = build_readiness_record(
        scaffold,
        calibration,
        decision=decision,
        reviewed_by=reviewed_by,
        reason=reason,
        promoted_at=promoted_at,
    )
    promoted_data = {
        "scaffold": scaffold,
        "calibration": calibration,
        "readiness": readiness,
    }
    before_hashes = {name: _sha256(path) for name, path in baseline_paths.items()}
    promoted_text = {
        name: json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        for name, data in promoted_data.items()
    }
    after_hashes = {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in promoted_text.items()
    }
    manifest = {
        "promotion_manifest_version": 1,
        "status": "prepared",
        "promoted_at": promoted_at,
        "reviewed_by": reviewed_by,
        "decision": decision,
        "reason": reason,
        "baseline_changed": True,
        "files": [
            {
                "name": baseline_paths[name].name,
                "before_sha256": before_hashes[name],
                "after_sha256": after_hashes[name],
                "backup_file": baseline_paths[name].name,
            }
            for name in ("scaffold", "calibration", "readiness")
        ],
        "rollback": {
            "available": True,
            "instruction": "Restore each backup_file to the formal baseline path with the same name.",
        },
        "candidate_bundle_sha256": {
            filename: _sha256(update_directory / filename)
            for filename in ARTIFACT_NAMES.values()
        },
    }

    lock_path = baseline_directory / ".calibration-promote.lock"
    with FileLock(lock_path):
        _publish_backup(backup_directory, baseline_paths, manifest)
        try:
            for name, path in baseline_paths.items():
                atomic_write_text(path, promoted_text[name])
            observed_hashes = {name: _sha256(path) for name, path in baseline_paths.items()}
            if observed_hashes != after_hashes:
                raise OSError("formal baseline write verification failed")
        except BaseException as exc:
            for path in baseline_paths.values():
                atomic_write_bytes(path, (backup_directory / path.name).read_bytes())
            manifest["status"] = "rolled_back_after_error"
            manifest["error"] = str(exc)
            atomic_write_text(
                backup_directory / "promotion-manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            raise
        manifest["status"] = "complete"
        atomic_write_text(
            backup_directory / "promotion-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("update_directory", type=Path)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--decision", choices=sorted(DECISIONS), required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--promoted-at", required=True)
    args = parser.parse_args(argv)
    try:
        result = promote(
            args.update_directory,
            args.baseline_dir,
            args.backup_dir,
            decision=args.decision,
            reviewed_by=args.reviewed_by,
            reason=args.reason,
            promoted_at=args.promoted_at,
        )
    except (OSError, ValueError, TypeError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if result["status"] == "deferred":
        print("PROMOTION DEFERRED: formal baseline unchanged")
        return 3
    print(
        f"PROMOTED: {args.update_directory} -> {args.baseline_dir}"
        f" | decision={args.decision} | backup={args.backup_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
