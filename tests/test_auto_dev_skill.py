#!/usr/bin/env python3
"""Structure of /gogogo:auto-dev's queue selection (gogogo#60).

The selection reads each card's labels and lints the label-less ones. These
pin the setting, script and output names the step depends on, never its
sentences (CLAUDE.md § Tests); whether it behaves is a scenario run.

    python3 -m unittest tests.test_auto_dev_skill
"""

import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "skills" / "auto-dev" / "SKILL.md"


def section(text, heading):
    return text.split(f"\n## {heading}")[1].split("\n## ")[0]


class QueueSelection(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")

    def test_select_reads_labels_and_lints_the_rest(self):
        select = section(self.text, "1. Select the queue")
        for name in ("tracker.ready_marker", "spec_lint.py", "--json"):
            self.assertIn(name, select)

    def test_the_lint_verdict_is_named(self):
        self.assertIn("label: apply", self.text)

    def test_branching_looks_for_earlier_work(self):
        self.assertIn("issue_work.py", section(self.text, "3. Branch from a fresh base"))
        dev = (SKILL.parents[1] / "dev" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("issue_work.py", section(dev, "4. Change"))

    def test_triage_only_names_the_ready_label(self):
        self.assertIn("ready label", section(self.text, "Triage-only mode"))


if __name__ == "__main__":
    unittest.main()
