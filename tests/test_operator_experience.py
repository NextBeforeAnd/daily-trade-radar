from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skill" / "daily-trade-radar" / "src"
sys.path.insert(0, str(SRC))

from daily_trade_radar.coverage_dashboard import build_dashboard, render_html, render_markdown
from daily_trade_radar.initializer import main as init_main
from daily_trade_radar.language_quality import assess_language
from daily_trade_radar.platforms.cli import main as platforms_main
from daily_trade_radar.platforms.registry import _load_config
from daily_trade_radar.profiles import load_profile
from daily_trade_radar.run import main as run_main


EXAMPLES = ROOT / "examples"


class OperatorExperienceTest(unittest.TestCase):
    def test_init_creates_narrow_valid_profile_and_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "pilot"
            result = init_main([
                "--directory", str(target), "--name", "Router Pilot",
                "--region", "European Union", "--product", "wireless router",
                "--hs-code", "851762", "--platform", "Amazon", "--sku", "ROUTER-001",
            ])
            self.assertEqual(result, 0)
            profile = load_profile(target / "profile.json")
            self.assertEqual(profile.scope["regions"], ["European Union"])
            self.assertEqual(profile.scope["platforms"], ["Amazon"])
            self.assertEqual(profile.language_mode, "strict")
            catalog = json.loads((target / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(catalog["items"][0]["sku"], "ROUTER-001")

    def test_init_defaults_to_china_without_marketplaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "starter"
            self.assertEqual(init_main(["--directory", str(target)]), 0)
            profile = load_profile(target / "profile.json")
            self.assertEqual(profile.scope["regions"], ["China"])
            self.assertEqual(profile.scope["platforms"], [])
            self.assertIsNone(profile.catalog)

    def test_platform_scaffold_is_conditional_and_validation_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "example-market.json"
            result = platforms_main([
                "scaffold", "--id", "example-market", "--display-name", "Example Market",
                "--url", "https://seller.example.test/updates", "--market", "US",
                "--output", str(output),
            ])
            self.assertEqual(result, 0)
            config = _load_config(output)
            route = config.official_routes[0]
            self.assertEqual(route["verification_status"], "conditional")
            self.assertTrue(route["verify_before_use"])
            self.assertEqual(
                set(config.source_profile["known_gaps"]),
                {"current_policy", "dashboard"},
            )

    def test_invalid_platform_scaffold_does_not_write_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "invalid.json"
            with self.assertRaises(SystemExit):
                platforms_main([
                    "scaffold", "--id", "Invalid ID", "--display-name", "Example",
                    "--url", "https://seller.example.test/", "--output", str(output),
                ])
            self.assertFalse(output.exists())

    def test_language_check_flags_english_body_in_chinese_report(self) -> None:
        report = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        report["language"] = "zh-CN"
        for event in report["events"]:
            for field in ("title", "summary", "impact", "action", "rationale"):
                event[field] = "This event contains a long English-only operational explanation that requires reviewed translation."
            event["products_or_channels"] = ["wireless network equipment"]
        result = assess_language(report, require_language="zh-CN")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["issue_count"], len(report["events"]))

    def test_strict_profile_stops_before_rendering_language_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
            report["language"] = "zh-CN"
            for event in report["events"]:
                for field in ("title", "summary", "impact", "action", "rationale"):
                    event[field] = "This is an English-only reviewed field with enough text to trigger the strict language gate."
                event["products_or_channels"] = ["example products"]
            events = root / "events.json"
            events.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            profile = root / "profile.json"
            profile.write_text(json.dumps({
                "schema_version": "1.0", "name": "language-gate",
                "scope": {
                    "created_at": "2026-08-08T10:00:00+08:00",
                    "window_start": "2026-08-07T10:00:00+08:00",
                    "cutoff": "2026-08-08T10:00:00+08:00",
                    "language": "zh-CN", "regions": ["European Union"], "platforms": [],
                },
                "candidate_report": "events.json",
                "quality": {"language_mode": "strict"},
                "output": {"directory": "output", "formats": ["markdown"]},
            }), encoding="utf-8")
            self.assertEqual(run_main(["--profile", str(profile)]), 1)
            status = json.loads((root / "output" / "run-status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "language_review_required")
            self.assertFalse((root / "output" / "daily-trade-radar.md").exists())

    def test_dashboard_prioritizes_gaps_and_renders_static_outputs(self) -> None:
        health = {
            "records": [{
                "platform": "Amazon", "audit_state": "blocked",
                "checked_at": "2026-08-08T10:00:00+08:00",
            }],
        }
        dashboard = build_dashboard(health=health, generated_at="2026-08-08T11:00:00+08:00")
        self.assertEqual(dashboard["summary"]["platform_count"], 11)
        self.assertEqual(dashboard["summary"]["full"], 2)
        amazon = next(row for row in dashboard["platforms"] if row["platform"] == "Amazon")
        self.assertIn("blocked", amazon["health_states"])
        self.assertTrue(any("failure" in action for action in amazon["actions"]))
        self.assertIn("Platform Source Coverage Dashboard", render_markdown(dashboard))
        html = render_html(dashboard)
        self.assertIn("<!doctype html>", html)
        self.assertIn("sellercentral.amazon.com", html)


if __name__ == "__main__":
    unittest.main()
