#!/usr/bin/env python3
"""The shared reference that defines a suspected gogogo fault, and the skills
that name it (gogogo#140).

A fault in the plugin noticed during a run is written as one visible line in
the report the run already writes. These pin that the line's template exists,
that dev and auto-dev name the reference, and that it holds no project's
facts. Whether a run writes the line is a scenario run, not a test here.

    python3 -m unittest tests.test_gogogo_faults
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
REFERENCE = PLUGIN / "references" / "gogogo-faults.md"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tech_eval import PROJECT_NAMES  # noqa: E402


class Faults(unittest.TestCase):
    def test_reference_holds_the_line_template(self):
        self.assertTrue(REFERENCE.is_file())
        self.assertIn("**Suspected gogogo fault:**", REFERENCE.read_text(encoding="utf-8"))

    def test_dev_and_auto_dev_name_it(self):
        for skill in ("dev", "auto-dev"):
            with self.subTest(skill=skill):
                text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("references/gogogo-faults.md", text)

    def test_no_project_names(self):
        self.assertTrue(REFERENCE.is_file())
        self.assertIsNone(re.search(PROJECT_NAMES, REFERENCE.read_text(encoding="utf-8"), re.I))


if __name__ == "__main__":
    unittest.main()
