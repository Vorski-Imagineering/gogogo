#!/usr/bin/env python3
"""Tests for the review record that /gogogo:dev §7 asks for on each issue.

The rounds rule in §5 is wording and gets no test here (CLAUDE.md § Tests): it
is checked by a live run. The record is a template a later counter will parse,
so these pin its keys and its format.

    python3 -m unittest tests.test_review_record
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "plugins" / "gogogo" / "skills" / "dev" / "SKILL.md"
KEYS = ["pr", "kind", "level", "rounds", "applied", "declined", "correctness", "stopped"]
MARKER = re.compile(r"<!-- gogogo:review (.*?) -->")
# Design 3's example, verbatim.
EXAMPLE = ("<!-- gogogo:review pr=482 kind=code level=high rounds=4 applied=5,2,1,0 "
           "declined=1,0,0,0 correctness=0,1,1,0 stopped=no -->")
LISTS = ("applied", "declined", "correctness")


def parse(line):
    """The record as a dict: list keys split on ',', everything else a string."""
    body = MARKER.search(line).group(1)
    record = dict(part.split("=", 1) for part in body.split(" "))
    for key in LISTS:
        record[key] = record[key].split(",")
    return record


def section_7():
    text = DEV.read_text(encoding="utf-8")
    return text.split("\n## 7.")[1].split("\n## 8.")[0]


class Template(unittest.TestCase):
    def test_the_template_is_complete(self):
        lines = [line for line in section_7().splitlines() if MARKER.search(line)]
        self.assertEqual(len(lines), 1, lines)
        keys = [part.split("=", 1)[0] for part in MARKER.search(lines[0]).group(1).split(" ")]
        self.assertEqual(keys, KEYS)


class Example(unittest.TestCase):
    def test_the_example_parses(self):
        record = parse(EXAMPLE)
        self.assertEqual(list(record), KEYS)
        self.assertEqual((record["rounds"], record["pr"]), ("4", "482"))
        for key in LISTS:
            self.assertEqual(len(record[key]), int(record["rounds"]), key)
        for applied, correctness in zip(record["applied"], record["correctness"]):
            self.assertLessEqual(int(correctness), int(applied))


if __name__ == "__main__":
    unittest.main()
