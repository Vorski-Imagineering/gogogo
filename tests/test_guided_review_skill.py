#!/usr/bin/env python3
"""Structure of /gogogo:guided-review (gogogo#263).

These pin the settings, commands and files the skill depends on, never its
sentences (CLAUDE.md § Tests); whether it behaves is its eval cases.

    python3 -m unittest tests.test_guided_review_skill
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
SKILL_DIR = PLUGIN / "skills" / "guided-review"
SKILL = SKILL_DIR / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "scripts"))

import profile_check as pc  # noqa: E402

ROOTS = {path.split(".")[0] for path in pc.FIELDS}
FILE_TYPES = {"md", "json", "jsonl", "py", "sh"}


class SkillNamesWhatItDependsOn(unittest.TestCase):
    def test_names_its_check_script_modes_section_and_references(self):
        body = SKILL.read_text(encoding="utf-8")
        for word in ('profile_check.py" --for guided-review', "record_outcome.py", "--walk", "--plan-only",
                     "--resume", "## Test data", ".claude/guided-review/",
                     "references/gather-and-prepare.md", "references/walk-and-record.md",
                     *pc.TEST_DATA_HEADINGS):
            self.assertIn(word, body)
        for name in ("gather-and-prepare.md", "walk-and-record.md"):
            self.assertTrue((SKILL_DIR / "references" / name).is_file(), name)

    def test_every_setting_it_names_is_known(self):
        for path in (SKILL, *sorted((SKILL_DIR / "references").glob("*.md"))):
            for token in re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", path.read_text(encoding="utf-8")):
                if token.split(".")[0] in ROOTS and token.rsplit(".", 1)[1] not in FILE_TYPES:
                    self.assertTrue(token in pc.FIELDS, f"{path.name}: {token} is not a setting")


class OptIn(unittest.TestCase):
    def test_it_needs_exactly_what_auto_test_needs(self):
        self.assertIn(pc.GUIDED, pc.SKILLS)
        self.assertEqual(pc.OPT_IN[pc.GUIDED], "auto_test")
        for path, (_, required_by, _) in pc.FIELDS.items():
            self.assertEqual(pc.TEST in required_by, pc.GUIDED in required_by, path)
        for title, needed_by in pc.SECTIONS.items():
            self.assertEqual(pc.TEST in needed_by, pc.GUIDED in needed_by, title)


class NoProjectNames(unittest.TestCase):
    def test_the_claude_md_greps_find_nothing(self):
        folders = [SKILL_DIR, *sorted((PLUGIN / "evals").glob("guided-review-*"))]
        self.assertGreater(len(folders), 1)
        for folder in folders:
            for path in folder.rglob("*"):
                if path.is_file():
                    body = path.read_text(encoding="utf-8")
                    self.assertIsNone(re.search(r"manage\.py|npm |firebase|django|htmx|sentry", body, re.I), path)


if __name__ == "__main__":
    unittest.main()
