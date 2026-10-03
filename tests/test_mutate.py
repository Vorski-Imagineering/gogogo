#!/usr/bin/env python3
"""Tests for tools/mutate.py, this repo's own `mutate` lane command (gogogo#45).

Git runs for real in a temporary repository; the mutation tool itself never
runs: `mutate._run` and `mutate._run_mutmut` are patched to answer for it, and
GOGOGO_MUTMUT points at a path that does not exist, so nothing is installed.
The wrapper and the stall check (gogogo#96) run for real, against a fake tool
that is a small Python script.

    python3 -m unittest tests.test_mutate
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import mutate  # noqa: E402

SCRIPTS = "plugins/gogogo/scripts"
REAL_RUN = mutate._run
TOOL = "/nonexistent/fake-tool"

# A real `show` output for the CLOSE_STEP = 5 survivor of #34's verify_merged.py.
SHOW = """--- plugins/gogogo/scripts/verify_merged.py
+++ plugins/gogogo/scripts/verify_merged.py
@@ -57,7 +57,7 @@


 def wait():
-CLOSE_STEP = 5
+CLOSE_STEP = 6
     return CLOSE_STEP


"""


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class Repo:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(os.path.realpath(self._tmp.name))
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "config", "user.email", "t@example.org")
        git(self.dir, "config", "user.name", "t")
        self.write(f"{SCRIPTS}/a.py", "def a():\n    return 1\n")
        self.write(f"{SCRIPTS}/c.sh", "echo one\n")
        self.write("tests/test_a.py", "import unittest\n")
        self.write(".gitignore", ".env\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "base")
        git(self.dir, "switch", "-q", "-c", "change")

    def write(self, path, text):
        (self.dir / path).parent.mkdir(parents=True, exist_ok=True)
        (self.dir / path).write_text(text)

    def close(self):
        self._tmp.cleanup()


def run_main(repo, *argv, fake=None):
    """main() in `repo`, with the tool's calls answered by `fake(args, cwd)`; returns (code, out, err, calls)."""
    calls = []

    def patched(args, cwd=None):
        calls.append((list(args), cwd))
        if args and args[0] == TOOL:
            return fake(args, cwd)
        return REAL_RUN(args, cwd=cwd)

    out, err = io.StringIO(), io.StringIO()
    with contextlib.chdir(repo), mock.patch.object(mutate, "_run", patched), \
            mock.patch.object(mutate, "_run_mutmut", patched), \
            mock.patch.dict(os.environ, {"GOGOGO_MUTMUT": TOOL}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mutate.main(["main", *argv])
    return code, out.getvalue(), err.getvalue(), calls


def done(args, stdout="", code=0):
    return subprocess.CompletedProcess(args, code, stdout, "")


def tool(run_code=0, ids=None, show=SHOW):
    ids = ids or {}

    def fake(args, cwd):
        if args[1] == "run":
            return done(args, "", run_code)
        if args[1] == "result-ids":
            return done(args, ids.get(args[2], ""))
        if args[1] == "show":
            return done(args, show)
        return done(args)
    return fake


class Changes(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.addCleanup(self.r.close)

    def test_scripts_patch_and_copy(self):
        self.r.write(f"{SCRIPTS}/a.py", "def a():\n    return 2\n")
        self.r.write(f"{SCRIPTS}/b.py", "def b():\n    return 1\n")
        self.r.write(f"{SCRIPTS}/c.sh", "echo two\n")
        self.r.write(".env", "TOKEN=secret\n")
        with contextlib.chdir(self.r.dir), contextlib.redirect_stdout(io.StringIO()) as out:
            fork = mutate.merge_base("main")
            scripts = mutate.changed_scripts(fork)
            patch = mutate.make_patch(fork, scripts)
            copy = Path(tempfile.mkdtemp())
            try:
                mutate.copy_tree(copy)
                copied = {str(p.relative_to(copy)) for p in copy.rglob("*") if p.is_file()}
            finally:
                mutate.shutil.rmtree(copy)
        self.assertEqual(sorted(scripts), [f"{SCRIPTS}/a.py", f"{SCRIPTS}/b.py"])
        self.assertIn(f"not covered: {SCRIPTS}/c.sh", out.getvalue())
        self.assertIn("+++ b/plugins/gogogo/scripts/b.py", patch)
        self.assertIn(f"{SCRIPTS}/a.py", copied)
        self.assertIn(f"{SCRIPTS}/b.py", copied)
        self.assertNotIn(".env", copied)

    def test_the_patch_keeps_a_b_prefixes_whatever_the_git_config(self):
        git(self.r.dir, "config", "diff.mnemonicPrefix", "true")
        self.r.write(f"{SCRIPTS}/a.py", "def a():\n    return 2\n")
        self.r.write(f"{SCRIPTS}/b.py", "def b():\n    return 1\n")
        with contextlib.chdir(self.r.dir), contextlib.redirect_stdout(io.StringIO()):
            fork = mutate.merge_base("main")
            patch = mutate.make_patch(fork, mutate.changed_scripts(fork))
        self.assertIn("+++ b/plugins/gogogo/scripts/a.py", patch)
        self.assertIn("+++ b/plugins/gogogo/scripts/b.py", patch)

    def test_nothing_to_mutate_installs_and_copies_nothing(self):
        self.r.write("README.md", "prose\n")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOGOGO_MUTMUT", None)
            calls = []

            def patched(args, cwd=None):
                calls.append(list(args))
                return REAL_RUN(args, cwd=cwd)
            out = io.StringIO()
            with contextlib.chdir(self.r.dir), mock.patch.object(mutate, "_run", patched), \
                    contextlib.redirect_stdout(out):
                code = mutate.main(["main"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().splitlines()[-1], "mutants: 0 killed: 0 survived: 0 timeout: 0")
        self.assertFalse([c for c in calls if any("venv" in a or "mutmut" in a for a in c)], calls)


class Runner(unittest.TestCase):
    def test_runner_names_each_scripts_test_module_or_the_whole_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_a.py").write_text("")
            (root / "tests" / "test_b.py").write_text("")
            both = mutate.runner([f"{SCRIPTS}/a.py", f"{SCRIPTS}/b.py"], root)
            one_missing = mutate.runner([f"{SCRIPTS}/a.py", f"{SCRIPTS}/c.py"], root)
        self.assertEqual(both, "python3 .gogogo-run.py python3 -m unittest tests.test_a tests.test_b")
        self.assertEqual(one_missing, "python3 .gogogo-run.py python3 -m unittest discover -s tests")


class Wrapper(unittest.TestCase):
    """The script every test run goes through, inside the copy."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        mutate.write_wrapper(self.dir)

    def wrap(self, code):
        return subprocess.run([sys.executable, mutate.WRAPPER, sys.executable, "-c", code],
                              cwd=self.dir, capture_output=True, timeout=60)

    def test_unreadable_output_is_made_readable_and_the_exit_code_kept(self):
        run = self.wrap("import sys; sys.stdout.buffer.write(b'\\xff\\xfe ok\\n'); sys.exit(3)")
        self.assertIn("ok", run.stdout.decode("utf-8"))
        self.assertEqual(run.returncode, 3)

    def test_the_heartbeat_is_written_before_and_after_the_command(self):
        run = self.wrap(f"import pathlib; print(pathlib.Path({mutate.HEARTBEAT!r}).read_text())")
        during = run.stdout.decode("utf-8").split()
        after = (self.dir / mutate.HEARTBEAT).read_text().split()
        self.assertEqual(run.returncode, 0)
        self.assertIn("start", during)
        self.assertNotIn("end", during)
        self.assertEqual(after.count("start"), 1)
        self.assertEqual(after.count("end"), 1)


    def test_the_wrapper_becomes_the_test_run_so_a_timeout_kill_reaches_it(self):
        # The tool kills the process it started when a mutant's run times out; that must be
        # the test run itself, or the run lives on after its mutant is scored.
        proc = subprocess.Popen([sys.executable, mutate.WRAPPER, sys.executable, "-c",
                                 "import os; print(os.getpid())"], cwd=self.dir, stdout=subprocess.PIPE)
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(int(out.decode("utf-8").split()[0]), proc.pid)

    def test_a_group_with_only_exited_members_is_not_an_error(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        proc.wait()
        with mock.patch.object(mutate.os, "killpg", side_effect=PermissionError(1, "not permitted")):
            mutate._end_group(proc, 0)

# A stand-in for the mutation tool: `run` starts the --runner command RUNS times,
# PAUSE seconds apart, then sleeps STALL seconds with a child of its own; it writes
# its pid and the child's to PIDS. Every other subcommand answers from IDS.
FAKE_TOOL = """#!{python}
import json, os, shlex, subprocess, sys, time
argv = sys.argv[1:]
if argv[0] == "run":
    runner = shlex.split(argv[argv.index("--runner") + 1])
    child = subprocess.Popen(["sleep", "60"])
    with open(os.environ["FAKE_PIDS"], "w") as f:
        f.write(f"{{os.getpid()}} {{child.pid}}")
    for _ in range(int(os.environ["FAKE_RUNS"])):
        subprocess.run(runner, capture_output=True)
        time.sleep(float(os.environ["FAKE_PAUSE"]))
    time.sleep(float(os.environ["FAKE_STALL"]))
    child.kill()
    sys.exit(0)
if argv[0] == "result-ids":
    print(json.loads(os.environ["FAKE_IDS"]).get(argv[1], ""))
"""


def gone(pid):
    """True once `pid` no longer exists; an orphan is reaped by init, so allow it a moment."""
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


class StallCheck(unittest.TestCase):
    """A tool that stops starting test runs is ended; one that keeps starting them is not."""

    def setUp(self):
        self.r = Repo()
        self.addCleanup(self.r.close)
        self.r.write(f"{SCRIPTS}/a.py", "def a():\n    return 2\n")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.tool = self.tmp / "mutmut"
        self.tool.write_text(FAKE_TOOL.format(python=sys.executable))
        self.tool.chmod(0o755)
        for name, value in (("STALL_MIN", 1), ("STALL_TIMES", 10), ("STALL_POLL", 0.1), ("KILL_AFTER", 1)):
            patcher = mock.patch.object(mutate, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_tool(self, runs, pause, stall, ids=""):
        env = {"GOGOGO_MUTMUT": str(self.tool), "FAKE_PIDS": str(self.tmp / "pids"), "FAKE_RUNS": str(runs),
               "FAKE_PAUSE": str(pause), "FAKE_STALL": str(stall), "FAKE_IDS": ids or "{}"}
        out, err = io.StringIO(), io.StringIO()
        with contextlib.chdir(self.r.dir), mock.patch.dict(os.environ, env), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mutate.main(["main"])
        return code, out.getvalue(), err.getvalue()

    def test_a_tool_that_stops_starting_tests_is_ended_as_a_failed_run(self):
        # The fake gives up by itself after 20 seconds, so a missing check is red, not a hang.
        code, out, err = self.run_tool(runs=1, pause=0, stall=20)
        self.assertEqual(code, 2, err)
        self.assertTrue(err.startswith("stalled:"), err)
        self.assertFalse([ln for ln in out.splitlines() if ln.startswith("mutants:")])
        pids = [int(p) for p in (self.tmp / "pids").read_text().split()]
        self.assertTrue(all(gone(pid) for pid in pids), pids)
        with self.assertRaises(ProcessLookupError):
            os.killpg(pids[0], 0)

    def test_a_run_that_keeps_starting_tests_is_not_stalled(self):
        # Five runs 0.4 seconds apart: two seconds in all, twice the one-second window.
        code, out, err = self.run_tool(runs=5, pause=0.4, stall=0, ids='{"killed": "1 2 3"}')
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[-1], "mutants: 3 killed: 3 survived: 0 timeout: 0")


class Counts(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.addCleanup(self.r.close)
        self.r.write(f"{SCRIPTS}/a.py", "def a():\n    return 2\n")

    def test_counts_and_survivors(self):
        ids = {"killed": "1 2 3", "survived": "4", "suspicious": "5", "timeout": "6"}
        code, out, _, _ = run_main(self.r.dir, fake=tool(run_code=2, ids=ids))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[-1], "mutants: 6 killed: 4 survived: 1 timeout: 1")

    def test_a_suspicious_mutant_is_killed_and_not_shown(self):
        ids = {"killed": "1 2", "suspicious": "3"}
        code, out, _, calls = run_main(self.r.dir, fake=tool(run_code=8, ids=ids))
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "mutants: 3 killed: 3 survived: 0 timeout: 0")
        self.assertFalse([ln for ln in out.splitlines() if ln.startswith("SURVIVED")])
        self.assertFalse([args for args, _ in calls if args[:1] == [TOOL] and args[1:] == ["show", "3"]])

    def test_a_failed_result_read_is_no_evidence(self):
        def fake(args, cwd):
            if args[1] == "result-ids":
                return done(args, "", 1)
            return tool()(args, cwd)
        code, out, _, _ = run_main(self.r.dir, fake=fake)
        self.assertEqual(code, 2)
        self.assertFalse([ln for ln in out.splitlines() if ln.startswith("mutants:")])

    def test_a_tool_that_cannot_start_exits_2(self):
        def fake(args, cwd):
            raise FileNotFoundError(2, "No such file or directory", args[0])
        code, out, err, _ = run_main(self.r.dir, fake=fake)
        self.assertEqual(code, 2)
        self.assertIn("No such file", err)
        self.assertNotIn("delete", err)

    def test_a_broken_install_says_to_rebuild_it(self):
        def fake(args, cwd):
            raise FileNotFoundError(2, "No such file or directory", "/cache/mutmut-2.5.1/bin/mutmut")
        code, _, err, _ = run_main(self.r.dir, fake=fake)
        self.assertEqual(code, 2)
        self.assertIn("delete", err)

    def test_untested_mutants_are_no_evidence(self):
        code, out, err, _ = run_main(self.r.dir, fake=tool(ids={"killed": "1", "untested": "2 3"}))
        self.assertEqual(code, 2)
        self.assertFalse([ln for ln in out.splitlines() if ln.startswith("mutants:")])
        self.assertIn("incomplete: 2 mutants were not run", err)

    def test_a_fatal_tool_exit_is_not_a_count(self):
        for status in (1, 3):
            code, out, _, _ = run_main(self.r.dir, fake=tool(run_code=status))
            self.assertEqual(code, 2, status)
            self.assertFalse([ln for ln in out.splitlines() if ln.startswith("mutants:")])

    def test_a_survivor_is_printed_with_its_line(self):
        code, out, _, _ = run_main(self.r.dir, fake=tool(run_code=2, ids={"survived": "4"}))
        self.assertEqual(code, 1)
        lines = out.splitlines()
        at = lines.index("SURVIVED plugins/gogogo/scripts/verify_merged.py:60")
        self.assertEqual(lines[at + 1:at + 3], ["-CLOSE_STEP = 5", "+CLOSE_STEP = 6"])

    def test_the_tool_runs_only_in_a_copy_that_is_removed(self):
        code, _, _, calls = run_main(self.r.dir, fake=tool(ids={"killed": "1"}))
        self.assertEqual(code, 0)
        tool_cwds = {cwd for args, cwd in calls if args and args[0] == TOOL}
        temp = os.path.realpath(tempfile.gettempdir())
        self.assertTrue(tool_cwds)
        for cwd in tool_cwds:
            self.assertTrue(os.path.realpath(cwd).startswith(temp), cwd)
            self.assertFalse(os.path.realpath(cwd).startswith(str(self.r.dir)), cwd)
            self.assertFalse(Path(cwd).exists(), cwd)
        code, _, err, calls = run_main(self.r.dir, "--keep", fake=tool(ids={"killed": "1"}))
        kept = {cwd for args, cwd in calls if args and args[0] == TOOL}
        self.assertTrue(all(Path(cwd).exists() for cwd in kept))
        self.assertIn(next(iter(kept)), err)
        for cwd in kept:
            mutate.shutil.rmtree(cwd)


if __name__ == "__main__":
    unittest.main()
