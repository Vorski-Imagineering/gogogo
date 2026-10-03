#!/usr/bin/env python3
"""Structure of /gogogo:dev's reading of the whole issue (gogogo#108).

A comment from someone with write access counts like the description once
§2 folds it in. These pin the commands, fields and filters the steps depend
on, never their sentences (CLAUDE.md § Tests); whether it behaves is a
scenario run.

    python3 -m unittest tests.test_dev_skill
"""

import re
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "skills"
SKILL = SKILLS / "dev" / "SKILL.md"

# The project-name grep in CLAUDE.md, as a regex.
PROJECT_NAMES = r"manage\.py|npm |firebase|django|htmx|sentry"
FOLD = "### Fold in comments the description does not hold yet"


def section(text, heading):
    return text.split(f"\n## {heading}")[1].split("\n## ")[0]


class WholeIssue(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")
        self.read = section(self.text, "1. ")
        self.triage = section(self.text, "2. ")

    def fold(self):
        self.assertIn(FOLD, self.triage)
        return self.triage.split(FOLD)[1].split("\n### ")[0]

    def test_the_old_rule_is_gone(self):
        self.assertNotIn("A comment does not count", self.triage)

    def test_the_fold_filters_are_named(self):
        for name in ("collaborators/", "/permission", "lastEditedAt", "<!-- gogogo:", "**Needs you:**"):
            self.assertIn(name, self.triage)

    def test_the_fold_is_linted_before_it_is_posted(self):
        lines = self.fold().splitlines()
        lint = next((i for i, line in enumerate(lines) if "spec_lint.py" in line), None)
        edit = next((i for i, line in enumerate(lines) if "gh issue edit" in line), None)
        self.assertIsNotNone(lint)
        self.assertIsNotNone(edit)
        self.assertLess(lint, edit)

    def test_read_fetches_the_comments_and_the_last_edit(self):
        for name in ("lastEditedAt", "comments(first:100)"):
            self.assertIn(name, self.read)

    def test_no_project_names(self):
        for skill in ("dev", "auto-dev"):
            text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertIsNone(re.search(PROJECT_NAMES, text, re.IGNORECASE), skill)


if __name__ == "__main__":
    unittest.main()
