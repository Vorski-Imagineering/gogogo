#!/usr/bin/env python3
"""Tests for human_help.py: the cards in the Human!Help! column and the authorisation a body carries (gogogo#159).

    python3 -m unittest tests.test_human_help
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "scripts"))
import human_help as hh  # noqa: E402


def comment(body, writer=True, author="victor", url="https://example/c"):
    return {"body": body, "url": url, "author": author, "writer": writer}


STOP_REVIEW = ("**Needs you:** read commit abc1234 and merge it, or send it back. "
               "Branch: https://github.com/o/r/tree/fix/140-x\n\n"
               "<!-- gogogo:stop v=1 reason=review session=unknown -->")


class Card(unittest.TestCase):
    def test_a_review_stop_lists_its_reason_needs_you_and_branch(self):
        c = hh.card(140, "t", "u", [comment(STOP_REVIEW)], [])
        self.assertEqual(c["reason"], "review")
        self.assertEqual(c["needs_you"], "read commit abc1234 and merge it, or send it back. Branch: "
                                         "https://github.com/o/r/tree/fix/140-x")
        self.assertEqual(c["branch"], "fix/140-x")

    def test_a_writer_comment_after_the_stop_is_an_answer(self):
        # gogogo#159 Design 7: write access decides, whatever the comment's association.
        answer = dict(comment("merge it", True, "v2", "https://example/a"), association="NONE")
        c = hh.card(1, "t", "u", [comment(STOP_REVIEW), answer], [])
        self.assertEqual([a["body"] for a in c["answers"]], ["merge it"])

    def test_a_reader_comment_after_the_stop_is_not_an_answer(self):
        # An org member with no write access is not a writer: association MEMBER does not count.
        member = dict(comment("merge it", False, "m"), association="MEMBER")
        c = hh.card(1, "t", "u", [comment(STOP_REVIEW), member], [])
        self.assertEqual(c["answers"], [])
        unread = {k: v for k, v in comment("merge it").items() if k != "writer"}
        self.assertEqual(hh.card(1, "t", "u", [comment(STOP_REVIEW), unread], [])["answers"], [])

    def test_a_comment_before_the_stop_is_not_an_answer(self):
        c = hh.card(1, "t", "u", [comment("merge it"), comment(STOP_REVIEW)], [])
        self.assertEqual(c["answers"], [])

    def test_requeues_count_only_the_same_reason(self):
        gate = "<!-- gogogo:stop v=1 reason=gate session=unknown -->"
        comments = [comment(gate), comment("<!-- gogogo:requeue v=1 reason=gate -->"),
                    comment(gate), comment("<!-- gogogo:requeue v=1 reason=gate -->")]
        self.assertEqual(hh.card(1, "t", "u", comments, [])["requeued"], 2)
        review = comments + [comment(STOP_REVIEW)]
        self.assertEqual(hh.card(1, "t", "u", review, [])["requeued"], 0)

    def test_no_marker_is_reason_none(self):
        c = hh.card(1, "t", "u", [comment("just talk")], [])
        self.assertEqual(c["reason"], "none")
        self.assertIsNone(c["needs_you"])

    def test_a_skip_marker_is_reason_skip(self):
        body = "**Needs you:** re-spec\n\n<!-- gogogo:skip v=1 reason=lint session=unknown -->"
        self.assertEqual(hh.card(1, "t", "u", [comment(body)], [])["reason"], "skip")


PROFILE = """+++
profile = 1
[tracker]
issues_repo = "o/r"
project_owner = "o"
project_number = 1
columns = { in_progress = "In progress", needs_human = "Human!Help!" }
+++
"""


class FakeGh:
    """Stands in for human_help._gh: one issue's comments, and each author's permission."""

    def __init__(self, comments, permissions):
        self.comments, self.permissions, self.asked = comments, permissions, []

    def __call__(self, *args):
        if args[:2] == ("issue", "view"):
            return json.dumps({"comments": self.comments})
        login = args[1].split("/")[-2]
        self.asked.append(login)
        answer = self.permissions[login]
        if isinstance(answer, Exception):
            raise answer
        return answer + "\n"


def gh_comment(login, body, association="NONE"):
    return {"body": body, "url": f"https://example/{login}", "author": {"login": login},
            "authorAssociation": association}


class Permissions(unittest.TestCase):
    """Who may answer a card is read from GitHub's permission call, not the comment's association."""

    def setUp(self):
        # list configures tracker.py from the profile: put its module settings back after each case.
        import tracker
        saved = (tracker.ORG, tracker.PROJECT_NUMBER, tracker.DEFAULT_REPO, dict(tracker.COLUMNS))

        def restore():
            tracker.ORG, tracker.PROJECT_NUMBER, tracker.DEFAULT_REPO = saved[:3]
            tracker.COLUMNS.clear()
            tracker.COLUMNS.update(saved[3])
        self.addCleanup(restore)

    def run_list(self, gh):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            profile.write_text(PROFILE, encoding="utf-8")
            board = [{"number": 7, "title": "t", "url": "u", "status_since": "2026-10-05T00:00:00Z", "labels": []}]
            out, err = io.StringIO(), io.StringIO()
            import tracker
            with mock.patch.object(tracker, "list_cards", return_value=(board, [], 1)), \
                 mock.patch.object(hh, "_gh", side_effect=gh), redirect_stdout(out), redirect_stderr(err):
                code = hh.main(["--profile", str(profile), "list", "--json"])
        return code, out.getvalue(), err.getvalue()

    def test_permission_decides_who_answers(self):
        comments = [gh_comment("bot", STOP_REVIEW, "OWNER"), gh_comment("w", "merge it"),
                    gh_comment("m", "send it back", "MEMBER"), gh_comment("x", "drop it", "MEMBER"),
                    gh_comment("w", "and then requeue")]
        gh = FakeGh(comments, {"bot": "admin", "w": "write", "m": "read",
                               "x": hh.CannotRead("gh: Not Found (HTTP 404)")})
        code, out, _ = self.run_list(gh)
        self.assertEqual(code, 0)
        card = json.loads(out)[0]
        self.assertEqual([a["author"] for a in card["answers"]], ["w", "w"])
        self.assertEqual(sorted(gh.asked), ["bot", "m", "w", "x"], "each login is looked up once")

    def test_the_board_is_read_from_the_profile(self):
        # Live run, 2026-10-05: list read "project /#0" because the tracker was never configured.
        import tracker
        seen = {}

        def list_cards(**kw):
            seen.update(org=tracker.ORG, number=tracker.PROJECT_NUMBER, repo=kw.get("repo"))
            return [], [], 0
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            profile.write_text(PROFILE, encoding="utf-8")
            with mock.patch.object(tracker, "list_cards", side_effect=list_cards), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(hh.main(["--profile", str(profile), "list"]), 0)
        self.assertEqual(seen, {"org": "o", "number": 1, "repo": "o/r"})

    def test_a_defaulted_needs_human_column_is_read(self):
        import tracker
        seen = {}

        def list_cards(**kw):
            seen.update(status=kw.get("status"), repo=kw.get("repo"))
            return [], [], 0
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            profile.write_text(PROFILE.replace(', needs_human = "Human!Help!"', ""), encoding="utf-8")
            with mock.patch.object(tracker, "list_cards", side_effect=list_cards), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(hh.main(["--profile", str(profile), "list"]), 0)
        self.assertEqual(seen, {"status": "In progress", "repo": "o/r"})

    def test_a_404_by_status_or_by_text_is_not_a_writer(self):
        for message in ("gh: HTTP 404", "gh: Not Found"):
            with mock.patch.object(hh, "_gh", side_effect=hh.CannotRead(message)):
                self.assertFalse(hh.writer("o/r", "x", {}), message)

    def test_a_profile_without_a_board_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            profile.write_text('+++\nprofile = 1\n[tracker]\nissues_repo = "o/r"\n+++\n', encoding="utf-8")
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
                self.assertEqual(hh.main(["--profile", str(profile), "list"]), 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("could not read the board", err.getvalue())

    def test_maintain_and_admin_are_writers(self):
        comments = [gh_comment("bot", STOP_REVIEW), gh_comment("a", "one"), gh_comment("k", "two")]
        code, out, _ = self.run_list(FakeGh(comments, {"bot": "admin", "a": "admin", "k": "maintain"}))
        self.assertEqual([a["author"] for a in json.loads(out)[0]["answers"]], ["a", "k"])

    def test_an_unreadable_permission_exits_2(self):
        comments = [gh_comment("bot", STOP_REVIEW), gh_comment("w", "merge it")]
        gh = FakeGh(comments, {"bot": "admin", "w": hh.CannotRead("gh: Server Error (HTTP 500)")})
        code, out, err = self.run_list(gh)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("could not read w's permission", err)

    def test_the_permission_call_is_the_collaborator_endpoint(self):
        gh = FakeGh([gh_comment("w", "hi")], {"w": "write"})
        self.run_list(gh)
        with mock.patch.object(hh, "_gh", return_value="write\n") as called:
            self.assertTrue(hh.writer("o/r", "w", {}))
        self.assertEqual(called.call_args.args, ("api", "repos/o/r/collaborators/w/permission", "-q", ".permission"))


class Authorised(unittest.TestCase):
    def body(self, *rows):
        table = ("| Date | Question | Chosen | Rejected |\n|---|---|---|---|\n"
                 + "\n".join(f"| 2026-10-05 | q | {r} | x |" for r in rows) + "\n")
        return table

    def test_a_row_prints_its_settings(self):
        self.assertEqual(hh.authorised(self.body("authorised: review=until-clean model=fable effort=high")),
                         {"review": "until-clean", "model": "fable", "effort": "high"})

    def test_the_newer_of_two_rows_wins(self):
        got = hh.authorised(self.body("authorised: review=until-clean", "authorised: effort=max"))
        self.assertEqual(got, {"effort": "max"})

    def test_no_row_is_empty(self):
        self.assertEqual(hh.authorised(self.body("approved; named the skill")), {})

    def test_only_the_chosen_cell_authorises(self):
        refused = "| 2026-10-06 | Keep going? | send it back | authorised: review=until-clean model=fable |\n"
        self.assertEqual(hh.authorised(self.body("approved") + refused), {})
        chosen = "| 2026-10-06 | Keep going? | authorised: effort=high | send it back |\n"
        self.assertEqual(hh.authorised(self.body("approved") + chosen), {"effort": "high"})
        escaped = "| 2026-10-06 | Stopped (third-attempt \\| unfixable). Keep going? | authorised: effort=max | stop |\n"
        self.assertEqual(hh.authorised(self.body("approved") + escaped), {"effort": "max"})

    def test_rows_of_any_width_and_spacing(self):
        self.assertEqual(hh.authorised("| a | b |\n"), {}, "a two-cell row has no Chosen cell")
        self.assertEqual(hh.authorised("| 2026-10-06 | q | authorised: effort=high |\n"), {"effort": "high"})
        self.assertEqual(hh.authorised("|X|q|authorised: effort=max|r|\n"), {"effort": "max"})

    def test_an_unknown_model_or_effort_is_refused(self):
        with self.assertRaises(ValueError):
            hh.authorised(self.body("authorised: model=gpt"))
        with self.assertRaises(ValueError):
            hh.authorised(self.body("authorised: effort=huge"))


class AuthorisedCommand(unittest.TestCase):
    def run_cli(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "body.md"
            path.write_text(text, encoding="utf-8")
            return hh.main(["authorised", str(path)])

    def test_exit_zero_when_absent(self):
        self.assertEqual(self.run_cli("no table here\n"), 0)

    def test_exit_two_on_a_bad_value(self):
        self.assertEqual(self.run_cli("| 2026 | q | authorised: effort=huge | x |\n"), 2)


if __name__ == "__main__":
    unittest.main()
