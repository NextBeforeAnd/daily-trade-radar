from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skill" / "daily-trade-radar" / "src"
sys.path.insert(0, str(SRC))

from daily_trade_radar.alerting import build_alert_batch, deliver_webhook
from daily_trade_radar.applicability import load_catalog, match_report
from daily_trade_radar.official_sources import load_registry
from daily_trade_radar.planning import build_research_plan
from daily_trade_radar.profiles import load_profile
from daily_trade_radar.run import main as run_main
from daily_trade_radar.validation import validate


EXAMPLES = ROOT / "examples"


class ProductizationTest(unittest.TestCase):
    def test_china_registry_routes_are_in_research_plan(self) -> None:
        registry = load_registry()
        self.assertEqual(set(registry), {"cn-mofcom", "cn-gacc", "cn-sta", "cn-samr"})
        plan = build_research_plan({
            "created_at": "2026-08-08T10:00:00+08:00",
            "window_start": "2026-08-07T10:00:00+08:00",
            "cutoff": "2026-08-08T10:00:00+08:00",
            "regions": ["China"],
            "platforms": [],
        })
        official = next(track for track in plan.tracks if track.kind == "official_updates")
        self.assertTrue(any("mofcom.gov.cn" in url for url in official.source_urls))
        self.assertTrue(any("customs.gov.cn" in url for url in official.source_urls))
        self.assertTrue(all(url.startswith("https://") for url in official.source_urls))

    def test_profile_resolves_relative_paths_and_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "profile.json"
            path.write_text(json.dumps({
                "schema_version": "1.0", "name": "example",
                "scope": {"regions": ["China"], "platforms": []},
                "catalog": "catalog.json",
                "output": {"directory": "runs/today", "formats": ["markdown"]},
                "deduplication": {"threshold": 0.9, "review_threshold": 0.7},
                "alerts": {"min_level": "medium", "state_file": "state.json"},
            }), encoding="utf-8")
            profile = load_profile(path)
            self.assertEqual(profile.catalog, root / "catalog.json")
            self.assertEqual(profile.output_directory, root / "runs" / "today")
            self.assertEqual(profile.threshold, 0.9)
            self.assertTrue(profile.alert_require_match)

    def test_hs_and_keyword_applicability_is_auditable(self) -> None:
        report = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        report["events"][1]["hs_codes"] = ["8517.62"]
        catalog = {
            "schema_version": "1.0", "organization": "Example Exporter",
            "items": [{
                "sku": "ROUTER-1", "name": "example products", "hs_codes": ["8517"],
                "keywords": ["router"], "markets": ["EU"], "platforms": [],
            }],
        }
        matched = match_report(report, catalog)
        applicability = matched["events"][1]["applicability"]
        self.assertEqual(applicability["status"], "matched")
        self.assertEqual(applicability["matched_items"][0]["sku"], "ROUTER-1")
        self.assertIn("hs_prefix", applicability["matched_items"][0]["basis"])
        self.assertEqual(validate(matched), [])

    def test_alerts_require_verified_level_and_optional_match(self) -> None:
        report = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        for event in report["events"]:
            event["applicability"] = {
                "organization": "Example", "status": "matched" if event["level"] == "high" else "no_match",
                "matched_items": ([{"sku": "SKU-1", "name": "Example", "basis": ["product_keyword"], "matched_hs_codes": [], "matched_terms": ["example"]}]
                                  if event["level"] == "high" else []),
                "reason": "test",
            }
        batch = build_alert_batch(report, min_level="high", require_applicability_match=True)
        self.assertEqual(batch["alert_count"], 1)
        signature = batch["alerts"][0]["signature"]
        repeated = build_alert_batch(
            report, min_level="high", require_applicability_match=True,
            seen_signatures={signature},
        )
        self.assertEqual(repeated["alert_count"], 0)
        self.assertTrue(any(item["reason"] == "already_alerted" for item in repeated["suppressed"]))

    def test_webhook_delivery_uses_json_post(self) -> None:
        calls = []

        class Response:
            status = 204
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def getcode(self): return self.status

        def opener(request, timeout):
            calls.append((request, timeout))
            return Response()

        status = deliver_webhook({"alerts": []}, "https://hooks.example.test/radar", opener=opener)
        self.assertEqual(status, 204)
        self.assertEqual(calls[0][0].method, "POST")
        self.assertEqual(calls[0][0].get_header("Content-type"), "application/json")

    def test_run_prepares_plan_then_completes_with_candidate_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "profile.json"
            catalog_path = root / "catalog.json"
            profile = {
                "schema_version": "1.0", "name": "end-to-end",
                "scope": {
                    "created_at": "2026-08-08T10:00:00+08:00",
                    "window_start": "2026-08-07T10:00:00+08:00",
                    "cutoff": "2026-08-08T10:00:00+08:00",
                    "regions": ["European Union"], "platforms": [],
                },
                "catalog": "catalog.json",
                "output": {"directory": "run", "formats": ["markdown"], "basename": "radar"},
                "alerts": {"min_level": "high", "require_applicability_match": True},
            }
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            catalog_path.write_text(json.dumps({
                "schema_version": "1.0", "organization": "Example Exporter",
                "items": [{
                    "sku": "SKU-1", "name": "example products", "hs_codes": [],
                    "keywords": [], "markets": ["EU"], "platforms": [],
                }],
            }), encoding="utf-8")
            self.assertEqual(run_main(["--profile", str(profile_path)]), 0)
            prepared = json.loads((root / "run" / "run-status.json").read_text(encoding="utf-8"))
            self.assertEqual(prepared["state"], "research_required")

            self.assertEqual(run_main([
                "--profile", str(profile_path), "--events", str(EXAMPLES / "current.json"),
            ]), 0)
            completed = json.loads((root / "run" / "run-status.json").read_text(encoding="utf-8"))
            self.assertEqual(completed["state"], "complete")
            self.assertTrue((root / "run" / "radar.md").exists())
            self.assertEqual(completed["alert_count"], 1)


if __name__ == "__main__":
    unittest.main()
