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


class NeverWaits(unittest.TestCase):
    """The loop never waits on chat or on a turn's end (gogogo#96)."""

    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")

    def test_the_chat_section_comes_before_selection(self):
        chat = self.text.find("\n## The loop never waits on chat\n")
        self.assertNotEqual(chat, -1)
        self.assertLess(chat, self.text.index("\n## 1. Select the queue"))

    def test_no_run_ends_a_turn_for_background_work(self):
        step = section(self.text, "4. Change, test, review, verify")
        self.assertIn("Never end a turn to wait for background work", step)
        both = [ln for ln in step.splitlines() if "headless" in ln.lower() and "never end a turn" in ln.lower()]
        self.assertFalse(both, both)

    def test_claude_specific_names_the_poll_and_the_banned_tool(self):
        claude = self.text.split("\n## Claude-specific")[1]
        for name in ("timeout 540", "AskUserQuestion"):
            self.assertIn(name, claude)



class TakeWithFrom(unittest.TestCase):
    """§3 takes the card with `move --from` before it branches (gogogo#101)."""

    def setUp(self):
        self.step = section(SKILL.read_text(encoding="utf-8"), "3. Branch from a fresh base")

    def test_the_move_carries_from_and_comes_before_the_branch(self):
        lines = self.step.splitlines()
        moves = [i for i, ln in enumerate(lines) if " move <n>" in ln and "--to in_progress" in ln]
        branch = next(i for i, ln in enumerate(lines) if "git switch -c" in ln)
        self.assertEqual(len(moves), 1, moves)
        self.assertIn("--from", lines[moves[0]])
        self.assertLess(moves[0], branch)

    def test_a_failed_branch_moves_the_card_back_from_in_progress(self):
        self.assertIn("--from in_progress", self.step)


if __name__ == "__main__":
    unittest.main()
