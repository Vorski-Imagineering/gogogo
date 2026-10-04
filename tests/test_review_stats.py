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
       escaped_from="none", escaped_as="none", extra=""):
    return (f"<!-- gogogo:review v=2 pr={pr} kind=code coverage=broad rounds={rounds} applied={applied} "
            f"declined={declined} refix={refix} applied_as={applied_as} declined_as={declined_as} followups=0 "
            f"end={end} escaped_from={escaped_from} escaped_as={escaped_as} impl=m1 reviewer=m2"
            f"{' ' + extra if extra else ''} -->")


def stop(reason, session=None):
    tail = f" session={session}" if session is not None else ""
    return f"**Needs you:** do the thing.\n<!-- gogogo:stop v=1 reason={reason}{tail} -->"


def skip(reason, session="unknown"):
    return f"**Needs you:** re-spec it.\n<!-- gogogo:skip v=1 reason={reason} session={session} -->"


SESSION = "0d6f3c2a-8b1e-4f5d-9a7c-2e4b6d8f0a1c"


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
        """comments: [(issue number, body[, created_at])]; issues: {n: (state, state_reason)}."""
        issues = issues or {}

        def fake_gh(args):
            self.calls.append(args)
            if fail:
                raise rs.GhError("gh: HTTP 502")
            if "issues/comments" in args[-1]:
                return json.dumps([[{"issue_url": f"https://api.github.com/repos/o/r/issues/{c[0]}", "body": c[1],
                                     **({"created_at": c[2]} if len(c) > 2 else {})}
                                    for c in comments]])
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



class PhaseTimes(StatsBase):
    def test_a_bad_session_is_not_an_id(self):
        data = self.json_of([(40, v2(extra="session=abc"))])
        self.assertIsNone(data["rows"][0]["session"])
        self.assertEqual(data["summary"]["malformed"], 1)

    def test_a_time_that_is_no_real_minute_is_malformed(self):
        data = self.json_of([(40, v2(extra="t_branch=2026-10-03T25:00Z t_verified=2026-10-03T10:30Z"))])
        self.assertIsNone(data["rows"][0]["t_branch"])
        self.assertEqual(data["summary"]["malformed"], 1)

    def test_an_empty_new_value_is_malformed_not_unreadable(self):
        code, out, _ = self.run_stats([(40, v2(extra="session= t_branch=unknown t_verified=unknown"))])
        self.assertEqual(code, 0)
        self.assertIn("1 review records", out.splitlines()[0])
        self.assertIn("0 unreadable skipped, 1 with malformed fields", out.splitlines()[0])

    def test_unknown_is_not_malformed(self):
        data = self.json_of([(40, v2(extra="session=unknown t_branch=unknown"))])
        self.assertEqual((data["rows"][0]["session"], data["rows"][0]["t_branch"]), (None, None))
        self.assertEqual(data["summary"]["malformed"], 0)

    def test_the_medians_come_from_the_right_fields(self):
        comments = [(40, v2(extra=f"session={SESSION} t_branch=2026-10-03T09:00Z t_verified=2026-10-03T10:30Z"),
                     "2026-10-03T11:00:00Z"),
                    (41, v2(pr=2, extra="t_branch=2026-10-03T09:00Z t_verified=2026-10-03T09:40Z"),
                     "2026-10-03T10:00:00Z")]
        s = self.json_of(comments)["summary"]
        self.assertEqual(s["timed"], 2)
        self.assertEqual(s["with_session"], 1)
        self.assertEqual(s["median_branch_to_verified"], 65)
        self.assertEqual(s["median_verified_to_report"], 25)
        row = self.json_of(comments)["rows"][0]
        self.assertEqual((row["session"], row["t_branch"], row["t_verified"], row["posted"]),
                         (SESSION, "2026-10-03T09:00Z", "2026-10-03T10:30Z", "2026-10-03T11:00:00Z"))

    def test_times_in_the_wrong_order_are_malformed_and_not_timed(self):
        s = self.json_of([(40, v2(extra="t_branch=2026-10-03T10:30Z t_verified=2026-10-03T09:00Z"))])["summary"]
        self.assertEqual(s["timed"], 0)
        self.assertEqual(s["malformed"], 1)
        code, out, _ = self.run_stats([(40, v2(extra="t_branch=2026-10-03T10:30Z t_verified=2026-10-03T09:00Z"))])
        self.assertIn("1 with malformed fields", out.splitlines()[0])

    def test_no_evidence_is_not_zero_minutes(self):
        s = self.json_of([(40, v2())])["summary"]
        self.assertEqual(s["timed"], 0)
        self.assertIsNone(s["median_branch_to_verified"])
        self.assertIsNone(s["median_verified_to_report"])
        code, out, _ = self.run_stats([(40, v2())])
        self.assertIn("phase times: 0 of 1 new records (median branch→verified - min, verified→report - min)", out)
        self.assertIn("session ids: 0 of 1 new records", out)

    def test_an_old_record_has_no_times_and_breaks_nothing(self):
        old = ("<!-- gogogo:review pr=482 kind=code level=high rounds=4 applied=5,2,1,0 "
               "declined=1,0,0,0 correctness=0,1,1,0 stopped=no -->")
        data = self.json_of([(26, old), (40, v2(extra="t_branch=2026-10-03T09:00Z t_verified=2026-10-03T09:30Z"))])
        old_row = next(r for r in data["rows"] if r["issue"] == 26)
        self.assertEqual((old_row["session"], old_row["t_branch"], old_row["t_verified"]), (None, None, None))
        self.assertEqual(data["summary"]["timed"], 1)
        self.assertEqual(data["summary"]["median_branch_to_verified"], 30)


class PhaseTimesExact(StatsBase):
    """Each line and boundary pinned exactly, so a changed word or bound is seen (mutation, gogogo#62)."""

    def test_the_header_and_its_blank_line(self):
        code, out, _ = self.run_stats([(40, v2())])
        self.assertEqual(out.splitlines()[:2], ["o/r: 1 review records (0 old format, 0 unreadable skipped)", ""])

    def test_the_phase_and_session_lines(self):
        old = ("<!-- gogogo:review pr=482 kind=code level=high rounds=4 applied=5,2,1,0 "
               "declined=1,0,0,0 correctness=0,1,1,0 stopped=no -->")
        comments = [(26, old),
                    (40, v2(extra=f"session={SESSION} t_branch=2026-10-03T09:00Z t_verified=2026-10-03T10:30Z"),
                     "2026-10-03T11:00:00Z"),
                    (41, v2(pr=2, extra="t_branch=2026-10-03T09:00Z t_verified=2026-10-03T09:40Z"),
                     "2026-10-03T10:00:00Z")]
        code, out, _ = self.run_stats(comments)
        lines = out.splitlines()
        self.assertIn("phase times: 2 of 2 new records (median branch→verified 65 min, verified→report 25 min)",
                      lines)
        self.assertIn("session ids: 1 of 2 new records", lines)

    def test_zero_minutes_is_a_time_not_an_error(self):
        s = self.json_of([(40, v2(extra="t_branch=2026-10-03T09:00Z t_verified=2026-10-03T09:00Z"),
                           "2026-10-03T09:00:00Z")])["summary"]
        self.assertEqual((s["timed"], s["malformed"]), (1, 0))
        self.assertEqual((s["median_branch_to_verified"], s["median_verified_to_report"]), (0, 0))

    def test_a_report_half_a_minute_after_verifying_counts(self):
        s = self.json_of([(40, v2(extra="t_branch=2026-10-03T09:00Z t_verified=2026-10-03T10:30Z"),
                           "2026-10-03T10:30:30Z")])["summary"]
        self.assertEqual(s["median_verified_to_report"], 0.5)

    def test_other_markers_still_count_mid_line(self):
        code, out, _ = self.run_stats([(40, "Report. " + v2())])
        self.assertEqual(code, 0)
        self.assertIn("1 review records", out.splitlines()[0])

    def test_medians_print_whole_minutes_rounded_half_up(self):
        extra = "t_branch=2026-10-03T09:00Z t_verified=2026-10-03T10:30Z"
        for posted, shown, exact in (("2026-10-03T10:32:11Z", "2", 2.1833), ("2026-10-03T10:32:30Z", "3", 2.5)):
            with self.subTest(posted=posted):
                code, out, _ = self.run_stats([(40, v2(extra=extra), posted)])
                self.assertIn(f"phase times: 1 of 1 new records (median branch→verified 90 min, "
                              f"verified→report {shown} min)", out.splitlines())
                s = self.json_of([(40, v2(extra=extra), posted)])["summary"]
                self.assertAlmostEqual(s["median_verified_to_report"], exact, places=3)

    def test_each_empty_new_value_names_its_key(self):
        for key in ("session", "t_branch", "t_verified"):
            record = rs.parse_review(v2(extra=f"{key}="))
            self.assertIsNotNone(record, key)
            self.assertEqual(record["malformed"], [key])

    def test_rows_keep_the_models(self):
        row = self.json_of([(40, v2())])["rows"][0]
        self.assertEqual((row["impl"], row["reviewer"]), ("m1", "m2"))

    def test_an_old_record_has_every_key_empty(self):
        old = rs.parse_review("<!-- gogogo:review pr=482 kind=code level=high rounds=4 applied=5,2,1,0 "
                              "declined=1,0,0,0 correctness=0,1,1,0 stopped=no -->")
        for key in ("escaped_from", "escaped_as", "impl", "reviewer", "session", "t_branch", "t_verified"):
            self.assertIsNone(old[key], key)


class Stops(StatsBase):
    def test_every_reason_is_counted(self):
        reasons = ("hard-stop", "decision", "spec", "review", "tests", "mutation", "verify", "gate", "ci", "merge", "reverted")
        s = self.json_of([(40 + i, stop(reason) + "\n" + v2(pr=i)) for i, reason in enumerate(reasons)])["summary"]
        self.assertEqual(s["stops"], dict.fromkeys(reasons, 1))
        self.assertEqual(s["unreadable_stops"], 0)

    def test_the_stops_line_exactly(self):
        comments = [(40, stop("review") + "\n" + v2()), (41, stop("ci") + "\n" + v2(pr=2)),
                    (42, "<!-- gogogo:stop v=1 reason=lunch -->\n" + v2(pr=3))]
        code, out, _ = self.run_stats(comments)
        self.assertIn("stops: review 1, ci 1 (1 unreadable)", out.splitlines())
        code, out, _ = self.run_stats([(40, v2())])
        self.assertIn("stops: none recorded", out.splitlines())

    def test_stops_by_reason_and_unreadable(self):
        template = "<!-- gogogo:stop v=1 reason=<hard-stop|decision|review> -->"
        comments = [(40, stop("review") + "\n" + v2()), (41, stop("ci") + "\n" + v2(pr=2)),
                    (42, stop("lunch") + "\n" + v2(pr=3)), (43, template + "\n" + v2(pr=4))]
        s = self.json_of(comments)["summary"]
        self.assertEqual(set(s["stops"]), set(rs.STOPS))
        self.assertEqual({k: v for k, v in s["stops"].items() if v}, {"review": 1, "ci": 1})
        self.assertEqual(s["unreadable_stops"], 2)
        code, out, _ = self.run_stats(comments)
        self.assertIn("stops: ", out)
        self.assertIn("review 1", out.split("stops: ")[1].splitlines()[0])
        self.assertIn("(2 unreadable)", out)

    def test_a_stop_without_a_review_record_still_counts(self):
        s = self.json_of([(40, stop("hard-stop")), (41, v2())])["summary"]
        self.assertEqual(s["stops"]["hard-stop"], 1)
        self.assertEqual(s["unreadable_stops"], 0)

    def test_no_stop_says_none_recorded(self):
        code, out, _ = self.run_stats([(40, v2())])
        self.assertIn("stops: none recorded", out)

    def test_only_unreadable_stops_say_none_recorded_and_count_them(self):
        code, out, _ = self.run_stats([(40, "<!-- gogogo:stop v=1 reason=lunch -->\n" + v2())])
        self.assertIn("stops: none recorded (1 unreadable)", out.splitlines())

    def test_a_mention_inside_a_sentence_is_ignored(self):
        comments = [(40, "Each hand-back gets `<!-- gogogo:stop v=1 reason=gate -->` under it.\n" + v2()),
                    (41, "see <!-- gogogo:stop … --> above\n" + v2(pr=2))]
        s = self.json_of(comments)["summary"]
        self.assertEqual(set(s["stops"].values()), {0})
        self.assertEqual(s["unreadable_stops"], 0)
        code, out, _ = self.run_stats(comments)
        self.assertIn("stops: none recorded", out.splitlines())

    def test_an_own_line_marker_with_spaces_and_crlf_counts(self):
        body = "**Needs you:** x.\r\n  <!-- gogogo:stop v=1 reason=gate -->  \r\n" + v2()
        s = self.json_of([(40, body)])["summary"]
        self.assertEqual(s["stops"]["gate"], 1)
        self.assertEqual(s["unreadable_stops"], 0)

    def test_two_markers_on_one_line_are_not_read(self):
        body = "<!-- gogogo:stop v=1 reason=gate --> <!-- gogogo:stop v=1 reason=ci -->\n" + v2()
        s = self.json_of([(40, body)])["summary"]
        self.assertEqual(set(s["stops"].values()), {0})
        self.assertEqual(s["unreadable_stops"], 1)

    def test_stops_alone_are_still_no_records(self):
        code, out, _ = self.run_stats([(40, stop("gate"))])
        self.assertEqual(code, 1)



OTHER = "7e1a2b3c-4d5e-4f60-8a9b-0c1d2e3f4a5b"
OLD_RECORD = ("<!-- gogogo:review pr=482 kind=code level=high rounds=4 applied=5,2,1,0 "
              "declined=1,0,0,0 correctness=0,1,1,0 stopped=no -->")


class SkipsAndSessions(StatsBase):
    """Triage skips on their issues, and runs rebuilt from a shared session id (gogogo#63)."""

    def at(self, hhmm, day="03"):
        return f"2026-10-{day}T{hhmm}:00Z"

    def two_runs(self):
        return [(40, v2(extra=f"session={SESSION}"), self.at("09:00")),
                (41, stop("spec", SESSION), self.at("10:00")),
                (42, skip("lint", SESSION), self.at("11:30")),
                (43, v2(extra=f"session={OTHER}"), self.at("12:00"))]

    def test_skips_by_reason_and_unreadable(self):
        comments = [(1, v2()), (2, skip("lint")), (3, skip("lint")), (4, skip("decision")),
                    (5, skip("lunch")), (6, "<!-- gogogo:skip v=1 reason=<lint|nospec> session=<id|unknown> -->")]
        s = self.json_of(comments)["summary"]
        self.assertEqual(s["skips"], {"lint": 2, "nospec": 0, "decision": 1, "hard-stop": 0})
        self.assertEqual(s["unreadable_skips"], 2)

    def test_a_skip_quoted_in_a_sentence_is_not_read(self):
        quoted = "the run posts `<!-- gogogo:skip v=1 reason=<lint|nospec> session=<id|unknown> -->` on it"
        s = self.json_of([(1, v2()), (2, quoted)])["summary"]
        self.assertEqual((sum(s["skips"].values()), s["unreadable_skips"]), (0, 0))

    def test_a_run_counts_its_records_stops_and_skips(self):
        sessions = self.json_of(self.two_runs())["summary"]["sessions"]
        self.assertEqual([x["session"] for x in sessions], [SESSION, OTHER])
        a, b = sessions
        self.assertEqual((a["taken"], a["needs_you"], a["skipped"]), (2, 1, 1))
        self.assertEqual((a["first"], a["last"]), (self.at("09:00"), self.at("11:30")))
        self.assertEqual((b["taken"], b["needs_you"], b["skipped"]), (1, 0, 0))

    def test_runs_are_ordered_by_their_first_marker_not_by_issue(self):
        comments = [(1, v2(extra=f"session={OTHER}"), self.at("12:00")),
                    (2, v2(extra=f"session={SESSION}"), self.at("09:00"))]
        sessions = self.json_of(comments)["summary"]["sessions"]
        self.assertEqual([x["session"] for x in sessions], [SESSION, OTHER])

    def test_a_run_counts_distinct_issues(self):
        comments = [(40, v2(extra=f"session={SESSION}") + "\n" + stop("review", SESSION), self.at("09:00")),
                    (40, stop("review", SESSION), self.at("10:00"))]
        (a,) = self.json_of(comments)["summary"]["sessions"]
        self.assertEqual((a["taken"], a["needs_you"]), (1, 1))

    def test_markers_without_a_session_are_counted_apart(self):
        comments = [(1, OLD_RECORD), (2, stop("spec")), (3, skip("lint", "unknown"))]
        s = self.json_of(comments)["summary"]
        self.assertEqual(s["sessions"], [])
        self.assertEqual(s["without_session"], 3)

    def test_an_empty_session_makes_a_stop_unreadable(self):
        s = self.json_of([(1, v2()), (2, "<!-- gogogo:stop v=1 reason=spec session= -->")])["summary"]
        self.assertEqual(s["unreadable_stops"], 1)

    def test_no_session_says_none_recorded(self):
        code, out, _ = self.run_stats([(1, v2()), (2, stop("spec"))])
        self.assertEqual(code, 0)
        self.assertIn("sessions: none recorded (2 records without one)", out)

    def test_the_session_line_exactly(self):
        code, out, _ = self.run_stats(self.two_runs())
        self.assertEqual(code, 0)
        self.assertIn("skips: lint 1", out)
        self.assertIn("sessions: 2 with a session id (0 records without one)", out)
        self.assertIn(f"  {SESSION[:8]} 2026-10-03 09:00–11:30  2 taken, 1 needs you, 1 skipped", out)
        self.assertIn(f"  {OTHER[:8]} 2026-10-03 12:00–12:00  1 taken, 0 needs you, 0 skipped", out)

    def test_the_skip_and_session_lines_are_whole_lines(self):
        comments = [(1, v2(extra=f"session={OTHER}"), self.at("12:00")),
                    (2, skip("lint", SESSION), self.at("23:00")), (3, skip("lint", SESSION), self.at("23:10")),
                    (4, skip("decision", SESSION), self.at("23:20")),
                    (5, stop("spec", SESSION), self.at("01:00", day="04")),
                    (6, skip("lunch")), (7, skip("lunch"))]
        code, out, _ = self.run_stats(comments)
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertIn("skips: lint 2, decision 1 (2 unreadable)", lines)
        self.assertIn("sessions: 2 with a session id (0 records without one)", lines)
        self.assertIn(f"  {OTHER[:8]} 2026-10-03 12:00–12:00  1 taken, 0 needs you, 0 skipped", lines)
        self.assertIn(f"  {SESSION[:8]} 2026-10-03 23:00–2026-10-04 01:00  1 taken, 1 needs you, 3 skipped", lines)
        self.assertEqual(lines.index(f"  {OTHER[:8]} 2026-10-03 12:00–12:00  1 taken, 0 needs you, 0 skipped") + 1,
                         lines.index(f"  {SESSION[:8]} 2026-10-03 23:00–2026-10-04 01:00  1 taken, 1 needs you, 3 skipped"))

    def test_a_run_with_no_times_is_listed_last_with_a_dash(self):
        comments = [(1, v2(extra=f"session={SESSION}")), (2, v2(extra=f"session={OTHER}"), self.at("08:00"))]
        code, out, _ = self.run_stats(comments)
        lines = out.splitlines()
        first = lines.index(f"  {OTHER[:8]} 2026-10-03 08:00–08:00  1 taken, 0 needs you, 0 skipped")
        self.assertEqual(lines[first + 1], f"  {SESSION[:8]} -  1 taken, 0 needs you, 0 skipped")

    def test_the_lines_with_nothing_recorded_are_whole_lines(self):
        code, out, _ = self.run_stats([(1, v2())])
        lines = out.splitlines()
        self.assertIn("skips: none recorded", lines)
        self.assertIn("sessions: none recorded (1 records without one)", lines)

    def test_skips_and_stops_alone_are_still_no_records(self):
        code, out, _ = self.run_stats([(1, skip("lint", SESSION)), (2, stop("spec", SESSION))])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
