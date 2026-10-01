"""The skills name the column settings the checker requires (gogogo#26).

A structure test: it pins setting names, not sentences.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"


class ColumnSettingsInSkills(unittest.TestCase):
    def test_dev_and_auto_dev_name_the_needs_human_column(self):
        for skill in ("dev", "auto-dev"):
            text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("tracker.columns.needs_human", text, skill)

    def test_dev_removes_the_ready_label_on_needs_human(self):
        # The Dev Ready view filters on the label, so a stopped card that
        # keeps it still shows there (gogogo#26 Approvals row 9).
        text = (PLUGIN / "skills" / "dev" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("tracker.ready_marker", text)
        self.assertIn("--remove-label", text)

    def test_no_skill_or_reference_names_back_to_queue(self):
        named = [str(p.relative_to(PLUGIN)) for folder in ("skills", "references")
                 for p in (PLUGIN / folder).rglob("*.md")
                 if "back_to_queue" in p.read_text(encoding="utf-8")]
        self.assertEqual(named, [])


if __name__ == "__main__":
    unittest.main()
