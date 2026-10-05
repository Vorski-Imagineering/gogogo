#!/usr/bin/env python3
"""Tests for the two guards in board.py that must never be assumed working.

Both cover failures that are *invisible* in the raw `gh` flow this replaces: a
board read that came back short, and a card move that returned cleanly without
moving anything. Neither can be provoked against the real board, so `graphql`
is faked here.

    python3 -m unittest discover -s .claude/scripts -p 'test_*.py'
"""

import io
import json
import re
import subprocess
import unittest
from pathlib import Path
from argparse import Namespace
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "scripts"))
import tracker as board

# A profile-shaped configuration, set once for every test in this module.
board.ORG = "acme"
board.PROJECT_NUMBER = 2
board.DEFAULT_REPO = "acme/issues"
board.COLUMNS.clear()
board.COLUMNS.update({
    "queue": board.Column("Dev Priority", "queue"),
    "in_progress": board.Column("In progress", "tracker.columns.in_progress"),
    "In Dev": board.Column("In Dev", "stage"),
    "In Production": board.Column("In Production", "stage"),
})


def page(nodes, total, has_next=False, cursor="next"):
    return {
        "repositoryOwner": {
            "projectV2": {
                "items": {
                    "totalCount": total,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "nodes": nodes,
                }
            }
        }
    }


def labels(*names, total=None):
    return {"totalCount": len(names) if total is None else total, "nodes": [{"name": n} for n in names]}


def card(number, title, status, label_names=()):
    return {
        "id": f"ITEM_{number}",
        "type": "ISSUE",
        "content": {
            "__typename": "Issue",
            "number": number,
            "title": title,
            "state": "OPEN",
            "url": f"https://example.invalid/{number}",
            "repository": {"nameWithOwner": board.DEFAULT_REPO},
            "assignees": {"nodes": []},
            "labels": labels(*label_names),
        },
        "fieldValueByName": {"name": status},
    }


class ShortReadTests(unittest.TestCase):
    def test_pages_that_do_not_reach_totalcount_are_refused(self):
        """The exact shape of the old bug: two pages served for a 300-card board."""
        pages = [
            page([card(1, "a", "Dev Priority")], total=300, has_next=True),
            page([card(2, "b", "Dev Priority")], total=300, has_next=False),
        ]
        with mock.patch.object(board, "graphql", side_effect=pages):
            with self.assertRaises(board.BoardError) as caught:
                board.fetch_items()
        self.assertIn("read 2 cards but the board reports 300", str(caught.exception))

    def test_a_complete_read_is_returned(self):
        pages = [
            page([card(1, "a", "Dev Priority")], total=2, has_next=True),
            page([card(2, "b", "Backlog")], total=2, has_next=False),
        ]
        with mock.patch.object(board, "graphql", side_effect=pages):
            items = board.fetch_items()
        self.assertEqual([board.flatten(i)["number"] for i in items], [1, 2])

    def test_a_card_with_no_content_stays_representable(self):
        """Draft and deleted cards count toward totalCount; they must not crash."""
        nodes = [{"id": "ITEM_x", "type": "DRAFT_ISSUE", "content": None,
                  "fieldValueByName": None}]
        with mock.patch.object(board, "graphql", side_effect=[page(nodes, total=1)]):
            flat = board.flatten(board.fetch_items()[0])
        self.assertIsNone(flat["number"])
        self.assertIsNone(flat["status"])


class MoveReadBackTests(unittest.TestCase):
    META = {
        "project_id": "PVT_x",
        "title": "Example board",
        "total": 300,
        "status_field_id": "PVTSSF_x",
        "options": {"Dev Priority": "aaa", "In review": "bbb"},
    }

    def _run_move(self, status_after):
        """move #7 to In review, with the board reading back `status_after`."""
        before = {"id": "ITEM_7", "isArchived": False,
                  "project": {"number": 2}, "fieldValueByName": {"name": "Dev Priority"}}
        after = dict(before, fieldValueByName={"name": status_after} if status_after else None)
        args = Namespace(issue=7, to="In review", repo=board.DEFAULT_REPO, add_missing=False)

        with mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch.object(board, "issue_card",
                               side_effect=[{"issue": {}, "card": before},
                                            {"issue": {}, "card": after}]), \
             mock.patch.object(board, "graphql", return_value={}) as wrote:
            code = board.cmd_move(args)
        return code, wrote

    def test_a_write_the_board_does_not_confirm_fails_loudly(self):
        """The near-miss this guards: mutation returns clean, card never moved."""
        code, _ = self._run_move("Dev Priority")
        self.assertEqual(code, 2)

    def test_a_card_with_no_status_after_the_write_also_fails(self):
        code, _ = self._run_move(None)
        self.assertEqual(code, 2)

    def test_a_confirmed_move_succeeds_and_writes_the_resolved_ids(self):
        code, wrote = self._run_move("In review")
        self.assertEqual(code, 0)
        sent = wrote.call_args.kwargs
        self.assertEqual(sent["option"], "bbb")
        self.assertEqual(sent["field"], "PVTSSF_x")

    def test_move_to_a_column_the_board_does_not_have_is_refused(self):
        args = Namespace(issue=7, to="Shipped", repo=board.DEFAULT_REPO, add_missing=False)
        with mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch.object(board, "graphql") as wrote:
            with self.assertRaises(board.BoardError):
                board.cmd_move(args)
        wrote.assert_not_called()


class NeedsHumanGuardTests(unittest.TestCase):
    """A move to the needs-a-person column needs the issue's newest comment to say why (#84)."""
    META = dict(MoveReadBackTests.META,
                options=dict(MoveReadBackTests.META["options"], **{"Human!Help!": "hhh", "In progress": "ppp"}))
    STOP = "**Needs you:** x\n<!-- gogogo:stop v=1 reason=spec -->"

    def setUp(self):
        board.COLUMNS["needs_human"] = board.Column("Human!Help!", "tracker.columns.needs_human")

    def tearDown(self):
        board.COLUMNS.pop("needs_human", None)

    def _move(self, to, comment, status_after="Human!Help!", card=True, add_missing=False):
        before = {"id": "ITEM_7", "isArchived": False,
                  "project": {"number": 2}, "fieldValueByName": {"name": "Dev Priority"}}
        after = dict(before, fieldValueByName={"name": status_after})
        reads = [{"issue": {}, "card": before if card else None}, {"issue": {}, "card": after}]
        newest = (mock.patch.object(board, "newest_comment", side_effect=comment) if callable(comment)
                  or isinstance(comment, BaseException) else
                  mock.patch.object(board, "newest_comment", return_value=comment))
        err = io.StringIO()
        with mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch.object(board, "issue_card", side_effect=reads) as read, \
             mock.patch.object(board, "graphql", return_value={}) as wrote, \
             newest as asked, redirect_stderr(err):
            code = board.move_card(7, board.DEFAULT_REPO, to, add_missing=add_missing)
        return code, wrote, read, asked, err.getvalue()

    def test_a_stop_marker_is_a_reason_and_an_unknown_reason_or_version_is_not(self):
        self.assertTrue(board.has_reason(self.STOP))
        self.assertFalse(board.has_reason(self.STOP.replace("reason=spec", "reason=lunch")))
        self.assertFalse(board.has_reason(self.STOP.replace("v=1", "v=2")))

    def test_extra_keys_on_the_stop_marker_are_ignored(self):
        self.assertTrue(board.has_reason(
            "<!-- gogogo:stop v=1 reason=spec session=0d6f3c2a-8b1e-4f5d-9a7c-2e4b6d8f0a1c -->"))

    def test_a_quoted_template_or_no_comment_is_not_a_reason(self):
        self.assertFalse(board.has_reason("<!-- gogogo:stop v=1 reason=<hard-stop|decision> -->"))
        self.assertFalse(board.has_reason("<!-- gogogo:skip v=1 reason=<why> -->"))
        self.assertFalse(board.has_reason(""))

    def test_skip_and_auto_test_markers_are_reasons(self):
        self.assertTrue(board.has_reason("<!-- gogogo:skip v=1 reason=lint session=unknown -->"))
        verdict = "<!-- auto-test v1 run=r issue=7 verdict=FAIL build=b skill=s -->"
        self.assertTrue(board.has_reason(verdict))
        self.assertFalse(board.has_reason(verdict.replace("FAIL", "PASS")))

    def test_a_move_by_role_key_with_no_reason_is_refused_before_any_write(self):
        code, wrote, read, _, err = self._move("needs_human", "just a comment")
        self.assertEqual(code, 4)
        self.assertTrue(err.startswith("#7: refused:"), err)
        wrote.assert_not_called()
        read.assert_not_called()

    def test_a_move_by_column_name_with_no_reason_is_refused(self):
        for to in ("Human!Help!", "human!help!"):
            code, wrote, _, _, _ = self._move(to, "just a comment")
            self.assertEqual(code, 4, to)
            wrote.assert_not_called()
        # A trailing space fails the column lookup before the guard (Design 4), so it is refused
        # as an unknown column with nothing written (Approvals row 5).
        with mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch.object(board, "issue_card") as read, \
             mock.patch.object(board, "graphql") as wrote, \
             mock.patch.object(board, "newest_comment") as asked:
            with self.assertRaisesRegex(board.BoardError, "no column named 'human!help! '"):
                board.move_card(7, board.DEFAULT_REPO, "human!help! ")
        asked.assert_not_called()  # refused by resolve_option, before the guard
        wrote.assert_not_called()
        read.assert_not_called()

    def test_a_move_with_a_stop_marker_goes_through(self):
        code, wrote, _, _, _ = self._move("needs_human", self.STOP)
        self.assertEqual(code, 0)
        self.assertEqual(wrote.call_args.kwargs["option"], "hhh")

    def test_a_failed_comment_read_writes_nothing(self):
        with mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch.object(board, "issue_card") as read, \
             mock.patch.object(board, "graphql") as wrote, \
             mock.patch.object(board, "newest_comment", side_effect=board.BoardError("partial data")):
            with self.assertRaises(board.BoardError):
                board.move_card(7, board.DEFAULT_REPO, "needs_human")
        wrote.assert_not_called()
        read.assert_not_called()

    def test_other_columns_never_read_the_comment(self):
        code, _, _, asked, _ = self._move("in_progress", AssertionError("read"), status_after="In progress")
        self.assertEqual(code, 0)
        asked.assert_not_called()

    def test_a_defaulted_needs_human_guards_only_the_role_key(self):
        # No needs_human in the profile: it shares the in_progress column (#87). Starting work
        # on an issue must not need a stop marker; handing it back still does.
        saved = board.COLUMNS.get("in_progress")
        board.COLUMNS["needs_human"] = board.Column("In progress", "tracker.columns.in_progress")
        board.COLUMNS["in_progress"] = board.Column("In progress", "tracker.columns.in_progress")
        try:
            for to in ("in_progress", "In progress"):
                code, _, _, asked, _ = self._move(to, AssertionError("read"), status_after="In progress")
                self.assertEqual(code, 0, to)
                asked.assert_not_called()
            code, wrote, _, _, _ = self._move("needs_human", "just a comment", status_after="In progress")
            self.assertEqual(code, 4)
            wrote.assert_not_called()
        finally:
            board.COLUMNS["in_progress"] = saved

    def test_no_needs_human_in_the_profile_means_no_guard(self):
        board.COLUMNS.pop("needs_human")
        code, _, _, asked, _ = self._move("Human!Help!", AssertionError("read"))
        self.assertEqual(code, 0)
        asked.assert_not_called()

    def test_a_refused_move_adds_no_card(self):
        code, wrote, _, _, _ = self._move("needs_human", "just a comment", card=False, add_missing=True)
        self.assertEqual(code, 4)
        self.assertNotIn(board.ADD_ITEM_MUTATION, [c.args[0] for c in wrote.call_args_list if c.args])
        wrote.assert_not_called()

    def test_marker_fields_are_parsed_strictly(self):
        has = board.has_reason
        self.assertFalse(has("<!-- gogogo:stop junk -->"))                  # a token with no `=`
        self.assertTrue(has("<!-- auto-test v1 build=a=b verdict=FAIL -->"))  # `=` inside a value
        self.assertFalse(has("<!-- gogogo:skip v=1 reason=<lint -->"))
        self.assertFalse(has("<!-- gogogo:skip v=1 reason=lint> -->"))
        self.assertFalse(has("<!-- auto-test v1 build= verdict=FAIL -->"))  # an empty value
        self.assertTrue(has("<!-- auto-test v1 run=r verdict=NEEDS_HUMAN -->"))

    def test_a_later_marker_counts_after_an_unreadable_one(self):
        for first in ("<!-- gogogo:stop junk -->", "<!-- gogogo:stop v=1 reason=<hard-stop|decision> -->"):
            self.assertTrue(board.has_reason(first + "\n" + self.STOP), first)

    def test_newest_comment_splits_the_repo_once_and_reads_a_null_body_as_empty(self):
        answer = {"repository": {"issue": {"comments": {"nodes": [{"body": None}]}}}}
        with mock.patch.object(board, "graphql", return_value=answer) as asked:
            self.assertEqual(board.newest_comment(7, "acme/issues/x"), "")
        self.assertEqual(asked.call_args.kwargs["name"], "issues/x")

    def test_the_move_command_reaches_move_card(self):
        with mock.patch.object(sys, "argv", ["tracker.py", "move", "7", "--to", "needs_human"]), \
             mock.patch.object(board, "configure"), \
             mock.patch.object(board, "move_card", return_value=4) as moved:
            self.assertEqual(board.main(), 4)
        self.assertEqual(moved.call_args.args[:3], (7, board.DEFAULT_REPO, "needs_human"))

    def test_the_stop_reasons_match_review_stats(self):
        import review_stats
        self.assertEqual(board.STOP_REASONS, review_stats.STOPS)

    def test_newest_comment_of_a_missing_issue_is_a_board_error(self):
        with mock.patch.object(board, "graphql", return_value={"repository": {"issue": None}}):
            with self.assertRaisesRegex(board.BoardError, "does not exist"):
                board.newest_comment(99999, "acme/issues")

    def test_newest_comment_reads_the_last_comment_or_nothing(self):
        def answer(nodes):
            return {"repository": {"issue": {"comments": {"nodes": nodes}}}}
        with mock.patch.object(board, "graphql", return_value=answer([{"body": "b"}])) as asked:
            self.assertEqual(board.newest_comment(7, "acme/issues"), "b")
        self.assertEqual(asked.call_args.kwargs, {"owner": "acme", "name": "issues", "number": 7})
        with mock.patch.object(board, "graphql", return_value=answer([])):
            self.assertEqual(board.newest_comment(7, "acme/issues"), "")

    def test_the_contract_names_the_refusal(self):
        text = (Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "references"
                / "tracker-contract.md").read_text(encoding="utf-8")
        section = text.split("## The shared tool", 1)[1].split("\n## ", 1)[0]
        self.assertIn("needs_human", section)
        self.assertRegex(section, r"refuses a move to `tracker\.columns\.needs_human`[^.]*exiting 4")


class MoveFromTests(unittest.TestCase):
    """`move --from`: refuse, writing nothing, when the card has gone elsewhere (#101)."""
    META = dict(MoveReadBackTests.META,
                options={"Dev Ready": "rrr", "In progress": "ppp", "Done": "ddd"})

    def _move(self, current, frm="Dev Ready", to="In progress", card=True, add_missing=False,
              status_after="In progress"):
        before = {"id": "ITEM_7", "isArchived": False, "project": {"number": 2},
                  "fieldValueByName": {"name": current} if current else None}
        after = dict(before, fieldValueByName={"name": status_after})
        reads = [{"issue": {}, "card": before if card else None}, {"issue": {}, "card": after}]
        err = io.StringIO()
        with mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch.object(board, "issue_card", side_effect=reads), \
             mock.patch.object(board, "graphql", return_value={}) as wrote, \
             redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = board.move_card(7, board.DEFAULT_REPO, to, add_missing=add_missing, expect_from=frm)
        sent = [c.args[0] for c in wrote.call_args_list if c.args]
        return code, sent, err.getvalue()

    def test_a_card_where_it_was_expected_moves(self):
        code, sent, _ = self._move("Dev Ready")
        self.assertEqual(code, 0)
        self.assertEqual(sent, [board.SET_FIELD_MUTATION])

    def test_a_card_elsewhere_is_refused_with_nothing_written(self):
        code, sent, err = self._move("In progress")
        self.assertEqual(code, 3)
        self.assertIn("In progress", err)
        self.assertIn("Dev Ready", err)
        self.assertEqual(err.strip(), "#7 is in In progress, not Dev Ready; not moved")
        self.assertNotIn(board.SET_FIELD_MUTATION, sent)
        self.assertNotIn(board.ADD_ITEM_MUTATION, sent)
        self.assertEqual(sent, [])

    def test_the_comparison_ignores_case(self):
        code, sent, _ = self._move("dev ready")
        self.assertEqual(code, 0)
        self.assertEqual(sent, [board.SET_FIELD_MUTATION])

    def test_from_takes_a_role_key(self):
        code, sent, _ = self._move("In progress", frm="in_progress", to="Done", status_after="Done")
        self.assertEqual(code, 0)
        self.assertEqual(sent, [board.SET_FIELD_MUTATION])

    def test_from_a_column_the_board_lacks_raises_before_any_read(self):
        with mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch.object(board, "issue_card") as read, \
             mock.patch.object(board, "graphql") as wrote:
            with self.assertRaisesRegex(board.BoardError, "No Such Column"):
                board.move_card(7, board.DEFAULT_REPO, "In progress", expect_from="No Such Column")
        read.assert_not_called()
        wrote.assert_not_called()

    def test_a_card_with_no_column_is_refused(self):
        code, sent, err = self._move(None)
        self.assertEqual(code, 3)
        self.assertEqual(sent, [])
        self.assertEqual(err.strip(), "#7 is in no column, not Dev Ready; not moved")

    def test_add_missing_with_from_and_no_card_adds_nothing(self):
        code, sent, err = self._move(None, card=False, add_missing=True)
        self.assertEqual(code, 3)
        self.assertEqual(sent, [])
        self.assertEqual(err.strip(), "#7 is in not on the board, not Dev Ready; not moved")

    def test_the_from_option_reaches_move_card(self):
        argv = ["tracker.py", "move", "7", "--from", "queue", "--to", "in_progress"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(board, "configure"), \
             mock.patch.object(board, "move_card", return_value=3) as moved:
            self.assertEqual(board.main(), 3)
        self.assertEqual(moved.call_args.kwargs.get("expect_from"), "queue")

    def test_move_help_names_from_and_that_it_only_narrows_the_gap(self):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["tracker.py", "move", "--help"]), \
             mock.patch.object(board, "configure"), redirect_stdout(out):
            with self.assertRaises(SystemExit):
                board.main()
        text = " ".join(out.getvalue().split())
        self.assertIn("[--from COLUMN]", text)
        self.assertRegex(text, r"--from COLUMN profile role key or column name; exit 3.* It narrows, "
                               r"but does not close, the gap between reading a card and moving it --to ")

    def test_the_help_names_from_and_its_exit_code(self):
        doc = board.__doc__
        self.assertRegex(doc, r'move <issue> \[--from "<column>"\] --to')
        self.assertRegex(doc, r"3 `show --expect` or `move --from`")

    def test_the_contract_move_row_names_from_and_exit_3(self):
        text = (Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "references"
                / "tracker-contract.md").read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| `move "))
        self.assertIn("--from", row)
        self.assertRegex(row.rsplit("|", 2)[1], r"\b3\b")


def issue_page(issues, has_next=False, cursor="next"):
    return {
        "repository": {
            "issues": {
                "totalCount": len(issues),
                "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                "nodes": issues,
            }
        }
    }


def issue_node(number, title, status, *, item_id=None, archived=False, project=2, label_names=()):
    return {
        "number": number,
        "title": title,
        "state": "OPEN",
        "url": f"https://example.invalid/{number}",
        "repository": {"nameWithOwner": board.DEFAULT_REPO},
        "assignees": {"nodes": []},
        "labels": labels(*label_names),
        "projectItems": {
            "nodes": [{
                "id": item_id or f"ITEM_{number}",
                "isArchived": archived,
                "project": {"number": project},
                "fieldValueByName": {"name": status} if status else None,
            }]
        },
    }


class IssueSideCrossCheckTests(unittest.TestCase):
    """The miss a totalCount guard structurally cannot catch.

    An issue sat in Dev Priority, unarchived, while `list` read
    "369 of 369" and never showed it: GitHub's project-side index dropped the
    item from the nodes *and* from the count, so the two agreed with each other
    and were both wrong. Only a second, independent index finds that.
    """

    def test_a_card_the_project_index_omits_is_recovered(self):
        board_side = page([card(1, "listed", "Dev Priority")], total=1)
        issue_side = issue_page([
            issue_node(1, "listed", "Dev Priority"),
            issue_node(410, "invisible", "Dev Priority"),
        ])
        with mock.patch.object(board, "graphql", side_effect=[board_side, issue_side]):
            missing = board.cards_the_board_did_not_list(
                [board.flatten(i) for i in board.fetch_items()], board.DEFAULT_REPO
            )
        self.assertEqual([c["number"] for c in missing], [410])
        self.assertEqual(missing[0]["status"], "Dev Priority")

    def test_the_count_guard_alone_would_have_passed_this(self):
        """Names why the second read exists: the first one is satisfied here."""
        board_side = page([card(1, "listed", "Dev Priority")], total=1)
        with mock.patch.object(board, "graphql", side_effect=[board_side]):
            board.fetch_items()  # does not raise — the board agrees with itself

    def test_an_archived_card_is_not_reported_as_missing(self):
        issue_side = issue_page([issue_node(9, "archived", "Done", archived=True)])
        with mock.patch.object(board, "graphql", side_effect=[issue_side]):
            missing = board.cards_the_board_did_not_list([], board.DEFAULT_REPO)
        self.assertEqual(missing, [])

    def test_a_card_on_another_project_is_not_reported_as_missing(self):
        issue_side = issue_page([issue_node(9, "elsewhere", "Todo", project=3)])
        with mock.patch.object(board, "graphql", side_effect=[issue_side]):
            missing = board.cards_the_board_did_not_list([], board.DEFAULT_REPO)
        self.assertEqual(missing, [])

    def test_an_agreeing_board_recovers_nothing(self):
        board_side = page([card(1, "listed", "Dev Priority")], total=1)
        issue_side = issue_page([issue_node(1, "listed", "Dev Priority")])
        with mock.patch.object(board, "graphql", side_effect=[board_side, issue_side]):
            missing = board.cards_the_board_did_not_list(
                [board.flatten(i) for i in board.fetch_items()], board.DEFAULT_REPO
            )
        self.assertEqual(missing, [])

    def test_the_issue_side_pages(self):
        pages = [
            issue_page([issue_node(1, "a", "Dev Priority")], has_next=True),
            issue_page([issue_node(2, "b", "Dev Priority")]),
        ]
        with mock.patch.object(board, "graphql", side_effect=pages):
            missing = board.cards_the_board_did_not_list([], board.DEFAULT_REPO)
        self.assertEqual([c["number"] for c in missing], [1, 2])

    def test_list_puts_recovered_cards_where_the_queue_is_read_from(self):
        """A recovered card is newest-added, so it belongs at the front."""
        board_side = page([card(1, "old", "Dev Priority")], total=1)
        issue_side = issue_page([
            issue_node(1, "old", "Dev Priority"),
            issue_node(412, "new and invisible", "Dev Priority"),
        ])
        args = Namespace(status="Dev Priority", open_only=True, issues_only=False,
                         json=True, repo=board.DEFAULT_REPO, no_crosscheck=False)
        with mock.patch.object(board, "graphql", side_effect=[board_side, issue_side]), \
             mock.patch.object(board, "board_meta",
                               return_value={"options": {"Dev Priority": "a"}}), \
             mock.patch("builtins.print") as printed:
            code = board.cmd_list(args)
        self.assertEqual(code, 0)
        payload = json.loads(printed.call_args_list[0].args[0])
        self.assertEqual([c["number"] for c in payload], [412, 1])

    def test_no_crosscheck_skips_the_second_read_entirely(self):
        board_side = page([card(1, "old", "Dev Priority")], total=1)
        args = Namespace(status=None, open_only=False, issues_only=False,
                         json=True, repo=board.DEFAULT_REPO, no_crosscheck=True)
        with mock.patch.object(board, "graphql", side_effect=[board_side]) as asked, \
             mock.patch("builtins.print"):
            board.cmd_list(args)
        self.assertEqual(asked.call_count, 1, "the issue side must not be read")


class ProfileColumnTests(unittest.TestCase):
    """The columns come from the profile; keys are roles, values are live names."""

    META = {"options": {"Dev Priority": "o1", "In progress": "o2", "In Dev": "o3", "In Production": "o4"}}

    def test_column_resolves_role_keys_and_passes_names_through(self):
        self.assertEqual(board.column("in_progress"), "In progress")
        self.assertEqual(board.column("queue"), "Dev Priority")
        self.assertEqual(board.column("Some Other Column"), "Some Other Column")

    def test_fields_check_exits_2_naming_the_missing_column(self):
        meta = {"options": {k: v for k, v in self.META["options"].items() if k != "In Dev"}}
        with mock.patch.object(board, "board_meta", return_value={**meta, "title": "t", "total": 0,
                                                                  "project_id": "p", "status_field_id": "f"}), \
             mock.patch("builtins.print") as printed:
            self.assertEqual(board.cmd_fields(Namespace(check=True)), 2)
        self.assertIn("'In Dev'", " ".join(str(c) for c in printed.call_args_list))

    def test_fields_check_passes_when_every_profile_column_exists(self):
        with mock.patch.object(board, "board_meta", return_value={**self.META, "title": "t", "total": 0,
                                                                  "project_id": "p", "status_field_id": "f"}), \
             mock.patch("builtins.print"):
            self.assertEqual(board.cmd_fields(Namespace(check=True)), 0)

    def _show(self, current, expect):
        found = {"issue": {"title": "t", "state": "OPEN", "url": "u"},
                 "card": {"id": "I", "isArchived": False, "fieldValueByName": {"name": current}}}
        with mock.patch.object(board, "issue_card", return_value=found), \
             mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch("builtins.print"):
            return board.cmd_show(Namespace(issue=7, repo=board.DEFAULT_REPO, expect=expect))

    def test_show_expect_exit_codes(self):
        self.assertEqual(self._show("In progress", "in_progress"), 0)
        self.assertEqual(self._show("In Dev", "in_progress"), 3)
        self.assertEqual(self._show("In Dev", "In Dev"), 0)

    def test_move_accepts_a_role_key(self):
        meta = {**self.META, "project_id": "P", "status_field_id": "F"}
        before = {"issue": {}, "card": {"id": "ITEM", "fieldValueByName": {"name": "Dev Priority"}}}
        after = {"issue": {}, "card": {"id": "ITEM", "fieldValueByName": {"name": "In progress"}}}
        with mock.patch.object(board, "board_meta", return_value=meta), \
             mock.patch.object(board, "issue_card", side_effect=[before, after]), \
             mock.patch.object(board, "graphql", return_value={}) as wrote, \
             mock.patch("builtins.print"):
            code = board.cmd_move(Namespace(issue=7, to="in_progress", repo=board.DEFAULT_REPO, add_missing=False))
        self.assertEqual(code, 0)
        self.assertEqual(wrote.call_args.kwargs["option"], "o2")


class ConfigureTests(unittest.TestCase):
    """configure() reads the board from the profile, and refuses without one."""

    def setUp(self):
        self.saved = (board.ORG, board.PROJECT_NUMBER, board.DEFAULT_REPO, dict(board.COLUMNS))

    def tearDown(self):
        board.ORG, board.PROJECT_NUMBER, board.DEFAULT_REPO = self.saved[:3]
        board.COLUMNS.clear()
        board.COLUMNS.update(self.saved[3])

    def write(self, text):
        import tempfile
        tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        tmp.write(text)
        tmp.close()
        return tmp.name

    def test_board_repo_and_columns_come_from_the_profile(self):
        path = self.write("""+++
profile = 1
[tracker]
project_owner = "someone"
project_number = 7
issues_repo = "someone/tracker"
queue = "Ready"
columns = { in_progress = "Doing", back_to_queue = "Ready" }
[[stages]]
code_is = "merged"
column = "Merged"
+++
""")
        board.configure(path)
        self.assertEqual((board.ORG, board.PROJECT_NUMBER, board.DEFAULT_REPO), ("someone", 7, "someone/tracker"))
        self.assertEqual(board.column("queue"), "Ready")
        self.assertEqual(board.column("in_progress"), "Doing")
        self.assertEqual(board.column("Merged"), "Merged")
        self.assertEqual(sorted({c.name for c in board.COLUMNS.values()}), ["Doing", "Merged", "Ready"])

    def test_the_needs_human_column_is_a_role_and_a_required_column(self):
        # gogogo#26: skills pass the role key (the name has "!", which an
        # interactive shell expands), and a board lacking it is named.
        path = self.write("""+++
profile = 1
[tracker]
project_owner = "someone"
project_number = 7
issues_repo = "someone/tracker"
columns = { in_progress = "Doing", needs_human = "Human!Help!" }
+++
""")
        board.configure(path)
        self.assertEqual(board.column("needs_human"), "Human!Help!")
        self.assertEqual(board.missing_columns({"options": ["Doing"]}), ["Human!Help!"])
        self.assertEqual(board.missing_columns({"options": ["Doing", "human!help!"]}), [])

    def test_a_profile_without_needs_human_uses_the_in_progress_column(self):
        # gogogo#87: the default profile_check.effective() fills in, so a move to
        # needs_human has a column rather than an unknown role.
        path = self.write("""+++
profile = 1
[tracker]
project_owner = "someone"
project_number = 7
issues_repo = "someone/tracker"
columns = { in_progress = "In progress" }
+++
""")
        board.configure(path)
        self.assertEqual(board.COLUMNS["needs_human"].name, "In progress")

    def test_a_profile_without_a_board_is_refused(self):
        path = self.write('+++\nprofile = 1\n[tracker]\nissues_repo = "a/b"\n+++\n')
        with self.assertRaises(board.ProfileMissing):
            board.configure(path)

    def test_no_profile_is_refused(self):
        with self.assertRaises(board.ProfileMissing):
            board.configure("/nonexistent/dev-process.md")


class GraphqlErrorTests(unittest.TestCase):
    def test_errors_alongside_partial_data_are_not_treated_as_success(self):
        result = mock.Mock(returncode=0, stdout='{"data":{"x":1},"errors":[{"message":"boom"}]}')
        with mock.patch.object(board.subprocess, "run", return_value=result):
            with self.assertRaises(board.BoardError) as caught:
                board.graphql("query {}")
        self.assertIn("boom", str(caught.exception))

    def test_a_non_transient_failure_is_not_retried(self):
        result = mock.Mock(returncode=1, stdout="", stderr="Could not resolve to a Project")
        with mock.patch.object(board.subprocess, "run", return_value=result) as run:
            with self.assertRaises(board.BoardError):
                board.graphql("query {}")
        self.assertEqual(run.call_count, 1)

    def test_int_variables_use_ghs_typed_flag(self):
        result = mock.Mock(returncode=0, stdout='{"data":{}}')
        with mock.patch.object(board.subprocess, "run", return_value=result) as run:
            board.graphql("query {}", number=2, after="123")
        cmd = run.call_args.args[0]
        self.assertIn("-F", cmd)
        self.assertEqual(cmd[cmd.index("-F") + 1], "number=2")
        # A digit-only cursor must stay a String, so it goes through -f.
        self.assertIn("after=123", cmd)
        self.assertEqual(cmd[cmd.index("after=123") - 1], "-f")


class LabelTests(unittest.TestCase):
    """Every card carries its labels, from both reads, so auto-dev can tell a
    labelled queue card from one dragged in by hand (gogogo#60)."""

    META = {"options": {"Dev Priority": "a"}}

    def test_flatten_carries_labels(self):
        self.assertEqual(board.flatten(card(1, "a", "Dev Priority", ("dev ready", "bug")))["labels"],
                         ["dev ready", "bug"])
        pr = {"id": "PR_1", "type": "PULL_REQUEST",
              "content": {"__typename": "PullRequest", "number": 5, "title": "p", "state": "OPEN",
                          "url": "u", "repository": {"nameWithOwner": board.DEFAULT_REPO}},
              "fieldValueByName": {"name": "Dev Priority"}}
        draft = {"id": "D_1", "type": "DRAFT_ISSUE", "content": {"__typename": "DraftIssue", "title": "d"},
                 "fieldValueByName": None}
        self.assertEqual(board.flatten(pr)["labels"], [])
        self.assertEqual(board.flatten(draft)["labels"], [])
        self.assertEqual(board.flatten({"id": "X", "type": "ISSUE", "content": None})["labels"], [])

    def test_flatten_carries_when_the_card_entered_its_column_and_why_it_closed(self):
        aged = card(1, "a", "Released")
        aged["fieldValueByName"]["updatedAt"] = "2026-10-01T09:00:00Z"
        aged["content"]["stateReason"] = "NOT_PLANNED"
        flat = board.flatten(aged)
        self.assertEqual(flat["status_since"], "2026-10-01T09:00:00Z")
        self.assertEqual(flat["state_reason"], "NOT_PLANNED")
        plain = board.flatten(card(2, "b", "Released"))
        self.assertIsNone(plain["status_since"])
        self.assertIsNone(plain["state_reason"])
        self.assertIsNone(board.flatten({"id": "X", "type": "ISSUE", "content": None})["status_since"])

    def test_both_reads_ask_for_the_column_time(self):
        for query in (board.ITEMS_QUERY, board.REPO_ISSUE_CARDS_QUERY):
            self.assertRegex(query, r"ProjectV2ItemFieldSingleSelectValue \{ name updatedAt \}")
        self.assertIn("stateReason", board.ITEMS_QUERY)

    def test_issue_side_cards_carry_labels(self):
        issue_side = issue_page([issue_node(7, "seen", "Dev Priority", label_names=("dev ready",))])
        with mock.patch.object(board, "graphql", side_effect=[issue_side]):
            cards = board.issue_side_cards(board.DEFAULT_REPO)
        self.assertEqual(cards[0]["labels"], ["dev ready"])

    def list_queue(self, board_nodes, issue_nodes):
        with mock.patch.object(board, "graphql",
                               side_effect=[page(board_nodes, total=len(board_nodes)), issue_page(issue_nodes)]), \
             mock.patch.object(board, "board_meta", return_value=self.META):
            cards, _, _ = board.list_cards(status="Dev Priority", repo=board.DEFAULT_REPO)
        return {c["number"]: c["labels"] for c in cards}

    def test_the_queue_read_keeps_both_halves_and_their_labels(self):
        got = self.list_queue([card(1, "a", "Dev Priority", ("dev ready",)), card(2, "b", "Dev Priority")],
                              [issue_node(1, "a", "Dev Priority", label_names=("dev ready",)),
                               issue_node(2, "b", "Dev Priority")])
        self.assertEqual(got, {1: ["dev ready"], 2: []})

    def test_a_recovered_card_keeps_its_label(self):
        got = self.list_queue([card(1, "a", "Dev Priority")],
                              [issue_node(1, "a", "Dev Priority"),
                               issue_node(9, "invisible", "Dev Priority", label_names=("dev ready",))])
        self.assertEqual(got[9], ["dev ready"])

    def test_truncated_labels_refuse_the_read(self):
        content = {"number": 12, "labels": labels(*[f"l{i}" for i in range(20)], total=25)}
        with self.assertRaises(board.BoardError) as raised:
            board.issue_labels(content)
        self.assertIn("#12", str(raised.exception))
        truncated = card(12, "many", "Dev Priority")
        truncated["content"]["labels"] = content["labels"]
        with mock.patch.object(board, "configure"), \
             mock.patch.object(board, "graphql", side_effect=[page([truncated], total=1)]), \
             mock.patch.object(board.sys, "argv", ["tracker.py", "list", "--no-crosscheck"]), \
             mock.patch("sys.stderr"), mock.patch("builtins.print"):
            self.assertEqual(board.main(), 2)

    def test_list_json_prints_labels_on_every_card(self):
        args = Namespace(status=None, open_only=False, issues_only=False,
                         json=True, repo=board.DEFAULT_REPO, no_crosscheck=True)
        nodes = [card(1, "a", "Dev Priority", ("dev ready",)), card(2, "b", "Dev Priority")]
        with mock.patch.object(board, "graphql", side_effect=[page(nodes, total=2)]), \
             mock.patch("builtins.print") as printed:
            board.cmd_list(args)
        payload = json.loads(printed.call_args_list[0].args[0])
        self.assertEqual([c["labels"] for c in payload], [["dev ready"], []])


class ColumnGuardTests(unittest.TestCase):
    """A column the board lacks is refused, never read as an empty column."""

    META = {"options": {"Dev Priority": "a", "Done": "b"}}

    def test_list_by_a_missing_column_raises_before_reading(self):
        with mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch.object(board, "fetch_items") as fetched:
            with self.assertRaises(board.BoardError):
                board.list_cards(status="in-dev")
        fetched.assert_not_called()

    def test_show_expect_a_missing_column_raises_instead_of_exit_3(self):
        args = Namespace(issue=7, repo=board.DEFAULT_REPO, expect="in-production")
        with mock.patch.object(board, "board_meta", return_value=self.META), \
             mock.patch.object(board, "issue_card") as read:
            with self.assertRaises(board.BoardError):
                board.cmd_show(args)
        read.assert_not_called()

    def test_a_crash_exits_2_not_1(self):
        """Exit 1 means "not on the board" to a caller; a traceback must not say that."""
        # configure() is patched so main() never reads a real profile: a repo's own
        # profile would otherwise reconfigure the module for every later test.
        with mock.patch.object(board, "configure"), \
             mock.patch.object(board, "issue_card", side_effect=KeyError("data")), \
             mock.patch.object(board.sys, "argv", ["board.py", "show", "7"]), \
             mock.patch("sys.stderr"):
            self.assertEqual(board.main(), 2)


class KeepingTheBoardCurrent(unittest.TestCase):
    """views and tidy: what keeps the board right between runs."""

    def test_only_views_that_filter_to_open_hide_closed_issues(self):
        views = [{"name": "none", "filter": None}, {"name": "empty", "filter": ""},
                 {"name": "label", "filter": "label:bug"}, {"name": "open", "filter": "label:bug is:open"},
                 {"name": "not closed", "filter": "-is:closed"}, {"name": "reopen", "filter": "is:opened"}]
        showing = [v["name"] for v in board.views_showing_closed(views)]
        self.assertEqual(showing, ["none", "empty", "label", "reopen"])

    def _hide_closed(self, read_back):
        before = [
            {"id": "V1", "number": 1, "name": "Table", "filter": None},
            {"id": "V2", "number": 2, "name": "Board", "filter": "label:bug"},
            {"id": "V3", "number": 3, "name": "Done", "filter": "is:open"}]
        with mock.patch.object(board, "board_views", side_effect=[before, read_back]), \
             mock.patch.object(board, "graphql", return_value={}) as wrote, \
             mock.patch("builtins.print"):
            code = board.cmd_views(Namespace(hide_closed=True))
        return code, [c.kwargs for c in wrote.call_args_list]

    def test_hide_closed_adds_is_open_and_keeps_the_existing_filter(self):
        code, writes = self._hide_closed([{"name": "x", "filter": "is:open"}])
        self.assertEqual(code, 0)
        self.assertEqual(writes, [{"view": "V1", "filter": "is:open"},
                                  {"view": "V2", "filter": "label:bug is:open"}])

    def test_hide_closed_fails_when_the_board_does_not_read_back_hidden(self):
        code, _ = self._hide_closed([{"name": "Table", "filter": ""}])
        self.assertEqual(code, 2)

    def _untidy(self):
        def item(n, state, status, kind="Issue", reason=None):
            return {"id": f"I{n}", "content": {"__typename": kind, "number": n, "title": "t",
                                               "state": state, "stateReason": reason,
                                               "repository": {"nameWithOwner": "acme/issues"}},
                    "fieldValueByName": {"name": status} if status else None}
        items = [item(1, "CLOSED", "Released", reason="COMPLETED"), item(2, "CLOSED", "Done"),
                 item(3, "OPEN", "Backlog"), item(4, "CLOSED", "In progress", kind="PullRequest"),
                 item(5, "CLOSED", None), item(8, "CLOSED", "Released", reason="NOT_PLANNED")]
        issues = [
            {"number": 3, "title": "on board", "repository": {"nameWithOwner": "acme/issues"},
             "projectItems": {"nodes": [{"project": {"number": 2}}]}},
            {"number": 6, "title": "on another board", "repository": {"nameWithOwner": "acme/issues"},
             "projectItems": {"nodes": [{"project": {"number": 9}}]}},
            {"number": 7, "title": "on no board", "repository": {"nameWithOwner": "acme/issues"},
             "projectItems": {"nodes": []}},
        ]
        with mock.patch.object(board, "fetch_items", return_value=items), \
             mock.patch.object(board, "open_issues", return_value=iter(issues)):
            return board.untidy("acme/issues")

    def test_untidy_finds_closed_issues_outside_done_and_open_issues_off_the_board(self):
        closed, archive, off_board = self._untidy()
        self.assertEqual([c["number"] for c in closed], [1, 5])
        self.assertEqual([c["number"] for c in archive], [8])
        self.assertEqual([i["number"] for i in off_board], [6, 7])

    def test_untidy_archives_not_planned_and_files_completed_under_done(self):
        """Done means work that was done; an issue closed as not planned leaves the board."""
        closed, archive, _ = self._untidy()
        self.assertNotIn(8, [c["number"] for c in closed])
        self.assertEqual([c["state_reason"] for c in archive], ["NOT_PLANNED"])
        self.assertIn("COMPLETED", [c["state_reason"] for c in closed])

    def test_tidy_apply_archives_not_planned_and_moves_completed_to_done(self):
        done = [{"number": 1, "repo": "acme/issues", "status": "Released", "item_id": "I1"}]
        archive = [{"number": 8, "repo": "acme/issues", "status": "Released", "item_id": "I8"}]
        with mock.patch.object(board, "untidy", return_value=(done, archive, [])), \
             mock.patch.object(board, "board_meta", return_value={"project_id": "PVT_x", "options": {}}), \
             mock.patch.object(board, "move_card", return_value=0) as moved, \
             mock.patch.object(board, "archive_card", return_value=0) as archived, \
             mock.patch("builtins.print"):
            code = board.cmd_tidy(Namespace(repo="acme/issues", apply=True))
        self.assertEqual(code, 0)
        self.assertEqual([c.args[0]["number"] for c in archived.call_args_list], [8])
        self.assertEqual([c.args[:3] for c in moved.call_args_list], [(1, "acme/issues", board.DONE_COLUMN)])

    def test_tidy_lists_the_archive_without_apply_and_writes_nothing(self):
        archive = [{"number": 8, "repo": "acme/issues", "status": "Released", "item_id": "I8"}]
        out = io.StringIO()
        with mock.patch.object(board, "untidy", return_value=([], archive, [])), \
             mock.patch.object(board, "archive_card") as archived, \
             mock.patch.object(board, "move_card") as moved, \
             mock.patch("sys.stdout", out):
            self.assertEqual(board.cmd_tidy(Namespace(repo="acme/issues", apply=False)), 0)
        archived.assert_not_called()
        moved.assert_not_called()
        self.assertIn("acme/issues#8", out.getvalue())
        self.assertIn("archive", out.getvalue())

    def test_archive_card_archives_the_item_and_reports_a_failure(self):
        with mock.patch.object(board, "graphql", return_value={"archiveProjectV2Item": {"item": {"id": "I8"}}}) as wrote, \
             mock.patch("builtins.print"):
            self.assertEqual(board.archive_card({"number": 8, "repo": "a/b", "item_id": "I8"}, {"project_id": "PVT_x"}), 0)
        self.assertEqual(wrote.call_args.kwargs, {"project": "PVT_x", "item": "I8"})
        self.assertIn("archiveProjectV2Item", wrote.call_args.args[0])
        with mock.patch.object(board, "graphql", side_effect=board.BoardError("nope")), \
             mock.patch("builtins.print"):
            self.assertEqual(board.archive_card({"number": 8, "repo": "a/b", "item_id": "I8"}, {"project_id": "PVT_x"}), 2)

    def test_tidy_apply_moves_closed_to_done_and_adds_missing_to_new(self):
        closed = [{"number": 1, "repo": "acme/issues", "status": "Released"}]
        off_board = [{"number": 7, "repo": "acme/issues", "title": "t"}]
        with mock.patch.object(board, "untidy", return_value=(closed, [], off_board)), \
             mock.patch.object(board, "board_meta", return_value={}), \
             mock.patch.object(board, "move_card", side_effect=[0, 2]) as moved, \
             mock.patch("builtins.print"):
            code = board.cmd_tidy(Namespace(repo="acme/issues", apply=True))
        self.assertEqual(code, 2, "one failed move must fail the run")
        self.assertEqual(moved.call_args_list[0].args, (1, "acme/issues", board.DONE_COLUMN))
        self.assertEqual(moved.call_args_list[1].args, (7, "acme/issues", board.NEW_COLUMN))
        self.assertTrue(moved.call_args_list[1].kwargs["add_missing"])

    def test_tidy_apply_moves_to_the_boards_spelling_of_new(self):
        with mock.patch.object(board, "untidy", return_value=([], [], [{"number": 7, "repo": "a/b", "title": "t"}])), \
             mock.patch.object(board, "board_meta", return_value={"options": {"\u26a1 New": "o1", "Done": "o2"}}), \
             mock.patch.object(board, "move_card", return_value=0) as moved, mock.patch("builtins.print"):
            self.assertEqual(board.cmd_tidy(Namespace(repo="a/b", apply=True)), 0)
        self.assertEqual(moved.call_args.args[2], "\u26a1 New")

    def test_tidy_apply_goes_on_after_a_card_that_cannot_move(self):
        closed = [{"number": 1, "repo": "a/b", "status": "Released"}, {"number": 2, "repo": "a/b", "status": "Released"}]
        with mock.patch.object(board, "untidy", return_value=(closed, [], [])), \
             mock.patch.object(board, "board_meta", return_value={"options": {}}), \
             mock.patch.object(board, "move_card", side_effect=[board.BoardError("gone"), 0]) as moved, \
             mock.patch("builtins.print"):
            self.assertEqual(board.cmd_tidy(Namespace(repo="a/b", apply=True)), 2)
        self.assertEqual(moved.call_count, 2)

    def test_views_made_to_show_closed_work_are_left_alone(self):
        views = [{"name": "Shipped", "filter": "is:closed"}, {"name": "Not open", "filter": "-is:open label:x"}]
        self.assertEqual(board.views_showing_closed(views), [])

    def test_a_card_with_an_odd_shape_does_not_stop_the_rest(self):
        closed = [{"number": 1, "repo": "a/b", "status": "Released"}, {"number": 2, "repo": "a/b", "status": "Released"}]
        with mock.patch.object(board, "untidy", return_value=(closed, [], [])), \
             mock.patch.object(board, "board_meta", return_value={"options": {}}), \
             mock.patch.object(board, "move_card", side_effect=[TypeError("None"), 0]) as moved, \
             mock.patch("builtins.print"):
            self.assertEqual(board.cmd_tidy(Namespace(repo="a/b", apply=True)), 2)
        self.assertEqual(moved.call_count, 2)

    def test_tidy_without_apply_writes_nothing(self):
        with mock.patch.object(board, "untidy", return_value=([{"number": 1, "repo": "a/b", "status": None}], [], [])), \
             mock.patch.object(board, "move_card") as moved, mock.patch("builtins.print"):
            self.assertEqual(board.cmd_tidy(Namespace(repo="a/b", apply=False)), 0)
        moved.assert_not_called()

    def test_cmd_move_delegates_to_move_card(self):
        args = Namespace(issue=7, to="Done", repo="acme/issues", add_missing=True)
        with mock.patch.object(board, "move_card", return_value=3) as moved:
            self.assertEqual(board.cmd_move(args), 3)
        moved.assert_called_once_with(7, "acme/issues", "Done", add_missing=True)


class GraphqlCallShape(unittest.TestCase):
    """What graphql() hands `subprocess.run`, and how often it tries."""

    def transient(self):
        return mock.Mock(returncode=1, stdout="", stderr="HTTP 502 bad gateway")

    def test_the_call_is_captured_as_text_with_no_time_limit_by_default(self):
        self.assertEqual((board.ATTEMPTS, board.CALL_TIMEOUT), (3, None))
        ok = mock.Mock(returncode=0, stdout='{"data":{}}')
        with mock.patch.object(board.subprocess, "run", return_value=ok) as run:
            board.graphql("query {}")
        self.assertEqual(run.call_args.kwargs, {"capture_output": True, "text": True, "timeout": None})

    def test_a_transient_failure_is_tried_attempts_times_with_a_growing_wait(self):
        for attempts, waits in ((1, []), (2, [2]), (3, [2, 4])):
            with self.subTest(attempts=attempts), \
                 mock.patch.object(board, "ATTEMPTS", attempts), \
                 mock.patch.object(board.time, "sleep") as slept, \
                 mock.patch.object(board.subprocess, "run", return_value=self.transient()) as run:
                with self.assertRaises(board.BoardError):
                    board.graphql("query {}")
                self.assertEqual(run.call_count, attempts)
                self.assertEqual([c.args[0] for c in slept.call_args_list], waits)

    def test_a_transient_failure_that_clears_is_answered(self):
        ok = mock.Mock(returncode=0, stdout='{"data":{"x":1}}')
        with mock.patch.object(board.time, "sleep"), \
             mock.patch.object(board.subprocess, "run", side_effect=[self.transient(), ok]) as run:
            self.assertEqual(board.graphql("query {}"), {"x": 1})
        self.assertEqual(run.call_count, 2)


class StatusSinceAndArchive(unittest.TestCase):
    def test_the_issue_side_card_carries_when_it_entered_its_column_and_no_close_reason(self):
        node = issue_node(7, "seen", "Released")
        node["projectItems"]["nodes"][0]["fieldValueByName"]["updatedAt"] = "2026-10-01T09:00:00Z"
        bare = issue_node(8, "bare", "Released")
        with mock.patch.object(board, "graphql", side_effect=[issue_page([node, bare])]):
            cards = board.issue_side_cards(board.DEFAULT_REPO)
        self.assertEqual(cards[0]["status_since"], "2026-10-01T09:00:00Z")
        self.assertIsNone(cards[1]["status_since"])
        self.assertIn("state_reason", cards[0])
        self.assertIsNone(cards[0]["state_reason"])

    def archive(self, card, wrote=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(board, "graphql", **(wrote or {"return_value": {}})), \
             redirect_stdout(out), redirect_stderr(err):
            code = board.archive_card(card, {"project_id": "P"})
        return code, out.getvalue(), err.getvalue()

    def test_archiving_names_the_card_and_the_column_it_left(self):
        code, out, _ = self.archive({"number": 8, "repo": "a/b", "item_id": "I", "status": "Released"})
        self.assertEqual((code, out), (0, "a/b#8: Released -> archived\n"))
        code, out, _ = self.archive({"number": 9, "repo": "a/b", "item_id": "I", "status": None})
        self.assertEqual(out, "a/b#9: no status -> archived\n")

    def test_a_failed_archive_names_the_card_on_stderr(self):
        code, out, err = self.archive({"number": 8, "repo": "a/b", "item_id": "I"},
                                      {"side_effect": board.BoardError("nope")})
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "FAILED a/b#8 -> archive: nope\n")

    def tidy(self, closed=(), archive=(), off_board=()):
        out = io.StringIO()
        with mock.patch.object(board, "untidy", return_value=(list(closed), list(archive), list(off_board))), \
             redirect_stdout(out):
            code = board.cmd_tidy(Namespace(repo="a/b", apply=False))
        return code, out.getvalue()

    def test_tidy_lists_each_kind_and_says_nothing_to_tidy_only_when_there_is_none(self):
        item = {"number": 8, "repo": "a/b", "status": None, "title": "t"}
        self.assertEqual(self.tidy(archive=[item]),
                         (0, "closed as not planned, to archive: a/b#8 (no status)\n"))
        self.assertEqual(self.tidy(closed=[dict(item, status="Released")]),
                         (0, f"closed, not in {board.DONE_COLUMN}: a/b#8 (Released)\n"))
        self.assertEqual(self.tidy(off_board=[item]), (0, "open, not on the board: a/b#8 t\n"))
        self.assertEqual(self.tidy(), (0, "nothing to tidy\n"))

    def test_tidy_is_a_command_with_an_apply_flag(self):
        with mock.patch.object(sys, "argv", ["tracker.py", "tidy", "--apply"]), \
             mock.patch.object(board, "configure"), \
             mock.patch.object(board, "cmd_tidy", return_value=5) as tidied:
            self.assertEqual(board.main(), 5)
        self.assertTrue(tidied.call_args.args[0].apply)



def linked(number, title, status, *, blocked_by=(), blocking=(), repo=None):
    """A board card whose issue carries GitHub's dependency links (gogogo#185)."""
    item = card(number, title, status)
    item["content"]["blockedBy"] = {"totalCount": len(blocked_by), "nodes": [
        {"number": n, "state": state, "stateReason": reason, "repository": {"nameWithOwner": r or board.DEFAULT_REPO}}
        for n, state, reason, r in blocked_by]}
    item["content"]["blocking"] = {"totalCount": len(blocking), "nodes": [
        {"number": n, "state": "OPEN", "repository": {"nameWithOwner": board.DEFAULT_REPO}} for n in blocking]}
    if repo:
        item["content"]["repository"] = {"nameWithOwner": repo}
    return item


class BlockedByLinks(unittest.TestCase):
    """gogogo#185: every reader sees which issues block which, from the one board read."""

    def test_flatten_carries_the_links_and_defaults_to_none(self):
        flat = board.flatten(linked(11, "go-live", "Dev Priority", blocked_by=[(136, "OPEN", None, None)],
                                    blocking=[12]))
        self.assertEqual(flat["blocked_by"], [{"number": 136, "repo": board.DEFAULT_REPO, "state": "OPEN",
                                               "state_reason": None}])
        self.assertEqual(flat["blocking"], [{"number": 12, "repo": board.DEFAULT_REPO, "state": "OPEN"}])
        plain = board.flatten(card(2, "b", "Dev Priority"))
        self.assertEqual((plain["blocked_by"], plain["blocking"]), ([], []))
        self.assertEqual(board.flatten({"id": "X", "type": "ISSUE", "content": None})["blocked_by"], [])

    def test_a_truncated_link_list_refuses_the_read(self):
        item = linked(11, "go-live", "Dev Priority", blocked_by=[(1, "OPEN", None, None), (2, "OPEN", None, None)])
        item["content"]["blockedBy"]["totalCount"] = 3
        with self.assertRaises(board.BoardError) as raised:
            board.flatten(item)
        self.assertIn("#11", str(raised.exception))
        item = linked(11, "go-live", "Dev Priority", blocking=[1])
        item["content"]["blocking"]["totalCount"] = 2
        with self.assertRaises(board.BoardError):
            board.flatten(item)

    def test_blocker_state_for_each_case(self):
        cards = {"acme/issues#136": {"status": "Dev Priority"}, "acme/issues#137": {"status": "In Production"},
                 "acme/issues#138": {"status": "in dev"}}
        stages = board.stage_columns()
        self.assertEqual(sorted(stages), ["In Dev", "In Production"])

        def state(number, st="OPEN", reason=None, repo=board.DEFAULT_REPO):
            entry = {"number": number, "repo": repo, "state": st, "state_reason": reason}
            return board.blocker_state(entry, cards, stages)
        self.assertEqual(state(136), "open")
        self.assertEqual(state(137), "merged")
        self.assertEqual(state(138), "merged", "a stage column is matched without regard to case")
        self.assertEqual(state(136, "CLOSED", "COMPLETED"), "merged")
        self.assertEqual(state(136, "CLOSED", None), "merged")
        self.assertEqual(state(136, "CLOSED", "NOT_PLANNED"), "dropped")
        self.assertEqual(state(136, "CLOSED", "DUPLICATE"), "dropped")
        self.assertEqual(state(137, repo="other/repo"), "open", "an open blocker not on this board blocks")

    def test_list_json_gives_each_blocker_its_column_and_state(self):
        args = Namespace(status=None, open_only=False, issues_only=False,
                         json=True, repo=board.DEFAULT_REPO, no_crosscheck=True)
        nodes = [linked(11, "go-live", "Dev Priority", blocked_by=[(136, "OPEN", None, None)]),
                 linked(136, "runtime", "Dev Priority", blocking=[11]),
                 linked(12, "after a shipped one", "Dev Priority", blocked_by=[(140, "OPEN", None, None)]),
                 linked(140, "shipped", "In Production")]
        with mock.patch.object(board, "graphql", side_effect=[page(nodes, total=len(nodes))]), \
             mock.patch("builtins.print") as printed:
            board.cmd_list(args)
        payload = {c["number"]: c for c in json.loads(printed.call_args_list[0].args[0])}
        self.assertEqual(payload[11]["blocked_by"], [{"number": 136, "repo": board.DEFAULT_REPO, "state": "OPEN",
                                                      "state_reason": None, "column": "Dev Priority",
                                                      "blocker_state": "open"}])
        self.assertEqual([b["number"] for b in payload[136]["blocking"]], [11])
        self.assertEqual(payload[136]["blocked_by"], [])
        self.assertEqual(payload[12]["blocked_by"][0]["column"], "In Production")
        self.assertEqual(payload[12]["blocked_by"][0]["blocker_state"], "merged")

    def test_a_filtered_list_still_reads_the_blockers_column_from_the_whole_board(self):
        nodes = [linked(11, "go-live", "Dev Priority", blocked_by=[(140, "OPEN", None, None)]),
                 linked(140, "shipped", "In Production")]
        with mock.patch.object(board, "graphql", side_effect=[page(nodes, total=2)]), \
             mock.patch.object(board, "board_meta", return_value={"options": {"Dev Priority": "a"}}):
            cards, _, _ = board.list_cards(status="Dev Priority", repo=board.DEFAULT_REPO, crosscheck=False)
        self.assertEqual([c["number"] for c in cards], [11])
        self.assertEqual(cards[0]["blocked_by"][0]["blocker_state"], "merged")

    def test_every_issue_query_asks_for_both_links_with_their_counts(self):
        for query in (board.ITEMS_QUERY, board.REPO_ISSUE_CARDS_QUERY, board.ISSUE_ITEMS_QUERY):
            self.assertIn("blockedBy(first: 20) { totalCount", query)
            self.assertIn("blocking(first: 20) { totalCount", query)
            self.assertIn("stateReason repository { nameWithOwner }", query)

    def test_the_issue_side_cards_carry_the_links(self):
        node = issue_node(7, "seen", "Dev Priority")
        node["blockedBy"] = {"totalCount": 1, "nodes": [{"number": 9, "state": "OPEN", "stateReason": None,
                                                         "repository": {"nameWithOwner": "x/y"}}]}
        with mock.patch.object(board, "graphql", side_effect=[issue_page([node])]):
            cards = board.issue_side_cards(board.DEFAULT_REPO)
        self.assertEqual(cards[0]["blocked_by"], [{"number": 9, "repo": "x/y", "state": "OPEN", "state_reason": None}])
        self.assertEqual(cards[0]["blocking"], [])
        node["blocking"] = {"totalCount": 1, "nodes": [{"number": 3, "state": "OPEN",
                                                        "repository": {"nameWithOwner": "x/y"}}]}
        with mock.patch.object(board, "graphql", side_effect=[issue_page([node])]):
            cards = board.issue_side_cards(board.DEFAULT_REPO)
        self.assertEqual(cards[0]["blocking"], [{"number": 3, "repo": "x/y", "state": "OPEN"}])

    def test_a_blockers_close_reason_is_carried(self):
        flat = board.flatten(linked(11, "go-live", "Dev Priority", blocked_by=[(136, "CLOSED", "NOT_PLANNED", None)]))
        self.assertEqual(flat["blocked_by"][0]["state_reason"], "NOT_PLANNED")

    def _show(self, blockers, cards_by_number):
        issue = {"title": "go-live", "state": "OPEN", "url": "u",
                 "blockedBy": {"totalCount": len(blockers), "nodes": blockers}}
        found = {"issue": issue, "card": {"id": "I", "isArchived": False, "fieldValueByName": {"name": "Dev Priority"}}}

        def issue_card(number, repo):
            if number == 11:
                return found
            status = cards_by_number.get((repo, number))
            return {"issue": {}, "card": {"id": "B", "fieldValueByName": {"name": status}} if status else None}
        out = io.StringIO()
        with mock.patch.object(board, "issue_card", side_effect=issue_card), redirect_stdout(out):
            code = board.cmd_show(Namespace(issue=11, repo=board.DEFAULT_REPO, expect=None))
        return code, out.getvalue().splitlines()

    def test_show_names_each_blocker_after_the_column_line(self):
        code, lines = self._show(
            [{"number": 136, "state": "OPEN", "stateReason": None, "repository": {"nameWithOwner": board.DEFAULT_REPO}},
             {"number": 4, "state": "OPEN", "stateReason": None, "repository": {"nameWithOwner": "x/y"}},
             {"number": 140, "state": "OPEN", "stateReason": None, "repository": {"nameWithOwner": board.DEFAULT_REPO}}],
            {(board.DEFAULT_REPO, 136): "Dev Priority", (board.DEFAULT_REPO, 140): "In Production"})
        self.assertEqual(code, 0)
        at = lines.index("column: Dev Priority")
        self.assertEqual(lines[at + 1:], ["blocked by: #136 (open, Dev Priority)",
                                          "blocked by: x/y#4 (open, not on this board)",
                                          "blocked by: #140 (merged, In Production)"])

    def test_the_docstring_names_the_block_command(self):
        self.assertIn("block <issue> --by", board.__doc__)
        self.assertRegex(board.__doc__, r"`block`: 0 linked")


class FakeGh:
    """Stands in for subprocess.run on `gh api` calls for `block`."""

    def __init__(self, *, database_id="99001", found=0, post=(0, '{"number": 11}', ""), blocking=None,
                 read_back=0):
        self.database_id, self.found, self.post, self.read_back = database_id, found, post, read_back
        self.blocking = [{"number": 11, "repository_url": "https://api.github.com/repos/acme/issues"}] \
            if blocking is None else blocking
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        path = next(a for a in cmd[2:] if a.startswith("repos/"))
        if path.endswith("/dependencies/blocked_by"):
            return subprocess.CompletedProcess(cmd, *self.post)
        if "/dependencies/blocking" in path:
            if self.read_back:
                return subprocess.CompletedProcess(cmd, self.read_back, "", "gh: Server Error (HTTP 500)")
            return subprocess.CompletedProcess(cmd, 0, json.dumps(self.blocking), "")
        if self.found:
            return subprocess.CompletedProcess(cmd, 1, "", "gh: Not Found (HTTP 404)")
        return subprocess.CompletedProcess(cmd, 0, self.database_id + "\n", "")


class BlockCommand(unittest.TestCase):
    """`block` writes one link and believes it only when the blocker's side lists it."""

    def run_block(self, gh, by="136", issue=11):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(board.subprocess, "run", side_effect=gh), redirect_stdout(out), redirect_stderr(err):
            code = board.cmd_block(Namespace(issue=issue, by=by, repo=board.DEFAULT_REPO))
        return code, out.getvalue(), err.getvalue()

    def test_it_sends_the_database_id_typed_and_confirms_from_the_blockers_side(self):
        gh = FakeGh()
        code, out, _ = self.run_block(gh)
        self.assertEqual(code, 0)
        post = next(c for c in gh.calls if "POST" in c)
        self.assertEqual(post[post.index("-F") + 1], "issue_id=99001")
        self.assertNotIn("issue_id=136", " ".join(post))
        self.assertIn("repos/acme/issues/issues/11/dependencies/blocked_by", post)
        self.assertTrue(any("repos/acme/issues/issues/136/dependencies/blocking" in a for c in gh.calls for a in c))

    def test_a_read_back_that_does_not_list_the_issue_exits_2(self):
        self.assertEqual(self.run_block(FakeGh(blocking=[]))[0], 2)
        other_repo = [{"number": 11, "repository_url": "https://api.github.com/repos/x/y"}]
        self.assertEqual(self.run_block(FakeGh(blocking=other_repo))[0], 2)
        self.assertEqual(self.run_block(FakeGh(read_back=1))[0], 2)

    def test_the_result_names_the_blocker_not_the_posts_answer(self):
        code, out, _ = self.run_block(FakeGh(post=(0, '{"number": 11, "title": "go-live"}', "")))
        self.assertEqual((code, out.strip()), (0, "#11 blocked by #136"))
        self.assertNotIn("#11 blocked by #11", out)

    def test_an_existing_link_is_confirmed_and_said(self):
        gh = FakeGh(post=(1, "", "gh: Issue is already blocked by this issue (HTTP 422)"))
        code, out, _ = self.run_block(gh)
        self.assertEqual(code, 0)
        self.assertIn("already linked", out)
        self.assertEqual(self.run_block(FakeGh(post=(1, "", "gh: Server Error (HTTP 500)")))[0], 2)

    def test_refs_in_each_form_and_errors(self):
        gh = FakeGh(blocking=[{"number": 11, "repository_url": "https://api.github.com/repos/acme/issues"}])
        code, out, _ = self.run_block(gh, by="x/y#4")
        self.assertEqual((code, out.strip()), (0, "#11 blocked by x/y#4"))
        self.assertTrue(any("repos/x/y/issues/4" == a for c in gh.calls for a in c))
        self.assertEqual(self.run_block(FakeGh(), by="#136")[0], 0)
        self.assertEqual(self.run_block(FakeGh(), by="nonsense")[0], 1)
        for bad in ("acme/svc2", "o/r136", "acme/svc#", "#"):
            gh = FakeGh()
            self.assertEqual(self.run_block(gh, by=bad)[0], 1, bad)
            self.assertEqual(gh.calls, [], f"{bad}: nothing is read or written for a ref with no '#' after its repo")
        self.assertEqual(self.run_block(FakeGh(found=1))[0], 1)
        self.assertEqual(self.run_block(FakeGh(database_id="null"))[0], 2)

    def test_each_gh_call_is_exact(self):
        seen = []

        def gh(cmd, **kw):
            seen.append((cmd, kw))
            return FakeGh()(cmd, **kw)

        self.assertEqual(self.run_block(gh)[0], 0)
        self.assertEqual([cmd for cmd, _ in seen], [
            ["gh", "api", "repos/acme/issues/issues/136", "--jq", ".id"],
            ["gh", "api", "-X", "POST", "repos/acme/issues/issues/11/dependencies/blocked_by", "-F", "issue_id=99001"],
            ["gh", "api", "repos/acme/issues/issues/136/dependencies/blocking?per_page=100"]])
        self.assertEqual({tuple(sorted(kw.items())) for _, kw in seen},
                         {(("capture_output", True), ("text", True), ("timeout", board.CALL_TIMEOUT))})

    def test_a_missing_blocker_is_1_and_any_other_read_failure_2(self):
        for reason, code in (("gh: HTTP 404", 1), ("gh: Not Found", 1), ("gh: Server Error (HTTP 502)", 2)):
            def gh(cmd, **kw):
                return subprocess.CompletedProcess(cmd, 1, "", reason)
            self.assertEqual(self.run_block(gh)[0], code, reason)

    def test_by_is_required(self):
        with mock.patch.object(board, "configure"), \
             mock.patch.object(board.sys, "argv", ["tracker.py", "block", "11"]), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            board.main()
        self.assertEqual(stop.exception.code, 2)

    def test_block_is_a_command(self):
        gh = FakeGh()
        with mock.patch.object(board, "configure"), \
             mock.patch.object(board.subprocess, "run", side_effect=gh), \
             mock.patch.object(board.sys, "argv", ["tracker.py", "block", "11", "--by", "#136"]), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(board.main(), 0)


class BlockedIsNotAStop(unittest.TestCase):
    def test_the_blocked_marker_is_not_a_stop_reason(self):
        self.assertEqual(board.STOP_REASONS, ("hard-stop", "decision", "spec", "review", "tests", "mutation",
                                              "verify", "gate", "ci", "merge", "reverted"))
        self.assertFalse(board.has_reason("**Blocked by #136:** x.\n<!-- gogogo:blocked v=1 by=o/r#136 session=x -->"))


SKILLS = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "skills"


class BlockedSkillSteps(unittest.TestCase):
    """The skills keep the steps that use the links (gogogo#185)."""

    def test_auto_dev_reads_its_blocked_reference(self):
        self.assertIn("references/blocked.md", (SKILLS / "auto-dev" / "SKILL.md").read_text(encoding="utf-8"))
        text = (SKILLS / "auto-dev" / "references" / "blocked.md").read_text(encoding="utf-8")
        self.assertIn("blocked_by", text)
        self.assertIn("blocker_state", text)

    def test_dev_hands_a_blocked_issue_back_with_the_link_and_its_marker(self):
        text = (SKILLS / "dev" / "references" / "hand-back.md").read_text(encoding="utf-8")
        self.assertIn("block <n> --by", text)
        self.assertIn("gogogo:blocked v=1", text)

    def test_spec_posting_sets_the_links(self):
        self.assertIn("block <N> --by", (SKILLS / "spec" / "references" / "posting.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
