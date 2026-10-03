#!/usr/bin/env python3
"""Tests for which worktrees worktree_sweep.py removes and which it keeps (gogogo#92).

Each test builds real repos in a temp dir (a bare `origin`, a clone with a
committed profile, worktrees beside it) and runs the script as a subprocess
from the clone, with a fake `gh` on PATH that answers from a JSON fixture.

    python3 -m unittest tests.test_worktree_sweep
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "scripts" / "worktree_sweep.py"

# Keep the machine's git config (hooks, signing, default branch) out of the tests.
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

# Answers `pr list` and `issue view` from the fixture; anything missing, or "fail", fails.
FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
fixture = json.load(open(os.environ["FAKE_GH"]))
def arg(flag):
    return args[args.index(flag) + 1]
if args[:2] == ["pr", "list"]:
    answer = fixture.get("pr", {}).get(arg("--head"), [])
elif args[:2] == ["issue", "view"]:
    answer = fixture.get("issue", {}).get(args[2], "fail")
else:
    answer = "fail"
if answer == "fail" or fixture.get("down"):
    print("gh: network down", file=sys.stderr)
    sys.exit(1)
print(json.dumps(answer))
"""


def pr(number, state, repo="o/code"):
    return {"number": number, "state": state, "headRefOid": "0" * 40,
            "headRepository": {"name": repo.split("/")[1], "nameWithOwner": repo}}


class Sweep(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        self.run_git(self.tmp, "init", "-q", "--bare", "-b", "main", "origin.git")
        self.run_git(self.tmp, "clone", "-q", "origin.git", "clone")
        self.clone = self.tmp / "clone"
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("checkout", "-q", "-b", "main")
        (self.clone / ".agents").mkdir()
        (self.clone / ".agents" / "dev-process.md").write_text(
            '+++\n[tracker]\nissues_repo = "o/code"\ncode_repo = "o/code"\n+++\n')
        self.git("add", ".agents")
        self.git("commit", "-q", "-m", "base")
        self.git("push", "-q", "origin", "main")
        bin_dir = self.tmp / "ghbin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(FAKE_GH)
        (bin_dir / "gh").chmod(0o755)
        self.fixture = self.tmp / "gh.json"
        self.fixture.write_text("{}")
        self.env = {**ENV, "PATH": f"{bin_dir}{os.pathsep}{ENV['PATH']}", "FAKE_GH": str(self.fixture)}

    def run_git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True)

    def git(self, *args):
        return self.run_git(self.clone, *args)

    def worktree(self, branch, name=None):
        path = self.tmp / (name or branch.replace("/", "-"))
        self.git("worktree", "add", "-q", "-b", branch, str(path), "main")
        return path

    def branches(self):
        return self.git("branch", "--format=%(refname:short)").stdout.split()

    def sweep(self, *args, fixture=None, cwd=None):
        self.fixture.write_text(json.dumps(fixture or {}))
        out = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd or self.clone,
                             env=self.env, capture_output=True, text=True)
        self.stderr = out.stderr
        return out.returncode, out.stdout.splitlines()

    def test_1_a_merged_pr_removes_the_worktree_and_its_branch(self):
        path = self.worktree("fix/12-x")
        fixture = {"pr": {"fix/12-x": [pr(3, "MERGED")]}}
        self.assertEqual(self.sweep(fixture=fixture), (0, [f"remove {path} (fix/12-x): PR #3 merged"]))
        code, _ = self.sweep("--apply", fixture=fixture)
        self.assertEqual(code, 0, self.stderr)
        self.assertFalse(path.exists())
        self.assertNotIn("fix/12-x", self.branches())

    def test_2_a_closed_issue_removes_the_worktree_and_keeps_the_branch(self):
        path = self.worktree("fix/12-x")
        fixture = {"issue": {"12": {"state": "CLOSED", "comments": []}}}
        self.assertEqual(self.sweep(fixture=fixture), (0, [f"remove {path} (fix/12-x): issue #12 closed"]))
        self.sweep("--apply", fixture=fixture)
        self.assertFalse(path.exists())
        self.assertIn("fix/12-x", self.branches())

    def test_3_uncommitted_changes_keep_it(self):
        path = self.worktree("fix/12-x")
        (path / "notes.txt").write_text("draft\n")
        fixture = {"pr": {"fix/12-x": [pr(3, "MERGED")]}}
        self.assertEqual(self.sweep("--apply", fixture=fixture),
                         (1, [f"keep {path} (fix/12-x): uncommitted changes"]))
        self.assertTrue((path / "notes.txt").exists())

    def test_4_a_commit_on_no_remote_keeps_it(self):
        path = self.worktree("fix/12-x")
        self.run_git(path, "commit", "-q", "--allow-empty", "-m", "local only")
        fixture = {"pr": {"fix/12-x": [pr(3, "MERGED")]}}
        self.assertEqual(self.sweep(fixture=fixture), (1, [f"keep {path} (fix/12-x): 1 commit(s) on no remote"]))

    def test_5_an_open_issue_with_no_merged_pr_keeps_it(self):
        path = self.worktree("fix/12-x")
        fixture = {"pr": {"fix/12-x": [pr(3, "CLOSED")]}, "issue": {"12": {"state": "OPEN", "comments": []}}}
        self.assertEqual(self.sweep("--apply", fixture=fixture),
                         (1, [f"keep {path} (fix/12-x): issue #12 open, work not merged"]))
        self.assertTrue(path.exists())

    def test_6_no_number_detached_and_locked_are_kept(self):
        plain = self.worktree("issue-x")
        detached = self.tmp / "detached"
        self.git("worktree", "add", "-q", "--detach", str(detached), "main")
        locked = self.worktree("fix/13-y")
        self.git("worktree", "lock", str(locked))
        code, lines = self.sweep("--apply", fixture={"issue": {"13": {"state": "CLOSED", "comments": []}}})
        self.assertEqual(code, 1)
        self.assertEqual(sorted(lines), sorted([f"keep {plain} (issue-x): no issue number in issue-x",
                                                f"keep {detached} (detached): detached HEAD",
                                                f"keep {locked} (fix/13-y): locked"]))
        self.assertTrue(locked.exists())

    def test_7_the_main_worktree_and_the_current_one_are_never_listed(self):
        here = self.worktree("fix/12-x")
        other = self.worktree("fix/14-z")
        fixture = {"issue": {"12": {"state": "CLOSED", "comments": []}, "14": {"state": "CLOSED", "comments": []}}}
        code, lines = self.sweep("--apply", fixture=fixture, cwd=here)
        self.assertEqual(lines, [f"remove {other} (fix/14-z): issue #14 closed"])
        self.assertTrue(here.exists())
        self.assertTrue(self.clone.exists())

    def test_8_a_failing_gh_keeps_everything(self):
        path = self.worktree("fix/12-x")
        code, lines = self.sweep("--apply", fixture={"down": True})
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith(f"keep {path} (fix/12-x): cannot tell: "), lines)
        self.assertTrue(path.exists())

    def test_8_a_failed_issue_lookup_is_not_a_closed_issue(self):
        path = self.worktree("fix/12-x")
        code, lines = self.sweep("--apply", fixture={"issue": {"12": "fail"}})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith(f"keep {path} (fix/12-x): cannot tell: "), lines)
        self.assertTrue(path.exists())

    def test_9_only_considers_that_worktree(self):
        first = self.worktree("fix/12-x")
        self.worktree("fix/14-z")
        fixture = {"issue": {"12": {"state": "CLOSED", "comments": []}, "14": {"state": "OPEN", "comments": []}}}
        self.assertEqual(self.sweep("--only", str(first), fixture=fixture),
                         (0, [f"remove {first} (fix/12-x): issue #12 closed"]))

    def test_10_a_folder_deleted_by_hand_is_pruned(self):
        path = self.worktree("fix/12-x")
        shutil.rmtree(path)
        self.sweep("--apply", fixture={"issue": {"12": {"state": "OPEN", "comments": []}}})
        listed = self.git("worktree", "list", "--porcelain").stdout
        self.assertNotIn(str(path), listed)

    def test_an_unreadable_worktree_list_exits_2(self):
        code, _ = self.sweep(cwd=self.tmp)
        self.assertEqual(code, 2)
        self.assertIn("cannot list the worktrees", self.stderr)


if __name__ == "__main__":
    unittest.main()
