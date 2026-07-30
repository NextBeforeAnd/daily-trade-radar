from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skill" / "daily-trade-radar" / "src"
sys.path.insert(0, str(SRC))

from daily_trade_radar.cli import main as cli_main
from daily_trade_radar.calibration_scaffold import merge_existing_scaffold, scaffold_calibration
from daily_trade_radar.evaluation import evaluate, main as evaluation_main
from daily_trade_radar.evaluation_history import evaluate_history
from daily_trade_radar.evaluation_scaffold import scaffold_labels


def event(event_id: str, *, source_url: str = "https://authority.example/policy", level: str = "high") -> dict:
    return {
        "id": event_id,
        "source_url": source_url,
        "published_date": "2026-07-29",
        "effective_date": "2026-07-30",
        "deadline": None,
        "status": "new",
        "level": level,
    }


def report() -> dict:
    return {
        "events": [event("event-a"), event("event-b", source_url="https://authority.example/rule")],
        "deduplication": {
            "matches": [{
                "current_id": "event-a",
                "previous_id": "previous-a",
                "disposition": "material_update",
            }]
        },
    }


def labels(*, review_status: str = "independently_reviewed") -> dict:
    value = {
        "dataset_version": 1,
        "dataset_name": "synthetic-evaluation-fixture",
        "review_status": review_status,
        "records": [
            {
                "event_id": "event-a",
                "should_include": True,
                "accepted_primary_source_urls": ["https://authority.example/policy"],
                "published_date": "2026-07-29",
                "effective_date": "2026-07-30",
                "deadline": None,
                "status": "new",
                "level": "high",
            },
            {
                "event_id": "event-b",
                "should_include": True,
                "accepted_primary_source_urls": ["https://authority.example/rule"],
                "published_date": "2026-07-29",
                "effective_date": "2026-07-30",
                "deadline": None,
                "status": "new",
                "level": "high",
            },
            {"event_id": "rejected-lead", "should_include": False},
        ],
        "deduplication_cases": [{
            "current_id": "event-a",
            "previous_id": "previous-a",
            "expected_disposition": "material_update",
        }],
    }
    if review_status == "independently_reviewed":
        value.update({"reviewed_by": "fixture-reviewer", "reviewed_at": "2026-07-30T12:00:00+08:00"})
    return value


def calibration_label_record(
    event_id: str,
    *,
    title: str,
    authority: str,
    source_title: str,
    source_url: str,
    published_date: str = "2026-07-23",
    effective_date: str | None = "2026-07-24",
    level: str = "high",
) -> dict:
    return {
        "event_id": event_id,
        "should_include": True,
        "accepted_primary_source_urls": [source_url],
        "published_date": published_date,
        "effective_date": effective_date,
        "deadline": None,
        "status": "ongoing",
        "level": level,
        "review_context": {
            "title": title,
            "jurisdiction": "test scope",
            "authority": authority,
            "source_title": source_title,
            "source_url": source_url,
        },
    }


class EvaluationTest(unittest.TestCase):
    def test_perfect_report_passes_quality_gate(self) -> None:
        result = evaluate(report(), labels(), minimum_positive_events=2)
        self.assertTrue(result["quality_gate"]["passed"])
        self.assertEqual(result["detection"]["precision"], 1.0)
        self.assertEqual(result["detection"]["recall"], 1.0)
        self.assertEqual(result["factual"]["primary_source_rate"], 1.0)
        self.assertEqual(result["factual"]["date_accuracy"], 1.0)
        self.assertEqual(result["deduplication"]["accuracy"], 1.0)

    def test_false_positive_bad_source_and_date_fail_closed(self) -> None:
        prediction = report()
        prediction["events"][0]["source_url"] = "https://secondary.example/story"
        prediction["events"][0]["effective_date"] = "2026-08-01"
        prediction["events"].append(event("hallucinated-event"))
        result = evaluate(prediction, labels(), minimum_positive_events=2)
        self.assertFalse(result["quality_gate"]["passed"])
        self.assertEqual(result["detection"]["false_positive_ids"], ["hallucinated-event"])
        self.assertEqual(result["factual"]["unsupported_source_count"], 2)
        self.assertEqual(result["factual"]["field_error_ids"]["effective_date"], ["event-a"])

    def test_missing_deduplication_labels_cannot_silently_pass_default_gate(self) -> None:
        gold = labels()
        gold["deduplication_cases"] = []
        result = evaluate(report(), gold, minimum_positive_events=2)
        self.assertIsNone(result["deduplication"]["accuracy"])
        self.assertFalse(result["quality_gate"]["checks"]["deduplication_accuracy"])

    def test_draft_labels_require_explicit_allowance(self) -> None:
        draft = labels(review_status="draft")
        strict = evaluate(report(), draft, minimum_positive_events=2)
        allowed = evaluate(
            report(), draft, minimum_positive_events=2, require_independently_reviewed=False
        )
        self.assertFalse(strict["quality_gate"]["checks"]["independently_reviewed"])
        self.assertTrue(allowed["quality_gate"]["passed"])

    def test_cli_writes_report_and_uses_distinct_gate_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "report.json"
            labels_path = root / "labels.json"
            output_path = root / "evaluation.json"
            report_path.write_text(json.dumps(report()), encoding="utf-8")
            labels_path.write_text(json.dumps(labels()), encoding="utf-8")
            args = [
                str(report_path), str(labels_path), "--minimum-positive-events", "2",
                "--output", str(output_path),
            ]
            self.assertEqual(evaluation_main(args), 0)
            self.assertTrue(json.loads(output_path.read_text(encoding="utf-8"))["quality_gate"]["passed"])

            failing = labels(review_status="draft")
            labels_path.write_text(json.dumps(failing), encoding="utf-8")
            self.assertEqual(cli_main(["evaluate", *args]), 3)

    def test_invalid_or_duplicate_labels_are_rejected(self) -> None:
        gold = labels()
        gold["records"].append(dict(gold["records"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate event_id"):
            evaluate(report(), gold, minimum_positive_events=2)

    def test_scaffold_preserves_rejected_candidates_and_deduplication_context(self) -> None:
        candidate = {
            "events": [event("event-a"), event("rejected-lead")],
        }
        final = report()
        result = scaffold_labels(candidate, final, "draft-run")
        records = {record["event_id"]: record for record in result["records"]}
        self.assertEqual(result["review_status"], "draft")
        self.assertTrue(records["event-a"]["should_include"])
        self.assertFalse(records["rejected-lead"]["should_include"])
        self.assertIn("event-b", records)
        self.assertIn("verify provenance", records["event-b"]["review_note"])
        self.assertEqual(result["deduplication_cases"][0]["expected_disposition"], "material_update")

    def test_scaffold_cli_writes_review_ready_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path = root / "current.json"
            final_path = root / "deduplicated.json"
            output_path = root / "labels.json"
            candidate_path.write_text(json.dumps({"events": report()["events"]}), encoding="utf-8")
            final_path.write_text(json.dumps(report()), encoding="utf-8")
            self.assertEqual(cli_main([
                "evaluation-scaffold", str(candidate_path), str(final_path), "--dataset-name", "draft-run",
                "--output", str(output_path),
            ]), 0)
            draft = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(draft["dataset_name"], "draft-run")
            self.assertEqual(len(draft["records"]), 2)

    def test_history_evaluation_namespaces_repeated_event_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            labels_root = root / "labels"
            reports_root = root / "reports"
            labels_root.mkdir()
            manifest = {"files": ["run-a.labels.json", "run-b.labels.json"]}
            for run in ("run-a", "run-b"):
                (reports_root / run).mkdir(parents=True)
                (labels_root / f"{run}.labels.json").write_text(
                    json.dumps(labels()), encoding="utf-8"
                )
                (reports_root / run / "deduplicated.json").write_text(
                    json.dumps(report()), encoding="utf-8"
                )
            result = evaluate_history(
                manifest, labels_root, reports_root, minimum_positive_events=4
            )
            self.assertTrue(result["quality_gate"]["passed"])
            self.assertEqual(result["run_count"], 2)
            self.assertEqual(result["sample"]["positive_event_count"], 4)
            self.assertEqual(result["sample"]["deduplication_case_count"], 2)

    def test_calibration_scaffold_excludes_generated_scores_and_rejected_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            label_data = labels()
            label_data["records"][0]["review_context"] = {"title": "Evidence-led title"}
            (root / "run-a.labels.json").write_text(json.dumps(label_data), encoding="utf-8")
            result = scaffold_calibration({"files": ["run-a.labels.json"]}, root)
            self.assertEqual(result["sample"]["record_count"], 2)
            self.assertTrue(result["generated_scores_excluded"])
            self.assertEqual(result["records"][0]["event_id"], "event-a")
            self.assertEqual(result["records"][0]["review_context"]["title"], "Evidence-led title")
            self.assertEqual(result["calibration_scaffold_version"], 2)
            self.assertEqual(
                result["records"][0]["review_evidence"]["published_date"],
                "2026-07-29",
            )
            self.assertEqual(len(result["records"][0]["review_fingerprint"]), 64)
            self.assertEqual(set(result["records"][0]["score_breakdown"].values()), {None})
            self.assertNotIn("rejected-lead", {item["event_id"] for item in result["records"]})

    def test_calibration_scaffold_deduplicates_runs_and_excludes_level_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = labels()
            second = labels()
            second["records"][0]["level"] = "medium"
            (root / "run-a.labels.json").write_text(json.dumps(first), encoding="utf-8")
            (root / "run-b.labels.json").write_text(json.dumps(second), encoding="utf-8")
            result = scaffold_calibration(
                {"files": ["run-a.labels.json", "run-b.labels.json"]}, root
            )
            self.assertEqual(result["sample"]["source_observation_count"], 4)
            self.assertEqual(result["sample"]["unique_event_count"], 2)
            self.assertEqual(result["sample"]["record_count"], 1)
            self.assertEqual(result["excluded_level_conflicts"][0]["event_id"], "event-a")
            self.assertEqual(result["records"][0]["source_runs"], ["run-a", "run-b"])

    def test_calibration_scaffold_auto_merges_cross_id_same_announcement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_url = (
                "https://sellercentral.amazon.com/seller-forums/discussions/"
                "t/145b6d0f-999c-4555-896c-c694bda2e470"
            )
            first = labels()
            second = labels()
            first["records"] = [calibration_label_record(
                "amazon-us-product-title-75-character-rule-2026",
                title="Amazon美国站商品标题75字符规则今天开始执行",
                authority="Amazon",
                source_title="Updates to improve your product titles begin on July 27",
                source_url=source_url,
                published_date="2026-06-10",
                effective_date="2026-07-27",
            )]
            second["records"] = [calibration_label_record(
                "amazon-product-title-75-character-2026",
                title="Amazon 商品标题 75 字符上限已生效，超长标题将被逐步自动改写（补录）",
                authority="Amazon",
                source_title="Updates to improve your product titles begin on July 27",
                source_url=source_url + "?utm_source=duplicate",
                published_date="2026-06-10",
                effective_date="2026-07-27",
            )]
            (root / "run-a.labels.json").write_text(json.dumps(first), encoding="utf-8")
            (root / "run-b.labels.json").write_text(json.dumps(second), encoding="utf-8")

            result = scaffold_calibration(
                {"files": ["run-a.labels.json", "run-b.labels.json"]}, root
            )

            self.assertEqual(result["sample"]["record_count"], 1)
            self.assertEqual(result["sample"]["excluded_semantic_duplicate_count"], 1)
            self.assertEqual(
                result["records"][0]["semantic_aliases"],
                ["amazon-product-title-75-character-2026"],
            )
            self.assertEqual(result["records"][0]["source_runs"], ["run-a", "run-b"])
            duplicate = result["excluded_semantic_duplicates"][0]
            self.assertEqual(
                duplicate["canonical_event_id"],
                "amazon-us-product-title-75-character-rule-2026",
            )
            self.assertTrue(duplicate["signals"]["same_canonical_url"])

    def test_calibration_scaffold_auto_merges_same_measure_across_official_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = labels()
            second = labels()
            first["records"] = [calibration_label_record(
                "eu-russia-21st-sanctions-package-2026",
                title="欧盟第21轮对俄制裁已生效，新增中国及香港实体与军工物项限制",
                authority="Council of the European Union",
                source_title=(
                    "Council Regulation (EU) 2026/1848 of 23 July 2026 amending "
                    "Regulation (EU) No 833/2014"
                ),
                source_url="https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202601848",
            )]
            second["records"] = [calibration_label_record(
                "eu-russia-sanctions-package-21-2026",
                title="欧盟第 21 轮对俄制裁扩大银行、加密、影子船队及贸易限制（补录）",
                authority="Council of the European Union",
                source_title=(
                    "21st package of sanctions: EU hits Russian energy, financial services "
                    "and crypto hard"
                ),
                source_url=(
                    "https://www.consilium.europa.eu/en/press/press-releases/2026/07/23/"
                    "21st-package-of-sanctions-eu-hits-russian-energy-financial-services-and-crypto-hard/"
                ),
                effective_date=None,
            )]
            (root / "run-a.labels.json").write_text(json.dumps(first), encoding="utf-8")
            (root / "run-b.labels.json").write_text(json.dumps(second), encoding="utf-8")

            result = scaffold_calibration(
                {"files": ["run-a.labels.json", "run-b.labels.json"]}, root
            )

            self.assertEqual(result["sample"]["record_count"], 1)
            self.assertEqual(result["sample"]["excluded_semantic_duplicate_count"], 1)
            duplicate = result["excluded_semantic_duplicates"][0]
            self.assertEqual(duplicate["event_id"], "eu-russia-sanctions-package-21-2026")
            self.assertIn("21", duplicate["signals"]["shared_numeric_anchors"])
            self.assertGreaterEqual(
                duplicate["signals"]["title_similarity"],
                0.44,
            )

    def test_calibration_scaffold_queues_ambiguous_reused_url_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = labels()
            second = labels()
            shared_url = "https://authority.example/rolling-announcements"
            first["records"] = [calibration_label_record(
                "authority-rule-alpha",
                title="Authority changes licensing for product alpha",
                authority="Example Authority",
                source_title="Rolling announcements",
                source_url=shared_url,
                published_date="2026-07-20",
            )]
            second["records"] = [calibration_label_record(
                "authority-rule-beta",
                title="Authority opens consultation on product beta",
                authority="Example Authority",
                source_title="Rolling announcements",
                source_url=shared_url,
                published_date="2026-07-29",
            )]
            (root / "run-a.labels.json").write_text(json.dumps(first), encoding="utf-8")
            (root / "run-b.labels.json").write_text(json.dumps(second), encoding="utf-8")

            result = scaffold_calibration(
                {"files": ["run-a.labels.json", "run-b.labels.json"]}, root
            )

            self.assertEqual(result["sample"]["excluded_semantic_duplicate_count"], 0)
            self.assertEqual(result["sample"]["pending_semantic_duplicate_review_count"], 1)
            self.assertEqual(result["sample"]["pending_semantic_duplicate_record_count"], 2)
            self.assertEqual(result["sample"]["record_count"], 0)
            self.assertEqual(
                result["semantic_duplicate_review_queue"][0]["reason"],
                "semantic_duplicate_requires_review",
            )

    def test_calibration_scaffold_excludes_cross_alias_level_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared_url = "https://authority.example/rule-42"
            first = labels()
            second = labels()
            first["records"] = [calibration_label_record(
                "rule-42-original-id",
                title="Rule 42 takes effect",
                authority="Example Authority",
                source_title="Rule 42",
                source_url=shared_url,
                level="high",
            )]
            second["records"] = [calibration_label_record(
                "rule-42-renamed-id",
                title="Rule 42 is now effective",
                authority="Example Authority",
                source_title="Rule 42",
                source_url=shared_url,
                level="medium",
            )]
            (root / "run-a.labels.json").write_text(json.dumps(first), encoding="utf-8")
            (root / "run-b.labels.json").write_text(json.dumps(second), encoding="utf-8")

            result = scaffold_calibration(
                {"files": ["run-a.labels.json", "run-b.labels.json"]}, root
            )

            self.assertEqual(result["sample"]["record_count"], 0)
            self.assertEqual(result["sample"]["excluded_semantic_level_conflict_count"], 1)
            conflict = result["excluded_semantic_level_conflicts"][0]
            self.assertEqual(
                conflict["reason"],
                "reviewed_level_changed_across_semantic_duplicates",
            )
            self.assertEqual(conflict["reviewed_levels"], ["high", "medium"])

    def test_incremental_merge_preserves_unchanged_scores_and_leaves_new_records_blank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = labels()
            first["records"] = first["records"][:1]
            (root / "run-a.labels.json").write_text(json.dumps(first), encoding="utf-8")
            old = scaffold_calibration({"files": ["run-a.labels.json"]}, root)
            old_record = old["records"][0]
            old_record["score_breakdown"] = {dimension: 2 for dimension in old_record["score_breakdown"]}
            old_record["score"] = 10

            second = labels()
            (root / "run-b.labels.json").write_text(json.dumps(second), encoding="utf-8")
            fresh = scaffold_calibration({"files": ["run-b.labels.json"]}, root)
            result = merge_existing_scaffold(fresh, old)

            records = {record["event_id"]: record for record in result["records"]}
            self.assertEqual(records["event-a"]["score"], 10)
            self.assertEqual(records["event-a"]["merge_status"], "preserved_complete")
            self.assertEqual(set(records["event-b"]["score_breakdown"].values()), {None})
            self.assertEqual(records["event-b"]["merge_status"], "new_unscored")
            self.assertEqual(result["sample"]["completed_score_breakdown_count"], 1)
            self.assertEqual(result["sample"]["pending_score_breakdown_count"], 1)
            diff = result["incremental_diff"]
            self.assertEqual(diff["summary"]["preserved_complete"], 1)
            self.assertEqual(diff["summary"]["new_unscored"], 1)
            self.assertFalse(diff["calibration_gate"]["ready"])
            self.assertEqual(
                diff["calibration_gate"]["blockers"][0],
                {"type": "new_events_require_scoring", "event_ids": ["event-b"]},
            )

    def test_incremental_merge_resets_score_when_evidence_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = labels()
            original["records"] = original["records"][:1]
            (root / "old.labels.json").write_text(json.dumps(original), encoding="utf-8")
            old = scaffold_calibration({"files": ["old.labels.json"]}, root)
            old["records"][0]["score_breakdown"] = {
                dimension: 2 for dimension in old["records"][0]["score_breakdown"]
            }
            old["records"][0]["score"] = 10

            changed = labels()
            changed["records"] = changed["records"][:1]
            changed["records"][0]["accepted_primary_source_urls"] = [
                "https://authority.example/revised-policy"
            ]
            changed["records"][0]["review_context"] = {
                "source_url": "https://authority.example/revised-policy"
            }
            (root / "new.labels.json").write_text(json.dumps(changed), encoding="utf-8")
            fresh = scaffold_calibration({"files": ["new.labels.json"]}, root)
            result = merge_existing_scaffold(fresh, old)

            record = result["records"][0]
            self.assertEqual(record["merge_status"], "evidence_changed_requires_review")
            self.assertNotIn("score", record)
            self.assertEqual(set(record["score_breakdown"].values()), {None})
            self.assertEqual(result["incremental_merge"]["reset_changed_count"], 1)
            self.assertEqual(
                result["incremental_merge"]["review_queue"][0]["reason"],
                "review_evidence_fingerprint_changed",
            )
            self.assertEqual(result["incremental_diff"]["summary"]["reset_changed"], 1)
            self.assertFalse(result["incremental_diff"]["calibration_gate"]["ready"])

    def test_incremental_merge_retains_manual_existing_only_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = labels()
            source["records"] = source["records"][:1]
            (root / "run-a.labels.json").write_text(json.dumps(source), encoding="utf-8")
            old = scaffold_calibration({"files": ["run-a.labels.json"]}, root)
            manual = json.loads(json.dumps(old["records"][0]))
            manual["event_id"] = "manual-watch-observation"
            manual["reviewed_level"] = "watch"
            manual["score_breakdown"] = {
                dimension: 0 for dimension in manual["score_breakdown"]
            }
            manual["score"] = 0
            manual.pop("review_fingerprint", None)
            old["records"].append(manual)

            fresh = scaffold_calibration({"files": ["run-a.labels.json"]}, root)
            result = merge_existing_scaffold(fresh, old)
            retained = next(
                record for record in result["records"]
                if record["event_id"] == "manual-watch-observation"
            )

            self.assertEqual(retained["merge_status"], "retained_existing_only")
            self.assertEqual(retained["record_origin"], "existing_only")
            self.assertEqual(result["incremental_merge"]["retained_existing_only_count"], 1)

    def test_incremental_merge_rejects_inconsistent_existing_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = labels()
            source["records"] = source["records"][:1]
            (root / "run-a.labels.json").write_text(json.dumps(source), encoding="utf-8")
            existing = scaffold_calibration({"files": ["run-a.labels.json"]}, root)
            existing["records"][0]["score_breakdown"] = {
                dimension: 2 for dimension in existing["records"][0]["score_breakdown"]
            }
            existing["records"][0]["score"] = 9
            fresh = scaffold_calibration({"files": ["run-a.labels.json"]}, root)

            with self.assertRaisesRegex(ValueError, "score must equal score_breakdown total 10"):
                merge_existing_scaffold(fresh, existing)

    def test_calibration_scaffold_cli_protects_existing_review_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            output_path = root / "worksheet.json"
            (root / "run-a.labels.json").write_text(json.dumps(labels()), encoding="utf-8")
            manifest_path.write_text(
                json.dumps({"files": ["run-a.labels.json"]}), encoding="utf-8"
            )
            output_path.write_text("human work", encoding="utf-8")
            self.assertEqual(cli_main([
                "calibration-scaffold", str(manifest_path), "--output", str(output_path),
            ]), 1)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "human work")

    def test_calibration_scaffold_cli_merges_existing_scores_to_new_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            existing_path = root / "reviewed.json"
            output_path = root / "updated.json"
            diff_path = root / "updated.diff.json"
            (root / "run-a.labels.json").write_text(json.dumps(labels()), encoding="utf-8")
            manifest = {"files": ["run-a.labels.json"]}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            existing = scaffold_calibration(manifest, root)
            for record in existing["records"]:
                record["score_breakdown"] = {
                    dimension: 2 for dimension in record["score_breakdown"]
                }
                record["score"] = 10
            existing_path.write_text(json.dumps(existing), encoding="utf-8")

            self.assertEqual(cli_main([
                "calibration-scaffold",
                str(manifest_path),
                "--existing",
                str(existing_path),
                "--output",
                str(output_path),
                "--diff-output",
                str(diff_path),
                "--require-calibration-ready",
            ]), 0)
            updated = json.loads(output_path.read_text(encoding="utf-8"))
            diff = json.loads(diff_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["incremental_merge"]["preserved_complete_count"], 2)
            self.assertEqual(updated["sample"]["pending_score_breakdown_count"], 0)
            self.assertTrue(diff["calibration_gate"]["ready"])
            self.assertEqual(diff["summary"]["preserved_complete"], 2)

    def test_calibration_scaffold_cli_gate_returns_three_after_writing_blocked_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            existing_path = root / "reviewed.json"
            output_path = root / "updated.json"
            diff_path = root / "updated.diff.json"
            source = labels()
            source["records"] = source["records"][:1]
            (root / "old.labels.json").write_text(json.dumps(source), encoding="utf-8")
            existing = scaffold_calibration({"files": ["old.labels.json"]}, root)
            existing["records"][0]["score_breakdown"] = {
                dimension: 2 for dimension in existing["records"][0]["score_breakdown"]
            }
            existing["records"][0]["score"] = 10
            existing_path.write_text(json.dumps(existing), encoding="utf-8")
            (root / "new.labels.json").write_text(json.dumps(labels()), encoding="utf-8")
            manifest_path.write_text(json.dumps({"files": ["new.labels.json"]}), encoding="utf-8")

            self.assertEqual(cli_main([
                "calibration-scaffold",
                str(manifest_path),
                "--existing",
                str(existing_path),
                "--output",
                str(output_path),
                "--diff-output",
                str(diff_path),
                "--require-calibration-ready",
            ]), 3)
            self.assertTrue(output_path.exists())
            diff = json.loads(diff_path.read_text(encoding="utf-8"))
            self.assertFalse(diff["calibration_gate"]["ready"])
            self.assertEqual(diff["summary"]["new_unscored"], 1)


if __name__ == "__main__":
    unittest.main()
