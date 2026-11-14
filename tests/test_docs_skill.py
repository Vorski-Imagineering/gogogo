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


class HistoryMode(unittest.TestCase):
    # gogogo#269: a history mode under evidence rules, in a reference of its own.
    def test_names_the_mode_its_rules_and_its_marker(self):
        body = SKILL.read_text(encoding="utf-8")
        self.assertIn("/gogogo:docs history", body)
        self.assertIn("references/history.md", body)
        self.assertIn("<!-- history: through", body)

    def test_its_rules_are_named_from_the_skill_alone(self):
        self.assertTrue((SKILL.parent / "references" / "history.md").is_file())
        # No other reference naming it is test_skill_budget's check.
        self.assertIn("references/history.md", SKILL.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
