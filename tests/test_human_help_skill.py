#!/usr/bin/env python3
"""Structure of the /gogogo:human-help skill (gogogo#159): every stop reason has a rule, and the
settings the skill names are the ones the profile checker requires for it.

    python3 -m unittest tests.test_human_help_skill
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))
import profile_check  # noqa: E402
import tracker  # noqa: E402

SKILL = ROOT / "plugins" / "gogogo" / "skills" / "human-help"
SKILL_MD = (SKILL / "SKILL.md").read_text(encoding="utf-8")
REASONS_MD = (SKILL / "references" / "reasons.md").read_text(encoding="utf-8")


class ReasonsHaveRules(unittest.TestCase):
    def test_every_stop_reason_has_a_heading(self):
        headings = set(re.findall(r"^## `([a-z-]+)`", REASONS_MD, re.M))
        for reason in tracker.STOP_REASONS:
            with self.subTest(reason=reason):
                self.assertIn(reason, headings, f"no rule for stop reason {reason!r}")

    def test_the_two_marker_only_reasons_have_rules_too(self):
        headings = set(re.findall(r"^## `([a-z-]+)`", REASONS_MD, re.M))
        self.assertTrue({"skip", "none"} <= headings, headings)


class SkillNamesTheSettingsItDependsOn(unittest.TestCase):
    def test_the_skill_names_each_setting_it_reads(self):
        for name in ("tracker.columns.needs_human", "tracker.queue", "tracker.ready_marker", "independence"):
            with self.subTest(name=name):
                self.assertIn(name, SKILL_MD)

    def test_the_skill_names_its_scripts_and_the_requeue_marker(self):
        for name in ("spec_lint.py", "human_help.py", "gogogo:requeue v=1"):
            with self.subTest(name=name):
                self.assertIn(name, SKILL_MD)

    def test_profile_check_requires_the_settings_the_skill_names(self):
        for path in ("tracker.ready_marker", "tracker.tool", "tracker.queue"):
            with self.subTest(path=path):
                self.assertIn(profile_check.HUMAN, profile_check.FIELDS[path][1])
        self.assertIn(profile_check.HUMAN, profile_check.SKILLS)


class ReasonsIsNamedFromSkillOnly(unittest.TestCase):
    def test_skill_names_the_reasons_file(self):
        self.assertIn("references/reasons.md", SKILL_MD)

    def test_no_other_reference_names_it(self):
        for path in (ROOT / "plugins" / "gogogo").rglob("*.md"):
            if path.parent.name == "references" and path.parent.parent.name == "human-help":
                continue
            with self.subTest(path=str(path)):
                self.assertNotIn("human-help/references/reasons", path.read_text(encoding="utf-8"))


class SkillSize(unittest.TestCase):
    def test_skill_md_is_within_the_line_budget(self):
        self.assertLessEqual(len(SKILL_MD.splitlines()), 500)


if __name__ == "__main__":
    unittest.main()
