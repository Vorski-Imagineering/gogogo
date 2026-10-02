#!/usr/bin/env python3
"""Tests for which branches stranded_work.py reports.

A local branch whose commits are all on some remote branch is a copy, not
stranded work, unless it is checked out in a worktree. Each test builds real
repos in a temp dir (a bare `origin` and a clone) and runs the script as a
subprocess from the clone, so no profile is found and no `gh` call is made.
Branch names carry no digits, so the issue lookup never runs.

`PullRequests` adds a profile in the clone and a fake `gh` on PATH that answers
from a JSON fixture and logs every call (gogogo#22).

    python3 -m unittest tests.test_stranded_work
"""

import json
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


class Repos(unittest.TestCase):
    """A bare `origin` and a clone with one pushed commit on main."""

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


class StrandedWorkTest(Repos):
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


FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
fixture = json.load(open(os.environ["FAKE_GH"]))
def arg(flag):
    return args[args.index(flag) + 1]
if args[:2] == ["pr", "list"]:
    answer = fixture.get("pr", {}).get(f"{arg('--repo')} {arg('--head')}", [])
elif args[:2] == ["repo", "view"]:
    answer = fixture.get("repo", {}).get(args[2], {"isArchived": False})
elif args[:2] == ["issue", "view"]:
    answer = fixture.get("issue", {}).get(args[2], {"state": "CLOSED"})
else:
    answer = "fail"
if answer == "fail":
    print("boom", file=sys.stderr)
    sys.exit(1)
print(json.dumps(answer))
"""


def pr(number, state, oid, repo="o/code"):
    return {"number": number, "state": state, "headRefOid": oid,
            "headRepository": {"name": repo.split("/")[1], "nameWithOwner": repo}}


class PullRequests(Repos):
    """Open PRs claim branches; closed and merged PRs, and history, are named."""

    def setUp(self):
        super().setUp()
        (self.clone / ".agents").mkdir()
        (self.clone / ".agents" / "dev-process.md").write_text(
            '+++\n[tracker]\nissues_repo = "o/code"\ncode_repo = "o/code"\n+++\n')
        bin_dir = self.tmp / "ghbin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(FAKE_GH)
        (bin_dir / "gh").chmod(0o755)
        self.fixture = self.tmp / "gh.json"
        self.log = self.tmp / "gh.log"
        self.log.write_text("")
        self.env = {**ENV, "PATH": f"{bin_dir}{os.pathsep}{ENV['PATH']}",
                    "FAKE_GH": str(self.fixture), "FAKE_GH_LOG": str(self.log)}

    def run_with(self, fixture):
        self.fixture.write_text(json.dumps(fixture))
        return self.stranded(self.env)

    def tip(self, ref):
        return subprocess.run(["git", "rev-parse", ref], cwd=self.clone, env=ENV, check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_an_open_pr_in_the_code_repo_claims_a_worktree_branch(self):
        self.branch_with("claimed", 1)
        self.git("push", "-q", "origin", "claimed")
        self.git("worktree", "add", "-q", str(self.tmp / "wt"), "claimed")
        fixture = {"pr": {"o/code claimed": [pr(5, "OPEN", self.tip("claimed"))]}}
        self.assertEqual(self.run_with(fixture), (0, []))

    def test_an_open_pr_does_not_hide_unpushed_commits(self):
        self.branch_with("ahead", 1)
        self.git("push", "-q", "origin", "ahead")
        pushed = self.tip("ahead")
        self.git("checkout", "-q", "ahead")
        self.commit("ahead local")
        self.git("checkout", "-q", "main")
        code, lines = self.run_with({"pr": {"o/code ahead": [pr(5, "OPEN", pushed)]}})
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].endswith("; PR #5 open, but 1 commit(s) are on no remote"), lines[0])

    def test_a_merged_pr_is_named(self):
        self.branch_with("done", 1)
        code, lines = self.run_with({"pr": {"o/code done": [pr(7, "MERGED", self.tip("done"))]}})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].endswith(
            "no issue number in the name; PR #7 merged, so its content may already be in main"), lines[0])

    def test_a_closed_pr_is_named(self):
        self.branch_with("done", 1)
        code, lines = self.run_with({"pr": {"o/code done": [pr(8, "CLOSED", self.tip("done"))]}})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].endswith("; PR #8 closed without merging"), lines[0])

    def test_a_branch_moved_since_its_pr_says_so(self):
        self.branch_with("done", 1)
        code, lines = self.run_with({"pr": {"o/code done": [pr(7, "MERGED", "abcdef1234567890")]}})
        self.assertEqual(code, 1)
        self.assertIn("PR #7 merged (the PR's head was abcdef1; the branch has moved since), "
                      "so its content may already be in main", lines[0])

    def test_an_open_pr_in_another_remote_does_not_claim(self):
        self.git("remote", "add", "old", "git@github.com:o/old.git")
        self.branch_with("legacy", 1)
        self.git("push", "-q", "origin", "legacy")
        self.git("worktree", "add", "-q", str(self.tmp / "wt"), "legacy")
        fixture = {"pr": {"o/old legacy": [pr(27, "OPEN", self.tip("legacy"), "o/old")]},
                   "repo": {"o/old": {"isArchived": True}}}
        code, lines = self.run_with(fixture)
        self.assertEqual(code, 1)
        self.assertIn("; PR #27 open in o/old (archived)", lines[0])

    def test_no_common_history_says_so(self):
        self.git("checkout", "-q", "--orphan", "rootless")
        self.commit("root 1")
        self.commit("root 2")
        self.git("checkout", "-q", "main")
        code, lines = self.run_with({})
        self.assertEqual(code, 1)
        self.assertIn("rootless: no history in common with main, no issue number in the name", lines[0])
        self.assertNotIn("commit(s) ahead", lines[0])

    def test_a_failed_pr_lookup_reports_and_never_claims(self):
        self.branch_with("claimed", 1)
        self.git("push", "-q", "origin", "claimed")
        self.git("worktree", "add", "-q", str(self.tmp / "wt"), "claimed")
        code, lines = self.run_with({"pr": {"o/code claimed": "fail"}})
        self.assertEqual(code, 1)
        self.assertIn("; pull requests in o/code not checked: boom", lines[0])

    def test_a_forks_pr_with_the_same_name_does_not_count(self):
        self.branch_with("claimed", 1)
        self.git("push", "-q", "origin", "claimed")
        self.git("worktree", "add", "-q", str(self.tmp / "wt"), "claimed")
        fixture = {"pr": {"o/code claimed": [pr(5, "OPEN", self.tip("claimed"), "stranger/code")]}}
        code, lines = self.run_with(fixture)
        self.assertEqual(code, 1)
        self.assertNotIn("PR #", lines[0])

    def test_no_gh_installed_still_reports(self):
        """A missing `gh` is a failed lookup: the branch is still reported, with the reason."""
        self.branch_with("done", 1)
        self.branch_with("fix/12-x", 1)
        bare = self.tmp / "nogh"
        bare.mkdir()
        (bare / "git").symlink_to(shutil.which("git"))
        code, lines = self.stranded({**self.env, "PATH": str(bare)})
        self.assertEqual(code, 1, self.stderr)
        self.assertEqual([line.split(":")[0] for line in lines], ["done", "fix/12-x"], self.stderr)
        for line in lines:
            self.assertIn("; pull requests in o/code not checked: cannot run gh", line)

    def test_no_profile_makes_no_gh_call(self):
        (self.clone / ".agents" / "dev-process.md").unlink()
        self.branch_with("claimed", 1)
        self.git("push", "-q", "origin", "claimed")
        self.git("worktree", "add", "-q", str(self.tmp / "wt"), "claimed")
        self.run_with({"pr": {"o/code claimed": [pr(5, "OPEN", self.tip("claimed"))]}})
        self.assertEqual(self.log.read_text(), "")

    def test_an_open_issue_claims_before_any_pr_lookup(self):
        self.branch_with("fix/12-x", 1)
        self.assertEqual(self.run_with({"issue": {"12": {"state": "OPEN"}}}), (0, []))
        self.assertNotIn("pr list", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
