"""The skills name the column settings the checker requires (gogogo#26).

A structure test: it pins setting names, not sentences.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
DEV_HAND_BACK = PLUGIN / "skills" / "dev" / "references" / "hand-back.md"
AUTO_DEV_BRANCH = PLUGIN / "skills" / "auto-dev" / "references" / "branch.md"


class ColumnSettingsInSkills(unittest.TestCase):
    def test_dev_and_auto_dev_name_the_needs_human_column(self):
        for skill, path in (("dev", DEV_HAND_BACK), ("auto-dev", PLUGIN / "skills" / "auto-dev" / "SKILL.md")):
            text = path.read_text(encoding="utf-8")
            self.assertIn("tracker.columns.needs_human", text, skill)

    def test_dev_removes_the_ready_label_on_needs_human(self):
        # The Dev Ready view filters on the label, so a stopped card that
        # keeps it still shows there (gogogo#26 Approvals row 9).
        text = DEV_HAND_BACK.read_text(encoding="utf-8")
        self.assertIn("tracker.ready_marker", text)
        self.assertIn("--remove-label", text)

    def test_dev_branches_like_auto_dev_inside_change(self):
        # dev puts its work on the issue's branch before the first edit, by
        # the same pattern as auto-dev (gogogo#41).
        dev = (PLUGIN / "skills" / "dev" / "SKILL.md").read_text(encoding="utf-8")
        change = dev[dev.index("## 4. Change"):dev.index("## 5. Review")]
        for needle in ("git switch -c fix/<issue-number>-<short-slug>", "integration.base",
                       "tracker.code_repo", "defaultBranchRef"):
            self.assertIn(needle, change)
        auto_dev = AUTO_DEV_BRANCH.read_text(encoding="utf-8")
        self.assertIn("git switch -c fix/<issue-number>-<short-slug>", auto_dev)

    def test_dev_does_not_read_origin_head(self):
        # `refs/remotes/origin/HEAD` is not set in every checkout.
        dev = (PLUGIN / "skills" / "dev" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("refs/remotes/origin/HEAD", dev)

    def test_no_skill_or_reference_names_back_to_queue(self):
        named = [str(p.relative_to(PLUGIN)) for folder in ("skills", "references")
                 for p in (PLUGIN / folder).rglob("*.md")
                 if "back_to_queue" in p.read_text(encoding="utf-8")]
        self.assertEqual(named, [])


if __name__ == "__main__":
    unittest.main()
