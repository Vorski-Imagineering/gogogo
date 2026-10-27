#!/usr/bin/env python3
"""Structure of /gogogo:sentry-debug (gogogo#204).

These pin the settings, commands and tools the skill depends on, never its
sentences (CLAUDE.md § Tests); whether it behaves is its eval cases.

    python3 -m unittest tests.test_sentry_debug_skill
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "plugins" / "gogogo" / "skills" / "sentry-debug"
SKILL = SKILL_DIR / "SKILL.md"
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import profile_check as pc  # noqa: E402

REQUIRED = ("sentry.org", "sentry.region_url", "sentry.projects", "sentry.release_format")
OPTIONAL = ("sentry.report_dir", "sentry.evidence_command")


def text():
    return SKILL.read_text(encoding="utf-8")


class SkillNamesTheSettingsItDependsOn(unittest.TestCase):
    def test_names_each_setting(self):
        body = text()
        for word in ("sentry.org", "sentry.projects", "sentry.release_format", "sentry.report_dir",
                     "sentry.evidence_command", "## Sentry", 'profile_check.py" --for sentry-debug'):
            self.assertIn(word, body)

    def test_profile_check_requires_them(self):
        self.assertIn(pc.SENTRY, pc.SKILLS)
        for path in REQUIRED:
            self.assertEqual(pc.FIELDS[path][1], (pc.SENTRY,), path)
        for path in OPTIONAL:
            self.assertEqual(pc.FIELDS[path][1], (), path)


class ReadOnly(unittest.TestCase):
    def test_names_the_mcp_setup_and_the_write_tools_it_never_calls(self):
        body = text()
        for word in ("claude mcp add --transport http sentry https://mcp.sentry.dev/mcp",
                     "update_issue", "find_dropped_events"):
            self.assertIn(word, body)


class Size(unittest.TestCase):
    def test_at_most_150_lines(self):
        self.assertLessEqual(len(text().splitlines()), 150)


class NoProjectNames(unittest.TestCase):
    def test_other_stack_names_absent(self):
        for path in SKILL_DIR.rglob("*"):
            if not path.is_file():
                continue
            body = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"manage\.py|npm |firebase|django|htmx", body, re.I), path)
            self.assertIsNone(re.search(r"https?://(?!mcp\.sentry\.dev)[^\s/]*sentry", body, re.I), path)


if __name__ == "__main__":
    unittest.main()
