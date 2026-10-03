#!/usr/bin/env python3
"""Tests for the review record that /gogogo:dev §7 asks for on each issue.

The review rule in §5 is wording and gets no test here (CLAUDE.md § Tests): it
is checked by scenario runs. The record is a template `review_stats.py`
parses, so these pin its keys, its worked example, the old format the records
already on issues use, and where the skill names its settings.

    python3 -m unittest tests.test_review_record
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
DEV = PLUGIN / "skills" / "dev" / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "scripts"))

import profile_check  # noqa: E402
import review_stats  # noqa: E402

KEYS = ["v", "pr", "kind", "coverage", "rounds", "applied", "declined", "refix", "applied_as",
        "declined_as", "followups", "end", "escaped_from", "escaped_as", "impl", "reviewer",
        "session", "t_branch", "t_verified"]
MARKER = re.compile(r"<!-- gogogo:review (.*?) -->")
# Design 2's worked example, verbatim.
EXAMPLE = ("<!-- gogogo:review v=2 pr=482 kind=mixed coverage=broad rounds=3 applied=5,2,0 declined=3,1,2 "
           "refix=0,1,0 applied_as=spec:2,regression:1,bug:3,risk:0,added:1 "
           "declined_as=hypothetical:3,style:1,settled:1,reversal:0,beyond:1,late:0 followups=1 end=clean "
           "escaped_from=none escaped_as=none impl=claude-opus-5-5 reviewer=claude-opus-5-5 "
           "session=0d6f3c2a-8b1e-4f5d-9a7c-2e4b6d8f0a1c t_branch=2026-10-03T09:00Z t_verified=2026-10-03T10:30Z -->")
# A v2 record from before gogogo#62: no session or phase times.
EXAMPLE_BEFORE_62 = EXAMPLE.split(" session=")[0] + " -->"
STOP = re.compile(r"<!-- gogogo:stop (.*?) -->")
# The format before gogogo#33, as records already on issues carry it.
OLD_EXAMPLE = ("<!-- gogogo:review pr=482 kind=code level=high rounds=4 applied=5,2,1,0 "
               "declined=1,0,0,0 correctness=0,1,1,0 stopped=no -->")


def section(text, start, end):
    return text.split(f"\n## {start}")[1].split(f"\n## {end}")[0]


class Template(unittest.TestCase):
    def test_the_template_is_complete(self):
        lines = [line for line in section(DEV.read_text(encoding="utf-8"), "7.", "8.").splitlines()
                 if MARKER.search(line)]
        self.assertEqual(len(lines), 1, lines)
        keys = [part.split("=", 1)[0] for part in MARKER.search(lines[0]).group(1).split(" ")]
        self.assertEqual(keys, KEYS)


class Example(unittest.TestCase):
    def test_the_example_parses_and_adds_up(self):
        record = review_stats.parse_review(EXAMPLE)
        self.assertIsNotNone(record)
        self.assertEqual((record["v"], record["rounds"], record["pr"]), (2, 3, "482"))
        for key in ("applied", "declined", "refix"):
            self.assertEqual(len(record[key]), record["rounds"], key)
        self.assertEqual(record["refix"][0], 0)
        for refix, applied in zip(record["refix"], record["applied"]):
            self.assertLessEqual(refix, applied)
        self.assertEqual(sum(record["applied_as"].values()), sum(record["applied"]))
        self.assertEqual(sum(record["declined_as"].values()), sum(record["declined"]))
        self.assertTrue(record["consistent"])
        self.assertEqual((record["session"], record["t_branch"], record["t_verified"]),
                         ("0d6f3c2a-8b1e-4f5d-9a7c-2e4b6d8f0a1c", "2026-10-03T09:00Z", "2026-10-03T10:30Z"))
        self.assertEqual(record["malformed"], [])

    def test_a_v2_record_without_the_new_keys_still_parses(self):
        record = review_stats.parse_review(EXAMPLE_BEFORE_62)
        self.assertIsNotNone(record)
        self.assertEqual((record["session"], record["t_branch"], record["t_verified"]), (None, None, None))
        self.assertEqual(record["malformed"], [])

    def test_the_old_format_still_parses(self):
        record = review_stats.parse_review(OLD_EXAMPLE)
        self.assertIsNotNone(record)
        self.assertEqual((record["v"], record["coverage"], record["end"]), (1, "broad", "clean"))
        self.assertIsNone(record["refix"])


class Settings(unittest.TestCase):
    def test_dev_names_the_coverage_setting_and_maps_it_in_claude_specific(self):
        text = DEV.read_text(encoding="utf-8")
        self.assertIn("`review.coverage`", text)
        self.assertIn("review.coverage", profile_check.FIELDS)
        claude = text.split("\n## Claude-specific")[1]
        for value in ("precise", "broad", "exhaustive"):
            self.assertIn(value, claude)
        review = section(text, "5.", "6.")
        self.assertIsNone(re.search(r"/code-review (medium|high|max)\b", review))
        self.assertIsNone(re.search(r"`(medium|high|max)`", review))

    def test_dev_names_the_stop_marker(self):
        markers = STOP.findall(section(DEV.read_text(encoding="utf-8"), "8.", "Do not"))
        self.assertEqual(len(markers), 1, markers)
        reasons = re.fullmatch(r"v=1 reason=<([^>]*)>", markers[0])
        self.assertIsNotNone(reasons, markers[0])
        self.assertEqual(tuple(reasons.group(1).split("|")), review_stats.STOPS)

    def test_dev_names_the_session_source(self):
        claude = DEV.read_text(encoding="utf-8").split("\n## Claude-specific")[1]
        self.assertIn("CLAUDE_CODE_SESSION_ID", claude)

    def test_readme_lists_review_stats(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertTrue(any(line.startswith("- `review_stats.py`") for line in readme.splitlines()))


if __name__ == "__main__":
    unittest.main()
