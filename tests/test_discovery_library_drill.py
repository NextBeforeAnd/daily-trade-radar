from __future__ import annotations

from copy import deepcopy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skill" / "daily-trade-radar" / "src"
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(SRC))

from daily_trade_radar.cli import main as cli_main
from daily_trade_radar.discovery import DiscoveryLead, cluster_leads, prioritize_discovery
from daily_trade_radar.drill import build_drill_plan
from daily_trade_radar.library import ingest_path, library_stats, search_library, show_event


CUTOFF = "2026-07-31T12:00:00+08:00"
CREATED = "2026-07-31T12:05:00+08:00"


def lead(
    title: str,
    url: str,
    claim: str,
    *,
    jurisdiction: str = "EU",
    source_tier: str = "trade_media",
    source_type: str = "trade_media",
    published_at: str = "2026-07-31T08:00:00+08:00",
    platform: str | None = "Amazon",
    products: list[str] | None = None,
    momentum_score: int = 0,
) -> dict:
    return {
        "source_title": title,
        "source_url": url,
        "source_name": url.split("/")[2],
        "source_tier": source_tier,
        "source_type": source_type,
        "published_at": published_at,
        "retrieved_at": "2026-07-31T10:00:00+08:00" if published_at < "2026-07-31T10:00:00+08:00" else CUTOFF,
        "jurisdiction": jurisdiction,
        "platform": platform,
        "products": products or ["LED lighting"],
        "hs_codes": ["940510"],
        "claim": claim,
        "momentum_score": momentum_score,
        "momentum_evidence": "Mentions doubled across two checks." if momentum_score else "",
    }


class DiscoveryTest(unittest.TestCase):
    def test_cross_source_cluster_is_prioritized_but_never_promoted(self) -> None:
        claim = "Amazon EU may require updated LED compliance documents for affected listings from August."
        value = {
            "cutoff": CUTOFF,
            "scope": {
                "regions": ["EU"], "platforms": ["Amazon"],
                "products": ["LED lighting"], "hs_codes": ["940510"],
            },
            "leads": [
                lead("Amazon EU LED document change", "https://trade.example/a", claim, momentum_score=3),
                lead("Possible Amazon LED compliance update", "https://sellers.example/b", claim, source_tier="seller_forum", source_type="seller_forum"),
                lead(
                    "Unrelated old shipping rumor", "https://social.example/c", "A creator discussed apparel trends.",
                    jurisdiction="US", source_tier="social", source_type="social_post",
                    published_at="2026-06-01T08:00:00+08:00", platform=None, products=["apparel"],
                ),
            ],
        }
        result = prioritize_discovery(value)
        self.assertEqual(result["outcome"], "candidates_found")
        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["corroborating_domain_count"], 2)
        self.assertTrue(candidate["corroborated_lead"])
        self.assertFalse(candidate["promotion_eligible"])
        self.assertEqual(candidate["event_status"], "unconfirmed")
        self.assertEqual(candidate["risk_level"], "watch")
        self.assertGreaterEqual(candidate["priority_score"], 45)
        self.assertEqual(len(result["excluded_below_threshold"]), 1)

    def test_conflicting_jurisdictions_do_not_cluster(self) -> None:
        common = "A customs authority may change documentation for low value parcels."
        leads = [
            DiscoveryLead.from_dict(lead("EU parcel documents", "https://one.example/a", common, jurisdiction="EU", platform=None)),
            DiscoveryLead.from_dict(lead("US parcel documents", "https://two.example/b", common, jurisdiction="US", platform=None)),
        ]
        self.assertEqual(len(cluster_leads(leads)), 2)

    def test_unknown_scope_cannot_bridge_conflicting_clusters(self) -> None:
        common = "A customs authority may change documentation for low value parcels."
        leads = [
            DiscoveryLead.from_dict(lead("EU parcel documents", "https://one.example/a", common, jurisdiction="EU", platform=None)),
            DiscoveryLead.from_dict(lead("Parcel documents", "https://bridge.example/b", common, jurisdiction="unknown", platform=None)),
            DiscoveryLead.from_dict(lead("US parcel documents", "https://two.example/c", common, jurisdiction="US", platform=None)),
        ]
        clusters = cluster_leads(leads)
        self.assertEqual(len(clusters), 2)
        self.assertFalse(any(
            {item.jurisdiction for item in cluster} >= {"EU", "US"}
            for cluster in clusters
        ))

    def test_nothing_solid_returns_only_a_weak_signal(self) -> None:
        value = {
            "cutoff": CUTOFF,
            "scope": {"regions": ["EU"]},
            "leads": [lead(
                "Old unrelated social post", "https://social.example/old", "Generic discussion.",
                jurisdiction="US", source_tier="social", source_type="social_post",
                published_at="2026-06-01T08:00:00+08:00", platform=None, products=["apparel"],
            )],
        }
        result = prioritize_discovery(value)
        self.assertEqual(result["outcome"], "nothing_solid")
        self.assertEqual(result["candidates"], [])
        self.assertIsNotNone(result["weak_signal"])

    def test_discovery_cli_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "leads.json"
            output = root / "discovery.json"
            source.write_text(json.dumps({
                "cutoff": CUTOFF, "scope": {},
                "leads": [lead("Lead", "https://trade.example/a", "A possible customs change was discussed.")],
            }), encoding="utf-8")
            self.assertEqual(cli_main(["discover", str(source), "--minimum-score", "0", "--output", str(output)]), 0)
            self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["candidates"][0]["promotion_eligible"])


class LibraryAndDrillTest(unittest.TestCase):
    def _reports(self, root: Path) -> tuple[Path, Path]:
        first = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        second = deepcopy(first)
        second["report_date"] = "2026-07-22"
        second["cutoff"] = "2026-07-22T17:00:00+08:00"
        second["events"][0]["summary"] = "示例平台标题规则进入临近生效复核。"
        first_path = root / "2026-07-21.json"
        second_path = root / "2026-07-22.json"
        first_path.write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")
        second_path.write_text(json.dumps(second, ensure_ascii=False), encoding="utf-8")
        return first_path, second_path

    def test_library_ingest_search_history_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "radar.sqlite3"
            first, _second = self._reports(root)
            result = ingest_path(database, root, ingested_at=CREATED)
            self.assertEqual(result["imported_count"], 2)
            self.assertEqual(result["event_count"], 4)
            stats = library_stats(database)
            self.assertEqual(stats["report_count"], 2)
            self.assertEqual(stats["unique_event_count"], 2)
            self.assertEqual(stats["sighting_count"], 4)
            search = search_library(database, "商品标题")
            self.assertEqual(search["result_count"], 1)
            history = show_event(database, "example-marketplace-title-rule-2026")
            self.assertEqual(history["sighting_count"], 2)
            self.assertEqual(history["first_seen"], "2026-07-21")
            self.assertEqual(history["last_seen"], "2026-07-22")
            ingest_path(database, first, ingested_at=CREATED)
            self.assertEqual(library_stats(database)["sighting_count"], 4)

    def test_library_rejects_invalid_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.json"
            invalid.write_text(json.dumps({"events": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "validation failed"):
                ingest_path(root / "radar.sqlite3", invalid, ingested_at=CREATED)

    def test_drill_uses_library_history_and_refresh_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "radar.sqlite3"
            self._reports(root)
            ingest_path(database, root, ingested_at=CREATED)
            plan = build_drill_plan(
                "example-marketplace-title-rule-2026", library_path=database,
                created_at=CREATED, refresh=True,
            )
            self.assertEqual(plan["mode"], "revalidation")
            self.assertEqual(plan["cache_policy"], "force_refresh")
            self.assertEqual(plan["history"]["sighting_count"], 2)
            self.assertFalse(plan["promotion_gate"]["eligible_before_research"])
            self.assertTrue(plan["primary_targets"])

    def test_unconfirmed_event_drill_stays_confirmation_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
            event = report["events"][0]
            event["status"] = "unconfirmed"
            event["level"] = "watch"
            event["level_override"] = {
                "level": "watch",
                "reason": "Unconfirmed discovery lead remains watch-level until primary confirmation.",
            }
            event["score_breakdown"]["evidence"] = 0
            event["score"] = 5
            path = root / "unconfirmed.json"
            path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            plan = build_drill_plan(event["id"], report_path=path, created_at=CREATED)
            self.assertEqual(plan["mode"], "confirmation")
            self.assertTrue(plan["promotion_gate"]["unconfirmed_must_remain_watch_until_gate_passes"])

    def test_library_and_drill_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "radar.sqlite3"
            report, _second = self._reports(root)
            ingest_output = root / "ingest.json"
            search_output = root / "search.json"
            drill_output = root / "drill.json"
            self.assertEqual(cli_main([
                "library", "ingest", str(report), "--db", str(database),
                "--ingested-at", CREATED, "--output", str(ingest_output),
            ]), 0)
            self.assertEqual(cli_main([
                "library", "search", "EU", "--db", str(database), "--json", "--output", str(search_output),
            ]), 0)
            self.assertEqual(cli_main([
                "drill", "example-eu-product-rule-2026", "--library", str(database),
                "--created-at", CREATED, "--output", str(drill_output),
            ]), 0)
            self.assertEqual(json.loads(drill_output.read_text(encoding="utf-8"))["event_id"], "example-eu-product-rule-2026")


if __name__ == "__main__":
    unittest.main()
