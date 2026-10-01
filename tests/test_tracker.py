#!/usr/bin/env python3
"""Tests for the two guards in board.py that must never be assumed working.

Both cover failures that are *invisible* in the raw `gh` flow this replaces: a
board read that came back short, and a card move that returned cleanly without
moving anything. Neither can be provoked against the real board, so `graphql`
is faked here.

    python3 -m unittest discover -s .claude/scripts -p 'test_*.py'
"""

import json
import re
import subprocess
import unittest
from pathlib import Path
from argparse import Namespace
from unittest import mock

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


def card(number, title, status):
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


def issue_node(number, title, status, *, item_id=None, archived=False, project=2):
    return {
        "number": number,
        "title": title,
        "state": "OPEN",
        "url": f"https://example.invalid/{number}",
        "repository": {"nameWithOwner": board.DEFAULT_REPO},
        "assignees": {"nodes": []},
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
