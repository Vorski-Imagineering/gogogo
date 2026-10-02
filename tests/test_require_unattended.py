"""require_unattended.sh finds this session's transcript by its session id.

The script used to name the transcript's folder from the current directory, so
run from a worktree (as auto-dev on this repo must) it found nothing and
refused every merge. Each test runs the real script with HOME pointed at a
temporary directory, and a fake `ps` first on PATH that exits 1, so the
headless fallback (`started_in_bypass`) can never pass a case for the wrong
reason when the suite itself runs under `claude -p` in bypass mode.
"""
import json
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "plugins", "gogogo", "scripts", "require_unattended.sh")
SESSION = "0f6e1c2a-1111-4222-8333-444455556666"


class RequireUnattendedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self.home = os.path.join(self.tmp, "home")
        self.projects = os.path.join(self.home, ".claude", "projects")
        os.makedirs(self.projects)
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        ps = os.path.join(bindir, "ps")
        with open(ps, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(ps, 0o755)
        self.elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(self.elsewhere)
        self.env = {
            "HOME": self.home,
            "CLAUDE_CODE_SESSION_ID": SESSION,
            "PATH": bindir + ":/usr/bin:/bin",
        }

    def tearDown(self):
        self._tmp.cleanup()

    def transcript(self, folder, *modes):
        d = os.path.join(self.projects, folder)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, SESSION + ".jsonl"), "w") as f:
            for m in modes:
                f.write(json.dumps({"type": "user", "permissionMode": m}, separators=(",", ":")) + "\n")

    def run_script(self, cwd=None, env=None):
        return subprocess.run(
            ["sh", SCRIPT], cwd=cwd or self.elsewhere, env=env or self.env,
            capture_output=True, text=True,
        )

    def test_found_from_a_folder_that_is_not_the_start_folder(self):
        self.transcript("-Users-someone-repo", "bypassPermissions")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "bypassPermissions: on")

    def test_found_elsewhere_still_checks_the_mode(self):
        self.transcript("-Users-someone-repo", "default")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("permission mode is 'default'", r.stderr)

    def test_the_last_mode_counts(self):
        self.transcript("-Users-someone-repo", "bypassPermissions", "default")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("permission mode is 'default'", r.stderr)

    def test_no_transcript_fails(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no session transcript named", r.stderr)
        self.assertIn(SESSION, r.stderr)

    def test_two_matches_fail(self):
        self.transcript("-Users-someone-repo", "bypassPermissions")
        self.transcript("-Users-someone-copy", "bypassPermissions")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("2 session transcripts", r.stderr)

    def test_start_folder_keeps_working(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        folder = os.path.realpath(repo).replace("/", "-").replace(".", "-")
        self.transcript(folder, "bypassPermissions")
        r = self.run_script(cwd=repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_session_id_fails(self):
        self.transcript("-Users-someone-repo", "bypassPermissions")
        env = dict(self.env)
        del env["CLAUDE_CODE_SESSION_ID"]
        r = self.run_script(env=env)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
