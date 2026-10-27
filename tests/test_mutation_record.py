#!/usr/bin/env python3
"""Tests for where mutation testing lives now (gogogo#199; first added for gogogo#45).

Mutation testing left the plugin: no skill or schema reads a lane's `mutate`
key, and no mutation tool's name is in the plugin. gogogo keeps the run for
its own scripts, named from CLAUDE.md and described in docs/mutation.md.

    python3 -m unittest tests.test_mutation_record
"""

import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"


class Named(unittest.TestCase):
    def test_no_mutation_tool_named_in_the_plugin(self):
        for path in PLUGIN.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertIsNone(re.search(r"mutmut|cosmic", text, re.I), path)

    def test_no_skill_or_schema_reads_the_mutate_key(self):
        """Guards a leftover instruction to run the retired key: `mutate`, mutate = or a /mutate/ list entry."""
        key = re.compile(r"`mutate`|\bmutate\s*=|/mutate/", re.I)
        for folder in (PLUGIN / "skills", PLUGIN / "references"):
            for path in folder.rglob("*.md"):
                self.assertIsNone(key.search(path.read_text(encoding="utf-8")), path)

    def test_this_repos_unit_lane_points_at_the_tool(self):
        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("tools/mutate.py", claude)
        self.assertIn("docs/mutation.md", claude)
        self.assertTrue((ROOT / "docs" / "mutation.md").is_file())
        tool = ROOT / "tools" / "mutate.py"
        self.assertTrue(tool.is_file())
        self.assertTrue(os.access(tool, os.X_OK))


if __name__ == "__main__":
    unittest.main()
