#!/usr/bin/env python3
"""Tests for the mutation record that /gogogo:dev §7 asks for (gogogo#45).

The mutation step in §6 is wording and gets no sentence test here
(CLAUDE.md § Tests): scenario runs check it. The record is a template
`review_stats.py` parses, so these pin its keys, its worked example, its
reason words and endings, where the skills and the schema name the lane key,
that no mutation tool's name leaks into the plugin, and that this repo's own
command exists.

    python3 -m unittest tests.test_mutation_record
"""

import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
DEV = PLUGIN / "skills" / "dev" / "SKILL.md"
AUTO_DEV = PLUGIN / "skills" / "auto-dev" / "SKILL.md"
DEV_VERIFY = PLUGIN / "skills" / "dev" / "references" / "verify.md"
SCHEMA = PLUGIN / "references" / "profile-schema.md"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_check  # noqa: E402
import review_stats  # noqa: E402
from test_dev_skill import moved  # noqa: E402

KEYS = ["v", "lane", "mutants", "killed", "survived", "timeout", "runs", "added", "declined_as", "end"]
MARKER = re.compile(r"<!-- gogogo:mutation (.*?) -->")
# Design 3's worked example, verbatim.
EXAMPLE = ("<!-- gogogo:mutation v=1 lane=unit mutants=128 killed=92 survived=35 timeout=1 runs=2 added=5 "
           "declined_as=equivalent:1,text:18,outside:11 end=clean -->")


def section(text, start):
    return text.split(f"\n## {start}")[1].split("\n## ")[0]


def template():
    return [line for line in section(DEV.read_text(encoding="utf-8"), "7.").splitlines()
            if "<!-- gogogo:mutation " in line]


class Template(unittest.TestCase):
    def test_one_template_with_its_keys_in_order(self):
        lines = template()
        self.assertEqual(len(lines), 1, lines)
        keys = [part.split("=", 1)[0] for part in MARKER.search(lines[0]).group(1).split(" ")]
        self.assertEqual(keys, KEYS)

    def test_reasons_and_endings_match_the_parser(self):
        fields = dict(p.split("=", 1) for p in MARKER.search(template()[0]).group(1).split(" "))
        reasons = tuple(part.split(":", 1)[0] for part in fields["declined_as"].split(","))
        self.assertEqual(reasons, review_stats.MUTATION_DECLINED_AS)
        self.assertEqual(tuple(fields["end"].strip("<>").split("|")), review_stats.MUTATION_ENDS)
        six = moved(DEV_VERIFY)
        for word in review_stats.MUTATION_DECLINED_AS:
            self.assertIn(f"`{word}`", six)


class Example(unittest.TestCase):
    def test_the_example_parses_and_adds_up(self):
        record = review_stats.parse_mutation(EXAMPLE)
        self.assertIsNotNone(record)
        self.assertEqual(record["mutants"], record["killed"] + record["survived"] + record["timeout"])


class Named(unittest.TestCase):
    def test_skills_and_schema_name_the_key(self):
        self.assertIn("`mutate`", moved(DEV_VERIFY))
        self.assertIn("`mutate`", section(AUTO_DEV.read_text(encoding="utf-8"), "4."))
        lanes = SCHEMA.read_text(encoding="utf-8").split("\n### Lanes")[1].split("\n### ")[0]
        self.assertIn("`mutate`", lanes)
        self.assertIn("<base>", lanes)
        self.assertIn("mutants: <n> killed: <n> survived: <n> timeout: <n>", lanes)

    def test_no_mutation_tool_named_in_the_plugin(self):
        for path in PLUGIN.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertIsNone(re.search(r"mutmut|cosmic", text, re.I), path)

    def test_this_repos_unit_lane_points_at_the_tool(self):
        settings, _ = profile_check.split_profile((ROOT / ".agents" / "dev-process.md").read_text(encoding="utf-8"))
        unit = next(lane for lane in settings["lanes"] if lane["name"] == "unit")
        self.assertIn("tools/mutate.py", unit.get("mutate", ""))
        tool = ROOT / "tools" / "mutate.py"
        self.assertTrue(tool.is_file())
        self.assertTrue(os.access(tool, os.X_OK))


if __name__ == "__main__":
    unittest.main()
