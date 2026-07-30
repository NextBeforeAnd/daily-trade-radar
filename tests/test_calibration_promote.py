from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skill" / "daily-trade-radar" / "src"
sys.path.insert(0, str(SRC))

from daily_trade_radar.calibration_scaffold import scaffold_calibration
from daily_trade_radar.cli import main as cli_main
from daily_trade_radar import calibration_promote as promotion_module
from tests.test_calibration_update import reviewed_labels, score_scaffold


BASELINE_FILES = {
    "calibration-review-scaffold.json",
    "calibration-report.json",
    "calibration-readiness.json",
}


def create_ready_update(root: Path, *, medium_score: int = 5) -> Path:
    labels_path = root / "run-a.labels.json"
    manifest_path = root / "manifest.json"
    existing_path = root / "existing.json"
    output_directory = root / "candidate-update"
    labels_path.write_text(json.dumps(reviewed_labels()), encoding="utf-8")
    manifest = {"files": [labels_path.name]}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    existing = scaffold_calibration(manifest, root)
    score_scaffold(existing)
    if medium_score != 5:
        record = next(item for item in existing["records"] if item["reviewed_level"] == "medium")
        remaining = medium_score
        for dimension in sorted(record["score_breakdown"]):
            record["score_breakdown"][dimension] = min(2, remaining)
            remaining -= record["score_breakdown"][dimension]
        record["score"] = medium_score
    existing_path.write_text(json.dumps(existing), encoding="utf-8")
    code = cli_main([
        "calibration-update",
        str(manifest_path),
        "--existing",
        str(existing_path),
        "--output-dir",
        str(output_directory),
        "--minimum-samples",
        "4",
        "--minimum-per-level",
        "1",
    ])
    if code != 0:
        raise AssertionError(f"fixture calibration-update failed with exit code {code}")
    return output_directory


def create_baseline(root: Path) -> tuple[Path, dict[str, str]]:
    baseline = root / "formal-baseline"
    baseline.mkdir()
    contents = {}
    for filename in BASELINE_FILES:
        content = json.dumps({"formal": "old", "filename": filename}) + "\n"
        (baseline / filename).write_text(content, encoding="utf-8")
        contents[filename] = content
    return baseline, contents


class CalibrationPromoteTest(unittest.TestCase):
    def test_promote_replaces_baseline_and_publishes_recoverable_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            update = create_ready_update(root)
            baseline, old_contents = create_baseline(root)
            backup = root / "backups" / "promotion-001"

            self.assertEqual(cli_main([
                "calibration-promote",
                str(update),
                "--baseline-dir",
                str(baseline),
                "--backup-dir",
                str(backup),
                "--decision",
                "retain_current_thresholds",
                "--reviewed-by",
                "workspace owner",
                "--reason",
                "Boundary evidence remains insufficient for a threshold change.",
                "--promoted-at",
                "2026-07-30T18:00:00+08:00",
            ]), 0)

            for filename, content in old_contents.items():
                self.assertEqual((backup / filename).read_text(encoding="utf-8"), content)
            manifest = json.loads(
                (backup / "promotion-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "complete")
            self.assertTrue(manifest["rollback"]["available"])
            readiness = json.loads(
                (baseline / "calibration-readiness.json").read_text(encoding="utf-8")
            )
            self.assertEqual(readiness["calibration_readiness_version"], 2)
            self.assertEqual(
                readiness["calibration_decision"]["decision"],
                "retain_current_thresholds",
            )
            self.assertEqual(
                json.loads((baseline / "calibration-review-scaffold.json").read_text(encoding="utf-8")),
                json.loads((update / "calibration-review-scaffold.json").read_text(encoding="utf-8")),
            )

    def test_tampered_candidate_is_rejected_without_touching_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            update = create_ready_update(root)
            baseline, old_contents = create_baseline(root)
            backup = root / "backup"
            diff_path = update / "calibration-diff.json"
            diff = json.loads(diff_path.read_text(encoding="utf-8"))
            diff["tampered"] = True
            diff_path.write_text(json.dumps(diff), encoding="utf-8")

            self.assertEqual(cli_main([
                "calibration-promote",
                str(update),
                "--baseline-dir",
                str(baseline),
                "--backup-dir",
                str(backup),
                "--decision",
                "retain_current_thresholds",
                "--reviewed-by",
                "reviewer",
                "--reason",
                "test",
                "--promoted-at",
                "2026-07-30T18:00:00+08:00",
            ]), 1)
            self.assertFalse(backup.exists())
            for filename, content in old_contents.items():
                self.assertEqual((baseline / filename).read_text(encoding="utf-8"), content)

    def test_defer_is_an_explicit_zero_mutation_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            update = create_ready_update(root)
            baseline, old_contents = create_baseline(root)
            backup = root / "backup"

            self.assertEqual(cli_main([
                "calibration-promote",
                str(update),
                "--baseline-dir",
                str(baseline),
                "--backup-dir",
                str(backup),
                "--decision",
                "defer",
                "--reviewed-by",
                "reviewer",
                "--reason",
                "Wait for more samples.",
                "--promoted-at",
                "2026-07-30T18:00:00+08:00",
            ]), 3)
            self.assertFalse(backup.exists())
            for filename, content in old_contents.items():
                self.assertEqual((baseline / filename).read_text(encoding="utf-8"), content)

    def test_candidate_threshold_acceptance_requires_separate_runtime_rule_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            update = create_ready_update(root, medium_score=4)
            baseline, old_contents = create_baseline(root)
            backup = root / "backup"

            self.assertEqual(cli_main([
                "calibration-promote",
                str(update),
                "--baseline-dir",
                str(baseline),
                "--backup-dir",
                str(backup),
                "--decision",
                "accept_candidate_thresholds",
                "--reviewed-by",
                "reviewer",
                "--reason",
                "Test explicit acceptance guard.",
                "--promoted-at",
                "2026-07-30T18:00:00+08:00",
            ]), 1)
            self.assertFalse(backup.exists())
            for filename, content in old_contents.items():
                self.assertEqual((baseline / filename).read_text(encoding="utf-8"), content)

    def test_write_failure_restores_every_baseline_file_and_marks_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            update = create_ready_update(root)
            baseline, old_contents = create_baseline(root)
            backup = root / "backup"
            real_write = promotion_module.atomic_write_text
            failure_injected = False

            def flaky_write(path: Path, text: str) -> None:
                nonlocal failure_injected
                if (
                    not failure_injected
                    and path.parent == baseline
                    and path.name == "calibration-report.json"
                ):
                    failure_injected = True
                    raise OSError("injected promotion failure")
                real_write(path, text)

            with patch.object(promotion_module, "atomic_write_text", side_effect=flaky_write):
                with self.assertRaisesRegex(OSError, "injected promotion failure"):
                    promotion_module.promote(
                        update,
                        baseline,
                        backup,
                        decision="retain_current_thresholds",
                        reviewed_by="reviewer",
                        reason="rollback test",
                        promoted_at="2026-07-30T18:00:00+08:00",
                    )

            for filename, content in old_contents.items():
                self.assertEqual((baseline / filename).read_text(encoding="utf-8"), content)
            manifest = json.loads(
                (backup / "promotion-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "rolled_back_after_error")
            self.assertTrue(manifest["rollback"]["available"])


if __name__ == "__main__":
    unittest.main()
