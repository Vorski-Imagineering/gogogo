#!/usr/bin/env python3
"""Tests for which worktrees worktree_sweep.py removes and which it keeps (gogogo#92).

Each test builds real repos in a temp dir (a bare `origin`, a clone with a
committed profile, worktrees beside it) and runs the script as a subprocess
from the clone, with a fake `gh` on PATH that answers from a JSON fixture.

    python3 -m unittest tests.test_worktree_sweep
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "scripts" / "worktree_sweep.py"

# Keep the machine's git config (hooks, signing, default branch) out of the tests.
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

# Answers `pr list` and `issue view` from the fixture; anything missing, or "fail", fails.
FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if os.environ.get("FAKE_GH_LOG"):
    open(os.environ["FAKE_GH_LOG"], "a").write(" ".join(args) + "\\n")
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

# Runs the real git, except `git branch -D` when FAKE_GIT_REFUSE_D is set (silently when it is
# "quiet") and `git rev-list` when FAKE_GIT_FAIL_REVLIST is set.
FAKE_GIT = """#!/bin/sh
if [ -n "$FAKE_GIT_REFUSE_D" ] && [ "$1" = branch ] && [ "$2" = -D ]; then
    [ "$FAKE_GIT_REFUSE_D" = quiet ] || echo "fatal: refused by the test" >&2
    exit 1
fi
if [ -n "$FAKE_GIT_FAIL_REVLIST" ] && [ "$1" = rev-list ]; then
    exit 1
fi
exec {git} "$@"
"""


def pr(number, state, repo="o/code", oid="0" * 40):
    return {"number": number, "state": state, "headRefOid": oid,
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
        (bin_dir / "git").write_text(FAKE_GIT.format(git=shutil.which("git")))
        (bin_dir / "git").chmod(0o755)
        self.fixture = self.tmp / "gh.json"
        self.fixture.write_text("{}")
        self.gh_log = self.tmp / "gh.log"
        self.env = {**ENV, "PATH": f"{bin_dir}{os.pathsep}{ENV['PATH']}", "FAKE_GH": str(self.fixture),
                    "FAKE_GH_LOG": str(self.gh_log)}

    def run_git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True)

    def git(self, *args):
        return self.run_git(self.clone, *args)

    def worktree(self, branch, name=None):
        path = self.tmp / (name or branch.replace("/", "-"))
        self.git("worktree", "add", "-q", "-b", branch, str(path), "main")
        return path

    def tip(self, branch):
        return self.git("rev-parse", f"refs/heads/{branch}").stdout.strip()

    def merged(self, branch, number=3):
        return {"pr": {branch: [pr(number, "MERGED", oid=self.tip(branch))]}}

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
        fixture = self.merged("fix/12-x")
        self.assertEqual(self.sweep(fixture=fixture), (0, [f"remove {path} (fix/12-x): PR #3 merged"]))
        self.assertTrue(path.exists(), "removed without --apply")
        self.assertEqual(self.sweep("--apply", fixture=fixture), (0, [f"remove {path} (fix/12-x): PR #3 merged"]))
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
        plain = self.worktree("issue-46")
        detached = self.tmp / "detached"
        self.git("worktree", "add", "-q", "--detach", str(detached), "main")
        locked = self.worktree("fix/13-y")
        self.git("worktree", "lock", "--reason", "in use", str(locked))
        bare_lock = self.worktree("fix/15-w")
        self.git("worktree", "lock", str(bare_lock))
        fixture = {"issue": {"13": {"state": "CLOSED", "comments": []}, "15": {"state": "CLOSED", "comments": []}}}
        code, lines = self.sweep("--apply", fixture=fixture)
        self.assertEqual(code, 1)
        self.assertEqual(sorted(lines), sorted([f"keep {plain} (issue-46): no issue number in issue-46",
                                                f"keep {detached} (detached): detached HEAD",
                                                f"keep {locked} (fix/13-y): locked",
                                                f"keep {bare_lock} (fix/15-w): locked"]))
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

    def test_9_only_from_inside_that_worktree_says_why_nothing_is_removed(self):
        here = self.worktree("fix/12-x")
        fixture = {"issue": {"12": {"state": "CLOSED", "comments": []}}}
        line = f"keep {here} (fix/12-x): the current directory is inside it; run this from {self.clone}"
        self.assertEqual(self.sweep("--only", str(here), fixture=fixture, cwd=here), (1, [line]))

    def test_9_only_from_inside_with_apply_removes_nothing(self):
        here = self.worktree("fix/12-x")
        fixture = {"issue": {"12": {"state": "CLOSED", "comments": []}}}
        line = f"keep {here} (fix/12-x): the current directory is inside it; run this from {self.clone}"
        self.assertEqual(self.sweep("--apply", "--only", str(here), fixture=fixture, cwd=here), (1, [line]))
        self.assertTrue(here.exists())
        self.assertIn("fix/12-x", self.branches())

    def test_9_only_from_a_subfolder_of_that_worktree_says_the_same(self):
        here = self.worktree("fix/12-x")
        sub = here / ".agents"
        sub.mkdir(exist_ok=True)
        line = f"keep {here} (fix/12-x): the current directory is inside it; run this from {self.clone}"
        self.assertEqual(self.sweep("--only", str(here), cwd=sub), (1, [line]))

    def test_9_only_from_inside_a_detached_worktree_names_it_detached(self):
        here = self.tmp / "detached-here"
        self.git("worktree", "add", "-q", "--detach", str(here), "main")
        line = f"keep {here} (detached): the current directory is inside it; run this from {self.clone}"
        self.assertEqual(self.sweep("--only", str(here), cwd=here), (1, [line]))

    def test_9_only_a_path_that_is_no_worktree_is_a_usage_error(self):
        folder = self.tmp / "plain"
        folder.mkdir()
        code, lines = self.sweep("--only", str(folder))
        self.assertEqual((code, lines), (2, []))
        self.assertEqual(self.stderr.strip(), f"worktree_sweep: {folder} is not a worktree of this repo")

    def test_9_only_the_main_worktree_is_kept_with_a_reason(self):
        self.assertEqual(self.sweep("--only", str(self.clone)),
                         (1, [f"keep {self.clone} (main): the main worktree is never removed"]))

    def local_branch(self, name, commits=1):
        """A local branch `commits` commits ahead of main, on no remote."""
        sha = self.git("rev-parse", "main").stdout.strip()
        tree = self.git("rev-parse", "main^{tree}").stdout.strip()
        for n in range(commits):
            sha = self.git("commit-tree", tree, "-p", sha, "-m", f"{name} {n}").stdout.strip()
        self.git("update-ref", f"refs/heads/{name}", sha)
        return sha

    def looked_up(self):
        return self.gh_log.read_text() if self.gh_log.exists() else ""

    def test_11_a_merged_pr_at_the_tip_removes_the_local_branch(self):
        tip = self.local_branch("fix/12-x")
        fixture = {"pr": {"fix/12-x": [pr(3, "MERGED", oid=tip)]}}
        line = "remove branch fix/12-x: PR #3 merged at its tip"
        self.assertEqual(self.sweep(fixture=fixture), (0, [line]))
        self.assertIn("fix/12-x", self.branches(), "removed without --apply")
        self.assertEqual(self.sweep("--apply", fixture=fixture), (0, [line]))
        self.assertNotIn("fix/12-x", self.branches())

    def test_11_a_merged_pr_from_an_older_tip_keeps_the_branch(self):
        tip = self.local_branch("fix/12-x", commits=2)
        older = self.git("rev-parse", f"{tip}^").stdout.strip()
        code, lines = self.sweep("--apply", fixture={"pr": {"fix/12-x": [pr(3, "MERGED", oid=older)]}})
        self.assertEqual((code, lines), (0, []))
        self.assertIn("fix/12-x", self.branches())

    def test_11_a_merged_pr_whose_head_is_ahead_of_the_tip_keeps_the_branch(self):
        head = self.local_branch("fix/12-x", commits=2)
        tip = self.git("rev-parse", f"{head}^").stdout.strip()
        self.git("update-ref", "refs/heads/fix/12-x", tip)
        code, lines = self.sweep("--apply", fixture={"pr": {"fix/12-x": [pr(3, "MERGED", oid=head)]}})
        self.assertEqual((code, lines), (0, []))
        self.assertIn("fix/12-x", self.branches())

    def test_11_an_open_pr_or_none_keeps_the_branch(self):
        tip = self.local_branch("fix/12-x")
        self.local_branch("fix/13-y")
        fixture = {"pr": {"fix/12-x": [pr(3, "OPEN", oid=tip)]}}
        self.assertEqual(self.sweep("--apply", fixture=fixture), (0, []))
        self.assertIn("fix/12-x", self.branches())
        self.assertIn("fix/13-y", self.branches())

    def test_11_a_branch_with_nothing_off_the_remotes_is_not_looked_up(self):
        self.git("branch", "fix/12-x", "main")
        self.assertEqual(self.sweep("--apply"), (0, []))
        self.assertNotIn("fix/12-x", self.looked_up())
        self.assertIn("fix/12-x", self.branches())

    def test_11_the_base_the_current_and_a_worktree_branch_are_never_touched(self):
        base_tip = self.local_branch("scratch")
        self.git("update-ref", "refs/heads/main", base_tip)
        current = self.local_branch("fix/12-x")
        self.git("switch", "-q", "fix/12-x")
        checked_out = self.local_branch("fix/13-y")
        self.git("worktree", "add", "-q", str(self.tmp / "wt-13"), "fix/13-y")
        (self.tmp / "wt-13" / "dirty.txt").write_text("not committed\n")
        fixture = {"pr": {"main": [pr(1, "MERGED", oid=base_tip)], "fix/12-x": [pr(2, "MERGED", oid=current)],
                          "fix/13-y": [pr(3, "MERGED", oid=checked_out)]},
                   "issue": {"13": {"state": "OPEN", "comments": []}}}
        code, lines = self.sweep("--apply", fixture=fixture)
        self.assertFalse([ln for ln in lines if ln.startswith("remove branch")], lines)
        self.assertTrue({"main", "fix/12-x", "fix/13-y"} <= set(self.branches()))
        self.assertNotIn("pr list --repo o/code --head main ", self.looked_up())

    def test_11_a_branch_only_on_origin_is_untouched(self):
        sha = self.local_branch("fix/15-w")
        self.git("push", "-q", "origin", "fix/15-w")
        self.git("branch", "-q", "-D", "fix/15-w")
        fixture = {"pr": {"fix/15-w": [pr(5, "MERGED", oid=sha)]}}
        self.assertEqual(self.sweep("--apply", fixture=fixture), (0, []))
        self.assertIn("fix/15-w", self.git("ls-remote", "--heads", "origin").stdout)

    def test_11_a_branch_that_will_not_delete_is_kept_and_reported(self):
        tip = self.local_branch("fix/12-x")
        self.env["FAKE_GIT_REFUSE_D"] = "1"
        code, lines = self.sweep("--apply", fixture={"pr": {"fix/12-x": [pr(3, "MERGED", oid=tip)]}})
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["remove branch fix/12-x: PR #3 merged at its tip",
                                 "  branch fix/12-x kept: fatal: refused by the test"])
        self.assertIn("fix/12-x", self.branches())

    def test_11_a_branch_that_will_not_delete_and_says_nothing_is_still_reported(self):
        tip = self.local_branch("fix/12-x")
        self.env["FAKE_GIT_REFUSE_D"] = "quiet"
        code, lines = self.sweep("--apply", fixture={"pr": {"fix/12-x": [pr(3, "MERGED", oid=tip)]}})
        self.assertEqual(code, 1)
        self.assertEqual(lines[1], "  branch fix/12-x kept: git branch -D exited 1")

    def test_11_a_branch_git_cannot_count_is_kept(self):
        tip = self.local_branch("fix/12-x")
        self.env["FAKE_GIT_FAIL_REVLIST"] = "1"
        self.assertEqual(self.sweep("--apply", fixture={"pr": {"fix/12-x": [pr(3, "MERGED", oid=tip)]}}), (0, []))
        self.assertIn("fix/12-x", self.branches())

    def test_11_a_branch_that_stays_does_not_stop_the_sweep_of_the_next(self):
        first = self.local_branch("fix/11-a")
        second = self.local_branch("fix/12-b")
        fixture = {"pr": {"fix/11-a": [pr(2, "OPEN", oid=first)], "fix/12-b": [pr(3, "MERGED", oid=second)]}}
        self.assertEqual(self.sweep("--apply", fixture=fixture), (0, ["remove branch fix/12-b: PR #3 merged at its tip"]))
        self.assertEqual(sorted(b for b in self.branches() if b.startswith("fix/")), ["fix/11-a"])

    def test_11_the_base_is_the_profiles_integration_base_else_main(self):
        sys.path.insert(0, str(SCRIPT.parent))
        import worktree_sweep
        profile = self.tmp / "profile.md"
        profile.write_text('+++\n[integration]\nbase = "develop"\n+++\n')
        with mock.patch.object(worktree_sweep.profile_check, "find_profile", return_value=profile):
            self.assertEqual(worktree_sweep.base_branch(), "develop")
        profile.write_text('+++\n[tracker]\nissues_repo = "o/code"\n+++\n')
        with mock.patch.object(worktree_sweep.profile_check, "find_profile", return_value=profile):
            self.assertEqual(worktree_sweep.base_branch(), "main")
        with mock.patch.object(worktree_sweep.profile_check, "find_profile", return_value=self.tmp / "missing.md"):
            self.assertEqual(worktree_sweep.base_branch(), "main")

    def test_11_a_failed_lookup_keeps_the_branch(self):
        self.local_branch("fix/12-x")
        self.assertEqual(self.sweep("--apply", fixture={"down": True}), (0, []))
        self.assertIn("fix/12-x", self.branches())

    def test_11_only_runs_no_branch_sweep(self):
        tip = self.local_branch("fix/12-x")
        here = self.worktree("fix/14-z")
        fixture = {"pr": {"fix/12-x": [pr(3, "MERGED", oid=tip)]},
                   "issue": {"14": {"state": "CLOSED", "comments": []}}}
        code, lines = self.sweep("--apply", "--only", str(here), fixture=fixture)
        self.assertEqual(lines, [f"remove {here} (fix/14-z): issue #14 closed"])
        self.assertIn("fix/12-x", self.branches())

    def test_10_a_folder_deleted_by_hand_is_pruned(self):
        path = self.worktree("fix/12-x")
        shutil.rmtree(path)
        code, lines = self.sweep("--apply", fixture={"issue": {"12": {"state": "OPEN", "comments": []}}})
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith(f"keep {path} (fix/12-x): cannot tell: fatal: "), lines)
        listed = self.git("worktree", "list", "--porcelain").stdout
        self.assertNotIn(str(path), listed)

    def test_every_remove_is_listed_without_apply(self):
        first, second = self.worktree("fix/12-x"), self.worktree("fix/14-z")
        fixture = {"issue": {"12": {"state": "CLOSED", "comments": []}, "14": {"state": "CLOSED", "comments": []}}}
        self.assertEqual(self.sweep(fixture=fixture), (0, [f"remove {first} (fix/12-x): issue #12 closed",
                                                          f"remove {second} (fix/14-z): issue #14 closed"]))
        self.assertTrue(first.exists() and second.exists())

    def test_a_profile_naming_one_repo_cannot_tell(self):
        (self.clone / ".agents" / "dev-process.md").write_text('+++\n[tracker]\ncode_repo = "o/code"\n+++\n')
        self.git("commit", "-q", "-am", "one repo")
        self.git("push", "-q", "origin", "main")
        path = self.worktree("fix/12-x")
        self.assertEqual(self.sweep(fixture={"pr": {"fix/12-x": [pr(3, "MERGED")]}}),
                         (1, [f"keep {path} (fix/12-x): cannot tell: the profile names no tracker.code_repo "
                              "or tracker.issues_repo"]))

    def in_process(self, fail, *args, fixture):
        """Run main() in the clone with `git <fail...>` answering exit 1 "refused"; (code, stdout)."""
        sys.path.insert(0, str(SCRIPT.parent))
        import worktree_sweep
        self.fixture.write_text(json.dumps(fixture))
        real = worktree_sweep.git

        def git(*argv):
            if argv[:len(fail)] == fail:
                return subprocess.CompletedProcess(["git", *argv], 1, "", "refused\n")
            return real(*argv)
        out = io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.clone)
        self.addCleanup(os.chdir, cwd)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(worktree_sweep, "git", git), \
                contextlib.redirect_stdout(out):
            code = worktree_sweep.main(list(args))
        return code, out.getvalue().splitlines()

    def test_a_refused_remove_keeps_it_and_goes_on(self):
        first, second = self.worktree("fix/12-x"), self.worktree("fix/14-z")
        fixture = {"issue": {"12": {"state": "CLOSED", "comments": []}, "14": {"state": "CLOSED", "comments": []}}}
        code, lines = self.in_process(("worktree", "remove", str(first)), "--apply", fixture=fixture)
        self.assertEqual(code, 1)
        self.assertEqual(lines, [f"remove {first} (fix/12-x): issue #12 closed", "  not removed: refused",
                                 f"remove {second} (fix/14-z): issue #14 closed"])
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())

    def test_a_refused_branch_delete_is_said_and_the_worktree_counts_as_removed(self):
        path = self.worktree("fix/12-x")
        code, lines = self.in_process(("branch", "-D"), "--apply", fixture=self.merged("fix/12-x"))
        self.assertEqual(code, 0)
        self.assertEqual(lines, [f"remove {path} (fix/12-x): PR #3 merged", "  branch fix/12-x kept: refused"])
        self.assertFalse(path.exists())

    def test_a_failed_count_of_unpushed_commits_cannot_tell(self):
        path = self.worktree("fix/12-x")
        code, lines = self.in_process(("rev-list",), fixture={"pr": {"fix/12-x": [pr(3, "MERGED")]}})
        self.assertEqual((code, lines), (1, [f"keep {path} (fix/12-x): cannot tell: refused"]))

    def test_a_squash_merged_branch_whose_remote_was_pruned_is_removed(self):
        path = self.worktree("fix/12-x")
        self.run_git(path, "commit", "-q", "--allow-empty", "-m", "the fix")
        self.run_git(path, "push", "-q", "origin", "fix/12-x")
        fixture = self.merged("fix/12-x")
        self.run_git(self.tmp / "origin.git", "branch", "-D", "fix/12-x")
        self.git("fetch", "-q", "--prune")
        self.assertEqual(self.sweep(fixture=fixture), (0, [f"remove {path} (fix/12-x): PR #3 merged"]))

    def test_a_merged_pr_from_an_older_tip_does_not_remove_new_work(self):
        path = self.worktree("fix/12-x")
        fixture = self.merged("fix/12-x")
        self.run_git(path, "commit", "-q", "--allow-empty", "-m", "more work")
        self.run_git(path, "push", "-q", "origin", "fix/12-x")
        fixture["issue"] = {"12": {"state": "OPEN", "comments": []}}
        self.assertEqual(self.sweep("--apply", fixture=fixture),
                         (1, [f"keep {path} (fix/12-x): issue #12 open, work not merged"]))
        self.assertIn("fix/12-x", self.branches())

    def test_a_pr_merged_from_a_newer_remote_head_still_removes(self):
        path = self.worktree("fix/12-x")
        self.run_git(path, "commit", "-q", "--allow-empty", "-m", "the fix")
        self.run_git(path, "commit", "-q", "--allow-empty", "-m", "update branch")
        self.run_git(path, "push", "-q", "origin", "fix/12-x")
        fixture = self.merged("fix/12-x")
        self.run_git(path, "reset", "-q", "--hard", "HEAD~1")
        self.assertEqual(self.sweep(fixture=fixture), (0, [f"remove {path} (fix/12-x): PR #3 merged"]))

    def test_a_tag_named_like_the_branch_does_not_hide_unpushed_commits(self):
        self.git("tag", "fix/12-x", "main")
        path = self.worktree("fix/12-x")
        self.run_git(path, "commit", "-q", "--allow-empty", "-m", "local only")
        fixture = {"issue": {"12": {"state": "CLOSED", "comments": []}}}
        self.assertEqual(self.sweep(fixture=fixture), (1, [f"keep {path} (fix/12-x): 1 commit(s) on no remote"]))

    def test_an_unreadable_worktree_list_exits_2(self):
        code, _ = self.sweep(cwd=self.tmp)
        self.assertEqual(code, 2)
        self.assertIn("cannot list the worktrees", self.stderr)


if __name__ == "__main__":
    unittest.main()
