from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skill" / "daily-trade-radar" / "src"
sys.path.insert(0, str(SRC))

from daily_trade_radar.calibration import calibrate, main as calibration_main
from daily_trade_radar.scoring import SCORE_DIMENSIONS, level_for_score


def breakdown_for_score(score: int) -> dict[str, int]:
    remaining = score
    result: dict[str, int] = {}
    for dimension in sorted(SCORE_DIMENSIONS):
        value = min(2, remaining)
        result[dimension] = value
        remaining -= value
    return result


def balanced_dataset() -> dict:
    scores = [0, 1, 0, 1, 1, 2, 3, 4, 2, 4, 5, 6, 7, 5, 7, 8, 9, 10, 8, 10]
    records = [
        {
            "event_id": f"event-{index:02d}",
            "reviewer": "reviewer-a",
            "score_breakdown": breakdown_for_score(score),
            "score": score,
            "reviewed_level": level_for_score(score),
        }
        for index, score in enumerate(scores)
    ]
    records.append({**records[0], "reviewer": "reviewer-b"})
    return {"records": records}


class CalibrationTest(unittest.TestCase):
    def test_balanced_history_supports_current_thresholds(self) -> None:
        result = calibrate(balanced_dataset())
        self.assertTrue(result["sample_gate"]["sufficient"])
        self.assertEqual(result["recommendation_status"], "current_rules_supported")
        self.assertEqual(result["current_rules"]["accuracy"], 1.0)
        self.assertEqual(result["recommended_candidate"]["thresholds"], {
            "watch_max": 1, "low_max": 4, "medium_max": 7,
        })
        self.assertEqual(result["reviewer_agreement"]["exact_pair_agreement"], 1.0)
        self.assertFalse(result["automatic_rule_change_allowed"])

    def test_tied_human_labels_are_excluded_and_disclosed(self) -> None:
        breakdown = breakdown_for_score(4)
        data = {"records": [
            {"event_id": "tie", "reviewer": "a", "reviewed_level": "low", "score_breakdown": breakdown},
            {"event_id": "tie", "reviewer": "b", "reviewed_level": "medium", "score_breakdown": breakdown},
        ]}
        result = calibrate(data)
        self.assertEqual(result["consensus_event_count"], 0)
        self.assertEqual(result["excluded_conflict_count"], 1)
        self.assertEqual(result["recommendation_status"], "insufficient_data")
        self.assertEqual(result["reviewer_agreement"]["exact_pair_agreement"], 0.0)

    def test_inconsistent_score_or_reviewer_breakdown_fails_closed(self) -> None:
        data = balanced_dataset()
        data["records"][0]["score"] = 10
        with self.assertRaisesRegex(ValueError, "must equal"):
            calibrate(data)
        data = balanced_dataset()
        data["records"][-1]["score_breakdown"] = breakdown_for_score(1)
        data["records"][-1]["score"] = 1
        with self.assertRaisesRegex(ValueError, "different score_breakdown"):
            calibrate(data)

    def test_incremental_gate_blocks_calibration_until_review_is_complete(self) -> None:
        data = balanced_dataset()
        data["incremental_merge"] = {"mode": "preserve_human_scores_fail_closed"}
        data["incremental_diff"] = {
            "calibration_gate": {
                "ready": False,
                "blockers": [{"type": "new_events_require_scoring"}],
            }
        }
        with self.assertRaisesRegex(
            ValueError,
            "incremental calibration gate blocked: new_events_require_scoring",
        ):
            calibrate(data)

        data["incremental_diff"]["calibration_gate"] = {
            "ready": True,
            "blockers": [],
        }
        self.assertTrue(calibrate(data)["sample_gate"]["sufficient"])

    def test_cli_writes_auditable_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "labels.json"
            output = root / "calibration.json"
            source.write_text(json.dumps(balanced_dataset()), encoding="utf-8")
            self.assertEqual(calibration_main([str(source), "--output", str(output)]), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(result["dataset_hash"]), 64)
            self.assertEqual(result["review_record_count"], 21)


if __name__ == "__main__":
    unittest.main()
