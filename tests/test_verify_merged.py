#!/usr/bin/env python3
"""Tests for verify_merged.py's `--ships` (the link read back from the merge
commit) and `--open` (the issue the merge must leave open).

Real git with a local bare `origin`, because the claim is about what git reads
from the commit; only `gh` is faked: the PR's merge commit and closing
references, the repo's default branch, and the issue's state.

    python3 -m unittest tests.test_verify_merged
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import stage_sync  # noqa: E402
import verify_merged as vm  # noqa: E402

PROFILE = """+++
profile = 1

[tracker]
issues_repo = "acme/issues"
code_repo = "acme/code"
+++
"""


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Repo(unittest.TestCase):
    """A clone with a local bare `origin`, and the profile."""

    def setUp(self):
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory(prefix="verify-merged-")
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        git("init", "-q", "--bare", "-b", "main", str(base / "origin.git"), cwd=base)
        git("clone", "-q", str(base / "origin.git"), str(base / "work"), cwd=base)
        self.work = base / "work"
        self.profile = base / "dev-process.md"
        self.profile.write_text(PROFILE)
        cwd = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, cwd)

    def merge(self, message):
        """A commit on origin/main, as a squash merge leaves one."""
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
            "-m", message, cwd=self.work)
        git("push", "-q", "origin", "HEAD:main", cwd=self.work)
        return git("rev-parse", "HEAD", cwd=self.work)


class Ships(Repo):
    def verify(self, sha, *extra, state="MERGED"):
        real_run = vm.run

        def fake_run(*cmd):
            if cmd[0] == "gh":
                return mock.Mock(returncode=0, stderr="",
                                 stdout=json.dumps({"state": state, "mergeCommit": {"oid": sha}}))
            return real_run(*cmd)

        out = io.StringIO()
        with mock.patch.object(vm, "run", side_effect=fake_run), \
             redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = vm.main(["7", "main", "--profile", str(self.profile), *extra])
        return code, out.getvalue()

    def test_ships_reads_the_merge_commits_trailer(self):
        sha = self.merge("Fix it (#7)\n\n* fix it\n\nShips-issue: acme/issues#450 reporter=jdoe\n"
                         "Co-Authored-By: A <a@x>")
        code, out = self.verify(sha, "--ships", "acme/issues#450")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("MERGED "))

        code, out = self.verify(sha, "--ships", "acme/issues#451")
        self.assertEqual(code, 3)
        self.assertIn("but no Ships-issue: acme/issues#451", out)

    def test_the_legacy_short_form_still_checks(self):
        sha = self.merge("Fix it (#7)\n\nShips-issue: issues#450")
        self.assertEqual(self.verify(sha, "--ships", "acme/issues#450")[0], 0)

    def test_a_short_form_for_another_repo_is_rejected_by_both_readers(self):
        """One reader: verify_merged accepts exactly what stage_sync reads."""
        sha = self.merge("Fix it (#7)\n\nShips-issue: other-repo#12")
        code, out = self.verify(sha, "--ships", "acme/other-repo#12")
        self.assertEqual(code, 3, out)
        known = stage_sync.load_profile(str(self.profile)).known
        with self.assertRaises(ValueError):
            stage_sync.parse_trailer("other-repo#12", known)
        self.assertEqual(self.verify(sha, "--ships", "Acme/Issues#450")[0], 3)
        sha = self.merge("Fix it (#8)\n\nShips-issue: Acme/Issues#450")
        self.assertEqual(self.verify(sha, "--ships", "acme/issues#450")[0], 0)

    def test_an_unreadable_profile_still_checks_full_form_links(self):
        """No profile only loses the short form; the full form is still checked."""
        sha = self.merge("Fix it (#7)\n\nShips-issue: acme/issues#450\nShips-issue: issues#451")
        self.profile.write_text("not a profile")
        self.assertEqual(self.verify(sha, "--ships", "acme/issues#450")[0], 0)
        self.assertEqual(self.verify(sha, "--ships", "acme/issues#452")[0], 3)
        self.assertEqual(self.verify(sha, "--ships", "acme/issues#451")[0], 3)

    def test_without_ships_a_commit_with_no_trailer_still_passes(self):
        sha = self.merge("Fix it (#7)")
        self.assertEqual(self.verify(sha)[0], 0)

    def test_an_unmerged_pr_is_still_not_merged(self):
        sha = self.merge("Fix it (#7)\n\nShips-issue: acme/issues#450")
        code, out = self.verify(sha, "--ships", "acme/issues#450", state="OPEN")
        self.assertEqual(code, 1)
        self.assertIn("NOT-MERGED", out)


class Open(Repo):
    """`--open`: the merge must leave the issue open. GitHub closes it a moment
    after the merge, so the script waits when something in the merge will close it."""

    def setUp(self):
        super().setUp()
        self.merge("base")  # so every merge below has a first parent

    def verify(self, sha, *extra, refs=(), states=("OPEN",), default="main", fail=()):
        real_run = vm.run
        self.state_reads = 0
        self.clock = 0.0
        self.slept = 0

        def fake_run(*cmd):
            if cmd[:3] == ("gh", "pr", "view"):
                return mock.Mock(returncode=0, stderr="", stdout=json.dumps({
                    "state": "MERGED", "mergeCommit": {"oid": sha},
                    "closingIssuesReferences": [{"url": u} for u in refs]}))
            if cmd[:3] == ("gh", "repo", "view"):
                if "repo" in fail:
                    return mock.Mock(returncode=1, stdout="", stderr="HTTP 502")
                return mock.Mock(returncode=0, stderr="", stdout=default + "\n")
            if cmd[:3] == ("gh", "issue", "view"):
                if "issue" in fail:
                    return mock.Mock(returncode=1, stdout="", stderr="HTTP 502")
                state = states[min(self.state_reads, len(states) - 1)]
                self.state_reads += 1
                return mock.Mock(returncode=0, stderr="", stdout=state + "\n")
            return real_run(*cmd)

        def fake_sleep(seconds):
            self.slept += 1
            self.clock += seconds

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(vm, "run", side_effect=fake_run), \
             mock.patch.object(vm.time, "sleep", side_effect=fake_sleep), \
             mock.patch.object(vm.time, "monotonic", side_effect=lambda: self.clock), \
             redirect_stdout(out), redirect_stderr(err):
            code = vm.main(["7", "main", "--profile", str(self.profile), *extra])
        return code, out.getvalue() + err.getvalue()

    def test_waits_for_the_close_a_closing_keyword_brings(self):
        sha = self.merge("Fix it\n\nFix: acme/issues#7")
        code, out = self.verify(sha, "--open", "acme/issues#7", states=("OPEN", "OPEN", "CLOSED"))
        self.assertEqual(code, 4, out)
        self.assertIn("CLOSED by this merge: acme/issues#7", out)
        self.assertEqual(self.state_reads, 3)

    def test_a_closing_reference_in_the_pr_counts(self):
        sha = self.merge("Fix it")
        code, out = self.verify(sha, "--open", "acme/issues#7",
                                refs=["https://github.com/acme/issues/issues/7"], states=("OPEN", "CLOSED"))
        self.assertEqual(code, 4, out)

    def test_no_closer_reads_once_and_never_waits(self):
        sha = self.merge("Fix it\n\nRefs acme/issues#7")
        code, out = self.verify(sha, "--open", "acme/issues#7")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state_reads, 1)
        self.assertEqual(self.slept, 0)

    def test_a_closer_that_never_fires_cannot_tell(self):
        sha = self.merge("Fix it\n\nCloses acme/issues#7")
        code, out = self.verify(sha, "--open", "acme/issues#7", states=("OPEN",))
        self.assertEqual(code, 2, out)
        self.assertIn("acme/issues#7", out)
        self.assertIn("still open", out)

    def test_a_close_from_elsewhere_still_reports(self):
        sha = self.merge("Fix it")
        code, out = self.verify(sha, "--open", "acme/issues#7", states=("CLOSED",))
        self.assertEqual(code, 4, out)
        self.assertIn("CLOSED (not by a closing reference in this merge): acme/issues#7", out)

    def test_no_closer_fires_off_the_default_branch(self):
        sha = self.merge("Fix it\n\nCloses acme/issues#7")
        code, out = self.verify(sha, "--open", "acme/issues#7", default="trunk")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.slept, 0)

    def test_the_short_form_means_the_prs_own_repo(self):
        sha = self.merge("Fix it\n\nCloses #7")
        code, out = self.verify(sha, "--open", "acme/issues#7")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.slept, 0)

    def test_the_short_form_counts_in_the_same_repo(self):
        sha = self.merge("Fix it\n\ncloses #7")
        code, out = self.verify(sha, "--repo", "acme/issues", "--open", "acme/issues#7",
                                states=("OPEN", "CLOSED"))
        self.assertEqual(code, 4, out)

    def test_seven_is_not_seventy(self):
        sha = self.merge("Fix it\n\nFixes acme/issues#70")
        code, out = self.verify(sha, "--open", "acme/issues#7")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.slept, 0)

    def test_every_commit_a_merge_commit_brings_counts(self):
        git("switch", "-q", "-c", "side", cwd=self.work)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
            "-m", "Side\n\nResolves acme/issues#7", cwd=self.work)
        git("switch", "-q", "main", cwd=self.work)
        git("-c", "user.name=t", "-c", "user.email=t@t", "merge", "-q", "--no-ff", "-m", "Merge side",
            "side", cwd=self.work)
        git("push", "-q", "origin", "HEAD:main", cwd=self.work)
        sha = git("rev-parse", "HEAD", cwd=self.work)
        code, out = self.verify(sha, "--open", "acme/issues#7", states=("OPEN", "CLOSED"))
        self.assertEqual(code, 4, out)

    def test_a_missing_link_and_a_closed_issue_both_report(self):
        sha = self.merge("Fix it")
        code, out = self.verify(sha, "--ships", "acme/issues#7", "--open", "acme/issues#7", states=("CLOSED",))
        self.assertEqual(code, 4, out)
        self.assertIn("no Ships-issue: acme/issues#7", out)
        self.assertIn("CLOSED (not by a closing reference in this merge): acme/issues#7", out)

    def test_every_open_link_is_checked_when_one_cannot_tell(self):
        sha = self.merge("Fix it\n\nCloses acme/issues#7")
        code, out = self.verify(sha, "--open", "acme/issues#7", "--open", "acme/issues#8",
                                states=("OPEN",) * 13 + ("CLOSED",))
        self.assertEqual(code, 2, out)
        self.assertIn("acme/issues#7 is named by a closing reference", out)
        self.assertIn("CLOSED (not by a closing reference in this merge): acme/issues#8", out)
        self.assertFalse(any(line.startswith("MERGED") for line in out.splitlines()), out)

    def test_cannot_tell_does_not_print_merged(self):
        sha = self.merge("Fix it")
        code, out = self.verify(sha, "--open", "acme/issues#7", fail=("issue",))
        self.assertEqual(code, 2)
        self.assertFalse(any(line.startswith("MERGED") for line in out.splitlines()), out)

    def test_an_unreadable_state_cannot_tell(self):
        sha = self.merge("Fix it")
        self.assertEqual(self.verify(sha, "--open", "acme/issues#7", fail=("issue",))[0], 2)

    def test_an_unreadable_default_branch_cannot_tell(self):
        sha = self.merge("Fix it")
        self.assertEqual(self.verify(sha, "--open", "acme/issues#7", fail=("repo",))[0], 2)


if __name__ == "__main__":
    unittest.main()
