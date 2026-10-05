#!/usr/bin/env python3
"""Tests for human_help.py: the cards in the Human!Help! column and the authorisation a body carries (gogogo#159).

    python3 -m unittest tests.test_human_help
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "scripts"))
import human_help as hh  # noqa: E402


def comment(body, association="OWNER", author="victor", url="https://example/c"):
    return {"body": body, "url": url, "author": author, "association": association}


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
        c = hh.card(1, "t", "u", [comment(STOP_REVIEW), comment("merge it", "MEMBER", "v2", "https://example/a")], [])
        self.assertEqual([a["body"] for a in c["answers"]], ["merge it"])

    def test_a_reader_comment_after_the_stop_is_not_an_answer(self):
        c = hh.card(1, "t", "u", [comment(STOP_REVIEW), comment("merge it", "NONE")], [])
        self.assertEqual(c["answers"], [])

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
