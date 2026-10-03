#!/usr/bin/env python3
"""Tests for the shared /gogogo:status skill and the settings it reads.

The skill is prose, so these pin what a reader of it depends on: that it can
start (its name, and `profile_check.py --for status` accepting it), that it
needs only what every skill needs, that every setting it names is one the
checker knows, that it names no write, that its report template has its two
blocks, and that no project's facts leak into it.

    python3 -m unittest tests.test_status
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
SKILL = PLUGIN / "skills" / "status" / "SKILL.md"
README = ROOT / "README.md"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_check as pc  # noqa: E402
from test_profile_check import COMPLETE, drop, parse  # noqa: E402
from test_tech_eval import PROJECT_NAMES  # noqa: E402

# Commands that write to the repo, the board, the tracker or a remote.
WRITES = ("gh issue edit", "gh issue close", "gh pr merge", "gh pr edit", "gh api -X",
          "git push", "git fetch", "git pull", "git switch", "git checkout",
          "git worktree add", "git worktree remove", "git branch -d", "git branch -D",
          "git stash", "git commit", "git reset")


def skill_text():
    return SKILL.read_text(encoding="utf-8")


class Skill(unittest.TestCase):
    def test_name_and_profile_command(self):
        text = skill_text()
        front = text.split("---")[1]
        self.assertRegex(front, r"(?m)^name: status$")
        self.assertIn('profile_check.py" --for status --show', text)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            profile.write_text(COMPLETE)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = pc.main(["--for", "status", "--path", str(profile)])
        self.assertEqual(code, pc.EXIT_OK)

    def test_requires_only_what_every_skill_requires(self):
        settings, sections = parse()
        for path, (_, required_by, _) in pc.FIELDS.items():
            if required_by is not pc.SKILLS and pc._lookup(settings, path)[1]:
                settings = drop(settings, path)
        self.assertNotIn("stages", settings)
        self.assertNotIn("tool", settings["tracker"])
        # Every skill reads `## superpowers boundary`, so it is the one section kept.
        kept = {"superpowers boundary": sections["superpowers boundary"]}
        self.assertEqual(pc.check(settings, kept, "status")[0], [])

    def test_every_setting_it_names_is_known(self):
        tops = {path.split(".")[0] for path in pc.FIELDS if "." in path}
        named = {f"{a}.{b}" for a, b in re.findall(r"[`<]([a-z_]+)\.([a-z_]+)[`>]", skill_text()) if a in tops}
        for setting in ("tracker.tool", "tracker.queue", "tracker.code_repo",
                        "tracker.issues_repo", "integration.base"):
            self.assertIn(setting, named)
        # Three-part and stage settings the two-part regex cannot see.
        self.assertIn("`tracker.columns.in_progress`", skill_text())
        self.assertIn("tracker.columns.in_progress", pc.FIELDS)
        stage_keys = re.findall(r"`stages\[\]\.([a-z_]+)`", skill_text())
        self.assertIn("column", stage_keys)
        self.assertIn("environment", stage_keys)
        for key in stage_keys:
            self.assertIn(key, pc.STAGE_KEYS, key)
        for setting in sorted(named):
            self.assertIn(setting, pc.FIELDS, setting)

    def test_reads_only(self):
        text = skill_text()
        self.assertNotRegex(text, r'tracker\.py"? move')
        for command in WRITES:
            self.assertNotIn(command, text, command)

    def test_template(self):
        blocks = re.findall(r"```[^\n]*\n(.*?)```", skill_text(), re.S)
        templates = [b for b in blocks
                     if re.search(r"(?m)^BOARD", b) and re.search(r"(?m)^CODE", b)]
        self.assertEqual(len(templates), 1, "one fenced report template")
        lines = templates[0].splitlines()
        board = next(i for i, l in enumerate(lines) if l.startswith("BOARD"))
        code = next(i for i, l in enumerate(lines) if l.startswith("CODE"))
        self.assertLess(board, code)
        after = "\n".join(lines[code:])
        self.assertIn("Pull requests:", after)
        self.assertIn("Branches ahead of", after)

    def test_board_names_pull_request_cards_and_where_to_stop_them(self):
        shape = skill_text().split("## Shape", 1)[1].split("## Template", 1)[0]
        line = next((l for l in shape.splitlines() if "pull-request card(s)" in l), "")
        for text in ("is:issue is:open", "<workflows URL>", "/gogogo:setup"):
            self.assertIn(text, line)
        self.assertIn("/projects/<n>/workflows", shape)
        self.assertIn("PullRequest", shape)

    def test_no_project_names(self):
        self.assertIsNone(re.search(PROJECT_NAMES, skill_text(), re.I))

    def test_readme_lists_it(self):
        self.assertRegex(README.read_text(encoding="utf-8"), r"(?m)^\| `/gogogo:status` \|")


if __name__ == "__main__":
    unittest.main()
