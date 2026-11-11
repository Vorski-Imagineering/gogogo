#!/usr/bin/env python3
"""Every doc is reachable from docs/README.md and every skill has a README row (gogogo#266).

    python3 -m unittest tests.test_docs_index
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DocsIndex(unittest.TestCase):
    """docs_check.py, on this repo's own profile (`[docs] index`), finds no broken link and no unlisted doc."""

    def test_every_doc_is_listed_and_every_link_resolves(self):
        run = subprocess.run([sys.executable, str(ROOT / "plugins" / "gogogo" / "scripts" / "docs_check.py"),
                              "--profile", str(ROOT / ".agents" / "dev-process.md"), "--json"],
                             capture_output=True, text=True)
        result = json.loads(run.stdout)
        found = [f for f in result["findings"] if f["kind"] in ("link", "index")]
        self.assertEqual(found, [], f"{found}\n{run.stderr}")
        self.assertGreaterEqual(result["files"], 10, run.stderr)


class SkillRows(unittest.TestCase):
    """README.md's skills table has a row for every skill folder."""

    def test_every_skill_has_a_row(self):
        rows = set(re.findall(r"^\| `/gogogo:([a-z0-9-]+)` \|", (ROOT / "README.md").read_text(), re.M))
        skills = {p.parent.name for p in (ROOT / "plugins" / "gogogo" / "skills").glob("*/SKILL.md")}
        self.assertTrue(skills)
        self.assertEqual(sorted(skills - rows), [])


if __name__ == "__main__":
    unittest.main()
