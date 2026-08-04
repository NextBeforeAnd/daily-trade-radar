from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skill" / "daily-trade-radar" / "src"
sys.path.insert(0, str(SRC))

from daily_trade_radar.acquisition.adapters.manual import manual_receipt
from daily_trade_radar.acquisition.manifest import build_platform_manifest
from daily_trade_radar.acquisition.receipts import create_receipt
from daily_trade_radar.cli import main as cli_main
from daily_trade_radar.planning import ResearchPlan, build_research_plan
from daily_trade_radar.source_health import (
    derive_source_health,
    inventory_source_health,
    load_postmortem,
    probe_source_health,
)


CREATED = "2026-07-31T09:00:00+08:00"
START = "2026-07-30T09:00:00+08:00"
CUTOFF = "2026-07-31T09:00:00+08:00"
PLATFORM_START = "2026-07-24T09:00:00+08:00"


class ResearchPlanTest(unittest.TestCase):
    def test_default_plan_has_required_evidence_tracks_and_windows(self) -> None:
        plan = build_research_plan({
            "created_at": CREATED,
            "window_start": START,
            "cutoff": CUTOFF,
        })
        self.assertEqual(plan.scope["regions"], ["China", "United States", "European Union"])
        self.assertTrue(
            {"official_updates", "effective_deadlines", "discovery_leads"}
            <= {track.kind for track in plan.tracks}
        )
        self.assertEqual(sum(track.kind == "marketplace_policy" for track in plan.tracks), 10)
        self.assertEqual(len(plan.manifest_requests), 10)
        self.assertEqual(plan.deadline_end, "2026-08-30T09:00:00+08:00")
        requirements = {track.kind: track.evidence_requirement for track in plan.tracks}
        self.assertEqual(requirements["official_updates"], "primary")
        self.assertEqual(requirements["discovery_leads"], "lead_only")
        official = next(track for track in plan.tracks if track.kind == "official_updates")
        self.assertIn("FCC Covered List", official.authorities)
        discovery = next(track for track in plan.tracks if track.kind == "discovery_leads")
        self.assertTrue(any("equipment authorization" in query for query in discovery.queries))
        self.assertIn("rolling seven-day backfill", discovery.notes)

    def test_product_and_platform_scope_create_tracks_and_manifest_request(self) -> None:
        plan = build_research_plan({
            "created_at": CREATED,
            "window_start": START,
            "cutoff": CUTOFF,
            "regions": ["European Union"],
            "products": ["LED lighting"],
            "hs_codes": ["9405.10"],
            "platforms": [{"platform": "Amazon", "seller_market": "DE", "program": "FBA"}],
        })
        kinds = [track.kind for track in plan.tracks]
        self.assertIn("product_scope", kinds)
        self.assertIn("marketplace_policy", kinds)
        self.assertEqual(plan.scope["hs_codes"], ["940510"])
        self.assertEqual(plan.manifest_requests[0]["window_start"], PLATFORM_START)
        platform_track = next(track for track in plan.tracks if track.kind == "marketplace_policy")
        self.assertEqual(platform_track.evidence_requirement, "platform_owned")
        self.assertTrue(platform_track.source_urls)

    def test_round_trip_and_identity_tampering_fail_closed(self) -> None:
        plan = build_research_plan({
            "created_at": CREATED, "window_start": START, "cutoff": CUTOFF, "platforms": [],
        })
        self.assertEqual(ResearchPlan.from_dict(plan.to_dict()), plan)
        changed = plan.to_dict()
        changed["tracks"][0]["weight"] = 0.5
        with self.assertRaisesRegex(ValueError, "plan_id"):
            ResearchPlan.from_dict(changed)

    def test_invalid_hs_code_and_unregistered_platform_are_rejected(self) -> None:
        base = {"created_at": CREATED, "window_start": START, "cutoff": CUTOFF, "platforms": []}
        with self.assertRaisesRegex(ValueError, "HS code"):
            build_research_plan({**base, "hs_codes": ["not-a-code"]})
        with self.assertRaisesRegex(ValueError, "unregistered platform"):
            build_research_plan({**base, "platforms": ["Imaginary Market"]})

    def test_unified_plan_cli_builds_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope = root / "scope.json"
            output = root / "plan.json"
            normalized = root / "normalized.json"
            manifests = root / "manifests"
            scope.write_text(json.dumps({
                "created_at": CREATED, "window_start": START, "cutoff": CUTOFF,
                "platforms": [{"platform": "Shopify", "seller_market": "SG", "program": "Markets"}],
            }), encoding="utf-8")
            self.assertEqual(cli_main([
                "plan", "--scope", str(scope), "--output", str(output),
                "--manifest-dir", str(manifests),
            ]), 0)
            self.assertEqual(cli_main(["plan", "--validate", str(output), "--output", str(normalized)]), 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), json.loads(normalized.read_text(encoding="utf-8")))
            manifest_files = list(manifests.glob("*.manifest.json"))
            self.assertEqual(len(manifest_files), 1)
            self.assertEqual(json.loads(manifest_files[0].read_text(encoding="utf-8"))["tasks"][0]["platform"], "Shopify")


class _Headers:
    def get_content_charset(self):
        return "utf-8"


class _Response:
    status = 200
    headers = _Headers()

    def __init__(self, url: str):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return 200

    def read(self, _limit):
        return b"public policy page"

    def geturl(self):
        return self.url


class SourceHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = build_platform_manifest(
            ["Shopify"], "SG", "Markets", PLATFORM_START, CUTOFF, CREATED,
        )

    def test_inventory_distinguishes_registered_but_unchecked_routes(self) -> None:
        report = inventory_source_health(["Shopify"], generated_at=CREATED)
        self.assertEqual(report["mode"], "inventory")
        self.assertEqual(report["overall_status"], "incomplete")
        self.assertEqual(report["summary"]["not_checked"], 4)

    def test_receipts_derive_no_update_partial_and_login_states(self) -> None:
        update = next(task for task in self.manifest.tasks if task.source_type == "official_updates")
        current = next(task for task in self.manifest.tasks if task.source_type == "current_policy")
        dashboard = next(task for task in self.manifest.tasks if task.source_type == "dashboard")
        receipts = [
            manual_receipt(update, CREATED, "no_relevant_update", "checked", snapshot={"snapshot_id": "one"}),
            manual_receipt(current, CREATED, "candidate_found", "candidate", snapshot={"snapshot_id": "two"}),
            create_receipt(dashboard, CREATED, "login_required", "manual", "login observed"),
        ]
        report = derive_source_health([self.manifest], receipts, generated_at=CREATED)
        self.assertEqual(report["overall_status"], "degraded")
        self.assertEqual(report["summary"]["no_relevant_update"], 1)
        self.assertEqual(report["summary"]["partial"], 1)
        self.assertEqual(report["summary"]["login_required"], 1)
        self.assertEqual(report["summary"]["not_checked"], 1)

    def test_error_types_map_to_typed_health_states(self) -> None:
        tasks = [task for task in self.manifest.tasks if not task.requires_auth]
        receipts = [
            create_receipt(tasks[0], CREATED, "blocked", "http", "slow", error_type="TimeoutError"),
            create_receipt(tasks[1], CREATED, "blocked", "http", "limited", http_status=429, error_type="http_429"),
            create_receipt(tasks[2], CREATED, "blocked", "http", "changed", error_type="schema_parse_error"),
        ]
        report = derive_source_health([self.manifest], receipts, generated_at=CREATED)
        self.assertEqual(report["summary"]["timeout"], 1)
        self.assertEqual(report["summary"]["rate_limited"], 1)
        self.assertEqual(report["summary"]["schema_drift"], 1)

    def test_postmortem_loads_run_directory_and_cli_emits_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            receipt_path = root / "receipt.json"
            output = root / "health.json"
            manifest_path.write_text(json.dumps(self.manifest.to_dict()), encoding="utf-8")
            receipt = manual_receipt(self.manifest.tasks[0], CREATED, "candidate_found", "review")
            receipt_path.write_text(json.dumps(receipt.to_dict()), encoding="utf-8")
            manifests, receipts = load_postmortem(root)
            self.assertEqual(len(manifests), 1)
            self.assertEqual(len(receipts), 1)
            self.assertEqual(cli_main([
                "doctor", "--postmortem", str(root), "--checked-at", CREATED,
                "--json", "--output", str(output),
            ]), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["mode"], "postmortem")
            self.assertEqual(report["summary"]["partial"], 1)

    def test_probe_checks_public_routes_and_leaves_dashboard_unchecked(self) -> None:
        report = probe_source_health(
            ["Shopify"], checked_at=CREATED, timeout=1, workers=2,
            opener=lambda request, timeout: _Response(request.full_url),
        )
        self.assertEqual(report["mode"], "probe")
        self.assertEqual(report["summary"]["partial"], 3)
        self.assertEqual(report["summary"]["not_checked"], 1)


if __name__ == "__main__":
    unittest.main()
