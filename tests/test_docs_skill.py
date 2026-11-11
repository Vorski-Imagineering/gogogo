#!/usr/bin/env python3
"""Structure of /gogogo:docs (gogogo#270).

These pin the settings, scripts and label the skill depends on, never its
sentences (CLAUDE.md § Tests); whether it behaves is its eval cases.

    python3 -m unittest tests.test_docs_skill
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
SKILL = PLUGIN / "skills" / "docs" / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "scripts"))

import profile_check as pc  # noqa: E402

SETTINGS = ("docs.dir", "docs.index", "docs.public")


class SkillNamesWhatItDependsOn(unittest.TestCase):
    def test_names_its_settings_scripts_label_and_gates(self):
        self.assertIn(pc.DOCS, pc.SKILLS)
        body = SKILL.read_text(encoding="utf-8")
        for word in (*SETTINGS, "docs_check.py", 'profile_check.py" --for docs', "documentation", "gates.always"):
            self.assertIn(word, body)

    def test_the_schema_documents_the_docs_table(self):
        schema = (PLUGIN / "references" / "profile-schema.md").read_text(encoding="utf-8")
        self.assertIn("### Docs", schema)
        for path in SETTINGS:
            self.assertIn(f"| `{path}` |", schema)
            self.assertIn(path, pc.FIELDS)


if __name__ == "__main__":
    unittest.main()
