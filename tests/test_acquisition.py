from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skill" / "daily-trade-radar" / "src"
sys.path.insert(0, str(SRC))

from daily_trade_radar.acquisition.adapters.http import HostRateLimiter, HttpAdapter
from daily_trade_radar.acquisition.adapters.manual import browser_receipt, manual_receipt
from daily_trade_radar.acquisition.adapters.xmlfeeds import parse_feed, parse_sitemap
from daily_trade_radar.acquisition.cache import AcquisitionCache
from daily_trade_radar.acquisition.cli import main as acquisition_main
from daily_trade_radar.acquisition.coverage import build_coverage_ledger
from daily_trade_radar.acquisition.manifest import build_platform_manifest
from daily_trade_radar.acquisition.models import AcquisitionTask, stable_task_id
from daily_trade_radar.validation import validate


START = "2026-07-20T00:00:00+08:00"
CUTOFF = "2026-07-28T00:00:00+08:00"
CHECKED = "2026-07-28T00:00:00+08:00"


def task(source_type: str = "official_updates") -> AcquisitionTask:
    platform = "Example"
    seller_market = "SG"
    program = "cross-border"
    url = f"https://example.com/{source_type}"
    return AcquisitionTask(
        task_id=stable_task_id(platform, seller_market, program, source_type, url, START),
        platform=platform, seller_market=seller_market, program=program, source_type=source_type,
        url=url, window_start=START,
        requires_auth=source_type == "dashboard",
    )


class ManifestTest(unittest.TestCase):
    def test_registry_routes_produce_stable_tasks(self) -> None:
        first = build_platform_manifest(["Shopify", "Shopee"], "SG", "cross-border", START, CUTOFF, CHECKED)
        second = build_platform_manifest(["Shopify", "Shopee"], "SG", "cross-border", START, CUTOFF, CHECKED)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.tasks), 6)
        shopee = next(item for item in first.tasks if item.platform == "Shopee" and item.source_type == "dashboard")
        self.assertTrue(shopee.requires_auth)
        self.assertTrue(shopee.route_verification_required)

    def test_market_mismatched_verified_route_requires_reverification(self) -> None:
        manifest = build_platform_manifest(["TikTok Shop"], "UK", "local seller", START, CUTOFF, CHECKED)
        self.assertTrue(all(task.route_verification_required for task in manifest.tasks))
        self.assertTrue(all("route mismatch" in task.notes for task in manifest.tasks))

    def test_registry_source_gaps_are_preserved_in_manifest_and_coverage(self) -> None:
        manifest = build_platform_manifest(["AliExpress"], "CN", "cross-border", START, CUTOFF, CHECKED)
        self.assertEqual(
            {gap["source_type"] for gap in manifest.planning_gaps},
            {"official_updates"},
        )
        self.assertTrue(any(task.source_type == "current_policy" for task in manifest.tasks))
        row = build_coverage_ledger(manifest, [])[0]
        self.assertTrue(any("Declared official_updates source gap" in gap for gap in row["gaps"]))

    def test_platform_window_must_cover_seven_days(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 7 days"):
            build_platform_manifest(["Shopify"], "SG", "Shopify", "2026-07-27T00:00:00+08:00", CUTOFF)

    def test_manifest_id_covers_cutoff_and_full_task_contents(self) -> None:
        manifest = build_platform_manifest(["Shopify"], "SG", "Shopify", START, CUTOFF, CHECKED)
        changed_cutoff = build_platform_manifest(
            ["Shopify"], "SG", "Shopify", START, "2026-07-29T00:00:00+08:00", CHECKED
        )
        self.assertNotEqual(manifest.manifest_id, changed_cutoff.manifest_id)
        value = manifest.to_dict()
        value["tasks"][0]["notes"] = "tampered"
        with self.assertRaisesRegex(ValueError, "manifest_id"):
            type(manifest).from_dict(value)

    def test_task_id_rejects_path_and_identity_tampering(self) -> None:
        value = task().to_dict()
        value["task_id"] = "../../outside"
        with self.assertRaisesRegex(ValueError, "task_id"):
            AcquisitionTask.from_dict(value)
        value = task().to_dict()
        value["url"] = "https://attacker.example/changed"
        with self.assertRaisesRegex(ValueError, "identity fields"):
            AcquisitionTask.from_dict(value)


class CacheAndReceiptTest(unittest.TestCase):
    def test_public_content_is_normalized_and_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = AcquisitionCache(Path(directory))
            receipt = manual_receipt(task(), CHECKED, "candidate_found", "review", " A\n\nB ", cache=cache)
            self.assertIsNotNone(receipt.content_ref)
            self.assertEqual(cache.get_content(receipt.content_ref or ""), "A\nB")
            self.assertEqual(cache.load_receipt(task().task_id), receipt)

    def test_authenticated_browser_text_is_never_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = AcquisitionCache(Path(directory))
            receipt = browser_receipt(
                task("dashboard"), CHECKED, "candidate_found", "visible after login",
                visible_text="private seller data", authenticated=True, cache=cache,
            )
            self.assertIsNotNone(receipt.content_hash)
            self.assertIsNone(receipt.content_ref)
            self.assertEqual(list((Path(directory) / "content").glob("**/*")), [])

    def test_receipt_cache_rejects_unsafe_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = AcquisitionCache(Path(directory))
            with self.assertRaisesRegex(ValueError, "task_id"):
                cache.load_receipt("../../escape")


class XmlDiscoveryTest(unittest.TestCase):
    def test_rss_atom_and_sitemap(self) -> None:
        rss = "<rss><channel><item><title>Rule</title><link>https://example.com/r</link><pubDate>today</pubDate></item></channel></rss>"
        atom = '<feed xmlns="urn:x"><entry><title>A</title><link href="https://example.com/a"/><updated>today</updated></entry></feed>'
        sitemap = '<urlset xmlns="urn:x"><url><loc>https://example.com/s</loc><lastmod>2026-07-28</lastmod></url></urlset>'
        self.assertEqual(parse_feed(rss)[0], "rss")
        self.assertEqual(parse_feed(atom)[1][0].url, "https://example.com/a")
        self.assertEqual(parse_sitemap(sitemap)[0].published_at, "2026-07-28")


class CoverageTest(unittest.TestCase):
    def test_missing_receipts_cannot_claim_checks(self) -> None:
        manifest = build_platform_manifest(["Shopify"], "SG", "Shopify", START, CUTOFF, CHECKED)
        row = build_coverage_ledger(manifest, [])[0]
        self.assertFalse(row["public_update_checked"])
        self.assertFalse(row["current_policy_checked"])
        self.assertEqual(row["access_result"], "not_checked")
        self.assertEqual(len(row["gaps"]), len(manifest.tasks))

    def test_receipt_is_embedded_and_snapshot_gap_is_explicit(self) -> None:
        manifest = build_platform_manifest(["Shopify"], "SG", "Shopify", START, CUTOFF, CHECKED)
        receipt = manual_receipt(manifest.tasks[0], CHECKED, "no_relevant_update", "checked")
        row = build_coverage_ledger(manifest, [receipt])[0]
        self.assertEqual(row["sources_checked"][0]["acquisition_receipt"]["task_id"], receipt.task_id)
        self.assertTrue(any("required snapshot" in gap for gap in row["gaps"]))

    def test_unverified_country_route_stays_a_gap(self) -> None:
        manifest = build_platform_manifest(["Shopee"], "SG", "cross-border", START, CUTOFF, CHECKED)
        dashboard = next(task for task in manifest.tasks if task.source_type == "dashboard")
        receipt = manual_receipt(dashboard, CHECKED, "login_required", "login wall")
        row = build_coverage_ledger(manifest, [receipt])[0]
        self.assertEqual(row["access_result"], "login_required")
        self.assertTrue(any("requires verification" in gap for gap in row["gaps"]))

    def test_validator_accepts_receipt_metadata_and_rejects_authenticated_content_ref(self) -> None:
        data = json.loads((ROOT / "examples" / "current.json").read_text(encoding="utf-8"))
        source = data["coverage_ledger"][0]["sources_checked"][0]
        source["acquisition_receipt"] = {
            "task_id": "a" * 24, "retrieval_method": "manual", "attempts": 1,
            "http_status": None, "content_hash": "a" * 64,
            "content_ref": "content/sha256/aa/value.txt", "error_type": None,
            "route_verified": True,
        }
        self.assertEqual(validate(data), [])
        source["acquisition_receipt"]["retrieval_method"] = "browser_authenticated"
        self.assertTrue(any("authenticated content" in error for error in validate(data)))

    def test_receipt_scope_must_match_manifest_task(self) -> None:
        manifest = build_platform_manifest(["Shopify"], "SG", "Shopify", START, CUTOFF, CHECKED)
        receipt = manual_receipt(manifest.tasks[0], CHECKED, "candidate_found", "checked")
        with self.assertRaisesRegex(ValueError, "platform"):
            build_coverage_ledger(manifest, [replace(receipt, platform="Tampered")])
        unrelated = manual_receipt(task(), CHECKED, "candidate_found", "checked")
        with self.assertRaisesRegex(ValueError, "not present"):
            build_coverage_ledger(manifest, [unrelated])


class _Headers:
    def get_content_charset(self):
        return "utf-8"


class _Response:
    status = 200
    headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return b"official text"

    def geturl(self):
        return "https://example.com/final"


class HttpAdapterTest(unittest.TestCase):
    def test_retry_then_cache_hit(self) -> None:
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise HTTPError(request.full_url, 503, "busy", {}, io.BytesIO())
            return _Response()

        with tempfile.TemporaryDirectory() as directory:
            cache = AcquisitionCache(Path(directory))
            adapter = HttpAdapter(
                cache=cache, opener=opener, sleep=lambda _: None,
                rate_limiter=HostRateLimiter(0, lambda _: None),
            )
            receipt = adapter.acquire(task(), CHECKED)
            self.assertEqual((receipt.result, receipt.attempts, len(calls)), ("candidate_found", 2, 2))
            self.assertEqual(adapter.acquire(task(), CHECKED), receipt)
            self.assertEqual(len(calls), 2)

    def test_unauthorized_becomes_login_required(self) -> None:
        def opener(request, timeout):
            raise HTTPError(request.full_url, 401, "auth", {}, io.BytesIO())

        adapter = HttpAdapter(opener=opener, rate_limiter=HostRateLimiter(0), sleep=lambda _: None)
        self.assertEqual(adapter.acquire(task(), CHECKED).result, "login_required")

    def test_failed_receipt_is_audited_but_not_reused(self) -> None:
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise HTTPError(request.full_url, 401, "auth", {}, io.BytesIO())
            return _Response()

        with tempfile.TemporaryDirectory() as directory:
            adapter = HttpAdapter(
                cache=AcquisitionCache(Path(directory)), opener=opener,
                rate_limiter=HostRateLimiter(0), sleep=lambda _: None,
            )
            self.assertEqual(adapter.acquire(task(), CHECKED).result, "login_required")
            self.assertEqual(adapter.acquire(task(), CHECKED).result, "candidate_found")
            self.assertEqual(len(calls), 2)
            history = list((Path(directory) / "receipt-history" / task().task_id).glob("*.json"))
            self.assertEqual(len(history), 2)

    def test_ttl_and_refresh_force_new_requests(self) -> None:
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            return _Response()

        with tempfile.TemporaryDirectory() as directory:
            adapter = HttpAdapter(
                cache=AcquisitionCache(Path(directory)), opener=opener,
                rate_limiter=HostRateLimiter(0), sleep=lambda _: None,
                cache_ttl_seconds=60,
            )
            adapter.acquire(task(), CHECKED)
            adapter.acquire(task(), "2026-07-28T00:00:30+08:00")
            self.assertEqual(len(calls), 1)
            adapter.acquire(task(), "2026-07-28T00:00:31+08:00", refresh=True)
            adapter.acquire(task(), "2026-07-28T00:02:00+08:00")
            self.assertEqual(len(calls), 3)

    def test_tampered_cached_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = AcquisitionCache(Path(directory))
            receipt = manual_receipt(task(), CHECKED, "candidate_found", "checked")
            cache.save_receipt(replace(receipt, platform="Tampered"))
            adapter = HttpAdapter(
                cache=cache, opener=lambda *_args, **_kwargs: _Response(),
                rate_limiter=HostRateLimiter(0), sleep=lambda _: None,
            )
            with self.assertRaisesRegex(ValueError, "platform"):
                adapter.acquire(task(), CHECKED)


class CliTest(unittest.TestCase):
    def test_manifest_command_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "manifest.json"
            code = acquisition_main([
                "manifest", "--platform", "Shopify", "--seller-market", "SG",
                "--program", "Shopify", "--window-start", START, "--cutoff", CUTOFF,
                "--created-at", CHECKED, "--output", str(output),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))["tasks"]), 4)


if __name__ == "__main__":
    unittest.main()
