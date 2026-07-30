"""Safely roll a formal calibration baseline back from a verified promotion backup."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

from .calibration_promote import BASELINE_NAMES
from .snapshots.filesystem import FileLock, atomic_write_bytes, atomic_write_text


def _read_object(path: Path, label: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} root must be an object")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validated_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("--rolled-back-at must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--rolled-back-at must include a UTC offset")
    return parsed.isoformat()


def validate_rollback_state(
    backup_directory: Path,
    baseline_directory: Path,
) -> tuple[dict, dict[str, dict], dict[str, Path]]:
    """Fail closed unless the backup and live baseline match one completed promotion."""
    manifest_path = backup_directory / "promotion-manifest.json"
    manifest = _read_object(manifest_path, "promotion manifest")
    if manifest.get("promotion_manifest_version") != 1:
        raise ValueError("unsupported promotion manifest version")
    if manifest.get("status") != "complete":
        raise ValueError("promotion manifest status must be complete and not previously rolled back")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise ValueError("promotion manifest files must be an array")
    expected_names = set(BASELINE_NAMES.values())
    by_name: dict[str, dict] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"promotion manifest files[{index}] must be an object")
        name = record.get("name")
        backup_file = record.get("backup_file")
        if name not in expected_names or backup_file != name:
            raise ValueError("promotion manifest contains an unexpected baseline or backup filename")
        if name in by_name:
            raise ValueError(f"promotion manifest contains duplicate file entry: {name}")
        for hash_field in ("before_sha256", "after_sha256"):
            value = record.get(hash_field)
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"promotion manifest {name}.{hash_field} is invalid")
        by_name[name] = record
    if set(by_name) != expected_names:
        raise ValueError("promotion manifest does not cover the complete formal baseline")

    baseline_paths = {
        name: baseline_directory / filename for name, filename in BASELINE_NAMES.items()
    }
    for path in baseline_paths.values():
        if not path.is_file():
            raise ValueError(f"formal baseline file is missing: {path.name}")
        record = by_name[path.name]
        if _sha256(path) != record["after_sha256"]:
            raise ValueError(
                f"formal baseline drift detected after promotion: {path.name}; refusing rollback"
            )
        backup_path = backup_directory / record["backup_file"]
        if not backup_path.is_file():
            raise ValueError(f"promotion backup file is missing: {backup_path.name}")
        if _sha256(backup_path) != record["before_sha256"]:
            raise ValueError(f"promotion backup hash mismatch: {backup_path.name}")
    return manifest, by_name, baseline_paths


def _publish_pre_rollback_snapshot(
    snapshot_directory: Path,
    backup_directory: Path,
    baseline_paths: dict[str, Path],
    attempt: dict,
) -> None:
    snapshot_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(
        prefix=f".{snapshot_directory.name}.", dir=snapshot_directory.parent
    ))
    try:
        for path in baseline_paths.values():
            shutil.copy2(path, staging / path.name)
            if _sha256(staging / path.name) != _sha256(path):
                raise OSError(f"pre-rollback snapshot verification failed for {path.name}")
        shutil.copy2(
            backup_directory / "promotion-manifest.json",
            staging / "promotion-manifest.before-rollback.json",
        )
        atomic_write_text(
            staging / "rollback-manifest.json",
            json.dumps(attempt, ensure_ascii=False, indent=2) + "\n",
        )
        staging.replace(snapshot_directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def rollback(
    backup_directory: Path,
    baseline_directory: Path,
    pre_rollback_directory: Path,
    *,
    rolled_back_by: str,
    reason: str,
    rolled_back_at: str,
) -> dict:
    if not rolled_back_by.strip():
        raise ValueError("rolled_back_by must be nonblank")
    if not reason.strip():
        raise ValueError("reason must be nonblank")
    rolled_back_at = _validated_time(rolled_back_at)
    if pre_rollback_directory.exists():
        raise ValueError("pre-rollback snapshot directory already exists")
    if not baseline_directory.is_dir():
        raise ValueError("baseline directory must already exist")
    resolved = {
        "backup": backup_directory.resolve(),
        "baseline": baseline_directory.resolve(),
        "pre_rollback": pre_rollback_directory.resolve(),
    }
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("backup, baseline, and pre-rollback directories must be distinct")
    if resolved["pre_rollback"].is_relative_to(resolved["backup"]):
        raise ValueError("pre-rollback snapshot must not be inside the promotion backup")
    if resolved["baseline"].is_relative_to(resolved["backup"]):
        raise ValueError("formal baseline must not be inside the promotion backup")

    manifest, by_name, baseline_paths = validate_rollback_state(
        backup_directory, baseline_directory
    )
    attempt = {
        "rollback_manifest_version": 1,
        "status": "prepared",
        "rolled_back_at": rolled_back_at,
        "rolled_back_by": rolled_back_by,
        "reason": reason,
        "files": [
            {
                "name": path.name,
                "pre_rollback_sha256": by_name[path.name]["after_sha256"],
                "restored_sha256": by_name[path.name]["before_sha256"],
                "pre_rollback_file": path.name,
                "restore_source": by_name[path.name]["backup_file"],
            }
            for path in baseline_paths.values()
        ],
        "recovery": {
            "available": True,
            "instruction": (
                "If rollback fails, restore each pre_rollback_file from this directory "
                "to the formal baseline path with the same name."
            ),
        },
    }

    lock_path = baseline_directory / ".calibration-promote.lock"
    with FileLock(lock_path):
        manifest, by_name, baseline_paths = validate_rollback_state(
            backup_directory, baseline_directory
        )
        _publish_pre_rollback_snapshot(
            pre_rollback_directory, backup_directory, baseline_paths, attempt
        )
        manifest_before_bytes = (
            pre_rollback_directory / "promotion-manifest.before-rollback.json"
        ).read_bytes()
        try:
            manifest["status"] = "rollback_in_progress"
            manifest["rollback"] = {
                "available": False,
                "rolled_back_at": rolled_back_at,
                "rolled_back_by": rolled_back_by,
                "reason": reason,
                "pre_rollback_snapshot": pre_rollback_directory.name,
            }
            atomic_write_text(
                backup_directory / "promotion-manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            for path in baseline_paths.values():
                source = backup_directory / by_name[path.name]["backup_file"]
                atomic_write_bytes(path, source.read_bytes())
            observed = {path.name: _sha256(path) for path in baseline_paths.values()}
            expected = {name: record["before_sha256"] for name, record in by_name.items()}
            if observed != expected:
                raise OSError("formal baseline rollback verification failed")
            manifest["status"] = "rolled_back"
            atomic_write_text(
                backup_directory / "promotion-manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            attempt["status"] = "complete"
            atomic_write_text(
                pre_rollback_directory / "rollback-manifest.json",
                json.dumps(attempt, ensure_ascii=False, indent=2) + "\n",
            )
        except BaseException as exc:
            for path in baseline_paths.values():
                atomic_write_bytes(path, (pre_rollback_directory / path.name).read_bytes())
            atomic_write_bytes(
                backup_directory / "promotion-manifest.json",
                manifest_before_bytes,
            )
            attempt["status"] = "pre_rollback_state_restored_after_error"
            attempt["error"] = str(exc)
            atomic_write_text(
                pre_rollback_directory / "rollback-manifest.json",
                json.dumps(attempt, ensure_ascii=False, indent=2) + "\n",
            )
            raise
    return attempt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_directory", type=Path)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--pre-rollback-dir", type=Path, required=True)
    parser.add_argument("--rolled-back-by", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--rolled-back-at", required=True)
    args = parser.parse_args(argv)
    try:
        rollback(
            args.backup_directory,
            args.baseline_dir,
            args.pre_rollback_dir,
            rolled_back_by=args.rolled_back_by,
            reason=args.reason,
            rolled_back_at=args.rolled_back_at,
        )
    except (OSError, ValueError, TypeError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"ROLLED BACK: {args.baseline_dir}"
        f" | promotion_backup={args.backup_directory}"
        f" | pre_rollback_snapshot={args.pre_rollback_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
