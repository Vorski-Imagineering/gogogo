#!/usr/bin/env python3
"""Tests for the shared /gogogo:roadmap skill and the setting it reads.

The skill is prose, so these pin what a reader of it depends on: that it can
start (its name, and `profile_check.py --for roadmap` accepting a profile),
that every setting it names is one the checker knows, that the legend it offers
is one the script accepts, that it names every keyword the script reads, and
that no project's facts leak into it.

    python3 -m unittest tests.test_roadmap_skill
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
SKILL = PLUGIN / "skills" / "roadmap" / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_check as pc  # noqa: E402
import roadmap_status as rs  # noqa: E402
import tracker  # noqa: E402
from test_profile_check import COMPLETE  # noqa: E402
from test_roadmap_status import keep_tracker_globals, profile_text  # noqa: E402

# The project-name grep in CLAUDE.md, as a regex.
PROJECT_NAMES = r"manage\.py|npm |firebase|django|htmx|sentry"
LEGEND_HEADER = "| Mark | State | Means | Covers |"


def skill_text():
    return SKILL.read_text(encoding="utf-8")


class Skill(unittest.TestCase):
    def test_name_and_profile_command(self):
        text = skill_text()
        front = text.split("---")[1]
        self.assertRegex(front, r"(?m)^name: roadmap$")
        self.assertIn('profile_check.py" --for roadmap --show', text)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            profile.write_text(COMPLETE)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = pc.main(["--for", "roadmap", "--path", str(profile)])
        self.assertEqual(code, pc.EXIT_OK)

    def test_every_setting_it_names_is_known(self):
        tops = {path.split(".")[0] for path in pc.FIELDS if "." in path}
        # Backticked (`roadmap.file`) or a placeholder in a command (<tracker.issues_repo>).
        named = {f"{a}.{b}" for a, b in re.findall(r"[`<]([a-z_]+)\.([a-z_]+)[`>]", skill_text()) if a in tops}
        for setting in ("roadmap.file", "tracker.issues_repo", "tracker.ready_marker"):
            self.assertIn(setting, named)
        for setting in sorted(named):
            self.assertIn(setting, pc.FIELDS, setting)

    def test_runs_the_script(self):
        self.assertIn('scripts/roadmap_status.py"', skill_text())

    def test_same_repo_path_opens_the_pr(self):
        self.assertIn("gh pr create --base <B>", skill_text())

    def test_same_repo_path_returns_the_checkout(self):
        text = skill_text()
        for command in ("git switch <S>", "git branch -d roadmap-refresh-", "git branch -D roadmap-refresh-"):
            self.assertIn(command, text, command)

    def test_checks_for_an_open_refresh_pr(self):
        text = skill_text()
        self.assertIn('startswith("roadmap-refresh-")', text)
        self.assertIn("gh pr list --state open", text)

    def test_its_legend_template_passes_the_script(self):
        blocks = re.findall(r"```[^\n]*\n(.*?)```", skill_text(), re.S)
        templates = [b for b in blocks if LEGEND_HEADER in b]
        self.assertEqual(len(templates), 1, "one fenced legend template")
        keep_tracker_globals(self)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            text = profile_text(stages=("Released",)).replace(
                'back_to_queue = "Dev Ready"', 'needs_human = "Human!Help!"')
            self.assertIn("Human!Help!", text)
            profile.write_text(text, encoding="utf-8")
            tracker.configure(str(profile))
            settings, _ = pc.split_profile(profile.read_text(encoding="utf-8"))
        lines = templates[0].splitlines(keepends=True)
        legend = rs.read_legend(rs.find_tables(lines), settings)
        self.assertEqual(len(legend.marks), 9)

    def test_names_every_keyword(self):
        text = skill_text()
        for keyword in rs.KEYWORDS:
            self.assertIn(f"`{keyword}`", text, keyword)

    def test_roadmap_file_is_optional(self):
        self.assertIn("roadmap.file", pc.FIELDS)
        self.assertEqual(pc.FIELDS["roadmap.file"][1], ())

    def test_no_project_names(self):
        self.assertIsNone(re.search(PROJECT_NAMES, skill_text(), re.I))


if __name__ == "__main__":
    unittest.main()
