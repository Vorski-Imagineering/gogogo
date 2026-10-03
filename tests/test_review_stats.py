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


class StatsBase(unittest.TestCase):
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


class Stats(StatsBase):
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


SPEC_CHECK = ("<!-- gogogo:spec-check v=1 items=62 met=57 missing=1 differs=3 na=1 outside=1 runs=2 fixed=2 "
              "declared=3 reader=fresh end=declared -->")


class SpecCheck(StatsBase):
    def test_a_spec_check_record_fills_its_columns_and_the_summary(self):
        comments = [(44, SPEC_CHECK + "\n" + v2())]
        row = self.json_of(comments)["rows"][0]
        self.assertEqual((row["spec_items"], row["spec_unmet"], row["spec_declared"]), (62, 4, 3))
        code, out, _ = self.run_stats(comments)
        self.assertEqual(code, 0)
        self.assertIn("spec check: 1 records, 62 items, 1 missing, 3 differs, 2 fixed, 3 declared", out)
        self.assertIn("spec check ended: clean 0, declared 1, stopped 0, nospec 0", out)

    def test_no_spec_check_record_shows_dashes(self):
        code, out, _ = self.run_stats([(40, v2())])
        self.assertEqual(code, 0)
        header = next(line for line in out.splitlines() if line.startswith("issue"))
        line = next(line for line in out.splitlines() if line.startswith("#40"))
        names = header.split()
        at = [names.index(n) for n in ("spec_items", "spec_unmet", "spec_declared")]
        self.assertEqual(at, [at[0], at[0] + 1, at[0] + 2])
        self.assertEqual([line.split()[i] for i in at], ["-", "-", "-"])
        self.assertIn("spec check: 0 records", out)
        self.assertNotIn("spec check ended", out)

    def test_a_record_that_does_not_add_up_and_a_template_are_unreadable(self):
        bad = SPEC_CHECK.replace("items=62", "items=61")
        template = ("<!-- gogogo:spec-check v=1 items=<n> met=<n> missing=<n> differs=<n> na=<n> outside=<n> "
                    "runs=<n> fixed=<n> declared=<n> reader=<fresh|self|none> end=<clean|declared|stopped|nospec> -->")
        code, out, _ = self.run_stats([(40, bad + "\n" + v2()), (41, template + "\n" + v2(pr=2))])
        self.assertEqual(code, 0)
        self.assertIn("2 unreadable skipped", out.splitlines()[0])
        self.assertIn("spec check: 0 records", out)

    def test_json_keys(self):
        data = self.json_of([(44, SPEC_CHECK + "\n" + v2()), (40, v2(pr=2))])
        for row in data["rows"]:
            self.assertTrue({"spec_items", "spec_unmet", "spec_declared"} <= set(row))
        spec = data["summary"]["spec_check"]
        self.assertEqual(spec["ends"], {"clean": 0, "declared": 1, "stopped": 0, "nospec": 0})
        self.assertEqual(spec["readers"], {"fresh": 1, "self": 0, "none": 0})
        self.assertEqual((spec["records"], spec["items"], spec["missing"], spec["differs"], spec["fixed"],
                          spec["declared"]), (1, 62, 1, 3, 2, 3))


TESTS_RECORD = ("<!-- gogogo:tests v=1 checked=yes hunks=3 weaker=1 licensed=1 restored=0 attempts=0 "
                "end=clean -->")


class TestsRecord(StatsBase):
    def test_a_tests_record_fills_its_column_and_the_summary(self):
        comments = [(58, v2() + "\n" + TESTS_RECORD)]
        row = self.json_of(comments)["rows"][0]
        self.assertEqual(row["weaker"], 1)
        code, out, _ = self.run_stats(comments)
        self.assertEqual(code, 0)
        self.assertIn("tests: 1 checked, 0 not checked, 1 weaker (1 licensed, 0 restored), 0 stopped", out)

    def test_unreadable_tests_records_are_counted_never_zero(self):
        for bad in (TESTS_RECORD.replace("v=1", "v=2"), TESTS_RECORD.replace(" attempts=0", "")):
            code, out, _ = self.run_stats([(58, v2() + "\n" + bad)])
            self.assertEqual(code, 0)
            self.assertIn("1 unreadable skipped", out.splitlines()[0], bad)
            self.assertIn("tests: no records", out)
        code, out, _ = self.run_stats([(40, v2())])
        line = next(line for line in out.splitlines() if line.startswith("#40"))
        header = next(line for line in out.splitlines() if line.startswith("issue"))
        self.assertEqual(line.split()[header.split().index("weaker")], "-")
        self.assertIn("tests: no records", out)


MUTATION = ("<!-- gogogo:mutation v=1 lane=unit mutants=128 killed=92 survived=35 timeout=1 runs=2 added=5 "
            "declined_as=equivalent:1,text:18,outside:11 end=clean -->")


class Mutation(StatsBase):
    def test_a_mutation_record_fills_its_columns_and_the_summary(self):
        comments = [(45, MUTATION + "\n" + v2())]
        row = self.json_of(comments)["rows"][0]
        self.assertEqual((row["mutants"], row["survived"], row["added"]), (128, 35, 5))
        code, out, _ = self.run_stats(comments)
        self.assertEqual(code, 0)
        self.assertIn("mutation: 1 records, 128 mutants, 35 survived (27%), 5 killed by added tests", out)
        self.assertIn("mutation declined by reason: equivalent 1, text 18, outside 11", out)
        self.assertIn("mutation ended: clean 1, survivors 0, failed 0", out)

    def test_the_mutation_lines_keep_the_rest_of_the_summary(self):
        code, out, _ = self.run_stats([(45, MUTATION + "\n" + v2())])
        self.assertTrue(out.splitlines()[0].startswith("o/r: 1 review records"))
        self.assertIn("median rounds: 1", out.splitlines())

    def test_a_record_with_no_mutants_shows_no_share(self):
        failed = ("<!-- gogogo:mutation v=1 lane=unit mutants=0 killed=0 survived=0 timeout=0 runs=0 added=0 "
                  "declined_as=equivalent:0,text:0,outside:0 end=failed -->")
        code, out, _ = self.run_stats([(45, failed + "\n" + v2())])
        self.assertIn("mutation: 1 records, 0 mutants, 0 survived (-), 0 killed by added tests", out.splitlines())

    def test_survivors_left_need_not_add_up_but_a_clean_end_must(self):
        left = MUTATION.replace("added=5", "added=2").replace("end=clean", "end=survivors")
        self.assertIsNotNone(rs.parse_mutation(left))
        self.assertIsNone(rs.parse_mutation(MUTATION.replace("added=5", "added=2")))

    def test_each_unreadable_mutation_marker_counts(self):
        bad = MUTATION.replace("mutants=128", "mutants=127")
        code, out, _ = self.run_stats([(45, bad + "\n" + bad + "\n" + v2())])
        self.assertIn("2 unreadable skipped", out.splitlines()[0])

    def test_no_mutation_record_shows_dashes(self):
        code, out, _ = self.run_stats([(40, v2())])
        header = next(line for line in out.splitlines() if line.startswith("issue")).split()
        line = next(line for line in out.splitlines() if line.startswith("#40")).split()
        self.assertEqual([line[header.index(c)] for c in ("mutants", "survived", "added")], ["-", "-", "-"])
        self.assertIn("mutation: 0 records", out.splitlines())
        self.assertNotIn("mutation declined", out)

    def test_two_lanes_are_summed_on_the_row(self):
        second = MUTATION.replace("lane=unit", "lane=browser")
        row = self.json_of([(45, MUTATION + "\n" + second + "\n" + v2())])["rows"][0]
        self.assertEqual((row["mutants"], row["survived"], row["added"]), (256, 70, 10))

    def test_a_record_that_does_not_add_up_is_unreadable(self):
        bad = MUTATION.replace("mutants=128", "mutants=127")
        code, out, _ = self.run_stats([(45, bad + "\n" + v2())])
        self.assertIn("1 unreadable skipped", out.splitlines()[0])
        self.assertIn("mutation: 0 records", out)

    def test_a_template_and_a_record_without_a_review_are_unreadable(self):
        template = ("<!-- gogogo:mutation v=1 lane=<name> mutants=<n> killed=<n> survived=<n> timeout=<n> runs=<n> "
                    "added=<n> declined_as=equivalent:<n>,text:<n>,outside:<n> end=<clean|survivors|failed> -->")
        code, out, _ = self.run_stats([(45, template + "\n" + v2()), (46, MUTATION), (47, v2(pr=3))])
        self.assertIn("2 unreadable skipped", out.splitlines()[0])
        self.assertIn("mutation: 0 records", out)

    def test_json_keys(self):
        data = self.json_of([(45, MUTATION + "\n" + v2()), (40, v2(pr=2))])
        for row in data["rows"]:
            self.assertTrue({"mutants", "survived", "added"} <= set(row))
        m = data["summary"]["mutation"]
        self.assertEqual(m["declined_as"], {"equivalent": 1, "text": 18, "outside": 11})
        self.assertEqual(m["ends"], {"clean": 1, "survivors": 0, "failed": 0})
        self.assertEqual((m["records"], m["mutants"], m["killed"], m["survived"], m["timeout"], m["added"]),
                         (1, 128, 92, 35, 1, 5))


if __name__ == "__main__":
    unittest.main()
