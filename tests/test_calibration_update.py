from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skill" / "daily-trade-radar" / "src"
sys.path.insert(0, str(SRC))

from daily_trade_radar.calibration import calibrate
from daily_trade_radar.calibration_scaffold import scaffold_calibration
from daily_trade_radar.calibration_update import compare_calibration_reports
from daily_trade_radar.cli import main as cli_main


LEVEL_SCORES = {"watch": 0, "low": 2, "medium": 5, "high": 8}


def label_record(level: str, index: int) -> dict:
    return {
        "event_id": f"event-{level}-{index}",
        "should_include": True,
        "accepted_primary_source_urls": [f"https://authority.example/{level}/{index}"],
        "published_date": "2026-07-30",
        "effective_date": "2026-08-01",
        "deadline": None,
        "status": "new",
        "level": level,
        "review_context": {
            "title": f"{level} event {index}",
            "jurisdiction": "test",
            "authority": "Example Authority",
            "source_title": f"Official {level} notice {index}",
            "source_url": f"https://authority.example/{level}/{index}",
        },
    }


def reviewed_labels(*, include_new: bool = False) -> dict:
    records = [label_record(level, index) for index, level in enumerate(LEVEL_SCORES)]
    if include_new:
        records.append(label_record("high", 99))
    return {
        "dataset_version": 1,
        "dataset_name": "calibration-update-test",
        "review_status": "independently_reviewed",
        "reviewed_by": "fixture-reviewer",
        "reviewed_at": "2026-07-30T12:00:00+08:00",
        "records": records,
    }


def score_scaffold(scaffold: dict) -> None:
    for record in scaffold["records"]:
        score = LEVEL_SCORES[record["reviewed_level"]]
        remaining = score
        breakdown = {}
        for dimension in sorted(record["score_breakdown"]):
            value = min(2, remaining)
            breakdown[dimension] = value
            remaining -= value
        record["score_breakdown"] = breakdown
        record["score"] = score


class CalibrationUpdateTest(unittest.TestCase):
    def test_ready_pipeline_writes_complete_atomic_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            labels_path = root / "run-a.labels.json"
            manifest_path = root / "manifest.json"
            existing_path = root / "existing.json"
            previous_path = root / "previous-calibration.json"
            output_directory = root / "update-2026-07-30"
            labels_path.write_text(json.dumps(reviewed_labels()), encoding="utf-8")
            manifest = {"files": [labels_path.name]}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            existing = scaffold_calibration(manifest, root)
            score_scaffold(existing)
            existing_path.write_text(json.dumps(existing), encoding="utf-8")
            previous_path.write_text(json.dumps(calibrate(existing, 4, 1)), encoding="utf-8")

            self.assertEqual(cli_main([
                "calibration-update",
                str(manifest_path),
                "--existing",
                str(existing_path),
                "--output-dir",
                str(output_directory),
                "--previous-calibration",
                str(previous_path),
                "--minimum-samples",
                "4",
                "--minimum-per-level",
                "1",
            ]), 0)

            self.assertEqual(
                {path.name for path in output_directory.iterdir()},
                {
                    "calibration-review-scaffold.json",
                    "calibration-diff.json",
                    "calibration-report.json",
                    "calibration-update.json",
                },
            )
            update = json.loads(
                (output_directory / "calibration-update.json").read_text(encoding="utf-8")
            )
            self.assertEqual(update["status"], "calibration_complete")
            self.assertTrue(update["calibration_gate"]["ready"])
            self.assertFalse(update["calibration_comparison"]["decision_relevant_change"])
            self.assertFalse(update["threshold_control"]["automatic_threshold_change_allowed"])

    def test_blocked_pipeline_writes_review_bundle_without_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_path = root / "old.labels.json"
            new_path = root / "new.labels.json"
            manifest_path = root / "manifest.json"
            existing_path = root / "existing.json"
            output_directory = root / "blocked-update"
            old_path.write_text(json.dumps(reviewed_labels()), encoding="utf-8")
            existing = scaffold_calibration({"files": [old_path.name]}, root)
            score_scaffold(existing)
            existing_path.write_text(json.dumps(existing), encoding="utf-8")
            new_path.write_text(json.dumps(reviewed_labels(include_new=True)), encoding="utf-8")
            manifest_path.write_text(json.dumps({"files": [new_path.name]}), encoding="utf-8")

            self.assertEqual(cli_main([
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
            ]), 3)

            self.assertFalse((output_directory / "calibration-report.json").exists())
            update = json.loads(
                (output_directory / "calibration-update.json").read_text(encoding="utf-8")
            )
            self.assertEqual(update["status"], "human_review_required")
            self.assertEqual(update["incremental_diff_summary"]["new_unscored"], 1)
            self.assertEqual(update["threshold_control"]["status"], "not_evaluated")

    def test_pipeline_refuses_to_overwrite_an_existing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_directory = root / "existing-output"
            output_directory.mkdir()
            marker = output_directory / "human-work.txt"
            marker.write_text("keep", encoding="utf-8")

            self.assertEqual(cli_main([
                "calibration-update",
                str(root / "missing-manifest.json"),
                "--existing",
                str(root / "missing-existing.json"),
                "--output-dir",
                str(output_directory),
            ]), 1)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_ready_but_insufficient_sample_returns_four_with_calibration_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            labels_path = root / "run-a.labels.json"
            manifest_path = root / "manifest.json"
            existing_path = root / "existing.json"
            output_directory = root / "insufficient-update"
            labels_path.write_text(json.dumps(reviewed_labels()), encoding="utf-8")
            manifest = {"files": [labels_path.name]}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            existing = scaffold_calibration(manifest, root)
            score_scaffold(existing)
            existing_path.write_text(json.dumps(existing), encoding="utf-8")

            self.assertEqual(cli_main([
                "calibration-update",
                str(manifest_path),
                "--existing",
                str(existing_path),
                "--output-dir",
                str(output_directory),
            ]), 4)
            self.assertTrue((output_directory / "calibration-report.json").exists())
            update = json.loads(
                (output_directory / "calibration-update.json").read_text(encoding="utf-8")
            )
            self.assertEqual(update["status"], "insufficient_calibration_sample")
            self.assertEqual(update["threshold_control"]["status"], "insufficient_data")

    def test_comparison_ignores_dataset_hash_only_changes(self) -> None:
        current = {
            "dataset_hash": "new",
            "consensus_event_count": 4,
            "label_counts": {level: 1 for level in LEVEL_SCORES},
            "current_rules": {
                "thresholds": {"watch_max": 1, "low_max": 4, "medium_max": 7},
                "accuracy": 1.0,
                "macro_f1": 1.0,
                "disagreement_count": 0,
            },
            "recommendation_status": "current_rules_supported",
            "recommended_candidate": {
                "thresholds": {"watch_max": 1, "low_max": 4, "medium_max": 7},
                "accuracy": 1.0,
                "macro_f1": 1.0,
            },
        }
        previous = {**current, "dataset_hash": "old"}
        result = compare_calibration_reports(current, previous)
        self.assertFalse(result["decision_relevant_change"])


if __name__ == "__main__":
    unittest.main()
