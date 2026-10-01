#!/usr/bin/env python3
"""Tests for roadmap_status.py: the legend, the derivation, and --write.

The tracker is never asked: every test passes a fake `reader` built from a dict
of issues, which also records which issue numbers were read. `main()` calls
`tracker.configure()`, which rewrites tracker's module globals, so each test
puts them back afterwards; test_tracker sets its own at import.

    python3 -m unittest tests.test_roadmap_status
"""

import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import roadmap_status as rs  # noqa: E402
import tracker  # noqa: E402

PROFILE = """+++
profile = 1

[tracker]
kind = "github-project"
tool = "shared"
issues_repo = "acme/issues"
code_repo = "acme/code"
project_owner = "acme"
project_number = 2
ready_marker = "dev ready"
queue = "Dev Ready"
columns = { in_progress = "In progress", back_to_queue = "Dev Ready" }

<STAGES>
[roadmap]
file = "roadmap.md"
+++

## superpowers boundary
Tracker work stays in the tracker.
"""

LEGEND_ROWS = [
    "| ⚪ | — | not started | none |",
    "| 🟣 | **spec** | the issue body has a Design section | spec |",
    "| ⛔ | **blocked** | held back; the note names what on | by hand |",
    "| 🔵 | **ready** | carries the ready label | ready label |",
    "| 🟡 | **in progress** | being built | In progress, In Staging |",
    "| 🟠 | **In Production** | on its last stage, not yet closed | In Production |",
    "| ✅ | **Closed** | closed as completed | closed |",
    "| ⚫ | **dropped** | closed as not planned | not planned |",
]
LEGEND_HEADER = ["| Mark | State | Means | Covers |", "|---|---|---|---|"]

ISSUE_HEADER = ["| Item | Issue | State | Note |", "|---|---|---|---|"]
STATE_HEADER = ["| Work | State |", "|---|---|"]


def url(number, repo="acme/issues", kind="issues"):
    return f"https://github.com/{repo}/{kind}/{number}"


def row(item, number, state, note="n"):
    """A row of the Issue table; `number` None leaves the Issue cell empty."""
    link = f"[#{number}]({url(number)})" if number else ""
    return f"| {item} | {link} | {state} | {note} |"


# Row line A: an escaped pipe in the first cell, uneven spacing everywhere.
LINE_A = "|  x \\| y |   [#2](https://github.com/acme/issues/issues/2) |  🟠 **In Production** — merged  | z |"


def issue(state="OPEN", reason=None, labels=(), body="", column=None):
    return {"state": state, "state_reason": reason, "labels": list(labels), "body": body, "column": column}


class Fake:
    """A reader over a dict of issues that records what it was asked for."""

    def __init__(self, issues):
        self.issues = issues
        self.asked = []

    def __call__(self, number, repo):
        self.asked.append(number)
        found = self.issues[number]
        if isinstance(found, Exception):
            raise found
        return found


def profile_text(stages=("In Staging", "In Production"), drop=(), **replace):
    blocks = "".join(f'[[stages]]\ncode_is = "stage {i}"\ncolumn = "{c}"\n\n' for i, c in enumerate(stages))
    text = PROFILE.replace("<STAGES>\n", blocks)
    for line in drop:
        assert line in text, line
        text = text.replace(line + "\n", "")
    for old, new in replace.items():
        text = text.replace(old, new)
    return text


def document(*tables, legend=LEGEND_ROWS, legend_header=LEGEND_HEADER, newline="\n"):
    lines = ["# Roadmap", "", *legend_header, *legend, ""]
    for table in tables:
        lines += [*table, ""]
    return newline.join(lines)


def keep_tracker_globals(test):
    saved = (tracker.ORG, tracker.PROJECT_NUMBER, tracker.DEFAULT_REPO, dict(tracker.COLUMNS))

    def restore():
        tracker.ORG, tracker.PROJECT_NUMBER, tracker.DEFAULT_REPO = saved[:3]
        tracker.COLUMNS.clear()
        tracker.COLUMNS.update(saved[3])
    test.addCleanup(restore)


class Case(unittest.TestCase):
    def setUp(self):
        keep_tracker_globals(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.profile = self.tmp / ".agents" / "dev-process.md"
        self.profile.parent.mkdir()
        self.profile.write_text(profile_text(), encoding="utf-8")
        self.roadmap = self.tmp / "roadmap.md"

    def write(self, text):
        self.roadmap.write_bytes(text.encode("utf-8"))

    def run_main(self, issues, *argv, default_file=False, reader=None):
        self.fake = Fake(issues)
        args = ["--profile", str(self.profile)]
        if not default_file:
            args += ["--file", str(self.roadmap)]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = rs.main(args + list(argv), reader=reader or self.fake)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def check_row(self, state, found, *argv, table=ISSUE_HEADER):
        """One row for issue 1 in `state`; the tracker says `found`."""
        line = row("Work", 1, state) if table is ISSUE_HEADER else f"| Work | {state} [#1]({url(1)}) |"
        self.write(document([*table, line]))
        return self.run_main({1: found}, *argv)

    def lines(self, kind):
        return [line for line in self.out.splitlines() if line.startswith(kind)]


class Legend(Case):
    def legend_fails(self, legend=LEGEND_ROWS, header=LEGEND_HEADER, **profile):
        if profile:
            self.profile.write_text(profile_text(**profile), encoding="utf-8")
        self.write(document([*ISSUE_HEADER, row("Work", 1, "⚪ —")], legend=legend, legend_header=header))
        code = self.run_main({1: issue()})
        self.assertEqual(code, rs.EXIT_UNUSABLE, self.out + self.err)
        self.assertIn("The legend cannot be used", self.err)
        self.assertEqual(self.fake.asked, [], "nothing is read before the legend is usable")
        return self.err

    @staticmethod
    def edit(old, new):
        return [line.replace(old, new) if old in line else line for line in LEGEND_ROWS]

    def test_valid_legend_on_a_clean_doc(self):
        self.write(document([*ISSUE_HEADER, row("Work", 1, "⚪ —")]))
        self.assertEqual(self.run_main({1: issue()}), rs.EXIT_OK, self.out + self.err)
        self.assertIn("1 rows, 1 issues read, 0 rows name no issue, 0 need attention", self.out)

    def test_no_covers_column(self):
        legend = [line.rsplit("|", 2)[0] + "|" for line in LEGEND_ROWS]
        err = self.legend_fails(legend, ["| Mark | State | Means |", "|---|---|---|"])
        self.assertIn("no Covers column", err)

    def test_in_progress_column_uncovered(self):
        err = self.legend_fails(self.edit("In progress, In Staging", "In Staging"))
        self.assertIn("nothing covers 'In progress'", err)

    def test_stage_column_covered_twice(self):
        err = self.legend_fails(self.edit("| In Production |", "| In Production, In Staging |"))
        self.assertRegex(err, r"'In Staging' is covered by both 🟡 and 🟠")

    def test_unknown_keyword(self):
        err = self.legend_fails(self.edit("| by hand |", "| blocked |"))
        self.assertIn("'blocked' is neither a keyword nor a column", err)

    def test_unknown_column(self):
        err = self.legend_fails(self.edit("| closed |", "| closed, Done |"))
        self.assertIn("'Done' is neither a keyword nor a column in the profile", err)

    def test_none_missing(self):
        err = self.legend_fails([line for line in LEGEND_ROWS if "⚪" not in line])
        self.assertIn("nothing covers 'none'", err)

    def test_by_hand_mixed(self):
        err = self.legend_fails(self.edit("| by hand |", "| by hand, spec |"))
        self.assertIn("'by hand' must be the only entry", err)

    def test_ready_label_with_no_ready_marker(self):
        err = self.legend_fails(drop=['ready_marker = "dev ready"'])
        self.assertIn("tracker.ready_marker: the legend uses 'ready label'", err)

    def test_every_problem_is_printed(self):
        legend = self.edit("| by hand |", "| blocked |")
        legend = [line for line in legend if "⚪" not in line]
        err = self.legend_fails(legend)
        self.assertIn("'blocked'", err)
        self.assertIn("nothing covers 'none'", err)


class Derivation(Case):
    def says(self, state, found, *argv, **kw):
        code = self.check_row(state, found, *argv, **kw)
        self.assertNotIn("Traceback", self.err)
        return code

    def test_closed_beats_column(self):
        code = self.says("🟡 **in progress**", issue("CLOSED", "COMPLETED", column="In progress"))
        self.assertEqual(code, rs.EXIT_ATTENTION)
        self.assertEqual(len(self.lines("MISMATCH")), 1, self.out)
        self.assertIn("GitHub says ✅ Closed  (#1 closed, column In progress)", self.out)

    def test_closed_with_no_reason(self):
        self.assertEqual(self.says("✅ **Closed**", issue("CLOSED", None)), rs.EXIT_OK, self.out)

    def test_not_planned_and_duplicate(self):
        for reason in ("NOT_PLANNED", "DUPLICATE"):
            with self.subTest(reason):
                self.assertEqual(self.says("⚫ **dropped**", issue("CLOSED", reason)), rs.EXIT_OK, self.out)
                self.says("✅ **Closed**", issue("CLOSED", reason))
                self.assertIn("GitHub says ⚫ dropped", self.out)

    def test_column_is_case_insensitive(self):
        self.assertEqual(self.says("🟡 **in progress**", issue(column="in staging")), rs.EXIT_OK, self.out)

    def test_uncovered_column_falls_through_to_the_ready_label(self):
        found = issue(column="Dev Ready", labels=["dev ready"])
        self.assertEqual(self.says("🔵 **ready**", found), rs.EXIT_OK, self.out)

    def test_spec(self):
        found = issue(body="Report\n\n## Design\n\nThe change.")
        self.assertEqual(self.says("🟣 **spec**", found), rs.EXIT_OK, self.out)

    def test_none(self):
        self.assertEqual(self.says("⚪ —", issue()), rs.EXIT_OK, self.out)

    def test_by_hand_survives_the_ready_label(self):
        found = issue(labels=["dev ready"])
        self.assertEqual(self.says("⛔ **blocked** — waits on #9", found), rs.EXIT_OK, self.out)
        self.assertEqual(self.lines("MISMATCH"), [])

    def test_by_hand_loses_to_a_column(self):
        code = self.says("⛔ **blocked** — waits on #9", issue(column="In Staging"))
        self.assertEqual(code, rs.EXIT_ATTENTION)
        self.assertIn("GitHub says 🟡 in progress", self.out)

    def test_spec_survives_none(self):
        self.assertEqual(self.says("🟣 **spec**", issue()), rs.EXIT_OK, self.out)

    def test_none_does_not_survive_spec(self):
        code = self.says("⚪ —", issue(body="## Design\n"))
        self.assertEqual(code, rs.EXIT_ATTENTION)
        self.assertIn("says ⚪ —, GitHub says 🟣 spec", self.out)

    def test_by_hand_without_a_note(self):
        self.write(document([*ISSUE_HEADER, row("w", 1, "⛔ **blocked**", note="")]))
        self.assertEqual(self.run_main({1: issue()}), rs.EXIT_ATTENTION)
        self.assertRegex(self.out, r"FIX BY HAND .*blocked, but the note does not say on what")

    def test_by_hand_issue_cell_after_state_is_not_a_note(self):
        self.write(document(["| Item | State | Issue |", "|---|---|---|", f"| w | ⛔ **blocked** | [#1]({url(1)}) |"]))
        self.assertEqual(self.run_main({1: issue()}), rs.EXIT_ATTENTION)
        self.assertRegex(self.out, r"FIX BY HAND .*the note does not say on what")

    def test_by_hand_dash_in_the_note_column_is_not_a_note(self):
        self.write(document([*ISSUE_HEADER, row("w", 1, "⛔ **blocked**", note="—")]))
        self.assertEqual(self.run_main({1: issue()}), rs.EXIT_ATTENTION)
        self.assertRegex(self.out, r"FIX BY HAND .*the note does not say on what")

    def test_by_hand_note_in_a_later_cell(self):
        self.write(document([*ISSUE_HEADER, row("w", 1, "⛔ **blocked**", note="waits on #9")]))
        self.assertEqual(self.run_main({1: issue()}), rs.EXIT_OK, self.out + self.err)
        self.assertEqual(self.lines("FIX BY HAND"), [])

    def test_stale_prose_on_a_correct_mark(self):
        code = self.says("✅ **Closed** — still open on GitHub", issue("CLOSED", "COMPLETED"))
        self.assertEqual(code, rs.EXIT_ATTENTION)
        self.assertEqual(self.lines("MISMATCH"), [])
        self.assertRegex(self.out, r"FIX BY HAND .*still says it is open")

    def test_open_pattern_override(self):
        code = self.says("✅ **Closed** — noch offen", issue("CLOSED", "COMPLETED"), "--open-pattern", "noch offen")
        self.assertEqual(code, rs.EXIT_ATTENTION)
        self.assertRegex(self.out, r"FIX BY HAND .*still says it is open")

    def test_unknown_prefix(self):
        self.assertEqual(self.says("done — x", issue()), rs.EXIT_ATTENTION)
        self.assertRegex(self.out, r"FIX BY HAND .*does not start with a known mark: 'done — x'")


class RowsAndIssues(Case):
    def test_the_issue_column_wins(self):
        self.write(document([*ISSUE_HEADER, row("Work", 2, f"⚪ — see [#3]({url(3)})")]))
        self.run_main({2: issue(), 3: issue()})
        self.assertEqual(self.fake.asked, [2])

    def test_no_fallback_in_an_issue_table(self):
        self.write(document([*ISSUE_HEADER, row("Work", 1, "⚪ —"), row("Other", None, f"⚪ — [#3]({url(3)})")]))
        self.assertEqual(self.run_main({1: issue(), 3: issue()}), rs.EXIT_OK, self.out + self.err)
        self.assertEqual(self.fake.asked, [1])
        self.assertIn("2 rows, 1 issues read, 1 rows name no issue", self.out)

    def test_state_cell_in_a_table_without_an_issue_column(self):
        self.write(document([*STATE_HEADER, f"| Work | ⚪ — [#4]({url(4)}) |"]))
        self.assertEqual(self.run_main({4: issue()}), rs.EXIT_OK, self.out + self.err)
        self.assertEqual(self.fake.asked, [4])

    def test_other_repos_and_pull_requests_are_ignored(self):
        state = f"⚪ — [a]({url(5, 'acme/other')}) [b]({url(6, kind='pull')}) [c]({url(7)})"
        self.write(document([*STATE_HEADER, f"| Work | {state} |"]))
        self.run_main({7: issue()})
        self.assertEqual(self.fake.asked, [7])

    def test_zero_issues_read(self):
        self.write(document([*STATE_HEADER, "| Work | ⚪ — nothing yet |"]))
        self.assertEqual(self.run_main({}), rs.EXIT_UNUSABLE)
        self.assertIn("nothing was checked", self.err)


class Fences(Case):
    def test_a_fenced_row_is_not_checked_or_rewritten(self):
        example = ["```", *ISSUE_HEADER, row("Example", 2, "🟠 **In Production**"), "```"]
        before = document([*ISSUE_HEADER, row("Work", 1, "⚪ —")], example)
        self.write(before)
        code = self.run_main({1: issue(), 2: issue("CLOSED", "COMPLETED")}, "--write")
        self.assertEqual(code, rs.EXIT_OK, self.out + self.err)
        self.assertEqual(self.fake.asked, [1])
        self.assertEqual(self.lines("WROTE"), [])
        self.assertEqual(self.roadmap.read_bytes(), before.encode("utf-8"))

    def test_a_fenced_legend_is_not_a_second_legend(self):
        for fence in ("```", "~~~"):
            with self.subTest(fence):
                quoted = [fence + "markdown", *LEGEND_HEADER, *LEGEND_ROWS, fence]
                self.write(document([*ISSUE_HEADER, row("Work", 1, "⚪ —")], quoted))
                self.assertEqual(self.run_main({1: issue()}), rs.EXIT_OK, self.out + self.err)
                self.assertNotIn("tables start", self.err)


class FenceEdges(Case):
    def closed_row_is_checked(self, *before):
        table = [*ISSUE_HEADER, row("Work", 1, "🟠 **In Production**")]
        self.write(document(list(before), table))
        code = self.run_main({1: issue("CLOSED", "COMPLETED")})
        self.assertEqual(code, rs.EXIT_ATTENTION, self.out + self.err)
        self.assertEqual(self.fake.asked, [1])
        self.assertEqual(len(self.lines("MISMATCH")), 1, self.out)

    def test_a_fence_that_closes_on_its_own_line_is_not_a_fence(self):
        self.closed_row_is_checked("```foo```")

    def test_an_unclosed_opener_is_not_a_fence(self):
        self.closed_row_is_checked("Below:", "```")


class Write(Case):
    def test_write_swaps_the_prefix_only(self):
        self.write(document([*ISSUE_HEADER, LINE_A]))
        self.assertEqual(self.run_main({2: issue("CLOSED", "COMPLETED")}, "--write"), rs.EXIT_OK, self.out + self.err)
        written = self.roadmap.read_text(encoding="utf-8").splitlines()
        expected = LINE_A.replace("🟠 **In Production**", "✅ **Closed**")
        self.assertIn(expected, written)
        self.assertEqual(len(self.lines("WROTE")), 1, self.out)

    def test_crlf_is_kept(self):
        before = document([*ISSUE_HEADER, LINE_A], newline="\r\n").encode("utf-8")
        self.roadmap.write_bytes(before)
        self.assertEqual(self.run_main({2: issue("CLOSED", "COMPLETED")}, "--write"), rs.EXIT_OK, self.out + self.err)
        expected = before.replace("🟠 **In Production**".encode(), "✅ **Closed**".encode())
        self.assertEqual(self.roadmap.read_bytes(), expected)

    def test_bare_dash_fix_ups(self):
        self.write(document([*ISSUE_HEADER, row("One", 1, "⚪ — note"), row("Two", 2, "🔵 **ready** — note")]))
        code = self.run_main({1: issue(labels=["dev ready"]), 2: issue()}, "--write")
        self.assertEqual(code, rs.EXIT_OK, self.out + self.err)
        written = self.roadmap.read_text(encoding="utf-8").splitlines()
        self.assertIn(row("One", 1, "🔵 **ready** — note"), written)
        self.assertIn(row("Two", 2, "⚪ — note"), written)

    def test_no_write_when_clean(self):
        self.write(document([*ISSUE_HEADER, row("Work", 1, "⚪ —")]))
        os.chmod(self.roadmap, stat.S_IRUSR)
        self.assertEqual(self.run_main({1: issue()}, "--write"), rs.EXIT_OK, self.out + self.err)
        self.assertNotIn("PermissionError", self.err)

    def test_read_failure_prints_no_traceback_and_writes_nothing(self):
        before = document([*ISSUE_HEADER, row("Work", 1, "⚪ —"), LINE_A])
        self.write(before)
        failing = {1: issue("CLOSED"), 2: rs.ReadError("acme/issues#2: HTTP 404")}
        self.assertEqual(self.run_main(failing, "--write"), rs.EXIT_UNUSABLE)
        self.assertIn("could not read acme/issues#2: HTTP 404", self.out + self.err)
        self.assertNotIn("Traceback", self.out + self.err)
        self.assertEqual(self.lines("WROTE"), [])
        self.assertEqual(self.roadmap.read_bytes(), before.encode("utf-8"))


class DefaultReader(Case):
    GOOD = '{"state": "OPEN", "stateReason": "", "labels": [], "body": ""}'

    def read(self, stdout, graphql=None):
        done = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
        with mock.patch.object(rs.subprocess, "run", return_value=done), \
                mock.patch.object(rs.tracker, "graphql", return_value=graphql):
            with self.assertRaises(rs.ReadError) as raised:
                rs.read_issue(2, "acme/issues")
        self.assertTrue(str(raised.exception).startswith("acme/issues#2: "), raised.exception)

    def test_gh_output_not_json_is_a_read_error(self):
        self.read("not json")

    def test_null_repository_or_issue_is_a_read_error(self):
        self.read(self.GOOD, {"repository": None})
        self.read(self.GOOD, {})

    def test_an_odd_graphql_payload_is_a_read_error(self):
        self.read(self.GOOD, None)
        self.read(self.GOOD, [])
        tracker.PROJECT_NUMBER = 2  # put back by the Case cleanup
        node = {"project": {"number": 2}, "fieldValueByName": "In progress"}
        self.read(self.GOOD, {"repository": {"issue": {"projectItems": {"nodes": [node]}}}})

    def test_a_bad_read_exits_2_without_a_traceback(self):
        self.write(document([*ISSUE_HEADER, row("Work", 2, "⚪ —")]))
        done = subprocess.CompletedProcess([], 0, stdout=self.GOOD, stderr="")
        with mock.patch.object(rs.subprocess, "run", return_value=done), \
                mock.patch.object(rs.tracker, "graphql", return_value={"repository": None}):
            code = self.run_main({}, reader=rs.read_issue)
        self.assertEqual(code, rs.EXIT_UNUSABLE)
        self.assertIn("could not read acme/issues#2: ", self.err)
        self.assertNotIn("Traceback", self.out + self.err)

    def test_gh_failure_is_a_read_error(self):
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="HTTP 404: Not Found\nmore\n")
        with mock.patch.object(rs.subprocess, "run", return_value=failed):
            with self.assertRaises(rs.ReadError) as raised:
                rs.read_issue(2, "acme/issues")
        self.assertEqual(str(raised.exception), "acme/issues#2: HTTP 404: Not Found")


class Profile(Case):
    def unusable(self, text, *argv, default_file=True):
        self.profile.write_text(text, encoding="utf-8")
        self.write(document([*ISSUE_HEADER, row("Work", 1, "⚪ —")]))
        self.assertEqual(self.run_main({1: issue()}, *argv, default_file=default_file), rs.EXIT_UNUSABLE)
        self.assertNotIn("Traceback", self.err)
        return self.err

    def test_reads_roadmap_file_by_default(self):
        self.write(document([*ISSUE_HEADER, row("Work", 1, "⚪ —")]))
        self.assertEqual(self.run_main({1: issue()}, default_file=True), rs.EXIT_OK, self.out + self.err)

    def test_not_the_shared_tool(self):
        err = self.unusable(profile_text(**{'tool = "shared"': 'tool = "python3 x.py"'}))
        self.assertIn("tracker.tool:", err)

    def test_not_a_project_board(self):
        err = self.unusable(profile_text(**{'kind = "github-project"': 'kind = "github-label"'}))
        self.assertIn("tracker.kind:", err)

    def test_no_roadmap_file(self):
        err = self.unusable(profile_text(drop=["[roadmap]", 'file = "roadmap.md"']))
        self.assertIn("roadmap.file: not set", err)

    def test_no_profile(self):
        self.profile.unlink()
        self.write(document([*ISSUE_HEADER, row("Work", 1, "⚪ —")]))
        self.assertEqual(self.run_main({1: issue()}), rs.EXIT_UNUSABLE)
        self.assertIn("profile: no file at", self.err)


if __name__ == "__main__":
    unittest.main()
