#!/usr/bin/env python3
"""Tests for merge_ready.py: one outcome from a PR's state, read-only.

Only `gh` is faked (the module's `run`); a real PR is never read.

    python3 -m unittest tests.test_merge_ready
"""

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import merge_ready as mr  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
OK = {"name": "suite", "status": "COMPLETED", "conclusion": "SUCCESS"}


def pr(**over):
    data = {"state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "reviewDecision": "", "headRefOid": SHA, "baseRefName": "main", "statusCheckRollup": [OK]}
    data.update(over)
    return data


def done(data, code=0, err=""):
    return subprocess.CompletedProcess([], code, json.dumps(data) if data is not None else "", err)


def outcome(*reads, argv=("7",), code=0, err=""):
    """(exit, stdout, stderr, number of gh calls) with `gh` answering each read in turn."""
    answers = [done(r, code, err) for r in reads]
    calls = []

    def fake(*cmd):
        calls.append(cmd)
        return answers.pop(0) if len(answers) > 1 else answers[0]

    out, errs = io.StringIO(), io.StringIO()
    with mock.patch.object(mr, "run", fake), mock.patch.object(mr.time, "sleep"), \
            redirect_stdout(out), redirect_stderr(errs):
        status = mr.main(list(argv))
    return status, out.getvalue(), errs.getvalue(), calls


class Outcomes(unittest.TestCase):
    def test_a_merged_pr_is_not_open(self):
        status, out, _, _ = outcome(pr(state="MERGED"))
        self.assertEqual(status, 1)
        self.assertTrue(out.startswith("not-open:"), out)

    def test_draft_comes_before_conflict(self):
        _, out, _, _ = outcome(pr(isDraft=True, mergeable="CONFLICTING"))
        self.assertTrue(out.startswith("draft:"), out)

    def test_conflict_by_mergeable_or_by_dirty(self):
        _, out, _, _ = outcome(pr(mergeable="CONFLICTING"))
        self.assertTrue(out.startswith("conflict:"), out)
        _, out, _, _ = outcome(pr(mergeStateStatus="DIRTY"))
        self.assertTrue(out.startswith("conflict:"), out)

    def test_a_failed_check_is_named(self):
        bad = {"name": "lint", "status": "COMPLETED", "conclusion": "FAILURE"}
        status, out, _, _ = outcome(pr(statusCheckRollup=[bad, OK]))
        self.assertEqual(status, 1)
        self.assertTrue(out.startswith("checks-failed:"), out)
        self.assertIn("lint", out)
        self.assertNotIn("suite", out)

    def test_a_status_context_error_is_a_failure(self):
        bad = {"context": "ci/other", "state": "ERROR"}
        _, out, _, _ = outcome(pr(statusCheckRollup=[bad]))
        self.assertTrue(out.startswith("checks-failed:"), out)
        self.assertIn("ci/other", out)

    def test_a_check_still_running_is_pending(self):
        run_ = {"name": "suite", "status": "IN_PROGRESS", "conclusion": ""}
        _, out, _, _ = outcome(pr(statusCheckRollup=[run_]))
        self.assertTrue(out.startswith("checks-pending:"), out)

    def test_failed_beats_pending(self):
        run_ = {"name": "slow", "status": "IN_PROGRESS", "conclusion": ""}
        bad = {"name": "lint", "status": "COMPLETED", "conclusion": "TIMED_OUT"}
        _, out, _, _ = outcome(pr(statusCheckRollup=[run_, bad]))
        self.assertTrue(out.startswith("checks-failed:"), out)

    def test_no_checks_fail_only_when_required(self):
        status, out, _, _ = outcome(pr(statusCheckRollup=[]), argv=("7", "--require-checks"))
        self.assertEqual(status, 1)
        self.assertTrue(out.startswith("no-checks:"), out)
        status, out, _, _ = outcome(pr(statusCheckRollup=[]))
        self.assertEqual(status, 0)
        self.assertTrue(out.startswith("ready:"), out)

    def test_checks_that_all_skipped_count_as_none(self):
        skipped = {"name": "suite", "status": "COMPLETED", "conclusion": "SKIPPED"}
        _, out, _, _ = outcome(pr(statusCheckRollup=[skipped]), argv=("7", "--require-checks"))
        self.assertTrue(out.startswith("no-checks:"), out)

    def test_behind(self):
        _, out, _, _ = outcome(pr(mergeStateStatus="BEHIND"))
        self.assertTrue(out.startswith("behind:"), out)

    def test_review_required_and_plain_blocked(self):
        _, out, _, _ = outcome(pr(mergeStateStatus="BLOCKED", reviewDecision="REVIEW_REQUIRED"))
        self.assertTrue(out.startswith("review-required:"), out)
        _, out, _, _ = outcome(pr(mergeStateStatus="BLOCKED", reviewDecision="CHANGES_REQUESTED"))
        self.assertTrue(out.startswith("review-required:"), out)
        _, out, _, _ = outcome(pr(mergeStateStatus="BLOCKED"))
        self.assertTrue(out.startswith("blocked:"), out)

    def test_clean_with_passing_checks_is_ready_and_names_the_head(self):
        status, out, _, _ = outcome(pr())
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), f"ready: {SHA}")


class Unknown(unittest.TestCase):
    def test_a_later_read_that_settles_is_used(self):
        unknown = pr(mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")
        status, out, _, calls = outcome(unknown, unknown, pr())
        self.assertEqual((status, len(calls)), (0, 3))
        self.assertTrue(out.startswith("ready:"), out)

    def test_unknown_on_every_read_is_never_ready(self):
        unknown = pr(mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")
        status, out, _, calls = outcome(unknown)
        self.assertEqual((status, len(calls)), (1, 4))
        self.assertTrue(out.startswith("unknown:"), out)

    def test_the_reads_are_ten_seconds_apart(self):
        unknown = pr(mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")
        answers = [done(unknown)]
        with mock.patch.object(mr, "run", lambda *c: answers[0]), \
                mock.patch.object(mr.time, "sleep") as sleep, redirect_stdout(io.StringIO()):
            mr.main(["7"])
        self.assertEqual([c.args for c in sleep.call_args_list], [(10,)] * 3)


class Unreadable(unittest.TestCase):
    def test_a_gh_failure_exits_2_with_its_message_and_prints_nothing(self):
        status, out, err, _ = outcome(None, code=1, err="HTTP 404: Not Found")
        self.assertEqual(status, 2)
        self.assertEqual(out, "")
        self.assertIn("HTTP 404", err)


class Reads(unittest.TestCase):
    def test_it_only_reads_and_passes_the_repo(self):
        _, _, _, calls = outcome(pr(), argv=("7", "--repo", "acme/code"))
        for cmd in calls:
            self.assertEqual(cmd[:3], ("gh", "pr", "view"), cmd)
            self.assertIn("acme/code", cmd)


if __name__ == "__main__":
    unittest.main()
