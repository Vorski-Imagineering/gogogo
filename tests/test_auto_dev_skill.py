#!/usr/bin/env python3
"""Structure of /gogogo:auto-dev's queue selection (gogogo#60).

The selection reads each card's labels and lints the label-less ones. These
pin the setting, script and output names the step depends on, never its
sentences (CLAUDE.md § Tests); whether it behaves is a scenario run.

    python3 -m unittest tests.test_auto_dev_skill
"""

import re
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "skills" / "auto-dev" / "SKILL.md"
sys.path.insert(0, str(SKILL.parents[2] / "scripts"))

import review_stats  # noqa: E402


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

    def test_the_skip_marker_matches_the_parser(self):
        triage = section(self.text, "2. Triage each issue before touching it")
        markers = re.findall(r"<!-- gogogo:skip (.*?) -->", triage)
        self.assertEqual(len(markers), 1, markers)
        found = re.fullmatch(r"v=1 reason=<([^>]*)> session=<id\|unknown>", markers[0])
        self.assertIsNotNone(found, markers[0])
        self.assertEqual(tuple(found.group(1).split("|")), review_stats.SKIPS)

    def test_a_skip_is_handed_back(self):
        triage = section(self.text, "2. Triage each issue before touching it")
        for name in ("tracker.columns.needs_human", "tracker.ready_marker", "gh issue comment", "--remove-label"):
            self.assertIn(name, triage)

    def test_the_skip_names_its_session_source(self):
        self.assertIn("CLAUDE_CODE_SESSION_ID", self.text.split("\n## Claude-specific")[1])

    def test_triage_only_still_posts_nothing(self):
        triage_only = section(self.text, "Triage-only mode")
        for words in ("post nothing", "move no card"):
            self.assertIn(words, triage_only)

    def test_triage_only_names_the_ready_label(self):
        self.assertIn("ready label", section(self.text, "Triage-only mode"))


if __name__ == "__main__":
    unittest.main()
