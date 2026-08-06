from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill" / "daily-trade-radar"
SRC = SKILL / "src"
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(SRC))

from daily_trade_radar.cli import main as cli_main
from daily_trade_radar.deduplication import (
    canonical_url,
    regulatory_identifiers,
    scope_conflicts,
    weighted_similarity,
)
from daily_trade_radar.paths import ASSETS_DIR, SKILL_ROOT
from daily_trade_radar.platforms import canonical_platform_id, load_registry, platforms_in_scope, source_depth
from daily_trade_radar.platforms.registry import _load_config
from daily_trade_radar.scoring import level_for_score
from daily_trade_radar.snapshots.filesystem import FilesystemSnapshotStore, normalize_content
from daily_trade_radar.snapshots.git import GitSnapshotStore
from daily_trade_radar.snapshots.sqlite import SQLiteSnapshotStore
from daily_trade_radar.snapshots.s3 import S3SnapshotStore, parse_s3_uri, validate_endpoint_url
from daily_trade_radar.snapshots.store import create_snapshot_store
from daily_trade_radar.validation import validate


class ScoringUnitTest(unittest.TestCase):
    def test_level_boundaries(self) -> None:
        self.assertEqual([level_for_score(score) for score in (0, 1)], ["watch", "watch"])
        self.assertEqual([level_for_score(score) for score in (2, 4)], ["low", "low"])
        self.assertEqual([level_for_score(score) for score in (5, 7)], ["medium", "medium"])
        self.assertEqual([level_for_score(score) for score in (8, 10)], ["high", "high"])


class DeduplicationUnitTest(unittest.TestCase):
    def test_canonical_url_removes_tracking_and_fragment(self) -> None:
        left = canonical_url("HTTPS://Example.COM/rule/?utm_source=x&b=2&a=1#details")
        right = canonical_url("https://example.com/rule?a=1&b=2")
        self.assertEqual(left, right)

    def test_scope_aliases_and_conflicts(self) -> None:
        self.assertEqual(scope_conflicts({"jurisdiction": "US"}, {"jurisdiction": "United States"}), [])
        self.assertEqual(scope_conflicts({"jurisdiction": "US"}, {"jurisdiction": "EU"}), ["jurisdiction"])

    def test_scope_conflict_blocks_even_an_exact_id(self) -> None:
        left = {"id": "same", "jurisdiction": "US"}
        right = {"id": "same", "jurisdiction": "EU"}
        score, method, components = weighted_similarity(left, right)
        self.assertEqual((score, method, components), (0.0, "scope_conflict", {}))

    def test_different_regulatory_identifiers_cap_similarity(self) -> None:
        left = {
            "title": "Commission Regulation 2026/100 product requirements",
            "source_title": "Regulation 2026/100",
            "authority": "Commission",
            "jurisdiction": "EU",
            "products_or_channels": ["product"],
            "source_url": "https://example.eu/rules",
        }
        right = dict(left)
        right["title"] = "Commission Regulation 2026/101 product requirements"
        right["source_title"] = "Regulation 2026/101"
        self.assertNotEqual(regulatory_identifiers(left), regulatory_identifiers(right))
        score, method, components = weighted_similarity(left, right)
        self.assertEqual(method, "weighted_fields")
        self.assertLess(score, 0.82)
        self.assertEqual(components["regulatory_identifiers"], 0.0)


class PackageUnitTest(unittest.TestCase):
    def test_validation_is_directly_importable(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(data), [])

    def test_snapshot_normalization_is_directly_importable(self) -> None:
        self.assertEqual(normalize_content("  A\u00a0  B\n\n C  "), "A B\nC")

    def test_skill_paths_resolve_after_module_move(self) -> None:
        self.assertEqual(SKILL_ROOT, SKILL.resolve())
        self.assertTrue((ASSETS_DIR / "radar-template.docx").exists())

    def test_unified_cli_dispatches_validation(self) -> None:
        self.assertEqual(cli_main(["validate", str(EXAMPLES / "current.json")]), 0)

    def test_validation_rejects_incomplete_or_unsafe_snapshot_refs(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        snapshot = data["coverage_ledger"][0]["sources_checked"][0]["snapshot"]
        snapshot.update({
            "storage_backend": "filesystem",
            "snapshot_ref": "../outside.json",
            "diff_ref": None,
        })
        errors = validate(data)
        self.assertTrue(any("portable storage metadata missing index_recovered" in error for error in errors))
        self.assertTrue(any("snapshot_ref: use a portable relative POSIX path" in error for error in errors))

    def test_validation_requires_complete_git_provenance(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        snapshot = data["coverage_ledger"][0]["sources_checked"][0]["snapshot"]
        snapshot.update({
            "storage_backend": "git",
            "snapshot_ref": "snapshots/example/page/snapshot.json",
            "diff_ref": None,
            "index_recovered": False,
            "git_commit": "not-an-object-id",
        })
        errors = validate(data)
        self.assertTrue(any("Git provenance missing git_tree" in error for error in errors))
        self.assertTrue(any("git_commit: use a Git object ID" in error for error in errors))


class PlatformRegistryUnitTest(unittest.TestCase):
    def test_registry_loads_all_bundled_platforms(self) -> None:
        registry = load_registry()
        self.assertEqual(
            set(registry),
            {
                "alibaba-com",
                "aliexpress",
                "amazon",
                "ebay",
                "jumia",
                "lazada",
                "shopee",
                "shopify",
                "temu",
                "tiktok-shop",
                "walmart-marketplace",
            },
        )
        for config in registry.values():
            self.assertTrue(config.official_routes)
            self.assertTrue(config.applicability_dimensions)
            self.assertEqual(set(config.source_profile["expected_source_types"]), {
                "official_updates", "current_policy", "dashboard",
            })
            for route in config.official_routes:
                self.assertIn(route["verification_status"], {"verified", "conditional"})
                self.assertTrue(route["markets"])

    def test_registry_resolves_english_and_chinese_aliases(self) -> None:
        self.assertEqual(canonical_platform_id("TikTok Shop"), "tiktok-shop")
        self.assertEqual(canonical_platform_id("速卖通"), "aliexpress")
        self.assertEqual(canonical_platform_id("虾皮"), "shopee")
        self.assertEqual(canonical_platform_id("阿里巴巴国际站"), "alibaba-com")
        self.assertEqual(canonical_platform_id("易贝"), "ebay")

    def test_scope_detection_finds_new_platforms(self) -> None:
        found = platforms_in_scope(["Shopee SG", "Lazada", "eBay UK", "Walmart Marketplace US"])
        self.assertEqual(
            {config.id for config in found},
            {"shopee", "lazada", "ebay", "walmart-marketplace"},
        )

    def test_unified_cli_lists_platform_registry(self) -> None:
        self.assertEqual(cli_main(["platforms"]), 0)

    def test_source_depth_exposes_verified_routes_and_declared_gaps(self) -> None:
        registry = load_registry()
        self.assertEqual(source_depth(registry["shopify"])["status"], "full")
        self.assertEqual(source_depth(registry["tiktok-shop"])["status"], "full")
        aliexpress = source_depth(registry["aliexpress"])
        self.assertEqual(aliexpress["status"], "hybrid")
        self.assertEqual(set(aliexpress["declared_gaps"]), {"official_updates"})
        self.assertEqual(source_depth(registry["lazada"])["status"], "hybrid")
        self.assertEqual(source_depth(registry["temu"])["status"], "hybrid")
        jumia = source_depth(registry["jumia"])
        self.assertEqual(jumia["status"], "hybrid")
        self.assertEqual(
            set(jumia["verified_source_types"]),
            {"current_policy", "dashboard"},
        )

    def test_platform_config_rejects_silent_or_weak_route_coverage(self) -> None:
        source = SKILL / "src" / "daily_trade_radar" / "platforms" / "data" / "shopify.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "shopify.json"
            data["official_routes"][0].pop("route_id")
            target.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "route_id"):
                _load_config(target)
            data = json.loads(source.read_text(encoding="utf-8"))
            data["official_routes"] = [
                route for route in data["official_routes"] if route["source_type"] != "dashboard"
            ]
            target.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing route or declared source gap"):
                _load_config(target)


class SnapshotStoreUnitTest(unittest.TestCase):
    url = "https://seller.example.com/policy"
    captured_at = "2026-07-28T10:00:00+08:00"

    def test_filesystem_store_returns_portable_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = FilesystemSnapshotStore(root)
            result = store.capture("Example", self.url, "Policy text", self.captured_at)
            self.assertEqual(result["storage_backend"], "filesystem")
            self.assertFalse(Path(result["snapshot_ref"]).is_absolute())
            self.assertTrue((root / result["snapshot_ref"]).exists())
            self.assertIsNone(result["diff_ref"])
            self.assertFalse(result["index_recovered"])

    def test_corrupt_index_recovers_from_snapshot_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FilesystemSnapshotStore(Path(temp_dir))
            first = store.capture("Example", self.url, "Policy text", self.captured_at)
            index_path = Path(first["snapshot_path"]).parent / "index.json"
            index_path.write_text("{broken", encoding="utf-8")

            second = store.capture(
                "Example",
                self.url,
                "Policy text changed",
                "2026-07-29T10:00:00+08:00",
            )
            self.assertTrue(second["index_recovered"])
            self.assertEqual(second["previous_snapshot_id"], first["snapshot_id"])
            self.assertEqual(second["change_status"], "changed")
            self.assertIsInstance(json.loads(index_path.read_text(encoding="utf-8")), dict)

    def test_concurrent_identical_capture_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FilesystemSnapshotStore(Path(temp_dir))

            def run_capture() -> dict:
                return store.capture("Example", self.url, "Policy text", self.captured_at)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _item: run_capture(), range(2)))

            self.assertEqual(results[0]["snapshot_id"], results[1]["snapshot_id"])
            record = store.load_latest("Example", self.url)
            self.assertIsNotNone(record)
            self.assertIsNone(record["previous_snapshot_id"])
            page_dir = Path(results[0]["snapshot_path"]).parent
            self.assertEqual(len([path for path in page_dir.glob("*.json") if path.name != "index.json"]), 1)
            self.assertFalse((page_dir / ".capture.lock").exists())

    def test_existing_lock_times_out_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FilesystemSnapshotStore(Path(temp_dir), lock_timeout=0.05)
            canonical = canonical_url(self.url)
            page_dir = store._page_dir("Example", canonical)
            page_dir.mkdir(parents=True)
            (page_dir / ".capture.lock").write_text("held", encoding="utf-8")
            with self.assertRaises(TimeoutError):
                store.capture("Example", self.url, "Policy text", self.captured_at)
            self.assertEqual(list(page_dir.glob("*.json")), [])


class SQLiteSnapshotStoreUnitTest(unittest.TestCase):
    url = "https://seller.example.com/policy?utm_source=test"
    captured_at = "2026-07-28T10:00:00+08:00"

    def test_factory_and_persistent_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = create_snapshot_store("SQLITE", root)
            self.assertIsInstance(store, SQLiteSnapshotStore)
            first = store.capture("Example", self.url, "Policy A", self.captured_at)
            second = store.capture("Example", self.url, "Policy A", "2026-07-29T10:00:00+08:00")
            third = store.capture("Example", self.url, "Policy B", "2026-07-30T10:00:00+08:00")

            self.assertEqual(first["storage_backend"], "sqlite")
            self.assertEqual(first["change_status"], "first_seen")
            self.assertEqual(second["change_status"], "unchanged")
            self.assertEqual(third["change_status"], "changed")
            self.assertEqual(third["previous_snapshot_id"], second["snapshot_id"])
            self.assertIsNotNone(third["diff_ref"])
            self.assertFalse(Path(third["snapshot_ref"]).is_absolute())
            self.assertTrue((root / "snapshots.sqlite3").exists())
            report = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
            report["coverage_ledger"][0]["sources_checked"][0]["snapshot"] = third
            self.assertEqual(validate(report), [])

            reopened = SQLiteSnapshotStore(root)
            latest = reopened.load_latest("Example", "https://seller.example.com/policy")
            self.assertIsNotNone(latest)
            self.assertEqual(latest["snapshot_id"], third["snapshot_id"])
            self.assertEqual(latest["content"], "Policy B")
            with closing(sqlite3.connect(root / "snapshots.sqlite3")) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 3)
                self.assertTrue(connection.execute(
                    "SELECT diff_text FROM snapshots WHERE snapshot_id = ?", (third["snapshot_id"],)
                ).fetchone()[0].startswith("--- previous"))

    def test_concurrent_identical_capture_is_transactionally_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteSnapshotStore(Path(temp_dir), timeout=10)

            def run_capture() -> dict:
                return store.capture("Example", self.url, "Policy A", self.captured_at)

            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _item: run_capture(), range(4)))
            self.assertEqual({item["snapshot_id"] for item in results}, {results[0]["snapshot_id"]})
            with closing(sqlite3.connect(store.db_path)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_older_capture_is_rejected_without_partial_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteSnapshotStore(Path(temp_dir))
            latest = store.capture("Example", self.url, "Policy A", self.captured_at)
            with self.assertRaisesRegex(ValueError, "must not be earlier"):
                store.capture("Example", self.url, "Policy B", "2026-07-27T10:00:00+08:00")
            self.assertEqual(store.load_latest("Example", self.url)["snapshot_id"], latest["snapshot_id"])
            with closing(sqlite3.connect(store.db_path)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_unified_cli_captures_to_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            content = root / "page.txt"
            output = root / "snapshot.json"
            content.write_text("Policy A", encoding="utf-8")
            code = cli_main([
                "snapshot", "--platform", "Example", "--url", self.url,
                "--content-file", str(content), "--store", str(root / "store"),
                "--backend", "sqlite", "--captured-at", self.captured_at,
                "--output", str(output),
            ])
            self.assertEqual(code, 0)
            metadata = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(metadata["storage_backend"], "sqlite")
            self.assertTrue((root / "store" / "snapshots.sqlite3").exists())


class FakeS3Error(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.puts: list[dict] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        try:
            body, etag = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise FakeS3Error("NoSuchKey") from exc
        return {"Body": io.BytesIO(body), "ETag": etag}

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        if (Bucket, Key) not in self.objects:
            raise FakeS3Error("NoSuchKey")
        matching = [item for item in self.puts if item["Bucket"] == Bucket and item["Key"] == Key]
        return {"ServerSideEncryption": matching[-1].get("ServerSideEncryption")}

    def list_objects_v2(self, *, Bucket: str, Prefix: str, ContinuationToken=None) -> dict:
        keys = sorted(key for bucket, key in self.objects if bucket == Bucket and key.startswith(Prefix))
        return {"Contents": [{"Key": key} for key in keys], "IsTruncated": False}

    def put_object(self, **arguments) -> dict:
        key = (arguments["Bucket"], arguments["Key"])
        current = self.objects.get(key)
        if arguments.get("IfNoneMatch") == "*" and current is not None:
            raise FakeS3Error("PreconditionFailed")
        if "IfMatch" in arguments and (current is None or current[1] != arguments["IfMatch"]):
            raise FakeS3Error("PreconditionFailed")
        body = bytes(arguments["Body"])
        etag = '"' + hashlib.md5(body, usedforsecurity=False).hexdigest() + '"'
        self.objects[key] = (body, etag)
        self.puts.append(dict(arguments))
        return {"ETag": etag}


class S3SnapshotStoreUnitTest(unittest.TestCase):
    url = "https://seller.example.com/policy?utm_source=test"
    captured_at = "2026-07-28T10:00:00+08:00"

    def test_factory_history_validation_and_encryption_header(self) -> None:
        client = FakeS3Client()
        store = create_snapshot_store("S3", "s3://radar-private/history", client=client)
        self.assertIsInstance(store, S3SnapshotStore)
        first = store.capture("Example", self.url, "Policy A", self.captured_at)
        second = store.capture("Example", self.url, "Policy A", "2026-07-29T10:00:00+08:00")
        third = store.capture("Example", self.url, "Policy B", "2026-07-30T10:00:00+08:00")

        self.assertEqual(first["change_status"], "first_seen")
        self.assertEqual(second["change_status"], "unchanged")
        self.assertEqual(third["change_status"], "changed")
        self.assertEqual(third["previous_snapshot_id"], second["snapshot_id"])
        self.assertEqual(third["storage_backend"], "s3")
        self.assertTrue(third["snapshot_path"].startswith("s3://radar-private/history/"))
        self.assertFalse(Path(third["snapshot_ref"]).is_absolute())
        self.assertIsNotNone(third["diff_ref"])
        self.assertTrue(all(item["ServerSideEncryption"] == "AES256" for item in client.puts))
        self.assertTrue(any(item.get("IfMatch") for item in client.puts))
        self.assertEqual(store.load_latest("Example", self.url)["snapshot_id"], third["snapshot_id"])
        audit = store.audit()
        self.assertTrue(audit["valid"], audit["errors"])
        self.assertEqual(audit["snapshot_count"], 3)

        report = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        report["coverage_ledger"][0]["sources_checked"][0]["snapshot"] = third
        self.assertEqual(validate(report), [])

    def test_idempotency_and_chronological_protection(self) -> None:
        client = FakeS3Client()
        store = S3SnapshotStore("s3://radar-private", client=client)
        first = store.capture("Example", self.url, "Policy A", self.captured_at)
        repeated = store.capture("Example", self.url, "Policy A", self.captured_at)
        self.assertEqual(repeated["snapshot_id"], first["snapshot_id"])
        with self.assertRaisesRegex(ValueError, "must advance"):
            store.capture("Example", self.url, "Policy B", self.captured_at)

    def test_store_uri_rejects_credentials_and_dot_segments(self) -> None:
        self.assertEqual(parse_s3_uri("s3://bucket/prefix"), ("bucket", "prefix"))
        for value in ("https://bucket/key", "s3://user:secret@bucket/key", "s3://bucket/a/../b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_s3_uri(value)
        self.assertEqual(validate_endpoint_url("https://objects.example.com/"), "https://objects.example.com")
        self.assertEqual(validate_endpoint_url("http://127.0.0.1:9000"), "http://127.0.0.1:9000")
        for endpoint in ("http://objects.example.com", "https://user:secret@objects.example.com"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_endpoint_url(endpoint)

    def test_audit_detects_tampering_and_unreferenced_objects(self) -> None:
        client = FakeS3Client()
        store = S3SnapshotStore("s3://radar-private/history", client=client)
        result = store.capture("Example", self.url, "Policy A", self.captured_at)
        snapshot_key = result["snapshot_ref"]
        body, etag = client.objects[("radar-private", snapshot_key)]
        record = json.loads(body.decode("utf-8"))
        record["content"] = "tampered"
        client.objects[("radar-private", snapshot_key)] = (
            (json.dumps(record) + "\n").encode("utf-8"),
            etag,
        )
        orphan = "history/pages/orphan/snapshots/orphan.json"
        client.put_object(
            Bucket="radar-private", Key=orphan, Body=b"{}", ContentType="application/json",
            ServerSideEncryption="AES256", IfNoneMatch="*",
        )
        audit = store.audit()
        self.assertFalse(audit["valid"])
        self.assertTrue(any("content hash mismatch" in error for error in audit["errors"]))
        self.assertTrue(any("unreferenced snapshot object" in error for error in audit["errors"]))


@unittest.skipUnless(shutil.which("git"), "Git executable is required")
class GitSnapshotStoreUnitTest(unittest.TestCase):
    url = "https://seller.example.com/policy?utm_source=test"
    captured_at = "2026-07-28T10:00:00+08:00"

    def test_factory_commits_history_and_validates_report_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "store"
            store = create_snapshot_store("GIT", root)
            self.assertIsInstance(store, GitSnapshotStore)
            first = store.capture("Example", self.url, "Policy A", self.captured_at)
            second = store.capture("Example", self.url, "Policy B", "2026-07-29T10:00:00+08:00")

            self.assertEqual(first["storage_backend"], "git")
            self.assertEqual(second["change_status"], "changed")
            self.assertEqual(second["previous_snapshot_id"], first["snapshot_id"])
            self.assertRegex(second["git_commit"], r"^[0-9a-f]{40,64}$")
            self.assertRegex(second["git_tree"], r"^[0-9a-f]{40,64}$")
            self.assertTrue((root / second["snapshot_ref"]).exists())
            report = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
            report["coverage_ledger"][0]["sources_checked"][0]["snapshot"] = second
            self.assertEqual(validate(report), [])
            audit = store.audit()
            self.assertTrue(audit["valid"], audit["errors"])
            self.assertEqual(audit["snapshot_count"], 2)

    def test_exact_capture_is_idempotent_and_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "store"
            store = GitSnapshotStore(root)
            first = store.capture("Example", self.url, "Policy A", self.captured_at)
            repeated = store.capture("Example", self.url, "Policy A", self.captured_at)
            self.assertEqual(repeated["git_commit"], first["git_commit"])
            snapshot_path = root / first["snapshot_ref"]
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["content"] = "tampered committed content"
            snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "uncommitted changes"):
                store.capture("Example", self.url, "Policy B", "2026-07-29T10:00:00+08:00")
            store._git("add", "--", first["snapshot_ref"])
            store._commit("Test committed tampering")
            audit = store.audit()
            self.assertFalse(audit["valid"])
            self.assertTrue(any("content hash mismatch" in error for error in audit["errors"]))

    def test_same_timestamp_with_different_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = GitSnapshotStore(Path(temp_dir) / "store")
            first = store.capture("Example", self.url, "Policy A", self.captured_at)
            with self.assertRaisesRegex(ValueError, "must advance"):
                store.capture("Example", self.url, "Policy B", self.captured_at)
            self.assertEqual(store.load_latest("Example", self.url)["snapshot_id"], first["snapshot_id"])
            self.assertTrue(store.audit()["valid"])

    def test_refuses_unmarked_or_nonempty_store_and_cli_audits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            nonempty = temp / "nonempty"
            nonempty.mkdir()
            (nonempty / "user.txt").write_text("do not commit", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-empty"):
                GitSnapshotStore(nonempty)

            root = temp / "store"
            content = temp / "page.txt"
            output = temp / "snapshot.json"
            audit_output = temp / "audit.json"
            content.write_text("Policy A", encoding="utf-8")
            self.assertEqual(cli_main([
                "snapshot", "--platform", "Example", "--url", self.url,
                "--content-file", str(content), "--store", str(root),
                "--backend", "git", "--captured-at", self.captured_at,
                "--output", str(output),
            ]), 0)
            self.assertEqual(cli_main([
                "snapshot-audit", "--store", str(root), "--output", str(audit_output),
            ]), 0)
            self.assertTrue(json.loads(audit_output.read_text(encoding="utf-8"))["valid"])


if __name__ == "__main__":
    unittest.main()
