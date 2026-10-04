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


def check_run(conclusion, status="COMPLETED", name="job"):
    return {"name": name, "status": status, "conclusion": conclusion}


class CheckStates(unittest.TestCase):
    """Each way a check run or a commit status can end, and what it makes of the PR."""

    def test_every_failing_conclusion_fails_the_checks(self):
        for conclusion in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"):
            with self.subTest(conclusion=conclusion):
                _, out, _, _ = outcome(pr(statusCheckRollup=[check_run(conclusion, name="x-" + conclusion)]))
                self.assertTrue(out.startswith("checks-failed:"), out)
                self.assertIn("x-" + conclusion, out)

    def test_every_passing_conclusion_counts_as_a_check_that_ran(self):
        for conclusion in ("SUCCESS", "NEUTRAL"):
            with self.subTest(conclusion=conclusion):
                status, out, _, _ = outcome(pr(statusCheckRollup=[check_run(conclusion)]),
                                            argv=("7", "--require-checks"))
                self.assertEqual((status, out.startswith("ready:")), (0, True), out)

    def test_a_conclusion_that_is_not_a_pass_is_not_a_pass(self):
        _, out, _, _ = outcome(pr(statusCheckRollup=[check_run("STALE", name="old")]))
        self.assertTrue(out.startswith("checks-pending:"), out)
        self.assertIn("old", out)

    def test_exactly_one_check_that_ran_satisfies_require_checks(self):
        skipped = check_run("SKIPPED", name="skipped")
        status, out, _, _ = outcome(pr(statusCheckRollup=[skipped, check_run("SUCCESS")]),
                                    argv=("7", "--require-checks"))
        self.assertEqual(status, 0, out)
        status, out, _, _ = outcome(pr(statusCheckRollup=[skipped, skipped]), argv=("7", "--require-checks"))
        self.assertEqual((status, out.startswith("no-checks:")), (1, True), out)

    def test_commit_statuses_pass_fail_or_wait_by_state(self):
        cases = {"SUCCESS": "ready", "FAILURE": "checks-failed", "ERROR": "checks-failed",
                 "PENDING": "checks-pending", "EXPECTED": "checks-pending"}
        for state, expected in cases.items():
            with self.subTest(state=state):
                _, out, _, _ = outcome(pr(statusCheckRollup=[{"context": "ci/x", "state": state}]))
                self.assertTrue(out.startswith(expected + ":"), out)

    def test_a_commit_status_that_passed_counts_as_a_check_that_ran(self):
        status, _, _, _ = outcome(pr(statusCheckRollup=[{"context": "ci/x", "state": "SUCCESS"}]),
                                  argv=("7", "--require-checks"))
        self.assertEqual(status, 0)

    def test_an_entry_with_a_status_and_a_state_is_read_as_a_check_run(self):
        both = {"name": "odd", "status": "COMPLETED", "conclusion": "FAILURE", "state": "SUCCESS"}
        _, out, _, _ = outcome(pr(statusCheckRollup=[both]))
        self.assertTrue(out.startswith("checks-failed:"), out)


class Details(unittest.TestCase):
    """The facts each outcome line carries (the wording around them is not pinned)."""

    def test_the_lines_carry_the_state_the_base_and_the_decision(self):
        _, out, _, _ = outcome(pr(state="CLOSED"))
        self.assertIn("CLOSED", out)
        _, out, _, _ = outcome(pr(mergeStateStatus="BEHIND", baseRefName="trunk"))
        self.assertIn("trunk", out)
        _, out, _, _ = outcome(pr(reviewDecision="REVIEW_REQUIRED", mergeStateStatus="BLOCKED"))
        self.assertIn("review required", out)
        _, out, _, _ = outcome(pr(reviewDecision="CHANGES_REQUESTED", mergeStateStatus="BLOCKED"))
        self.assertIn("changes requested", out)

    def test_each_outcome_is_one_line(self):
        for data in (pr(), pr(state="MERGED"), pr(isDraft=True), pr(mergeStateStatus="BEHIND")):
            _, out, _, _ = outcome(data)
            self.assertEqual(len(out.splitlines()), 1, out)


class Settling(unittest.TestCase):
    def test_either_field_reading_unknown_is_read_again(self):
        for field in ("mergeable", "mergeStateStatus"):
            with self.subTest(field=field):
                _, out, _, calls = outcome(pr(**{field: "UNKNOWN"}), pr())
                self.assertEqual(len(calls), 2)
                self.assertTrue(out.startswith("ready:"), out)

    def test_either_field_still_unknown_is_unknown_never_ready(self):
        for field in ("mergeable", "mergeStateStatus"):
            with self.subTest(field=field):
                status, out, _, _ = outcome(pr(**{field: "UNKNOWN"}))
                self.assertEqual(status, 1)
                self.assertTrue(out.startswith("unknown:"), out)

    def test_a_draft_or_closed_pr_is_not_waited_on(self):
        for data in (pr(isDraft=True, mergeable="UNKNOWN"), pr(state="MERGED", mergeable="UNKNOWN")):
            _, _, _, calls = outcome(data)
            self.assertEqual(len(calls), 1)


class Plumbing(unittest.TestCase):
    def test_gh_is_asked_for_exactly_these_fields(self):
        _, _, _, calls = outcome(pr(), argv=("7",))
        self.assertEqual(calls, [("gh", "pr", "view", "7", "--json", "state,isDraft,mergeable,"
                                  "mergeStateStatus,reviewDecision,headRefOid,baseRefName,statusCheckRollup")])
        _, _, _, calls = outcome(pr(), argv=("7", "--repo", "acme/code"))
        self.assertEqual(calls[0][:6], ("gh", "pr", "view", "7", "--repo", "acme/code"))
        self.assertEqual(calls[0][6], "--json")

    def test_run_captures_text_output(self):
        done_ = mr.run(sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)")
        self.assertEqual((done_.stdout, done_.stderr), ("out\n", "err\n"))

    def test_a_silent_gh_failure_still_reports_its_exit(self):
        status, out, err, _ = outcome(None, code=3, err="")
        self.assertEqual((status, out), (2, ""))
        self.assertIn("3", err)

    def test_output_that_is_not_json_is_unreadable_not_ready(self):
        answers = [subprocess.CompletedProcess([], 0, "not json", "")]
        out, errs = io.StringIO(), io.StringIO()
        with mock.patch.object(mr, "run", lambda *c: answers[0]), redirect_stdout(out), redirect_stderr(errs):
            status = mr.main(["7"])
        self.assertEqual((status, out.getvalue()), (2, ""))
        self.assertIn("7", errs.getvalue())

    def test_run_as_a_script_it_runs_main(self):
        done_ = subprocess.run([sys.executable, str(ROOT / "plugins" / "gogogo" / "scripts" / "merge_ready.py"),
                                "--help"], capture_output=True, text=True)
        self.assertEqual(done_.returncode, 0)
        self.assertIn("usage:", done_.stdout)
        self.assertIn("--require-checks", done_.stdout)


if __name__ == "__main__":
    unittest.main()
