#!/usr/bin/env python3
"""Tests for which branches stranded_work.py reports.

A local branch whose commits are all on some remote branch is a copy, not
stranded work, unless it is checked out in a worktree. Each test builds real
repos in a temp dir (a bare `origin` and a clone) and runs the script as a
subprocess from the clone, so no profile is found and no `gh` call is made.
Branch names carry no digits, so the issue lookup never runs.

    python3 -m unittest tests.test_stranded_work
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "scripts" / "stranded_work.py"

# Keep the machine's git config (hooks, signing, default branch) out of the tests.
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class StrandedWorkTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.run_git(self.tmp, "init", "-q", "--bare", "-b", "main", "origin.git")
        self.run_git(self.tmp, "clone", "-q", "origin.git", "clone")
        self.clone = self.tmp / "clone"
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("checkout", "-q", "-b", "main")
        self.commit("base")
        self.git("push", "-q", "origin", "main")

    def run_git(self, cwd, *args):
        subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True)

    def git(self, *args):
        self.run_git(self.clone, *args)

    def commit(self, message):
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def branch_with(self, name, commits):
        """Create `name` from main with `commits` new commits, and return to main."""
        self.git("checkout", "-q", "-b", name, "main")
        for i in range(commits):
            self.commit(f"{name} {i}")
        self.git("checkout", "-q", "main")

    def stranded(self, env=ENV):
        out = subprocess.run([sys.executable, str(SCRIPT), "--base", "main"], cwd=self.clone,
                             env=env, capture_output=True, text=True)
        self.stderr = out.stderr
        return out.returncode, out.stdout.splitlines()

    def test_pushed_copy_is_not_reported(self):
        self.branch_with("copy", 2)
        self.git("push", "-q", "origin", "copy")
        self.assertEqual(self.stranded(), (0, []))

    def test_unpushed_branch_is_reported(self):
        self.branch_with("local-only", 1)
        code, lines = self.stranded()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("local-only: 1 commit(s) ahead of main, no issue number in the name"),
                        lines[0])

    def test_local_commit_on_top_of_a_pushed_branch_is_reported(self):
        self.branch_with("partly", 1)
        self.git("push", "-q", "-u", "origin", "partly")
        self.git("checkout", "-q", "partly")
        self.commit("partly local")
        self.git("checkout", "-q", "main")
        code, lines = self.stranded()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("partly: 2 commit(s) ahead of main"), lines[0])

    def test_with_no_remote_every_ahead_branch_is_reported(self):
        self.branch_with("orphan", 1)
        self.git("remote", "remove", "origin")
        code, lines = self.stranded()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("orphan: "), lines[0])

    def test_pushed_branch_backing_a_worktree_is_reported(self):
        self.branch_with("in-tree", 1)
        self.git("push", "-q", "origin", "in-tree")
        self.git("worktree", "add", "-q", str(self.tmp / "wt"), "in-tree")
        code, lines = self.stranded()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("in-tree: "), lines[0])
        self.assertIn("(worktree ", lines[0])

    def test_pushed_branch_in_the_main_checkout_is_reported(self):
        self.branch_with("checked-out", 1)
        self.git("push", "-q", "origin", "checked-out")
        self.git("checkout", "-q", "checked-out")
        code, lines = self.stranded()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("checked-out: "), lines[0])
        self.assertIn("(worktree ", lines[0])

    def test_worktree_branch_sharing_a_tag_name_is_reported(self):
        self.branch_with("release", 1)
        self.git("push", "-q", "origin", "release")
        self.git("tag", "release", "main")
        self.git("worktree", "add", "-q", str(self.tmp / "wt"), "release")
        code, lines = self.stranded()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("release: 1 commit(s) ahead of main"), lines[0])
        self.assertIn("(worktree ", lines[0])

    def test_unpushed_branch_sharing_a_tag_name_is_reported(self):
        self.branch_with("release", 1)
        self.git("tag", "release", "main")
        code, lines = self.stranded()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("release: 1 commit(s) ahead of main"), lines[0])

    def test_unreadable_worktree_list_reports_every_ahead_branch(self):
        """Without the worktree list, a pushed branch in a worktree could pass as a copy."""
        self.branch_with("copy", 1)
        self.git("push", "-q", "origin", "copy")
        self.branch_with("in-tree", 1)
        self.git("push", "-q", "origin", "in-tree")
        self.git("worktree", "add", "-q", str(self.tmp / "wt"), "in-tree")
        real = shutil.which("git")
        self.assertIsNotNone(real)
        shim = self.tmp / "bin"
        shim.mkdir()
        (shim / "git").write_text(f'#!/bin/sh\n[ "$1" = worktree ] && exit 1\nexec "{real}" "$@"\n')
        (shim / "git").chmod(0o755)
        code, lines = self.stranded({**ENV, "PATH": f"{shim}{os.pathsep}{ENV['PATH']}"})
        self.assertEqual(code, 1)
        self.assertEqual([line.split(":")[0] for line in lines], ["copy", "in-tree"])
        self.assertIn("cannot read worktrees, so copies of pushed branches are reported too: git exited 1",
                      self.stderr)

    def test_branch_pushed_under_another_name_is_not_reported(self):
        self.branch_with("renamed", 1)
        self.git("push", "-q", "origin", "renamed:other-name")
        self.assertEqual(self.stranded(), (0, []))

    def test_only_the_unpushed_branch_is_listed(self):
        self.branch_with("copy", 2)
        self.git("push", "-q", "origin", "copy")
        self.branch_with("local-only", 1)
        code, lines = self.stranded()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("local-only: "), lines[0])


if __name__ == "__main__":
    unittest.main()
