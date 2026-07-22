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

    def test_skill_frontmatter(self) -> None:
        content = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        frontmatter = content.split("---", 2)[1]
        self.assertIn("name: daily-trade-radar", frontmatter)
        self.assertIn("description:", frontmatter)

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
