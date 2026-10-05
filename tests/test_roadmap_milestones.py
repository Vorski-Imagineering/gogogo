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

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "gogogo" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import roadmap_milestones as rm  # noqa: E402
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
