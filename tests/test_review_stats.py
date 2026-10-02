#!/usr/bin/env python3
"""Tests for review_stats.py: the review records on an issues repo, read back.

Every `gh` call goes through `review_stats._gh`, patched here to answer from
fixtures, so nothing touches GitHub (gogogo#33).

    python3 -m unittest tests.test_review_stats
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import review_stats as rs  # noqa: E402

PROFILE = '+++\nprofile = 1\n\n[tracker]\nissues_repo = "o/r"\ncode_repo = "o/r"\n+++\n'


def v2(pr=1, rounds=1, applied="1", declined="0", refix="0", applied_as="spec:1,regression:0,bug:0,risk:0,added:0",
       declined_as="hypothetical:0,style:0,settled:0,reversal:0,beyond:0,late:0", end="clean",
       escaped_from="none", escaped_as="none"):
    return (f"<!-- gogogo:review v=2 pr={pr} kind=code coverage=broad rounds={rounds} applied={applied} "
            f"declined={declined} refix={refix} applied_as={applied_as} declined_as={declined_as} followups=0 "
            f"end={end} escaped_from={escaped_from} escaped_as={escaped_as} impl=m1 reviewer=m2 -->")


def autotest(n, verdict):
    return f"<!-- auto-test v1 run=r issue={n} verdict={verdict} build=b skill=s -->\n## Auto-test"


class Stats(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name) / "dev-process.md"
        self.profile.write_text(PROFILE)
        self.calls = []

    def run_stats(self, comments, issues=None, *argv, fail=False):
        """comments: [(issue number, body)]; issues: {n: (state, state_reason)}."""
        issues = issues or {}

        def fake_gh(args):
            self.calls.append(args)
            if fail:
                raise rs.GhError("gh: HTTP 502")
            if "issues/comments" in args[-1]:
                return json.dumps([[{"issue_url": f"https://api.github.com/repos/o/r/issues/{n}", "body": b}
                                    for n, b in comments]])
            n = int(args[-1].rsplit("/", 1)[1])
            state, reason = issues.get(n, ("open", None))
            return json.dumps({"number": n, "title": f"issue {n}", "state": state, "state_reason": reason})

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(rs, "_gh", side_effect=fake_gh), redirect_stdout(out), redirect_stderr(err):
            code = rs.main(["--profile", str(self.profile), *argv])
        return code, out.getvalue(), err.getvalue()

    def json_of(self, comments, issues=None, *argv):
        code, out, err = self.run_stats(comments, issues, "--json", *argv)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_one_record_gives_one_row_with_its_numbers(self):
        data = self.json_of([(40, v2(pr=7, rounds=2, applied="3,0", declined="1,2", refix="0,0",
                                      applied_as="spec:1,regression:0,bug:2,risk:0,added:0",
                                      declined_as="hypothetical:2,style:1,settled:0,reversal:0,beyond:0,late:0"))])
        self.assertEqual(len(data["rows"]), 1)
        row = data["rows"][0]
        self.assertEqual((row["issue"], row["pr"], row["rounds"], row["applied"], row["declined"], row["end"]),
                         (40, "7", 2, [3, 0], [1, 2], "clean"))

    def test_a_record_that_does_not_add_up_is_flagged_and_left_out_of_reasons(self):
        bad = v2(rounds=1, applied="2", applied_as="spec:1,regression:0,bug:0,risk:0,added:0")
        good = v2(pr=2, rounds=1, applied="1", applied_as="spec:0,regression:0,bug:1,risk:0,added:0")
        code, out, _ = self.run_stats([(40, bad), (41, good)])
        self.assertEqual(code, 0)
        self.assertIn("#40!", out)
        data = self.json_of([(40, bad), (41, good)])
        self.assertEqual(data["summary"]["applied_as"]["spec"], 0)
        self.assertEqual(data["summary"]["applied_as"]["bug"], 1)

    def test_two_records_on_one_issue_are_two_rows(self):
        data = self.json_of([(40, v2(pr=1)), (40, v2(pr=2))])
        self.assertEqual([(r["issue"], r["pr"]) for r in data["rows"]], [(40, "1"), (40, "2")])

    def test_outcome(self):
        comments = [(1, v2()), (2, v2()), (3, v2()), (4, v2() + "\n" + autotest(4, "PASS")),
                    (4, autotest(4, "FAIL"))]
        issues = {1: ("closed", "completed"), 2: ("closed", "not_planned"), 3: ("open", None),
                  4: ("closed", "completed")}
        outcomes = {r["issue"]: r["outcome"] for r in self.json_of(comments, issues)["rows"]}
        self.assertEqual(outcomes, {1: "confirmed", 2: "dropped", 3: "waiting", 4: "fail"})

    def test_an_escaped_bug_shows_on_the_issue_it_came_from(self):
        data = self.json_of([(31, v2()), (40, v2(escaped_from="31", escaped_as="declined"))])
        rows = {r["issue"]: r for r in data["rows"]}
        self.assertEqual(rows[31]["escaped"], ["#40 (declined)"])
        self.assertEqual(data["summary"]["escaped"], {"declined": 1, "missed": 0})

    def test_no_record_is_not_a_clean_result(self):
        code, out, _ = self.run_stats([(40, "just a comment")])
        self.assertEqual(code, 1)
        self.assertIn("0 review records in o/r", out)

    def test_a_gh_failure_prints_no_table(self):
        code, out, err = self.run_stats([], None, fail=True)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("HTTP 502", err)

    def test_a_quoted_template_is_skipped_and_counted(self):
        template = ("<!-- gogogo:review v=2 pr=<n|none> kind=<code|prose|mixed> coverage=<precise|broad|exhaustive> "
                    "rounds=<n> applied=<a1,a2,…> -->")
        code, out, _ = self.run_stats([(40, template), (41, v2())])
        self.assertEqual(code, 0)
        first = out.splitlines()[0]
        self.assertIn("1 review records", first)
        self.assertIn("1 unreadable skipped", first)
        self.assertIn("#41", out)

    def test_summary_median_and_refix_rate(self):
        comments = [(1, v2(rounds=2, applied="2,1", declined="0,0", refix="0,1",
                           applied_as="spec:3,regression:0,bug:0,risk:0,added:0")),
                    (2, v2(rounds=3, applied="1,1,0", declined="0,0,0", refix="0,0,0",
                           applied_as="spec:2,regression:0,bug:0,risk:0,added:0")),
                    (3, v2(rounds=7, applied="1,1,1,1,0,0,0", declined="0,0,0,0,0,0,0", refix="0,1,1,0,0,0,0",
                           applied_as="spec:4,regression:0,bug:0,risk:0,added:0"))]
        summary = self.json_of(comments)["summary"]
        self.assertEqual(summary["median_rounds"], 3)
        self.assertAlmostEqual(summary["refix_rate"], 3 / 9)

    def test_json_holds_what_the_table_shows(self):
        comments = [(40, v2(pr=7, rounds=2, applied="3,0", declined="1,2", refix="0,0",
                            applied_as="spec:1,regression:0,bug:2,risk:0,added:0",
                            declined_as="hypothetical:2,style:1,settled:0,reversal:0,beyond:0,late:0"))]
        code, table, _ = self.run_stats(comments)
        self.assertEqual(code, 0)
        data = self.json_of(comments)
        self.assertEqual(set(data), {"rows", "summary"})
        row = data["rows"][0]
        line = next(line for line in table.splitlines() if line.startswith("#40"))
        for value in ("7", "code", "broad", "3,0", "1,2", "0,0", "clean", row["outcome"]):
            self.assertIn(value, line.split())

    def test_since_is_passed_to_the_comments_call(self):
        self.run_stats([(40, v2())], None, "--since", "2026-10-01")
        comment_calls = [a for a in self.calls if "issues/comments" in a[-1]]
        self.assertTrue(comment_calls)
        self.assertIn("since=2026-10-01T00:00:00Z", comment_calls[0][-1])

    def test_an_old_record_is_read_as_old_format(self):
        old = ("<!-- gogogo:review pr=482 kind=code level=high rounds=4 applied=5,2,1,0 "
               "declined=1,0,0,0 correctness=0,1,1,0 stopped=no -->")
        code, out, _ = self.run_stats([(26, old)])
        self.assertEqual(code, 0)
        self.assertIn("1 review records (1 old format", out.splitlines()[0])
        row = self.json_of([(26, old)])["rows"][0]
        self.assertEqual((row["rounds"], row["format"], row["end"]), (4, "old", "clean"))


if __name__ == "__main__":
    unittest.main()
