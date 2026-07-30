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

from daily_trade_radar import calibration_rollback as rollback_module
from daily_trade_radar.calibration_promote import promote
from daily_trade_radar.cli import main as cli_main
from tests.test_calibration_promote import create_baseline, create_ready_update


def create_promoted_baseline(root: Path) -> tuple[Path, Path, dict[str, str], dict[str, str]]:
    update = create_ready_update(root)
    baseline, original = create_baseline(root)
    backup = root / "promotion-backup"
    promote(
        update,
        baseline,
        backup,
        decision="retain_current_thresholds",
        reviewed_by="workspace owner",
        reason="promotion fixture",
        promoted_at="2026-07-30T18:00:00+08:00",
    )
    promoted = {
        path.name: path.read_text(encoding="utf-8")
        for path in baseline.glob("*.json")
    }
    return baseline, backup, original, promoted


class CalibrationRollbackTest(unittest.TestCase):
    def test_rollback_restores_originals_and_preserves_pre_rollback_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, backup, original, promoted = create_promoted_baseline(root)
            snapshot = root / "pre-rollback"

            self.assertEqual(cli_main([
                "calibration-rollback",
                str(backup),
                "--baseline-dir",
                str(baseline),
                "--pre-rollback-dir",
                str(snapshot),
                "--rolled-back-by",
                "workspace owner",
                "--reason",
                "Regression detected after promotion.",
                "--rolled-back-at",
                "2026-07-30T19:00:00+08:00",
            ]), 0)

            for filename, content in original.items():
                self.assertEqual((baseline / filename).read_text(encoding="utf-8"), content)
            for filename, content in promoted.items():
                self.assertEqual((snapshot / filename).read_text(encoding="utf-8"), content)
            promotion_manifest = json.loads(
                (backup / "promotion-manifest.json").read_text(encoding="utf-8")
            )
            rollback_manifest = json.loads(
                (snapshot / "rollback-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(promotion_manifest["status"], "rolled_back")
            self.assertEqual(rollback_manifest["status"], "complete")
            self.assertEqual(rollback_manifest["rolled_back_by"], "workspace owner")

    def test_repeat_rollback_is_rejected_without_new_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, backup, original, _promoted = create_promoted_baseline(root)
            first_snapshot = root / "pre-rollback-1"
            second_snapshot = root / "pre-rollback-2"
            arguments = [
                "calibration-rollback",
                str(backup),
                "--baseline-dir",
                str(baseline),
                "--pre-rollback-dir",
                str(first_snapshot),
                "--rolled-back-by",
                "reviewer",
                "--reason",
                "first rollback",
                "--rolled-back-at",
                "2026-07-30T19:00:00+08:00",
            ]
            self.assertEqual(cli_main(arguments), 0)
            arguments[arguments.index(str(first_snapshot))] = str(second_snapshot)
            self.assertEqual(cli_main(arguments), 1)
            self.assertFalse(second_snapshot.exists())
            for filename, content in original.items():
                self.assertEqual((baseline / filename).read_text(encoding="utf-8"), content)

    def test_baseline_drift_is_rejected_before_snapshot_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, backup, _original, promoted = create_promoted_baseline(root)
            snapshot = root / "pre-rollback"
            drift_path = baseline / "calibration-readiness.json"
            drift_path.write_text('{"manual":"later change"}\n', encoding="utf-8")

            self.assertEqual(cli_main([
                "calibration-rollback",
                str(backup),
                "--baseline-dir",
                str(baseline),
                "--pre-rollback-dir",
                str(snapshot),
                "--rolled-back-by",
                "reviewer",
                "--reason",
                "test drift guard",
                "--rolled-back-at",
                "2026-07-30T19:00:00+08:00",
            ]), 1)
            self.assertFalse(snapshot.exists())
            self.assertEqual(drift_path.read_text(encoding="utf-8"), '{"manual":"later change"}\n')
            for filename, content in promoted.items():
                if filename != drift_path.name:
                    self.assertEqual((baseline / filename).read_text(encoding="utf-8"), content)

    def test_backup_tampering_is_rejected_before_snapshot_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, backup, _original, promoted = create_promoted_baseline(root)
            snapshot = root / "pre-rollback"
            tampered = backup / "calibration-report.json"
            tampered.write_text('{"tampered":true}\n', encoding="utf-8")

            self.assertEqual(cli_main([
                "calibration-rollback",
                str(backup),
                "--baseline-dir",
                str(baseline),
                "--pre-rollback-dir",
                str(snapshot),
                "--rolled-back-by",
                "reviewer",
                "--reason",
                "test backup guard",
                "--rolled-back-at",
                "2026-07-30T19:00:00+08:00",
            ]), 1)
            self.assertFalse(snapshot.exists())
            for filename, content in promoted.items():
                self.assertEqual((baseline / filename).read_text(encoding="utf-8"), content)

    def test_rollback_write_failure_restores_promoted_state_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, backup, _original, promoted = create_promoted_baseline(root)
            snapshot = root / "pre-rollback"
            promotion_manifest_before = (
                backup / "promotion-manifest.json"
            ).read_text(encoding="utf-8")
            real_write = rollback_module.atomic_write_bytes
            failure_injected = False

            def flaky_write(path: Path, content: bytes) -> None:
                nonlocal failure_injected
                if (
                    not failure_injected
                    and path.parent == baseline
                    and path.name == "calibration-report.json"
                ):
                    failure_injected = True
                    raise OSError("injected rollback failure")
                real_write(path, content)

            with patch.object(rollback_module, "atomic_write_bytes", side_effect=flaky_write):
                with self.assertRaisesRegex(OSError, "injected rollback failure"):
                    rollback_module.rollback(
                        backup,
                        baseline,
                        snapshot,
                        rolled_back_by="reviewer",
                        reason="failure recovery test",
                        rolled_back_at="2026-07-30T19:00:00+08:00",
                    )

            for filename, content in promoted.items():
                self.assertEqual((baseline / filename).read_text(encoding="utf-8"), content)
            self.assertEqual(
                (backup / "promotion-manifest.json").read_text(encoding="utf-8"),
                promotion_manifest_before,
            )
            attempt = json.loads(
                (snapshot / "rollback-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(attempt["status"], "pre_rollback_state_restored_after_error")


if __name__ == "__main__":
    unittest.main()
