#!/usr/bin/env python3
"""Tests for the shared /gogogo:tech-eval skill and the settings it reads.

The skill is prose, so these pin what a reader of it depends on: that it can
start (its name, and `profile_check.py --for tech-eval` accepting it), that
every setting it names is one the checker knows, that a register it starts
matches the format a repo's own register parser enforces, and that no
project's facts leak into it.

    python3 -m unittest tests.test_tech_eval
"""

import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
SKILL = PLUGIN / "skills" / "tech-eval" / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_check as pc  # noqa: E402
from test_profile_check import COMPLETE  # noqa: E402

# The project-name grep in CLAUDE.md, as a regex.
PROJECT_NAMES = r"manage\.py|npm |firebase|django|htmx|sentry"
HEADER = "| Technology | Status | Why | Reopen when | Decided in |"
SEPARATOR = "|---|---|---|---|---|"
STATUSES = ("Adopted", "Not now", "Rejected", "Superseded")


def skill_text():
    return SKILL.read_text(encoding="utf-8")


class Skill(unittest.TestCase):
    def test_name_and_profile_command(self):
        text = skill_text()
        front = text.split("---")[1]
        self.assertRegex(front, r"(?m)^name: tech-eval$")
        self.assertIn('profile_check.py" --for tech-eval --show', text)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            profile.write_text(COMPLETE)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = pc.main(["--for", "tech-eval", "--path", str(profile)])
        self.assertEqual(code, pc.EXIT_OK)

    def test_every_setting_it_names_is_known(self):
        tops = {path.split(".")[0] for path in pc.FIELDS if "." in path}
        # Backticked (`state.forbidden`) or a placeholder in a command (<tracker.issues_repo>).
        named = {f"{a}.{b}" for a, b in re.findall(r"[`<]([a-z_]+)\.([a-z_]+)[`>]", skill_text()) if a in tops}
        self.assertGreaterEqual(len(named), 3, named)
        for setting in ("technology.register", "tracker.issues_repo", "state.forbidden"):
            self.assertIn(setting, named)
        for setting in sorted(named):
            self.assertIn(setting, pc.FIELDS, setting)

    def test_names_the_register_setting(self):
        self.assertIn("`technology.register`", skill_text())
        self.assertIn("technology.register", pc.FIELDS)
        self.assertEqual(pc.FIELDS["technology.register"][1], ())

    def test_register_template_matches_the_rules(self):
        text = skill_text()
        blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
        templates = [b for b in blocks if "## Register" in b]
        self.assertEqual(len(templates), 1, "one fenced register template")
        lines = [line.strip() for line in templates[0].splitlines()]
        self.assertIn("## Register", lines)
        self.assertIn(HEADER, lines)
        after = lines.index(HEADER) + 1
        self.assertEqual(lines[after:after + 1], [SEPARATOR])
        for status in STATUSES:
            self.assertIn(f"`{status}`", text, status)

    def test_no_project_names(self):
        self.assertIsNone(re.search(PROJECT_NAMES, skill_text(), re.I))


if __name__ == "__main__":
    unittest.main()
