#!/usr/bin/env python3
"""Tests for tools/changes.py: one month's section of docs/changes.md, from main's first-parent commits.

They run real git in a temp repo, because what they guard is which commits a
month holds and which group each lands in.

    python3 -m unittest tests.test_changes_tool
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import changes  # noqa: E402


def git(root, *args, date=None):
    env = dict(os.environ)
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, env=env)


def write(root, rel, text="x\n"):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class Month(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        write(self.root, "README.md")
        write(self.root, "plugins/gogogo/skills/dev/SKILL.md")
        write(self.root, "plugins/gogogo/references/profile-schema.md")
        write(self.root, "plugins/gogogo/scripts/tracker.py")
        self.commit("start", "2026-09-30T12:00:00Z")

    def commit(self, subject, date):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", subject, date=date)

    def run_tool(self, month):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = changes.main([month, "--ref", "main"], root=Path(self.root))
        return code, out.getvalue()

    def test_a_new_skill_is_listed_once_under_new_skills(self):
        write(self.root, "plugins/gogogo/skills/x/SKILL.md")
        self.commit("x: a new skill (Refs #5) (#6)", "2026-10-03T12:00:00Z")
        code, out = self.run_tool("2026-10")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("x: a new skill"), 1)
        self.assertLess(out.index("### New skills"), out.index("x: a new skill"))
        self.assertNotIn("### Skill changes", out)

    def test_a_settings_change_lands_under_settings(self):
        write(self.root, "plugins/gogogo/references/profile-schema.md", "new\n")
        write(self.root, "plugins/gogogo/scripts/tracker.py", "new\n")
        self.commit("profile: a setting (Refs #7) (#8)", "2026-10-04T12:00:00Z")
        code, out = self.run_tool("2026-10")
        self.assertLess(out.index("### Settings"), out.index("profile: a setting"))
        self.assertNotIn("### Scripts", out)

    def test_only_the_month_asked_for_and_each_line_links_its_issue(self):
        write(self.root, "README.md", "october\n")
        self.commit("x: y (Refs #12) (#34)", "2026-10-05T12:00:00Z")
        write(self.root, "README.md", "november\n")
        self.commit("later: z (Refs #13) (#35)", "2026-11-02T12:00:00Z")
        code, out = self.run_tool("2026-10")
        self.assertTrue(out.startswith("## October 2026\n"), out)
        self.assertIn("- x: y, [#12](https://github.com/Vorski-Imagineering/gogogo/issues/12)", out)
        self.assertNotIn("later: z", out)

    def test_a_side_branch_commit_is_not_listed_but_its_merge_is(self):
        git(self.root, "checkout", "-q", "-b", "side")
        write(self.root, "README.md", "side\n")
        self.commit("side: work (Refs #20)", "2026-10-06T12:00:00Z")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", "merge: side (Refs #21) (#22)", "side",
            date="2026-10-07T12:00:00Z")
        code, out = self.run_tool("2026-10")
        self.assertNotIn("side: work", out)
        self.assertIn("- merge: side, [#21](", out)

    def test_each_subject_form_links_its_issue_or_else_its_pull_request(self):
        base = "https://github.com/Vorski-Imagineering/gogogo"
        self.assertEqual(changes.line("a (Refs #159, partial) (#183)"), f"- a, [#159]({base}/issues/159)")
        self.assertEqual(changes.line("b (#5) (#7)"), f"- b, [#5]({base}/issues/5)")
        self.assertEqual(changes.line("c (#9)"), f"- c, [#9]({base}/pull/9)")
        self.assertEqual(changes.line("d"), "- d")

    def test_a_month_with_no_commits_says_so_and_fails(self):
        code, out = self.run_tool("2026-12")
        self.assertEqual(code, 1)
        self.assertIn("no changes in 2026-12", out)


if __name__ == "__main__":
    unittest.main()
