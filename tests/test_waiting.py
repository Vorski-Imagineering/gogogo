#!/usr/bin/env python3
"""Tests for waiting.py: the session-start line naming cards that wait for a person.

The board is faked; the profile is a real file. The hook runs at every session
start in every adopting repo, so the tests that matter most are the ones where
it must say nothing at all: no profile, nothing waiting, a board it cannot read.

    python3 -m unittest tests.test_waiting
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import waiting  # noqa: E402

tracker = waiting.tracker

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

PROFILE = """+++
profile = 1

[tracker]
kind = "github-project"
issues_repo = "acme/issues"
code_repo = "acme/issues"
tool = "{tool}"
project_owner = "acme"
project_number = 2
queue = "Dev Ready"
columns = {{ in_progress = "In progress", needs_human = "Human!Help!" }}

[[environments]]
name = "production"
roles = ["production"]

[[stages]]
code_is = "merged to main"
environment = "production"
column = "Released"
+++
"""


def since(**ago):
    return (NOW - timedelta(**ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def card(number, status="Released", state="OPEN", kind="Issue", **ago):
    return {"number": number, "repo": "acme/issues", "kind": kind, "state": state,
            "status": status, "status_since": since(**ago) if ago else None, "title": f"t{number}"}


class Waiting(unittest.TestCase):
    def setUp(self):
        saved = (tracker.ORG, tracker.PROJECT_NUMBER, tracker.DEFAULT_REPO, dict(tracker.COLUMNS))

        def restore():
            tracker.ORG, tracker.PROJECT_NUMBER, tracker.DEFAULT_REPO = saved[:3]
            tracker.COLUMNS.clear()
            tracker.COLUMNS.update(saved[3])
        self.addCleanup(restore)
        no_network = mock.patch.object(tracker, "graphql", side_effect=AssertionError("graphql called"))
        no_network.start()
        self.addCleanup(no_network.stop)
        tmp = tempfile.TemporaryDirectory(prefix="waiting-")
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def profile(self, tool="shared"):
        path = self.dir / "dev-process.md"
        path.write_text(PROFILE.format(tool=tool), encoding="utf-8")
        return str(path)

    def run_main(self, *argv, cards=(), error=None, profile=None):
        listing = mock.Mock(side_effect=error) if error else mock.Mock(return_value=(list(cards), [], 0))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(tracker, "list_cards", listing), redirect_stdout(out), redirect_stderr(err):
            code = waiting.main(["--profile", profile or self.profile(), *argv], now=NOW)
        return code, out.getvalue(), err.getvalue()

    def test_two_cards_name_the_count_and_the_oldest_age(self):
        cards = [card(1, days=2), card(2, days=5, hours=3), card(3, status="Dev Ready", days=9)]
        code, out, _ = self.run_main(cards=cards)
        self.assertEqual(code, 1)
        self.assertEqual(out, "2 card(s) wait for you in Released, oldest 5 days: run /gogogo:status\n")

        code, out, _ = self.run_main("--hook", cards=cards)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"systemMessage":
                         "2 card(s) wait for you in Released, oldest 5 days: run /gogogo:status"})

    def test_nothing_waiting_says_nothing(self):
        for cards in ([], [card(3, status="Dev Ready", days=1)]):
            with self.subTest(cards=cards):
                self.assertEqual(self.run_main("--hook", cards=cards)[:2], (0, ""))
                self.assertEqual(self.run_main(cards=cards)[:2], (0, ""))

    def test_an_unreadable_board_is_silent_in_the_hook_and_exits_2_otherwise(self):
        for error in (tracker.BoardError("gh api graphql failed: offline"), RuntimeError("boom")):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(self.run_main("--hook", error=error), (0, "", ""))
                code, out, err = self.run_main(error=error)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(str(error), err)

    def test_closed_and_pull_request_cards_are_not_counted(self):
        cards = [card(1, hours=3), card(2, state="CLOSED", days=8), card(3, kind="PullRequest", days=8)]
        code, out, _ = self.run_main(cards=cards)
        self.assertEqual((code, out), (1, "1 card(s) wait for you in Released, oldest 3 hours: run /gogogo:status\n"))

    def test_no_profile_is_silent_in_the_hook(self):
        missing = str(self.dir / "none" / "dev-process.md")
        self.assertEqual(self.run_main("--hook", profile=missing), (0, "", ""))
        self.assertEqual(self.run_main(profile=missing)[0], 2)
        broken = self.dir / "broken.md"
        broken.write_text("not a profile\n", encoding="utf-8")
        self.assertEqual(self.run_main("--hook", profile=str(broken)), (0, "", ""))

    def test_a_tracker_other_than_the_shared_one_is_not_read(self):
        code, out, err = self.run_main("--hook", cards=[card(1, days=1)], profile=self.profile(tool="other"))
        self.assertEqual((code, out, err), (0, "", ""))

    def test_a_bad_argument_in_the_hook_is_silent(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = waiting.main(["--hook", "--nonsense"], now=NOW)
        self.assertEqual((code, out.getvalue(), err.getvalue()), (0, "", ""))

    def test_ages(self):
        self.assertEqual(waiting.age(since(minutes=59), NOW), "under an hour")
        self.assertEqual(waiting.age(since(hours=1), NOW), "1 hour")
        self.assertEqual(waiting.age(since(hours=23, minutes=59), NOW), "23 hours")
        self.assertEqual(waiting.age(since(days=1), NOW), "1 day")
        self.assertEqual(waiting.age(since(days=5, hours=23), NOW), "5 days")

    def test_a_card_with_no_column_time_still_counts(self):
        code, out, _ = self.run_main(cards=[card(1)])
        self.assertEqual((code, out), (1, "1 card(s) wait for you in Released: run /gogogo:status\n"))

    def test_one_board_read_without_retries_or_the_second_index(self):
        listing = mock.Mock(return_value=([], [], 0))
        seen = {}

        def record(**kw):
            seen.update(kw, attempts=tracker.ATTEMPTS)
            return [], [], 0
        listing.side_effect = record
        with mock.patch.object(tracker, "list_cards", listing), redirect_stdout(io.StringIO()):
            waiting.main(["--profile", self.profile(), "--hook"], now=NOW)
        self.assertEqual(listing.call_count, 1)
        self.assertEqual(seen["attempts"], 1)
        self.assertFalse(seen["crosscheck"])
        self.assertEqual(seen["repo"], "acme/issues")


if __name__ == "__main__":
    unittest.main()
