#!/usr/bin/env python3
"""Tests for roadmap_milestones.py: the plan of milestone changes, and applying only approved ids (gogogo#184).

Each case builds a temporary git repo holding a profile and a roadmap, with the
roadmap's history made of real commits at set dates. GitHub is a fake reader and
a recording writer, so nothing is ever read from or written to GitHub.

    python3 -m unittest tests.test_roadmap_milestones
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "gogogo" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import roadmap_milestones as rm  # noqa: E402
from roadmap_status import content as rs_content  # noqa: E402
from test_roadmap_status import LEGEND_HEADER, LEGEND_ROWS, keep_tracker_globals, profile_text  # noqa: E402

REPO = "acme/issues"
HEADER = ["| Issue | Work | State | Note |", "|---|---|---|---|"]
D1, D2, D3, D4 = "2026-10-01T10:00:00Z", "2026-10-02T10:00:00Z", "2026-10-03T10:00:00Z", "2026-10-04T10:00:00Z"


def link(number, repo=REPO):
    return f"https://github.com/{repo}/milestone/{number}"


def heading(text, number=None, repo=REPO):
    return f"## [{text}]({link(number, repo)})" if number else f"## {text}"


def row(number, work="w"):
    return f"| [#{number}](https://github.com/{REPO}/issues/{number}) | {work} | ⚪ — | |"


def roadmap(*sections, newline="\n"):
    """`sections` are (heading line, [issue numbers]) pairs, each a section with one table."""
    lines = ["# Roadmap", "", *LEGEND_HEADER, *LEGEND_ROWS, ""]
    for head, numbers in sections:
        lines += [head, ""]
        if numbers is not None:
            lines += [*HEADER, *(row(n) for n in numbers), ""]
    return newline.join(lines)


def iss(number, milestone=None, event=None, state="OPEN", title=None):
    return {"number": number, "state": state, "title": title or f"Issue {number}", "milestone": milestone,
            "last_event": event}


class FakeGitHub:
    def __init__(self, milestones=(), issues=(), visibility="PUBLIC", errors=None):
        self.list = [dict(m) for m in milestones]
        self.issues = {i["number"]: i for i in issues}
        self.issues.update(errors or {})
        self.vis = visibility

    def milestones(self, repo):
        return [dict(m) for m in self.list]

    def milestone_issues(self, repo, number):
        return sorted(n for n, i in self.issues.items() if not isinstance(i, Exception) and i["milestone"] == number)

    def issue(self, repo, number):
        found = self.issues.get(number) or iss(number)
        if isinstance(found, Exception):
            raise found
        return dict(found)

    def visibility(self, repo):
        return self.vis


def ms(number, title, state="open"):
    return {"number": number, "title": title, "state": state}


class Writer:
    def __init__(self):
        self.calls = []

    def create_milestone(self, repo, title):
        self.calls.append(("create_milestone", title))
        return 99

    def update_milestone(self, repo, number, **fields):
        self.calls.append(("update_milestone", number, fields))

    def set_issue_milestone(self, repo, issue, number):
        self.calls.append(("set_issue_milestone", issue, number))


class Case(unittest.TestCase):
    def setUp(self):
        keep_tracker_globals(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / ".agents").mkdir()
        self.profile = self.root / ".agents" / "dev-process.md"
        self.profile.write_text(profile_text(), encoding="utf-8")
        self.git("init", "-q")
        self.doc = self.root / "roadmap.md"

    def git(self, *args, date=None):
        env = dict(os.environ, GIT_AUTHOR_DATE=date or D1, GIT_COMMITTER_DATE=date or D1)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.autocrlf=false",
                        *args], cwd=self.root, env=env, check=True, capture_output=True)

    def commit(self, text, date):
        with open(self.doc, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        self.git("add", "-A")
        self.git("commit", "-qm", f"roadmap at {date}", date=date)

    def run_main(self, *argv, github=None, writer=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = rm.main(["--profile", str(self.profile), *argv], github=github or FakeGitHub(),
                           writer=writer or Writer())
        return code, out.getvalue(), err.getvalue()

    def plan(self, github, *extra):
        code, out, err = self.run_main("plan", *extra, github=github)
        return code, (json.loads(out) if out.strip() else None), err

    def items(self, plan, issue=None):
        return [i for i in plan["items"] if issue is None or i["issue"] == issue]

    def save(self, plan):
        path = self.root / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return str(path)


TWO = [ms(1, "A"), ms(2, "B")]


class Headings(Case):
    def test_linked_other_repo_and_plain_headings(self):  # 1
        self.commit(roadmap((heading("A", 1), [5]), (heading("X", 1, "x/y"), [6]), (heading("C"), None)), D1)
        code, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 1)]))
        self.assertEqual(code, 1)
        self.assertEqual(len(plan["skipped"]), 1)
        self.assertIn("x/y", plan["skipped"][0]["why"])
        self.assertEqual(plan["unlinked"], ["X", "C"])
        self.assertEqual(plan["items"], [], "the x/y section is unlinked, so #6 is outside")

    def test_everything_agrees(self):  # 2
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [6])), D1)
        code, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 1, D2), iss(6, 2, D2)]))
        self.assertEqual((code, plan["items"], plan["skipped"]), (0, [], []))


class Membership(Case):
    def test_a_newer_row_move_sets_the_milestone(self):  # 3
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D1)
        self.commit(roadmap((heading("A", 1), []), (heading("B", 2), [5])), D3)
        _, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 1, D2)]))
        (entry,) = self.items(plan, 5)
        self.assertEqual((entry["kind"], entry["side"], entry["expect"]), ("set-milestone", "github", 1))
        self.assertEqual(entry["milestone"], {"number": 2, "title": "B"})
        self.assertIn("roadmap newer", entry["why"])

    def test_a_newer_milestone_moves_the_row(self):  # 4
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D1)
        _, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 2, D2)]))
        (entry,) = self.items(plan, 5)
        self.assertEqual((entry["kind"], entry["from"], entry["section"]), ("move-row", "A", "B"))
        self.assertIn("GitHub newer", entry["why"])

    def test_a_cleared_milestone_is_a_question(self):  # 5
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D1)
        _, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, None, D2)]))
        (entry,) = self.items(plan, 5)
        self.assertEqual(entry["kind"], "question")
        labels = [c["label"] for c in entry["choices"]]
        self.assertEqual(len(labels), 3)
        self.assertIn("remove the row", labels[0])
        self.assertIn("set the milestone back", labels[1])
        self.assertEqual(labels[2], "leave both")
        self.assertEqual([c["item"]["kind"] if c["item"] else None for c in entry["choices"]],
                         ["remove-row", "set-milestone", None])

    def test_a_milestone_no_heading_links_is_a_question(self):  # 6
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D1)
        _, plan, _ = self.plan(FakeGitHub([*TWO, ms(3, "Elsewhere")], [iss(5, 3, D2)]))
        (entry,) = self.items(plan, 5)
        self.assertEqual(entry["kind"], "question")
        self.assertEqual([c["label"] for c in entry["choices"]][1], "leave both")
        self.assertEqual(len(entry["choices"]), 2)

    def test_the_first_row_is_home_and_a_second_row_makes_a_question(self):  # 7
        self.commit(roadmap((heading("A", 1), [9]), (heading("B", 2), [9])), D1)
        code, plan, _ = self.plan(FakeGitHub(TWO, [iss(9, 1, D2)]))
        self.assertEqual((code, plan["items"]), (0, []))
        _, plan, _ = self.plan(FakeGitHub(TWO, [iss(9, 2, D2)]))
        (entry,) = self.items(plan, 9)
        self.assertEqual(entry["kind"], "question")
        self.assertEqual([i["kind"] for i in plan["items"] if i["kind"] == "move-row"], [])

    def test_a_newer_milestone_with_no_row_adds_one(self):  # 8
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [6])), D1)
        github = FakeGitHub(TWO, [iss(5, 1, D1), iss(6, 2, D1), iss(7, 2, D2, title="New | work")])
        code, plan, _ = self.plan(github)
        (entry,) = self.items(plan, 7)
        self.assertEqual((entry["kind"], entry["section"]), ("add-row", "B"))
        code, out, _ = self.run_main("apply", "--plan", self.save(plan), "--items", str(entry["id"]), github=github)
        self.assertEqual(code, 0, out)
        lines = self.doc.read_text(encoding="utf-8").splitlines()
        at = lines.index(row(6))
        self.assertEqual(lines[at + 1], f"| [#7](https://github.com/{REPO}/issues/7) | New \\| work | ⚪ — | |")

    def test_a_removed_row_clears_an_open_issue_and_keeps_a_closed_one(self):  # 9
        self.commit(roadmap((heading("A", 1), [5, 6]), (heading("B", 2), [])), D1)
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D3)
        _, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 1, D2), iss(6, 1, D2)]))
        (entry,) = self.items(plan, 6)
        self.assertEqual((entry["kind"], entry["expect"]), ("clear-milestone", 1))
        _, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 1, D2), iss(6, 1, D2, state="CLOSED")]))
        self.assertEqual(self.items(plan, 6), [])
        self.assertEqual(plan["kept"], [{"issue": 6, "why": "closed; its milestone is never cleared"}])

    def test_an_issue_only_in_an_unlinked_section_is_left_alone(self):  # 10
        self.commit(roadmap((heading("A", 1), [5]), (heading("History"), [3])), D1)
        code, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 1, D1), iss(3, 1, D2)]))
        self.assertEqual((code, self.items(plan, 3)), (1 if plan["skipped"] else 0, []))


class Milestones(Case):
    def test_rename_close_and_leave_other_milestones_alone(self):  # 11
        self.commit(roadmap((heading("A", 1), [5]), (heading("D", 4), [])), D1)
        self.commit(roadmap((heading("A", 1), [5])), D2)
        github = FakeGitHub([ms(1, "Old A"), ms(4, "D"), ms(5, "Someone else's")], [iss(5, 1, D1)])
        _, plan, _ = self.plan(github)
        kinds = {i["kind"]: i for i in plan["items"]}
        self.assertEqual(kinds["rename-milestone"]["milestone"], {"number": 1, "title": "A"})
        self.assertEqual(kinds["rename-milestone"]["expect"], "Old A")
        self.assertEqual(kinds["close-milestone"]["milestone"]["number"], 4)
        self.assertNotIn("Someone else", json.dumps(plan))
        self.assertFalse([i for i in plan["items"] if (i["milestone"] or {}).get("number") == 5])

    def test_new_links_reuse_a_milestone_of_the_same_title(self):  # 12
        self.commit(roadmap((heading("A"), [5]), (heading("B"), [6])), D1)
        github = FakeGitHub([ms(7, "A", "closed")], [iss(5), iss(6)])
        _, plan, _ = self.plan(github)
        links = [i for i in plan["items"] if i["kind"] == "link-section"]
        self.assertEqual([(i["section"], i["milestone"]["number"]) for i in links], [("A", 7), ("B", None)])
        sets = {i["issue"]: i["milestone"] for i in plan["items"] if i["kind"] == "set-milestone"}
        self.assertEqual(sets, {5: {"number": 7, "title": "A"}, 6: {"number": None, "title": "B"}})
        writer = Writer()
        code, out, _ = self.run_main("apply", "--plan", self.save(plan), "--items", str(links[0]["id"]),
                                     github=github, writer=writer)
        self.assertEqual(code, 0, out)
        self.assertEqual(writer.calls, [], "the milestone titled A is reused, not created again")
        self.assertIn(f"## [A]({link(7)})\n", self.doc.read_text(encoding="utf-8"))

    def test_a_new_link_by_name(self):
        self.commit(roadmap((heading("A", 1), [5]), (heading("B"), [6])), D1)
        code, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 1, D1), iss(6)]), "--link", "B")
        self.assertEqual([i["kind"] for i in plan["items"]], ["link-section", "set-milestone"])
        self.assertEqual(self.plan(FakeGitHub(TWO, [iss(5, 1, D1)]), "--link", "Nope")[0], 2)

    def test_with_nothing_linked_link_adds_to_every_table_section(self):
        self.commit(roadmap((heading("A"), [5]), (heading("B"), [6]), (heading("C"), None)), D1)
        _, plan, _ = self.plan(FakeGitHub([], [iss(5), iss(6)]), "--link", "C")
        self.assertEqual([i["section"] for i in plan["items"] if i["kind"] == "link-section"], ["A", "B", "C"])


class Apply(Case):
    def setUp(self):
        super().setUp()
        self.commit(roadmap((heading("A", 1), [5, 6]), (heading("B", 2), [8])), D1)
        self.commit(roadmap((heading("A", 1), [6]), (heading("B", 2), [5, 8])), D3)
        self.github = FakeGitHub(TWO, [iss(5, 1, D2), iss(6, None, D2), iss(8, 2, D1)])
        _, self.plan_, _ = self.plan(self.github)

    def test_a_stale_item_is_skipped_and_writes_nothing(self):  # 13
        (entry,) = [i for i in self.plan_["items"] if i["kind"] == "set-milestone"]
        self.github.issues[5]["milestone"] = 2
        writer = Writer()
        code, out, _ = self.run_main("apply", "--plan", self.save(self.plan_), "--items", str(entry["id"]),
                                     github=self.github, writer=writer)
        self.assertEqual(code, 1)
        self.assertIn(f"SKIPPED stale {entry['id']}", out)
        self.assertEqual(writer.calls, [])

    def test_only_the_approved_ids_are_written(self):  # 14
        ids = [i["id"] for i in self.plan_["items"]]
        self.assertGreaterEqual(len(ids), 2, self.plan_)
        set_id = next(i["id"] for i in self.plan_["items"] if i["kind"] == "set-milestone")
        writer = Writer()
        code, _, _ = self.run_main("apply", "--plan", self.save(self.plan_), "--items", str(set_id),
                                   github=self.github, writer=writer)
        self.assertEqual((code, writer.calls), (0, [("set_issue_milestone", 5, 2)]))
        question = next(i["id"] for i in self.plan_["items"] if i["kind"] == "question")
        writer = Writer()
        before = self.doc.read_bytes()
        code, _, err = self.run_main("apply", "--plan", self.save(self.plan_), "--items", f"{set_id},{question}",
                                     github=self.github, writer=writer)
        self.assertEqual((code, writer.calls), (2, []))
        self.assertIn("--choose", err)
        self.assertEqual(self.doc.read_bytes(), before)

    def test_a_chosen_answer_is_applied(self):
        question = next(i for i in self.plan_["items"] if i["kind"] == "question")
        writer = Writer()
        code, out, _ = self.run_main("apply", "--plan", self.save(self.plan_), "--items", str(question["id"]),
                                     "--choose", f"{question['id']}=2", github=self.github, writer=writer)
        self.assertEqual((code, writer.calls), (0, [("set_issue_milestone", 6, 1)]), out)


class RoundOne(Case):
    """Review round 1 of gogogo#184."""

    def test_a_row_the_refresh_rewrote_still_moves(self):
        self.commit(roadmap((heading("A", 1), [5, 6]), (heading("B", 2), [8])), D1)
        github = FakeGitHub(TWO, [iss(5, 2, D2), iss(6, 1, D1), iss(8, 2, D1)])
        _, plan, _ = self.plan(github)
        (entry,) = self.items(plan, 5)
        text = self.doc.read_text(encoding="utf-8").replace(row(5), row(5).replace("⚪ —", "🟡 **in progress**"))
        self.doc.write_text(text, encoding="utf-8")
        code, out, _ = self.run_main("apply", "--plan", self.save(plan), "--items", str(entry["id"]), github=github)
        self.assertEqual(code, 0, out)
        lines = self.doc.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[lines.index(row(8)) + 1], row(5).replace("⚪ —", "🟡 **in progress**"))

    def test_an_added_row_in_a_table_without_an_issue_column_names_its_issue(self):
        text = roadmap((heading("A", 1), [5])) + "\n" + "\n".join([
            heading("B", 2), "", "| Work | State |", "|---|---|",
            f"| w | ⚪ — [#6](https://github.com/{REPO}/issues/6) |", ""])
        self.commit(text, D1)
        github = FakeGitHub(TWO, [iss(5, 1, D1), iss(6, 2, D1), iss(7, 2, D2, title="Seven")])
        _, plan, _ = self.plan(github)
        (entry,) = self.items(plan, 7)
        code, _, _ = self.run_main("apply", "--plan", self.save(plan), "--items", str(entry["id"]), github=github)
        self.assertEqual(code, 0)
        self.assertIn(f"| Seven | ⚪ — [#7](https://github.com/{REPO}/issues/7) |", self.doc.read_text(encoding="utf-8"))
        self.git("commit", "-qam", "add #7", date=D3)
        _, plan, _ = self.plan(github)
        self.assertEqual(self.items(plan, 7), [], "the added row is #7's home: nothing to add again")

    def test_a_heading_whose_milestone_is_gone_sets_nothing(self):
        self.commit(roadmap((heading("A", 1), [5]), (heading("Gone", 7), [6])), D1)
        _, plan, _ = self.plan(FakeGitHub([ms(1, "A")], [iss(5, 1, D1), iss(6)]))
        self.assertEqual(self.items(plan, 6), [])
        self.assertIn("no longer exists", plan["skipped"][0]["why"])

    def test_a_heading_with_a_bracket_is_not_linked(self):
        self.commit(roadmap((heading("[WIP] Auth"), [5]), (heading("B"), [6])), D1)
        _, plan, _ = self.plan(FakeGitHub([], [iss(5), iss(6)]))
        self.assertEqual([i["section"] for i in plan["items"] if i["kind"] == "link-section"], ["B"])
        self.assertEqual(self.items(plan, 5), [])
        self.assertIn("square bracket", plan["skipped"][0]["why"])

    def test_a_roadmap_once_deleted_still_plans(self):
        self.commit(roadmap((heading("A", 1), [5])), D1)
        self.git("rm", "-q", "roadmap.md")
        self.git("commit", "-qm", "gone", date=D2)
        self.commit(roadmap((heading("A", 1), [5])), D3)
        code, plan, err = self.plan(FakeGitHub(TWO, [iss(5, 1, D1)]))
        self.assertEqual(code, 0, err)

    def test_a_renamed_milestone_is_not_linked(self):
        self.commit(roadmap((heading("A"), [5])), D1)
        github = FakeGitHub([ms(7, "A")], [iss(5)])
        _, plan, _ = self.plan(github)
        (link_id,) = [i["id"] for i in plan["items"] if i["kind"] == "link-section"]
        github.list[0]["title"] = "Archive"
        writer = Writer()
        code, out, _ = self.run_main("apply", "--plan", self.save(plan), "--items", str(link_id),
                                     github=github, writer=writer)
        self.assertEqual((code, writer.calls), (1, []))
        self.assertIn("SKIPPED stale", out)
        self.assertNotIn("milestone/7", self.doc.read_text(encoding="utf-8"))


class RoundTwo(Case):
    """Review round 2 of gogogo#184."""

    def test_a_renamed_milestone_takes_no_issue_either(self):
        self.commit(roadmap((heading("A"), [5])), D1)
        github = FakeGitHub([ms(7, "A")], [iss(5)])
        _, plan, _ = self.plan(github)
        self.assertEqual([i["kind"] for i in plan["items"]], ["link-section", "set-milestone"])
        github.list[0]["title"] = "Archive"
        writer = Writer()
        code, out, _ = self.run_main("apply", "--plan", self.save(plan), "--items", "1,2",
                                     github=github, writer=writer)
        self.assertEqual((code, writer.calls), (1, []), out)
        self.assertEqual(out.count("SKIPPED stale"), 2, out)

    def test_a_gone_milestone_keeps_its_rows_home(self):
        self.commit(roadmap((heading("A", 1), [5]), (heading("Gone", 7), [6]), (heading("B", 2), [6])), D1)
        _, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 1, D1), iss(6)]))
        self.assertEqual(self.items(plan, 6), [], "B's row for #6 is an extra row: it sets nothing")
        self.assertEqual(plan["unlinked"], [], "the heading still links; --link could not change it")


class RoundThree(Case):
    """Review round 3 of gogogo#184."""

    def test_a_heading_renamed_with_a_new_row_applies_both(self):
        self.commit(roadmap((heading("Old", 1), [])), D1)
        self.commit(roadmap((heading("B", 1), [5])), D3)
        github = FakeGitHub([ms(1, "Old")], [iss(5)])
        _, plan, _ = self.plan(github)
        self.assertEqual([i["kind"] for i in plan["items"]], ["rename-milestone", "set-milestone"])

        def rename(repo, number, **fields):
            Writer.update_milestone(writer, repo, number, **fields)
            github.list[0].update(fields)

        writer = Writer()
        writer.update_milestone = rename
        code, out, _ = self.run_main("apply", "--plan", self.save(plan), "--items", "1,2",
                                     github=github, writer=writer)
        self.assertEqual((code, writer.calls), (0, [("update_milestone", 1, {"title": "B"}),
                                                    ("set_issue_milestone", 5, 1)]), out)


def flat(entry):
    """An item's fields as one tuple, its milestone as (number, title)."""
    if entry is None:
        return None
    m = entry["milestone"]
    return (entry.get("id"), entry["kind"], entry["side"], entry["issue"], entry["section"],
            m and (m["number"], m["title"]), entry["from"], entry["expect"], entry.get("by_title"), entry["why"])


def rule_branches(version):
    """A roadmap that reaches every rule: 90 lines of prose first, so homes sit past line 90."""
    other = ["| Issue | State |", "|---|---|", f"| [#16](https://github.com/{REPO}/issues/16) | ⚪ — |"]
    lines = ["# Roadmap", "", *LEGEND_HEADER, *LEGEND_ROWS, "", *["Prose."] * 90, ""]
    for head, rows in ((heading("A", 1), [5, 6, 10, 11, 15] + ([13, 14] if version == 1 else [])),
                       (heading("X", 1, "x/y"), [20]), (heading("B", 2), [5])):
        lines += [head, "", *HEADER, *(row(n) for n in rows), ""]
    lines += [heading("C", 3), "", *other, "", heading("Gone", 7), "", *HEADER, row(17), ""]
    if version == 1:
        lines += [heading("D", 4), "", *HEADER, ""]
    lines += [heading("History"), "", *HEADER, row(3), ""]
    return "\n".join(lines)


class Exact(Case):
    """What the person is shown and what is written, exactly: the plan, each apply line, each gh call."""

    def sha(self, rev):
        return subprocess.run(["git", "rev-parse", "--short=7", rev], cwd=self.root, capture_output=True,
                              text=True, check=True).stdout.strip()

    def test_every_rule_branch(self):
        self.commit(rule_branches(1), D1)
        self.commit(rule_branches(2), D3)
        github = FakeGitHub([ms(1, "Old A"), ms(2, "B"), ms(3, "C"), ms(4, "D"), ms(9, "Elsewhere")], [
            iss(5, 2, D4), iss(6, None, D4), iss(10, 9, D4), iss(11, 3, D4), iss(15, 2, D1),
            iss(12, 2, "2026-09-30T10:00:00Z"), iss(13, 1, D2), iss(14, 1, D2, state="CLOSED"),
            iss(16, 3, D1), iss(17), iss(20), iss(3, 1, D4)])
        code, plan, _ = self.plan(github)
        first, second = self.sha("HEAD~1"), self.sha("HEAD")
        gh = f"GitHub newer: milestone changed 2026-10-04T10:00Z; row placed 2026-10-01T10:00Z ({first})"
        old = "the roadmap newer: milestone changed 2026-10-01T10:00Z; row placed 2026-10-01T10:00Z"
        row5, row6 = rs_content(row(5)), rs_content(row(6))
        self.assertEqual(code, 1)
        self.assertEqual((plan["repo"], plan["doc"]), (REPO, str(self.doc)))
        self.assertEqual([flat(i) for i in plan["items"]], [
            (1, "rename-milestone", "github", None, "A", (1, "A"), "Old A", "Old A", None,
             "the heading reads 'A'; the milestone 'Old A'"),
            (2, "close-milestone", "github", None, None, (4, "D"), "open", "open", None,
             "an earlier version of the roadmap linked it; none does now"),
            (3, "question", "both", 5, "A", (2, "B"), "A", 2, None, gh + "; 'B' already has a row for it"),
            (4, "question", "both", 6, "A", None, "A", None, None, gh + "; its milestone was cleared"),
            (5, "question", "both", 10, "A", (9, "Elsewhere"), "A", 9, None,
             gh + "; its milestone is not linked from any heading"),
            (6, "set-milestone", "github", 15, "A", (1, "Old A"), "B", 2, None, f"{old} ({first})"),
            (7, "add-row", "doc", 12, "B", (2, "B"), None, None, None,
             "GitHub newer: milestone changed 2026-09-30T10:00Z; row placed never"),
            (8, "clear-milestone", "github", 13, None, (1, "Old A"), "Old A", 1, None,
             f"the roadmap newer: milestone changed 2026-10-02T10:00Z; row placed 2026-10-03T10:00Z ({second})"),
        ])
        choices = {i["issue"]: [(c["label"], flat(c["item"])) for c in i["choices"]]
                   for i in plan["items"] if i["kind"] == "question"}
        self.assertEqual(choices, {
            5: [("remove the row in 'A'", (None, "remove-row", "doc", 5, "A", None, "A", row5, None, gh)),
                ("set the milestone back to 'A'", (None, "set-milestone", "github", 5, "A", (1, "Old A"), "B", 2,
                                                   None, gh)),
                ("leave both", None)],
            6: [("remove the row in 'A'", (None, "remove-row", "doc", 6, "A", None, "A", row6, None, gh)),
                ("set the milestone back to 'A'", (None, "set-milestone", "github", 6, "A", (1, "Old A"), None,
                                                   None, None, gh)),
                ("leave both", None)],
            10: [("set the milestone back to 'A'", (None, "set-milestone", "github", 10, "A", (1, "Old A"),
                                                    "Elsewhere", 9, None, gh)),
                 ("leave both", None)],
        })
        lines = rule_branches(2).split("\n")
        self.assertEqual(plan["skipped"], [
            {"line": lines.index(heading("X", 1, "x/y")) + 1,
             "why": "the heading links a milestone in x/y, not this tracker; its section is not synced"},
            {"line": lines.index(heading("Gone", 7)) + 1, "why": "the milestone this heading links no longer exists"},
            {"line": lines.index(row(11)) + 1, "why": "#11: the tables differ; move it by hand from 'A' to 'C'"},
        ])
        self.assertEqual(plan["kept"], [{"issue": 14, "why": "closed; its milestone is never cleared"}])
        self.assertEqual(plan["unlinked"], ["X", "History"])

    def test_new_sections(self):
        self.commit(roadmap((heading("A"), [5]), (heading("B"), [6]), (heading("C"), None)), D1)
        _, plan, _ = self.plan(FakeGitHub([ms(3, "Elsewhere")], [iss(5, 3, D1), iss(6)]), "--link", "C")
        self.assertEqual([flat(i) for i in plan["items"]], [
            (1, "link-section", "both", None, "A", (None, "A"), None, None, None, "no heading links a milestone yet"),
            (2, "link-section", "both", None, "B", (None, "B"), None, None, None, "no heading links a milestone yet"),
            (3, "link-section", "both", None, "C", (None, "C"), None, None, None, "asked for by name with --link"),
            (4, "set-milestone", "github", 5, "A", (None, "A"), "Elsewhere", 3, True, "first row in 'A', a new milestone"),
            (5, "set-milestone", "github", 6, "B", (None, "B"), None, None, True, "first row in 'B', a new milestone"),
        ])
        code, _, err = self.plan(FakeGitHub(), "--link", "Nope")
        self.assertEqual((code, err.strip()), (2, "--link 'Nope': no ## heading with that text in the roadmap"))

    def test_a_section_is_placed_by_its_latest_arrival(self):
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D1)
        self.commit(roadmap((heading("A", 1), []), (heading("B", 2), [5])), D2)
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D3)
        history = rm.History(rm.Git(self.doc), REPO)
        self.assertEqual(history.placed(5), ("2026-10-03T10:00:00+00:00", self.git_sha("HEAD")))
        self.assertEqual(history.placed(9), (None, None))

    def git_sha(self, rev):
        return subprocess.run(["git", "rev-parse", rev], cwd=self.root, capture_output=True, text=True,
                              check=True).stdout.strip()

    def apply_plan(self, items, github, ids, *choose, writer=None):
        writer = writer or Writer()
        path = self.save({"items": items})
        code, out, err = self.run_main("apply", "--plan", path, "--items", ids, *choose, github=github, writer=writer)
        return code, out.splitlines(), err, writer.calls

    def test_apply_runs_every_kind_in_order(self):
        self.commit(roadmap((heading("A", 1), [5, 6, 7]), (heading("B", 2), [8]), (heading("New"), [9])), D1)
        github = FakeGitHub([ms(1, "Old A"), ms(2, "B"), ms(4, "D")], [iss(9), iss(13, 1), iss(12, 2)])
        doc_item = dict(issue=None, section=None, milestone=None, expect=None, why="")
        items = [
            dict(doc_item, id=1, kind="add-row", side="doc", issue=12, section="B"),
            dict(doc_item, id=2, kind="move-row", side="doc", issue=5, section="B", **{"from": "A"}),
            dict(doc_item, id=3, kind="question", side="both", issue=6, choices=[
                {"label": "remove", "item": dict(doc_item, kind="remove-row", side="doc", issue=6, **{"from": "A"})},
                {"label": "leave both", "item": None}]),
            dict(doc_item, id=4, kind="question", side="both", issue=7, choices=[
                {"label": "remove", "item": dict(doc_item, kind="remove-row", side="doc", issue=7, **{"from": "A"})},
                {"label": "leave both", "item": None}]),
            dict(doc_item, id=5, kind="clear-milestone", side="github", issue=13, expect=1),
            dict(doc_item, id=6, kind="close-milestone", side="github", milestone={"number": 4, "title": "D"},
                 expect="open"),
            dict(doc_item, id=7, kind="set-milestone", side="github", issue=9, section="New", by_title=True,
                 milestone={"number": None, "title": "New"}),
            dict(doc_item, id=8, kind="rename-milestone", side="github", section="A",
                 milestone={"number": 1, "title": "A"}, expect="Old A"),
            dict(doc_item, id=9, kind="link-section", side="both", section="New",
                 milestone={"number": None, "title": "New"}),
        ]
        code, out, _, calls = self.apply_plan(items, github, "1,2,3,4,5,6,7,8,9", "--choose", "3=1",
                                              "--choose", "4=2")
        self.assertEqual(code, 0)
        self.assertEqual(out, [
            "APPLIED 9 link-section: milestone 99",
            "APPLIED 8 rename-milestone: 'Old A' -> 'A'",
            "APPLIED 7 set-milestone #9: milestone 99",
            "APPLIED 5 clear-milestone #13: milestone cleared",
            "APPLIED 6 close-milestone: milestone 4 closed",
            "APPLIED 2 move-row #5: row moved to 'B'",
            "APPLIED 1 add-row #12: row added to 'B'",
            "APPLIED 3 remove-row #6: row removed from 'A'",
            "APPLIED 4 leave: left both as they are",
        ])
        self.assertEqual(calls, [("create_milestone", "New"), ("update_milestone", 1, {"title": "A"}),
                                 ("set_issue_milestone", 9, 99), ("set_issue_milestone", 13, None),
                                 ("update_milestone", 4, {"state": "closed"})])
        added = f"| [#12](https://github.com/{REPO}/issues/12) | Issue 12 | ⚪ — | |"
        self.assertEqual(self.doc.read_text(encoding="utf-8"), roadmap(
            (heading("A", 1), [7]), (heading("B", 2), [8, 5]), (heading("New", 99), [9])).replace(
            row(5), row(5) + "\n" + added))

    def test_apply_says_why_each_item_was_skipped(self):
        self.commit(roadmap((heading("A", 1), [5]), (heading("C"), None)), D1)
        github = FakeGitHub([ms(1, "Other"), ms(4, "D", "closed")], [iss(5, 2), iss(6)])
        base = dict(issue=None, section=None, milestone=None, expect=None, why="")
        items = [
            dict(base, id=1, kind="link-section", section="Nope", milestone={"number": None, "title": "Nope"}),
            dict(base, id=2, kind="rename-milestone", milestone={"number": 1, "title": "A"}, expect="Old A"),
            dict(base, id=3, kind="rename-milestone", milestone={"number": 8, "title": "A"}, expect="Old A"),
            dict(base, id=4, kind="close-milestone", milestone={"number": 4, "title": "D"}, expect="open"),
            dict(base, id=5, kind="close-milestone", milestone={"number": 8, "title": "D"}, expect="open"),
            dict(base, id=6, kind="set-milestone", issue=5, section="A", milestone={"number": 1, "title": "A"},
                 expect=1),
            dict(base, id=7, kind="set-milestone", issue=6, section="Zed", by_title=True,
                 milestone={"number": None, "title": "Zed"}),
            dict(base, id=8, kind="move-row", issue=9, section="C", **{"from": "A"}),
            dict(base, id=9, kind="move-row", issue=5, section="C", **{"from": "A"}),
            dict(base, id=10, kind="add-row", issue=6, section="C"),
        ]
        for entry in items:
            entry.setdefault("from", None)
        code, out, _, calls = self.apply_plan(items, github, ",".join(str(i["id"]) for i in items))
        self.assertEqual((code, calls), (1, []))
        self.assertEqual(out, [
            "SKIPPED stale 1 link-section: no heading 'Nope' in the roadmap",
            "SKIPPED stale 2 rename-milestone: the milestone now reads 'Other'",
            "SKIPPED stale 3 rename-milestone: the milestone now reads 'nothing (gone)'",
            "SKIPPED stale 6 set-milestone #5: #5 is now in milestone 2",
            "SKIPPED stale 7 set-milestone #6: no milestone titled 'Zed' (link its section first)",
            "SKIPPED stale 4 close-milestone: the milestone is now closed",
            "SKIPPED stale 5 close-milestone: the milestone is now gone",
            "SKIPPED stale 8 move-row #9: the row is no longer in 'A'",
            "SKIPPED stale 9 move-row #5: 'C' has no table",
            "SKIPPED stale 10 add-row #6: 'C' has no table",
        ])

    def test_a_failed_item_does_not_stop_the_rest(self):
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D1)
        github = FakeGitHub(TWO, [iss(6, 1)], errors={7: rm.ReadError("#7: HTTP 502")})
        base = dict(section=None, milestone=None, expect=None, why="", **{"from": None})
        items = [dict(base, id=1, kind="set-milestone", issue=7, milestone={"number": 2, "title": "B"}),
                 dict(base, id=2, kind="clear-milestone", issue=6, expect=1),
                 dict(base, id=3, kind="bogus", issue=None)]
        code, out, _, calls = self.apply_plan(items, github, "1,2,3")
        self.assertEqual(code, 1)
        self.assertEqual(out, ["FAILED 1 set-milestone #7: #7: HTTP 502",
                               "APPLIED 2 clear-milestone #6: milestone cleared",
                               "FAILED 3 bogus: unknown kind 'bogus'"])
        self.assertEqual(calls, [("set_issue_milestone", 6, None)])
        code, out, _, _ = self.apply_plan(items[:1], github, "1")
        self.assertEqual((code, len(out)), (1, 1))

    def test_ids_and_choices_are_checked(self):
        self.commit(roadmap((heading("A", 1), [5])), D1)
        question = {"id": 3, "kind": "question", "issue": 5, "choices": [
            {"label": "x", "item": None}, {"label": "y", "item": None}, {"label": "z", "item": None}]}
        for choose, code in (("3=0", 2), ("3=1", 0), ("3=3", 0), ("3=4", 2)):
            got, out, err, _ = self.apply_plan([question], FakeGitHub(), "3", "--choose", choose)
            self.assertEqual(got, code, choose)
            if code == 2:
                self.assertEqual(err.strip(), "--items: id 3 is a question; give --choose 3=<1..3>")
            else:
                self.assertEqual(out, ["APPLIED 3 leave: left both as they are"])
        self.assertEqual(self.apply_plan([question], FakeGitHub(), "42")[2].strip(),
                         "--items: id 42 is not in the plan")
        self.assertEqual(self.apply_plan([question], FakeGitHub(), "x")[2].strip(),
                         "--items is a comma list of ids, --choose is ID=CHOICE")
        code, _, err = self.run_main("apply", "--plan", str(self.root / "none.json"), "--items", "1")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith(f"--plan {self.root / 'none.json'}: cannot be read ("), err)

    def test_every_problem_line_is_printed(self):
        text = roadmap((heading("A", 1), [5])).replace(LEGEND_ROWS[0] + "\n", "").replace(LEGEND_ROWS[-2] + "\n", "")
        self.commit(text, D1)
        code, _, err = self.run_main("apply", "--plan", self.save({"items": []}), "--items", "")
        self.assertEqual(code, 2)
        self.assertGreaterEqual(len(err.splitlines()), 2, err)

    def test_the_command_and_its_arguments_are_required(self):
        for argv in ([], ["apply", "--items", "1"], ["apply", "--plan", "p.json"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                rm.main(["--profile", str(self.profile), *argv], github=FakeGitHub(), writer=Writer())
            self.assertEqual(stop.exception.code, 2, argv)


class Edges(Case):
    """Tables at the edges of the file, sections at the edges of the document."""

    def test_tables_at_the_edges(self):
        self.assertEqual([i for i, _ in rm.tables_at(["| Issue | State |\n", "|---|---|\n", "| #1 | ⚪ — |\n"])], [0])
        self.assertEqual(rm.tables_at(["text\n", "| stray |"]), [])
        self.assertEqual(rm.tables_at(["| Issue | Work |\n", "|---|---|\n", "| #1 | w |\n"]), [])

    def test_a_table_before_the_first_heading_belongs_to_no_section(self):
        text = roadmap((heading("A", 1), [5])).replace("# Roadmap\n", "# Roadmap\n\n" + "\n".join(
            [*HEADER, row(6)]) + "\n\n")
        doc = rm.parse_doc(text, REPO)
        self.assertEqual([(s.heading, [n for _, _, n in s.rows]) for s in doc.sections], [("A", [5])])

    def test_rows_move_between_middle_and_last_sections(self):
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [6]), (heading("C"), None),
                            (heading("D", 4), [7])), D1)
        base = dict(milestone=None, expect=None, why="", side="doc")
        items = [dict(base, id=1, kind="move-row", issue=6, section="D", **{"from": "B"}),
                 dict(base, id=2, kind="move-row", issue=5, section="C", **{"from": "A"})]
        code, out, _, _ = Exact.apply_plan(self, items, FakeGitHub(), "1,2")
        self.assertEqual(out, ["APPLIED 1 move-row #6: row moved to 'D'", "SKIPPED stale 2 move-row #5: 'C' has no table"])
        self.assertEqual(self.doc.read_text(encoding="utf-8"), roadmap(
            (heading("A", 1), [5]), (heading("B", 2), []), (heading("C"), None), (heading("D", 4), [7, 6])))

    def test_a_row_lands_in_an_empty_table_and_at_a_file_end_with_no_newline(self):
        text = roadmap((heading("A", 1), [5, 6]), (heading("B", 2), [])) + "\n" + "\n".join(
            [heading("C", 3), "", *HEADER, row(8)])
        self.commit(text, D1)
        base = dict(milestone=None, expect=None, why="", side="doc")
        items = [dict(base, id=1, kind="move-row", issue=5, section="B", **{"from": "A"}),
                 dict(base, id=2, kind="move-row", issue=6, section="C", **{"from": "A"}),
                 dict(base, id=3, kind="add-row", issue=9, section="C", **{"from": None})]
        code, out, _, _ = Exact.apply_plan(self, items, FakeGitHub([], [iss(9, title="Nine")]), "1,2,3")
        self.assertEqual(code, 0, out)
        nine = f"| [#9](https://github.com/{REPO}/issues/9) | Nine | ⚪ — | |"
        self.assertEqual(self.doc.read_text(encoding="utf-8"), roadmap((heading("A", 1), []), (heading("B", 2), [5]))
                         + "\n" + "\n".join([heading("C", 3), "", *HEADER, row(8), row(6), nine]) + "\n")

    def test_an_added_row_names_its_issue_once_and_fills_the_first_work_column(self):
        text = roadmap((heading("A", 1), [5])) + "\n" + "\n".join([
            heading("B", 2), "", "| Issue | Work | Owner | State | Note |", "|---|---|---|---|---|", ""])
        self.commit(text, D1)
        item = dict(id=1, kind="add-row", side="doc", issue=9, section="B", milestone=None, expect=None, why="",
                    **{"from": None})
        code, _, _, _ = Exact.apply_plan(self, [item], FakeGitHub([], [iss(9, title="Nine")]), "1")
        self.assertEqual(code, 0)
        self.assertIn(f"\n| [#9](https://github.com/{REPO}/issues/9) | Nine | | ⚪ — | |\n",
                      self.doc.read_text(encoding="utf-8"))


class RunTwo(Case):
    """Mutation run 2's survivors that a real roadmap reaches."""

    def test_headings_with_one_bracket_are_skipped_on_their_line(self):
        self.commit(roadmap((heading("[WIP Auth"), [5]), (heading("Auth] two"), [6]), (heading("B"), [7])), D1)
        _, plan, _ = self.plan(FakeGitHub([], [iss(5), iss(6), iss(7)]))
        lines = self.doc.read_text(encoding="utf-8").split("\n")
        why = "the heading has a square bracket, so a link to it could not be read back; link it by hand"
        self.assertEqual(plan["skipped"], [{"line": lines.index(heading("[WIP Auth")) + 1, "why": why},
                                           {"line": lines.index(heading("Auth] two")) + 1, "why": why}])

    def test_new_sections_skip_issues_already_in_place_and_sections_without_tables(self):
        self.commit(roadmap((heading("A"), [5, 6]), (heading("C"), None)), D1)
        _, plan, _ = self.plan(FakeGitHub([ms(7, "A")], [iss(5, 7, D1), iss(6)]))
        self.assertEqual([(i["kind"], i["section"], i["issue"]) for i in plan["items"]],
                         [("link-section", "A", None), ("set-milestone", "A", 6)])

    def test_a_milestone_never_set_says_so(self):
        self.commit(roadmap((heading("A", 1), [5])), D1)
        _, plan, _ = self.plan(FakeGitHub(TWO, [iss(5)]))
        self.assertEqual([(i["kind"], i["why"]) for i in plan["items"]], [
            ("set-milestone", f"the roadmap newer: milestone never set; row placed 2026-10-01T10:00Z "
                              f"({Exact.sha(self, 'HEAD')})")])

    def test_a_moved_row_is_the_documents_side(self):
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D1)
        _, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 2, D2)]))
        self.assertEqual([(i["kind"], i["side"]) for i in plan["items"]], [("move-row", "doc")])

    def set_by_title(self, milestones, number):
        self.commit(roadmap((heading("A", 1), [5]), (heading("New"), [6])), D1)
        item = dict(id=1, kind="set-milestone", side="github", issue=6, section="New", by_title=True,
                    milestone={"number": number, "title": "New"}, expect=None, why="", **{"from": None})
        code, out, _, calls = Exact.apply_plan(self, [item], FakeGitHub(milestones, [iss(6)]), "1")
        return code, out, calls

    def test_a_new_sections_milestone_found_by_title_is_used_while_it_keeps_it(self):
        self.assertEqual(self.set_by_title([ms(7, "New")], 7), (0, ["APPLIED 1 set-milestone #6: milestone 7"],
                                                                [("set_issue_milestone", 6, 7)]))

    def test_a_new_sections_milestone_made_since_the_plan_is_found_by_title(self):
        self.assertEqual(self.set_by_title([ms(12, "New")], None)[2], [("set_issue_milestone", 6, 12)])

    def test_a_new_sections_milestone_renamed_or_gone_is_stale(self):
        self.assertEqual(self.set_by_title([ms(7, "Archive")], 7)[:2],
                         (1, ["SKIPPED stale 1 set-milestone #6: milestone 7 now reads 'Archive'"]))
        self.assertEqual(self.set_by_title([], 7)[:2],
                         (1, ["SKIPPED stale 1 set-milestone #6: milestone 7 now reads 'nothing (gone)'"]))

    def test_a_link_on_the_last_line_ends_it(self):
        self.commit(roadmap((heading("A", 1), [5])) + "\n## New", D1)
        item = dict(id=1, kind="link-section", side="both", issue=None, section="New",
                    milestone={"number": None, "title": "New"}, expect=None, why="", **{"from": None})
        Exact.apply_plan(self, [item], FakeGitHub(), "1")
        self.assertTrue(self.doc.read_text(encoding="utf-8").endswith(f"\n## [New]({link(99)})\n"))

    def test_the_files_last_row_moves_and_a_row_is_added_after_it(self):
        text = roadmap((heading("A", 1), [5]), (heading("B", 2), [6]))
        self.commit(text.rstrip("\n"), D1)
        base = dict(side="doc", milestone=None, expect=None, why="")
        moved = [dict(base, id=1, kind="move-row", issue=6, section="A", **{"from": "B"})]
        Exact.apply_plan(self, moved, FakeGitHub(), "1")
        self.assertEqual(self.doc.read_text(encoding="utf-8"),
                         roadmap((heading("A", 1), [5, 6]), (heading("B", 2), [])).rstrip("\n") + "\n")
        self.commit(text.rstrip("\n"), D2)
        added = [dict(base, id=1, kind="add-row", issue=9, section="B", **{"from": None})]
        Exact.apply_plan(self, added, FakeGitHub([], [iss(9, title="Nine")]), "1")
        self.assertEqual(self.doc.read_text(encoding="utf-8"), text.rstrip("\n") + "\n"
                         + f"| [#9](https://github.com/{REPO}/issues/9) | Nine | ⚪ — | |\n")

    def test_a_file_with_carriage_returns_only_keeps_them(self):
        text = roadmap((heading("A", 1), [5, 6]), (heading("B", 2), [8]), newline="\r")
        self.commit(text, D1)
        base = dict(side="doc", milestone=None, expect=None, why="")
        items = [dict(base, id=1, kind="move-row", issue=5, section="B", **{"from": "A"}),
                 dict(base, id=2, kind="add-row", issue=9, section="B", **{"from": None})]
        code, out, _, _ = Exact.apply_plan(self, items, FakeGitHub([], [iss(9, title="Nine")]), "1,2")
        self.assertEqual(code, 0, out)
        nine = f"| [#9](https://github.com/{REPO}/issues/9) | Nine | ⚪ — | |"
        with open(self.doc, encoding="utf-8", newline="") as handle:
            self.assertEqual(handle.read(), roadmap((heading("A", 1), [6]), (heading("B", 2), [8, 5]),
                                                    newline="\r").replace(row(5) + "\r", row(5) + "\r" + nine + "\r"))

    def mixed_endings(self):
        """B's last row ends LF; the lines around it end CRLF; A's row is the file's last line, with no ending."""
        head = roadmap((heading("C", 3), [7])).rstrip("\n") + "\n"
        text = head + "".join([heading("B", 2) + "\r\n", "\r\n", HEADER[0] + "\r\n", HEADER[1] + "\r\n",
                               row(8) + "\r\n", row(9) + "\n", "\r\n", heading("A", 1) + "\r\n", "\r\n",
                               HEADER[0] + "\r\n", HEADER[1] + "\r\n", row(5)])
        self.commit(text, D1)
        return text

    def read_raw(self):
        with open(self.doc, encoding="utf-8", newline="") as handle:
            return handle.read()

    def test_a_moved_row_with_no_ending_takes_the_ending_of_the_row_above(self):
        text = self.mixed_endings()
        item = dict(id=1, kind="move-row", side="doc", issue=5, section="B", milestone=None, expect=None, why="",
                    **{"from": "A"})
        code, out, _, _ = Exact.apply_plan(self, [item], FakeGitHub(), "1")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read_raw(), text.replace(row(9) + "\n", row(9) + "\n" + row(5) + "\n")[:-len(row(5))])

    def test_an_added_row_takes_the_ending_of_the_row_above(self):
        text = self.mixed_endings()
        item = dict(id=1, kind="add-row", side="doc", issue=12, section="B", milestone=None, expect=None, why="",
                    **{"from": None})
        code, out, _, _ = Exact.apply_plan(self, [item], FakeGitHub([], [iss(12, title="Twelve")]), "1")
        self.assertEqual(code, 0, out)
        added = f"| [#12](https://github.com/{REPO}/issues/12) | Twelve | ⚪ — | |\n"
        self.assertEqual(self.read_raw(), text.replace(row(9) + "\n", row(9) + "\n" + added))

    def test_only_a_version_without_the_roadmap_reads_as_empty(self):
        class FakeGit:
            rel = "roadmap.md"

            def __init__(self, error):
                self.error = error

            def versions(self):
                return [("b", D2), ("a", D1)]

            def text_at(self, sha):
                if sha == "b":
                    return roadmap((heading("A", 1), [5]))
                raise rm.ReadError(self.error)

        for error in ("fatal: path 'roadmap.md' does not exist in 'a'",
                      "fatal: path 'roadmap.md' exists on disk, but not in 'a'"):
            self.assertEqual(rm.History(FakeGit(error), REPO).placed(5), (D2, "b"), error)
        with self.assertRaisesRegex(rm.ReadError, "bad object"):
            rm.History(FakeGit("fatal: bad object a"), REPO)


class GhCalls(unittest.TestCase):
    """The exact gh calls behind each read and write; nothing here reaches GitHub."""

    def calls(self, method, *args, out="", **kwargs):
        seen = []

        def fake(*argv):
            seen.append(argv)
            return out

        with mock.patch.object(rm, "_gh", fake):
            result = method(*args, **kwargs)
        return seen, result

    def test_writes(self):
        writer = rm.GhWriter()
        self.assertEqual(self.calls(writer.create_milestone, REPO, "Now", out="12\n"), (
            [("api", "-X", "POST", f"repos/{REPO}/milestones", "-f", "title=Now", "--jq", ".number")], 12))
        self.assertEqual(self.calls(writer.update_milestone, REPO, 4, state="closed")[0], [
            ("api", "-X", "PATCH", f"repos/{REPO}/milestones/4", "-f", "state=closed", "--jq", ".number")])
        for number, value in ((None, "null"), (3, "3")):
            self.assertEqual(self.calls(writer.set_issue_milestone, REPO, 5, number)[0], [
                ("api", "-X", "PATCH", f"repos/{REPO}/issues/5", "-F", f"milestone={value}", "--jq", ".number")])

    def test_reads(self):
        github = rm.GitHub()
        self.assertEqual(self.calls(github.milestones, REPO, out='{"number":1,"title":"A","state":"open"}\n\n'), (
            [("api", "--paginate", f"repos/{REPO}/milestones?state=all&per_page=100",
              "--jq", ".[] | {number, title, state}")], [{"number": 1, "title": "A", "state": "open"}]))
        self.assertEqual(self.calls(github.milestone_issues, REPO, 3, out="5\n6\n"), (
            [("api", "--paginate", f"repos/{REPO}/issues?milestone=3&state=all&per_page=100",
              "--jq", ".[] | select(.pull_request == null) | .number")], [5, 6]))
        self.assertEqual(self.calls(github.visibility, REPO, out="PUBLIC\n"), (
            [("repo", "view", REPO, "--json", "visibility", "-q", ".visibility")], "PUBLIC"))

    def test_an_issue(self):
        github = rm.GitHub()
        node = {"number": 5, "state": "OPEN", "title": "T", "milestone": {"number": 2, "title": "B"},
                "timelineItems": {"nodes": [{"createdAt": D1}, {}, {"createdAt": D2}]}}
        with mock.patch.object(rm.tracker, "graphql", return_value={"repository": {"issue": node}}) as query:
            self.assertEqual(github.issue("acme/issues", 5), {"number": 5, "state": "OPEN", "title": "T",
                                                              "milestone": 2, "last_event": D2})
        self.assertEqual(query.call_args.kwargs, {"owner": "acme", "name": "issues", "number": 5})
        node.update(milestone=None, timelineItems={"nodes": [None]})
        with mock.patch.object(rm.tracker, "graphql", return_value={"repository": {"issue": node}}):
            self.assertEqual(github.issue(REPO, 5)["milestone"], None)
            self.assertEqual(github.issue(REPO, 5)["last_event"], None)
        with mock.patch.object(rm.tracker, "graphql", return_value={"repository": {"issue": None}}):
            with self.assertRaisesRegex(rm.ReadError, "^#5: no such issue in acme/issues$"):
                github.issue(REPO, 5)
        with mock.patch.object(rm.tracker, "graphql", side_effect=rm.tracker.BoardError("HTTP 502\nmore")):
            with self.assertRaisesRegex(rm.ReadError, "^#5: HTTP 502$"):
                github.issue(REPO, 5)

    def test_gh_itself(self):
        done = subprocess.CompletedProcess([], 0, stdout="out", stderr="")
        with mock.patch.object(rm.subprocess, "run", return_value=done) as run:
            self.assertEqual(rm._gh("api", "x"), "out")
        self.assertEqual(run.call_args, mock.call(["gh", "api", "x"], capture_output=True, text=True))
        for code, out, err, message in ((1, "", "HTTP 404\nmore", "^HTTP 404$"), (2, "only out", "", "^only out$")):
            failed = subprocess.CompletedProcess([], code, stdout=out, stderr=err)
            with mock.patch.object(rm.subprocess, "run", return_value=failed), \
                    self.assertRaisesRegex(rm.ReadError, message):
                rm._gh("api")
        with mock.patch.object(rm.subprocess, "run", side_effect=FileNotFoundError("no gh")), \
                self.assertRaisesRegex(rm.ReadError, "^gh: no gh$"):
            rm._gh("api")


class Safety(Case):
    def test_no_milestone_is_ever_deleted(self):  # 15
        source = (SCRIPTS / "roadmap_milestones.py").read_text(encoding="utf-8")
        self.assertNotIn("-X DELETE", source)
        self.assertNotIn('"DELETE"', source)
        self.assertFalse([name for name in dir(Writer) if "delete" in name.lower()])
        self.assertFalse([name for name in dir(rm.GhWriter) if "delete" in name.lower()])

    def test_document_edits_keep_every_other_byte(self):  # 16
        text = roadmap((heading("A", 1), [5, 6]), (heading("B", 2), [8]), newline="\r\n")
        self.commit(text, D1)
        github = FakeGitHub(TWO, [iss(5, 2, D2), iss(6, 1, D1), iss(8, 2, D1), iss(9, 2, D2, title="Nine")])
        _, plan, _ = self.plan(github)
        ids = ",".join(str(i["id"]) for i in plan["items"] if i["kind"] in ("move-row", "add-row"))
        code, out, _ = self.run_main("apply", "--plan", self.save(plan), "--items", ids, github=github)
        self.assertEqual(code, 0, out)
        moved = row(5) + "\r\n"
        added = f"| [#9](https://github.com/{REPO}/issues/9) | Nine | ⚪ — | |\r\n"
        expected = text.replace(moved, "").replace(row(8) + "\r\n", row(8) + "\r\n" + moved + added)
        with open(self.doc, encoding="utf-8", newline="") as handle:
            self.assertEqual(handle.read(), expected)

    def test_the_plan_reads_the_committed_roadmap(self):  # 17
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D1)
        self.doc.write_text(roadmap((heading("A", 1), []), (heading("B", 2), [5])), encoding="utf-8")
        code, plan, _ = self.plan(FakeGitHub(TWO, [iss(5, 1, D2)]))
        self.assertEqual((code, plan["items"]), (0, []))

    def test_a_roadmap_in_a_subfolder_reads_its_history(self):
        # Live run, 2026-10-05: a roadmap at docs/roadmap.md read as "no commit at HEAD".
        self.profile.write_text(profile_text().replace('file = "roadmap.md"', 'file = "docs/roadmap.md"'),
                                encoding="utf-8")
        (self.root / "docs").mkdir()
        self.doc = self.root / "docs" / "roadmap.md"
        self.commit(roadmap((heading("A", 1), [5]), (heading("B", 2), [])), D1)
        _, plan, err = self.plan(FakeGitHub(TWO, [iss(5, 2, D2)]))
        self.assertIsNotNone(plan, err)
        self.assertEqual([i["kind"] for i in plan["items"]], ["move-row"])

    def test_a_failed_read_is_exit_2_naming_the_issue(self):  # 18
        self.commit(roadmap((heading("A", 1), [5, 6])), D1)
        code, plan, err = self.plan(FakeGitHub(TWO, [iss(5, 1)], errors={6: rm.ReadError("#6: HTTP 502")}))
        self.assertEqual((code, plan), (2, None))
        self.assertIn("#6", err)

    def test_a_private_roadmap_never_reaches_a_public_tracker(self):  # 19
        self.profile.write_text(profile_text().replace(f'issues_repo = "{REPO}"',
                                                       f'issues_repo = "{REPO}"\npublic = true'), encoding="utf-8")
        self.commit(roadmap((heading("A"), [5])), D1)
        self.git("remote", "add", "origin", "git@github.com:acme/private-plans.git")
        code, plan, err = self.plan(FakeGitHub([], [iss(5)], visibility="PRIVATE"))
        self.assertEqual((code, plan), (2, None))
        self.assertIn("milestone titles would publish headings from acme/private-plans, which is not public, "
                      f"in {REPO}", err)
        code, plan, _ = self.plan(FakeGitHub([], [iss(5)], visibility="PUBLIC"))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
