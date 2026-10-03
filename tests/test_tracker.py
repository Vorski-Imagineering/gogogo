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
        self.assertIn("no column", err)

    def test_add_missing_with_from_and_no_card_adds_nothing(self):
        code, sent, err = self._move(None, card=False, add_missing=True)
        self.assertEqual(code, 3)
        self.assertEqual(sent, [])
        self.assertIn("not on the board", err)

    def test_the_from_option_reaches_move_card(self):
        argv = ["tracker.py", "move", "7", "--from", "queue", "--to", "in_progress"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(board, "configure"), \
             mock.patch.object(board, "move_card", return_value=3) as moved:
            self.assertEqual(board.main(), 3)
        self.assertEqual(moved.call_args.kwargs.get("expect_from"), "queue")

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
        def item(n, state, status, kind="Issue"):
            return {"id": f"I{n}", "content": {"__typename": kind, "number": n, "title": "t",
                                               "state": state, "repository": {"nameWithOwner": "acme/issues"}},
                    "fieldValueByName": {"name": status} if status else None}
        items = [item(1, "CLOSED", "Released"), item(2, "CLOSED", "Done"), item(3, "OPEN", "Backlog"),
                 item(4, "CLOSED", "In progress", kind="PullRequest"), item(5, "CLOSED", None)]
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
        closed, off_board = self._untidy()
        self.assertEqual([c["number"] for c in closed], [1, 5])
        self.assertEqual([i["number"] for i in off_board], [6, 7])

    def test_tidy_apply_moves_closed_to_done_and_adds_missing_to_new(self):
        closed = [{"number": 1, "repo": "acme/issues", "status": "Released"}]
        off_board = [{"number": 7, "repo": "acme/issues", "title": "t"}]
        with mock.patch.object(board, "untidy", return_value=(closed, off_board)), \
             mock.patch.object(board, "board_meta", return_value={}), \
             mock.patch.object(board, "move_card", side_effect=[0, 2]) as moved, \
             mock.patch("builtins.print"):
            code = board.cmd_tidy(Namespace(repo="acme/issues", apply=True))
        self.assertEqual(code, 2, "one failed move must fail the run")
        self.assertEqual(moved.call_args_list[0].args, (1, "acme/issues", board.DONE_COLUMN))
        self.assertEqual(moved.call_args_list[1].args, (7, "acme/issues", board.NEW_COLUMN))
        self.assertTrue(moved.call_args_list[1].kwargs["add_missing"])

    def test_tidy_apply_moves_to_the_boards_spelling_of_new(self):
        with mock.patch.object(board, "untidy", return_value=([], [{"number": 7, "repo": "a/b", "title": "t"}])), \
             mock.patch.object(board, "board_meta", return_value={"options": {"\u26a1 New": "o1", "Done": "o2"}}), \
             mock.patch.object(board, "move_card", return_value=0) as moved, mock.patch("builtins.print"):
            self.assertEqual(board.cmd_tidy(Namespace(repo="a/b", apply=True)), 0)
        self.assertEqual(moved.call_args.args[2], "\u26a1 New")

    def test_tidy_apply_goes_on_after_a_card_that_cannot_move(self):
        closed = [{"number": 1, "repo": "a/b", "status": "Released"}, {"number": 2, "repo": "a/b", "status": "Released"}]
        with mock.patch.object(board, "untidy", return_value=(closed, [])), \
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
        with mock.patch.object(board, "untidy", return_value=(closed, [])), \
             mock.patch.object(board, "board_meta", return_value={"options": {}}), \
             mock.patch.object(board, "move_card", side_effect=[TypeError("None"), 0]) as moved, \
             mock.patch("builtins.print"):
            self.assertEqual(board.cmd_tidy(Namespace(repo="a/b", apply=True)), 2)
        self.assertEqual(moved.call_count, 2)

    def test_tidy_without_apply_writes_nothing(self):
        with mock.patch.object(board, "untidy", return_value=([{"number": 1, "repo": "a/b", "status": None}], [])), \
             mock.patch.object(board, "move_card") as moved, mock.patch("builtins.print"):
            self.assertEqual(board.cmd_tidy(Namespace(repo="a/b", apply=False)), 0)
        moved.assert_not_called()

    def test_cmd_move_delegates_to_move_card(self):
        args = Namespace(issue=7, to="Done", repo="acme/issues", add_missing=True)
        with mock.patch.object(board, "move_card", return_value=3) as moved:
            self.assertEqual(board.cmd_move(args), 3)
        moved.assert_called_once_with(7, "acme/issues", "Done", add_missing=True)


if __name__ == "__main__":
    unittest.main()
