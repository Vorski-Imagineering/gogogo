#!/usr/bin/env python3
"""Tests for verify_merged.py's `--ships`: the link read back from the merge commit.

Real git with a local bare `origin`, because the claim is about what git reads
from the commit; only `gh pr view` is faked, to return that commit's oid.

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


class Ships(unittest.TestCase):
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

    def test_without_ships_a_commit_with_no_trailer_still_passes(self):
        sha = self.merge("Fix it (#7)")
        self.assertEqual(self.verify(sha)[0], 0)

    def test_an_unmerged_pr_is_still_not_merged(self):
        sha = self.merge("Fix it (#7)\n\nShips-issue: acme/issues#450")
        code, out = self.verify(sha, "--ships", "acme/issues#450", state="OPEN")
        self.assertEqual(code, 1)
        self.assertIn("NOT-MERGED", out)


if __name__ == "__main__":
    unittest.main()
