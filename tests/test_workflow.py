from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()

