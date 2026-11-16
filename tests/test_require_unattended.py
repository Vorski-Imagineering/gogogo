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

    def parent(self, comm, args):
        self.chain((comm, args))

    def chain(self, *procs):
        """Replace the fake `ps` with one whose walk meets `procs`, nearest first.

        Any pid it does not know is the script's own shell, whose parent is
        pid 1001; process 1000+k is procs[k-1], and the last one's parent is 1.
        """
        def q(v):
            return "'" + v.replace("'", "'\\''") + "'"
        rows = "".join(
            f"  {1001 + k}) comm={q(c)}; args={q(a)}; ppid={1002 + k if k + 1 < len(procs) else 1} ;;\n"
            for k, (c, a) in enumerate(procs))
        with open(os.path.join(self.tmp, "bin", "ps"), "w") as f:
            f.write(
                "#!/bin/sh\n"
                'case "$4" in\n'
                + rows +
                "  *) comm=sh; args='sh require_unattended.sh'; ppid=1001 ;;\n"
                "esac\n"
                'case "$2" in comm=) echo "$comm" ;; args=) echo "$args" ;; ppid=) echo "$ppid" ;; esac\n'
            )

    def bare_transcript(self, folder, *lines):
        d = os.path.join(self.projects, folder)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, SESSION + ".jsonl"), "w") as f:
            for line in lines:
                f.write(json.dumps(line, separators=(",", ":")) + "\n")

    def test_no_mode_recorded_passes_when_started_with_bypass(self):
        self.bare_transcript("-Users-someone-repo", {"type": "user"})
        self.parent("claude", "claude --permission-mode bypassPermissions")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(),
                         "bypassPermissions: on (started with a bypass flag; no mode change recorded)")

    def test_no_mode_recorded_fails_without_the_flag(self):
        self.bare_transcript("-Users-someone-repo", {"type": "user"})
        self.parent("claude", "claude --chrome")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not started with a bypass flag", r.stderr)
        self.assertIn("Shift+Tab", r.stderr)

    def test_a_recorded_mode_wins_over_the_flag(self):
        self.transcript("-Users-someone-repo", "default")
        self.parent("claude", "claude --permission-mode bypassPermissions")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("permission mode is 'default'", r.stderr)

    def test_permission_mode_record_type_is_read(self):
        self.bare_transcript("-Users-someone-repo", {"type": "user"},
                             {"type": "permission-mode", "permissionMode": "bypassPermissions"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "bypassPermissions: on")

    def test_a_shell_mentioning_the_flag_does_not_count(self):
        self.bare_transcript("-Users-someone-repo", {"type": "user"})
        self.parent("sh", 'sh -c "claude --permission-mode bypassPermissions"')
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not started with a bypass flag", r.stderr)

    def test_no_transcript_interactive_still_fails(self):
        self.parent("claude", "claude --permission-mode bypassPermissions")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no session transcript named", r.stderr)

    def test_the_first_claude_process_decides(self):
        self.bare_transcript("-Users-someone-repo", {"type": "user"})
        self.chain(("claude", "claude --chrome"),
                   ("claude", "claude --permission-mode bypassPermissions"))
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not started with a bypass flag", r.stderr)

    def test_a_background_session_named_by_its_version(self):
        self.bare_transcript("-Users-someone-repo", {"type": "user"})
        self.parent("2.1.325", "/home/someone/.local/share/claude/versions/2.1.325"
                    " --session-id x --permission-mode bypassPermissions")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_session_id_fails(self):
        self.transcript("-Users-someone-repo", "bypassPermissions")
        env = dict(self.env)
        del env["CLAUDE_CODE_SESSION_ID"]
        r = self.run_script(env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("CLAUDE_CODE_SESSION_ID is not set", r.stderr)


if __name__ == "__main__":
    unittest.main()
