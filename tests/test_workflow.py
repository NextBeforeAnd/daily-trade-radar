from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill" / "daily-trade-radar"
SCRIPTS = SKILL / "scripts"
EXAMPLES = ROOT / "examples"


class WorkflowTest(unittest.TestCase):
    def run_script(self, name: str, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *(str(arg) for arg in args)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def platform_event(self, event: dict) -> dict:
        event = dict(event)
        event["platform_policy"] = {
            "platform": "TikTok Shop",
            "seller_market": "US",
            "program": "US local seller",
            "policy_area": "listing_product_compliance",
            "change_type": "rule_change",
            "seller_scope": "US sellers in named categories",
            "previous_state": None,
            "new_state": "Listing-level documents are required.",
            "enforcement_consequence": "Listings cannot go live without documents.",
            "backend_verification_required": True,
        }
        event["action_items"] = [{
            "owner": "marketplace operations",
            "action": "Export affected listings and map each SKU to a document.",
            "deadline": "within 2 business days",
            "completion_evidence": "Reviewed SKU-document matrix",
        }]
        return event

    def coverage_entry(self, platform: str = "TikTok Shop") -> dict:
        def snapshot(snapshot_id: str, captured_at: str) -> dict:
            return {
                "snapshot_id": snapshot_id,
                "captured_at": captured_at,
                "content_hash": "a" * 64,
                "previous_snapshot_id": None,
                "change_status": "first_seen",
                "diff_summary": "First captured snapshot; no historical baseline is available.",
                "snapshot_path": f"C:/snapshots/{snapshot_id}.json",
                "diff_path": None,
            }
        return {
            "platform": platform,
            "seller_market": "US",
            "program": "US local seller",
            "lookback_start": "2026-07-14T16:30:00+08:00",
            "public_update_checked": True,
            "current_policy_checked": True,
            "dashboard_checked": False,
            "access_result": "login_required",
            "checked_at": "2026-07-21T16:30:00+08:00",
            "sources_checked": [
                {
                    "source_type": "official_updates",
                    "url": "https://seller-us.tiktok.com/university/",
                    "result": "no_relevant_update",
                    "checked_at": "2026-07-21T16:20:00+08:00",
                    "notes": "Opened the official update route.",
                    "snapshot": snapshot("20260721162000-aaaaaaaaaaaa", "2026-07-21T16:20:00+08:00"),
                },
                {
                    "source_type": "current_policy",
                    "url": "https://seller-us.tiktok.com/university/essay?knowledge_id=example",
                    "result": "no_relevant_update",
                    "checked_at": "2026-07-21T16:25:00+08:00",
                    "notes": "Opened the current policy page.",
                    "snapshot": snapshot("20260721162500-aaaaaaaaaaaa", "2026-07-21T16:25:00+08:00"),
                },
                {
                    "source_type": "dashboard",
                    "url": "https://seller-us.tiktok.com/",
                    "result": "login_required",
                    "checked_at": "2026-07-21T16:30:00+08:00",
                    "notes": "Authentication was required.",
                },
            ],
            "verified_event_ids": [],
            "gaps": ["Seller Center account notices were not accessible"],
        }

    def deduplicate_pair(self, previous: dict, current: dict) -> dict:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            previous_path = temp / "previous.json"
            current_path = temp / "current.json"
            output_path = temp / "deduplicated.json"
            previous_path.write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")
            current_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            self.run_script(
                "deduplicate.py",
                current_path,
                "--previous",
                previous_path,
                "--output",
                output_path,
            )
            return json.loads(output_path.read_text(encoding="utf-8"))

    def test_skill_frontmatter(self) -> None:
        content = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        frontmatter = content.split("---", 2)[1]
        self.assertIn("name: daily-trade-radar", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertIn("今天的外贸行情", frontmatter)
        agent_config = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("allow_implicit_invocation: true", agent_config)
        self.assertIn("$daily-trade-radar", agent_config)

    def test_validate_deduplicate_and_render(self) -> None:
        self.run_script("validate_events.py", EXAMPLES / "previous.json")
        self.run_script("validate_events.py", EXAMPLES / "current.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            deduplicated = temp / "deduplicated.json"
            markdown = temp / "radar.md"

            self.run_script(
                "deduplicate.py",
                EXAMPLES / "current.json",
                "--previous",
                EXAMPLES / "previous.json",
                "--output",
                deduplicated,
            )
            data = json.loads(deduplicated.read_text(encoding="utf-8"))
            self.assertEqual([event["id"] for event in data["events"]], ["example-eu-product-rule-2026"])
            self.assertEqual(data["deduplication"]["matches"][0]["disposition"], "duplicate_removed")

            self.run_script("validate_events.py", deduplicated)
            self.run_script("build_markdown.py", deduplicated, "--output", markdown)
            rendered = markdown.read_text(encoding="utf-8")
            self.assertIn("示例欧盟产品规则更新", rendered)
            self.assertIn("移除 1 条", rendered)

    def test_deduplicate_ignores_editorial_rewrites(self) -> None:
        previous = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        current = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        current["report_date"] = "2026-07-21"
        current["events"][0]["summary"] = "商品标题规则将进行调整。"
        current["events"][0]["impact"] = "需要重新检查商品标题。"
        current["events"][0]["action"] = "本周由平台运营导出商品，并复核标题！"
        current["events"][0]["score"] = 7

        result = self.deduplicate_pair(previous, current)

        self.assertEqual(result["events"], [])
        match = result["deduplication"]["matches"][0]
        self.assertEqual(match["disposition"], "duplicate_removed")
        self.assertEqual(match["change_reasons"], [])

    def test_deduplicate_keeps_material_fact_change(self) -> None:
        previous = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        current = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        previous["events"][0]["summary"] = "平台将加征10%服务费。"
        current["report_date"] = "2026-07-21"
        current["events"][0]["summary"] = "平台将加征12.5%服务费。"

        result = self.deduplicate_pair(previous, current)

        self.assertEqual([event["id"] for event in result["events"]], ["example-marketplace-title-rule-2026"])
        match = result["deduplication"]["matches"][0]
        self.assertEqual(match["disposition"], "material_update")
        self.assertIn("summary_facts_or_obligation", match["change_reasons"])

    def test_deduplicate_does_not_treat_chinese_substring_as_obligation(self) -> None:
        previous = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        current = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        previous["events"][0]["summary"] = "货物进入消费。"
        current["report_date"] = "2026-07-21"
        current["events"][0]["summary"] = "货物从仓库提取消费。"

        result = self.deduplicate_pair(previous, current)

        self.assertEqual(result["events"], [])
        self.assertEqual(result["deduplication"]["matches"][0]["disposition"], "duplicate_removed")

    def test_deduplicate_keeps_effective_date_operational_refresh(self) -> None:
        previous = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        current = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        previous["events"][0]["effective_date"] = "2026-07-21"
        current["report_date"] = "2026-07-21"
        current["events"][0]["effective_date"] = "2026-07-21"
        current["events"][0]["status"] = "effective"

        result = self.deduplicate_pair(previous, current)

        self.assertEqual([event["id"] for event in result["events"]], ["example-marketplace-title-rule-2026"])
        match = result["deduplication"]["matches"][0]
        self.assertEqual(match["disposition"], "operational_refresh")
        self.assertIn("effective_date_reached", match["change_reasons"])

    def test_render_english_report(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        data["language"] = "en-US"
        data["coverage_gaps"] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "english.json"
            markdown = temp / "radar-en.md"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            self.run_script("build_markdown.py", source, "--output", markdown)
            rendered = markdown.read_text(encoding="utf-8")
            self.assertIn("# Daily Trade Radar | 2026-07-21", rendered)
            self.assertIn("## Today's assessment", rendered)
            self.assertIn("| Medium | Ongoing |", rendered)
            self.assertIn("| High | New today |", rendered)
            self.assertIn("**示例欧盟产品规则更新:**", rendered)
            self.assertIn("## Official sources", rendered)
            self.assertIn("- No known coverage gaps.", rendered)
            self.assertNotIn("## 今日判断", rendered)

    def test_validate_and_render_structured_platform_policy(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        data["events"][1] = self.platform_event(data["events"][1])

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "platform.json"
            markdown = temp / "platform.md"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            self.run_script("validate_events.py", source)
            self.run_script("build_markdown.py", source, "--output", markdown)
            rendered = markdown.read_text(encoding="utf-8")
            self.assertIn("## 平台政策分析", rendered)
            self.assertIn("TikTok Shop / US", rendered)
            self.assertIn("完成凭证：Reviewed SKU-document matrix", rendered)

    def test_validate_and_render_reporting_window_and_coverage_ledger(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        data["scope"] = ["EU", "TikTok Shop US"]
        data["window_start"] = "2026-07-20T17:00:00+08:00"
        data["coverage_ledger"] = [self.coverage_entry()]
        data["events"][0]["deadline_at"] = "2026-07-31T23:59:00-04:00"
        data["events"][0]["source_timezone"] = "America/New_York"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "coverage.json"
            markdown = temp / "coverage.md"
            docx = temp / "coverage.docx"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            self.run_script("validate_events.py", source)
            self.run_script("build_markdown.py", source, "--output", markdown)
            self.run_script("build_docx.py", source, "--output", docx)

            rendered = markdown.read_text(encoding="utf-8")
            self.assertIn("## 平台覆盖台账", rendered)
            self.assertIn("2026-07-20T17:00:00+08:00", rendered)
            self.assertIn("2026-07-31T23:59:00-04:00", rendered)
            self.assertIn("https://seller-us.tiktok.com/university/", rendered)
            self.assertIn("快照: first_seen", rendered)
            self.assertIn("需要登录", rendered)
            with zipfile.ZipFile(docx) as package:
                document_xml = package.read("word/document.xml").decode("utf-8")
                self.assertIn("平台覆盖台账", document_xml)
                self.assertIn("2026-07-31T23:59:00-04:00", document_xml)
                self.assertIn("https://seller-us.tiktok.com/university/", document_xml)
                self.assertIn("快照: first_seen", document_xml)
                self.assertIn("需要登录", document_xml)

    def test_reject_invalid_coverage_ledger_timestamp_and_result(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        entry = self.coverage_entry("Amazon")
        entry["access_result"] = "partial"
        entry["checked_at"] = "2026-07-21T16:30:00"
        data["coverage_ledger"] = [entry]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "invalid-coverage.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_events.py"), str(source)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("access_result: invalid value", result.stderr)
            self.assertIn("checked_at: use ISO 8601 date-time with a UTC offset", result.stderr)

    def test_reject_platform_check_without_opened_source_evidence(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        data["scope"] = ["TikTok Shop US"]
        entry = self.coverage_entry()
        entry["sources_checked"] = []
        data["coverage_ledger"] = [entry]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "missing-evidence.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_events.py"), str(source)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sources_checked: must be a non-empty array", result.stderr)
            self.assertIn("public_update_checked: requires a official_updates source entry", result.stderr)

    def test_reject_platform_named_in_scope_without_ledger(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        data["scope"] = ["China", "Temu semi-managed"]
        data.pop("coverage_ledger", None)
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "missing-ledger.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_events.py"), str(source)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing entry for platform named in scope: temu", result.stderr)

    def test_reject_platform_lookback_shorter_than_seven_days(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        data["scope"] = ["TikTok Shop US"]
        entry = self.coverage_entry()
        entry["lookback_start"] = "2026-07-20T16:30:01+08:00"
        data["coverage_ledger"] = [entry]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "short-lookback.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_events.py"), str(source)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("platform lookback must be at least 7 days", result.stderr)

    def test_snapshot_platform_page_first_unchanged_and_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            store = temp / "snapshots"
            content = temp / "page.txt"
            output = temp / "snapshot.json"
            content.write_text("Policy title\nSellers must submit documents.\n", encoding="utf-8")

            self.run_script(
                "snapshot_platform_page.py",
                "--platform", "Amazon",
                "--url", "https://sellercentral.amazon.com/help/example?utm_source=test",
                "--content-file", content,
                "--store", store,
                "--captured-at", "2026-07-21T10:00:00+08:00",
                "--output", output,
            )
            first = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(first["change_status"], "first_seen")
            self.assertIsNone(first["previous_snapshot_id"])

            self.run_script(
                "snapshot_platform_page.py",
                "--platform", "Amazon",
                "--url", "https://sellercentral.amazon.com/help/example",
                "--content-file", content,
                "--store", store,
                "--captured-at", "2026-07-22T10:00:00+08:00",
                "--output", output,
            )
            unchanged = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(unchanged["change_status"], "unchanged")
            self.assertEqual(unchanged["previous_snapshot_id"], first["snapshot_id"])

            content.write_text("Policy title\nSellers must submit documents within 48 hours.\n", encoding="utf-8")
            self.run_script(
                "snapshot_platform_page.py",
                "--platform", "Amazon",
                "--url", "https://sellercentral.amazon.com/help/example",
                "--content-file", content,
                "--store", store,
                "--captured-at", "2026-07-23T10:00:00+08:00",
                "--output", output,
            )
            changed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(changed["change_status"], "changed")
            self.assertEqual(changed["previous_snapshot_id"], unchanged["snapshot_id"])
            self.assertIn("+1 / -1 lines", changed["diff_summary"])
            self.assertTrue(Path(changed["diff_path"]).exists())

    def test_reject_public_platform_source_without_snapshot(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        data["coverage_ledger"][0]["sources_checked"][0].pop("snapshot")
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "missing-snapshot.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_events.py"), str(source)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("snapshot: required for an opened public policy page", result.stderr)

    def test_amazon_and_aliexpress_scope_require_coverage_ledger(self) -> None:
        for scope, expected in (("Amazon US", "amazon"), ("速卖通半托管", "aliexpress")):
            data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
            data["scope"] = [scope]
            data.pop("coverage_ledger", None)
            with tempfile.TemporaryDirectory() as temp_dir:
                source = Path(temp_dir) / "missing-platform-ledger.json"
                source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS / "validate_events.py"), str(source)],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"missing entry for platform named in scope: {expected}", result.stderr)

    def test_blocked_access_is_not_login_required(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        data["scope"] = ["Jumia"]
        entry = self.coverage_entry("Jumia")
        entry["access_result"] = "login_required"
        entry["sources_checked"][-1]["result"] = "blocked"
        data["coverage_ledger"] = [entry]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "blocked-as-login.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_events.py"), str(source)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("login_required requires a dashboard access attempt", result.stderr)

            entry["access_result"] = "blocked"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.run_script("validate_events.py", source)

    def test_deduplicate_keeps_exact_timestamp_change(self) -> None:
        previous = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        current = json.loads((EXAMPLES / "previous.json").read_text(encoding="utf-8"))
        previous["events"][0]["published_at"] = "2026-07-20T00:01:00-04:00"
        current["events"][0]["published_at"] = "2026-07-20T00:02:00-04:00"

        result = self.deduplicate_pair(previous, current)

        match = result["deduplication"]["matches"][0]
        self.assertEqual(match["disposition"], "material_update")
        self.assertIn("published_at", match["change_reasons"])

    def test_reject_incomplete_platform_policy(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        data["events"][1]["platform_policy"] = {"platform": "Temu"}
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "invalid-platform.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_events.py"), str(source)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("platform_policy and action_items must be supplied together", result.stderr)

    def test_build_chinese_and_english_docx(self) -> None:
        data = json.loads((EXAMPLES / "current.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            chinese = temp / "radar-zh.docx"
            english_source = temp / "english.json"
            english = temp / "radar-en.docx"

            self.run_script("build_docx.py", EXAMPLES / "current.json", "--output", chinese)
            data["language"] = "en-US"
            english_source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.run_script("build_docx.py", english_source, "--output", english)

            for path, required, forbidden in (
                (chinese, "每日外贸雷达", "����"),
                (english, "DAILY TRADE RADAR", "今日判断"),
            ):
                self.assertTrue(path.exists())
                with zipfile.ZipFile(path) as package:
                    document_xml = package.read("word/document.xml").decode("utf-8")
                    core_xml = package.read("docProps/core.xml").decode("utf-8")
                    self.assertIn(required, document_xml)
                    self.assertNotIn(forbidden, document_xml)
                    self.assertNotIn("<dc:creator>biger</dc:creator>", core_xml)
                    package_xml = b"".join(package.read(name) for name in package.namelist() if name.endswith(".xml"))
                    self.assertNotIn(b"rsid", package_xml)


if __name__ == "__main__":
    unittest.main()
