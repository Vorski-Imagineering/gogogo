#!/usr/bin/env python3
"""Tests for tools/mutate.py, this repo's own `mutate` lane command (gogogo#45).

Git runs for real in a temporary repository; the mutation tool itself never
runs: `mutate._run` is patched to answer for it, and GOGOGO_MUTMUT points at a
path that does not exist, so nothing is installed.

    python3 -m unittest tests.test_mutate
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
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
        self.assertEqual(both, "python3 -m unittest tests.test_a tests.test_b")
        self.assertEqual(one_missing, "python3 -m unittest discover -s tests")


class Counts(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.addCleanup(self.r.close)
        self.r.write(f"{SCRIPTS}/a.py", "def a():\n    return 2\n")

    def test_counts_and_survivors(self):
        # The tool's "suspicious" means the tests failed (killed) but ran slowly.
        ids = {"killed": "1 2 3", "survived": "4", "suspicious": "5", "timeout": "6"}
        code, out, _, _ = run_main(self.r.dir, fake=tool(run_code=2, ids=ids))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[-1], "mutants: 6 killed: 4 survived: 1 timeout: 1")

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
