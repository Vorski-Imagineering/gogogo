#!/usr/bin/env python3
"""The shared reference for a decision question, and the skills that name it
(gogogo#303).

A question that asks a person to decide about a change or an issue says, before
its options, what it is, where its risk reaches and its run time. These pin
that the reference holds the three lines, that spec, human-help and wrap-up
name it, and that it holds no project's facts. Whether a question says them is
a scenario run, not a test here.

    python3 -m unittest tests.test_decision_questions
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
REFERENCE = PLUGIN / "references" / "decision-questions.md"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tech_eval import PROJECT_NAMES  # noqa: E402


class Reference(unittest.TestCase):
    def test_holds_the_three_lines(self):
        self.assertTrue(REFERENCE.is_file())
        text = REFERENCE.read_text(encoding="utf-8")
        for word in ("What it is", "Where its risk reaches", "Its run time", "not measured", "Never run anything"):
            self.assertIn(word, text)

    def test_covered_skills_name_it(self):
        for skill in ("spec", "human-help", "wrap-up"):
            with self.subTest(skill=skill):
                text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("references/decision-questions.md", text)

    def test_no_project_names(self):
        self.assertTrue(REFERENCE.is_file())
        text = REFERENCE.read_text(encoding="utf-8")
        self.assertIsNone(re.search(PROJECT_NAMES, text, re.I))
        self.assertNotIn("adopting", text.lower())


if __name__ == "__main__":
    unittest.main()
