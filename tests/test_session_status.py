#!/usr/bin/env python3
"""Tests for session_status.py, the plugin's SessionStart hook, and its hooks.json.

The board and GitHub are never called: `subprocess.run` is replaced by a stand-in
returning fixed outputs, the clock is a fake, and each case writes its own profile.

    python3 -m unittest tests.test_session_status
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "gogogo" / "scripts"
HOOKS = ROOT / "plugins" / "gogogo" / "hooks" / "hooks.json"
sys.path.insert(0, str(SCRIPTS))

import session_status  # noqa: E402

PROJECT_NAMES = r"manage\.py|npm |firebase|django|htmx|sentry"

PROFILE = """\
+++
profile = 1

[tracker]
kind = "github-project"
issues_repo = "o/r"
code_repo = "o/r"
tool = "{tool}"
project_owner = "o"
project_number = 5
queue = "Dev Ready"
columns = {{ in_progress = "In progress", needs_human = "Human!Help!" }}

[[stages]]
column = "Released"
code_is = "merged"
+++

## Whatever
text
"""

COLUMNS = ["New", "Dev Ready", "In progress", "Human!Help!", "Released", "Done"]
LINE = ("gogogo · {name}: Dev Ready 3 · In progress 1 · Human!Help! 2 · Released 4 · "
        "2 PRs open — /gogogo:status for detail")


def cards():
    counts = {"Dev Ready": 3, "In progress": 1, "Human!Help!": 2, "Released": 4, "New": 5, "Done": 6}
    return [{"number": i, "status": col} for col, n in counts.items() for i in range(n)]


def fields_output(columns):
    lines = ["Board (#5) — 21 items", "project id:      P", "Status field id: F"]
    return "\n".join([*lines, *(f"  {i:08x}  {name}" for i, name in enumerate(columns))]) + "\n"


class Board:
    """Stands in for subprocess.run: fields, list --json and gh pr list."""

    def __init__(self, columns=COLUMNS, list_exit=0, raise_on=None, exc=None):
        self.columns, self.list_exit, self.raise_on, self.exc = columns, list_exit, raise_on, exc
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        which = "gh" if cmd[0] == "gh" else cmd[-2] if cmd[-1] == "--json" else cmd[-1]
        if which == self.raise_on:
            raise self.exc
        if which == "fields":
            return subprocess.CompletedProcess(cmd, 0, fields_output(self.columns), "")
        if which == "list":
            if self.list_exit:
                return subprocess.CompletedProcess(cmd, self.list_exit, "", "tracker.py: no board\n")
            return subprocess.CompletedProcess(cmd, 0, json.dumps(cards()), "61 of 61 read.\n")
        return subprocess.CompletedProcess(cmd, 0, "2\n", "")


class Clock:
    """A fake monotonic clock; a timed-out read moves it on by the timeout it was given."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def repo_with_profile(tool="shared"):
    tmp = Path(tempfile.mkdtemp()).resolve() / "myrepo"
    (tmp / ".git").mkdir(parents=True)
    (tmp / ".agents").mkdir()
    (tmp / ".agents" / "dev-process.md").write_text(PROFILE.format(tool=tool), encoding="utf-8")
    return tmp


def run_main(start, board, clock=None):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = session_status.main(start=start, run=board, clock=clock or Clock())
    return code, out.getvalue(), err.getvalue()


def message(stdout):
    obj = json.loads(stdout)
    assert list(obj) == ["systemMessage"], obj
    return obj["systemMessage"]


class Line(unittest.TestCase):
    def test_counts_each_profile_column_in_order_then_prs(self):
        repo = repo_with_profile()
        code, out, _ = run_main(repo, Board())
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1)
        obj = json.loads(out)
        self.assertEqual(list(obj), ["systemMessage"])
        self.assertEqual(obj["systemMessage"], LINE.format(name="myrepo"))

    def test_reads_through_the_profile_with_a_time_limit(self):
        repo = repo_with_profile()
        board = Board()
        run_main(repo, board)
        profile = str(repo / ".agents" / "dev-process.md")
        tracker_cmds = [c for c, _ in board.calls if c[0] != "gh"]
        self.assertTrue(all(c[c.index("--profile") + 1] == profile for c in tracker_cmds))
        gh = [c for c, _ in board.calls if c[0] == "gh"]
        self.assertEqual(gh, [["gh", "pr", "list", "--repo", "o/r", "--state", "open",
                               "--json", "number", "-q", "length"]])
        for _, kw in board.calls:
            self.assertGreater(kw["timeout"], 0)
            self.assertLessEqual(kw["timeout"], 15)

    def test_column_missing_from_board_shows_question_mark(self):
        repo = repo_with_profile()
        _, out, _ = run_main(repo, Board(columns=[c for c in COLUMNS if c != "Human!Help!"]))
        line = message(out)
        self.assertIn("· Human!Help! ? ·", line)
        self.assertIn("Released 4", line)

    def test_column_with_no_cards_shows_zero(self):
        repo = repo_with_profile()
        board = Board(columns=COLUMNS)
        text = PROFILE.format(tool="shared").replace('column = "Released"', 'column = "Testing"')
        (repo / ".agents" / "dev-process.md").write_text(text, encoding="utf-8")
        board.columns = COLUMNS + ["Testing"]
        _, out, _ = run_main(repo, board)
        self.assertIn("· Testing 0 ·", message(out))

    def test_other_tracker_shows_prs_only(self):
        repo = repo_with_profile(tool="./bin/board")
        board = Board()
        _, out, _ = run_main(repo, board)
        self.assertEqual(message(out), "gogogo · myrepo: 2 PRs open — /gogogo:status for detail")
        self.assertEqual([c[0] for c, _ in board.calls], ["gh"])


class Silence(unittest.TestCase):
    def test_no_profile_prints_nothing(self):
        tmp = Path(tempfile.mkdtemp()).resolve()
        (tmp / ".git").mkdir()
        board = Board()
        code, out, _ = run_main(tmp, board)
        self.assertEqual((code, out, board.calls), (0, "", []))

    def test_no_profile_as_a_process_exits_0_silently(self):
        tmp = Path(tempfile.mkdtemp()).resolve()
        (tmp / ".git").mkdir()
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp)}
        done = subprocess.run([sys.executable, str(SCRIPTS / "session_status.py")],
                              capture_output=True, text=True, env=env, cwd=tmp, timeout=30)
        self.assertEqual((done.returncode, done.stdout), (0, ""))


class Failures(unittest.TestCase):
    def test_broken_profile_says_so(self):
        repo = repo_with_profile()
        (repo / ".agents" / "dev-process.md").write_text("no front matter\n", encoding="utf-8")
        code, out, _ = run_main(repo, Board())
        self.assertEqual(code, 0)
        self.assertEqual(message(out), "gogogo: status unavailable: "
                         "settings: the file must start with a +++ line (TOML front matter)")

    def test_board_read_failing_is_unavailable(self):
        repo = repo_with_profile()
        code, out, _ = run_main(repo, Board(list_exit=2))
        self.assertEqual(code, 0)
        line = message(out)
        self.assertTrue(line.startswith("gogogo: status unavailable: board"), line)
        self.assertIn("no board", line)
        self.assertNotIn("\n", line)

    def test_timeout_is_unavailable_within_the_budget(self):
        repo = repo_with_profile()
        clock = Clock()
        start = clock.now

        def slow(cmd, **kw):
            clock.now += kw["timeout"]
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])

        code, out, _ = run_main(repo, slow, clock)
        self.assertEqual(code, 0)
        self.assertIn("status unavailable", message(out))
        self.assertLess(clock.now - start, 16)

    def test_slow_reads_share_one_budget(self):
        repo = repo_with_profile()
        clock = Clock()
        start = clock.now
        board, timeouts = Board(), []

        def slow(cmd, **kw):
            # every read takes 6 seconds: 15 for the first, 9 for the second, 3 for the third
            timeouts.append(kw["timeout"])
            clock.now += min(6, kw["timeout"])
            if kw["timeout"] < 6:
                raise subprocess.TimeoutExpired(cmd, kw["timeout"])
            return board(cmd, **kw)

        _, out, _ = run_main(repo, slow, clock)
        self.assertEqual(timeouts, [15, 9, 3])
        self.assertLess(clock.now - start, 16)
        self.assertTrue(message(out).startswith("gogogo: status unavailable: pull requests"))

    def test_pr_read_failing_is_unavailable(self):
        repo = repo_with_profile()
        _, out, _ = run_main(repo, Board(raise_on="gh", exc=FileNotFoundError("gh")))
        self.assertTrue(message(out).startswith("gogogo: status unavailable: pull requests"))


class OnlyTheSystemMessage(unittest.TestCase):
    def test_unexpected_exception_still_one_json_object(self):
        repo = repo_with_profile()
        code, out, err = run_main(repo, Board(raise_on="list", exc=RuntimeError("boom")))
        self.assertEqual(code, 0)
        self.assertNotIn("additionalContext", out)
        self.assertIn("status unavailable", message(out))
        self.assertIn("Traceback", err)
        self.assertIn("boom", err)

    def test_no_additional_context_on_success(self):
        repo = repo_with_profile()
        _, out, _ = run_main(repo, Board())
        self.assertNotIn("additionalContext", out)
        message(out)


class HooksJson(unittest.TestCase):
    def test_one_session_start_hook_on_startup_and_resume(self):
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(list(hooks), ["SessionStart"])
        self.assertEqual(len(hooks["SessionStart"]), 1)
        entry = hooks["SessionStart"][0]
        self.assertEqual(entry["matcher"], "startup|resume")
        self.assertEqual(len(entry["hooks"]), 1)
        hook = entry["hooks"][0]
        self.assertEqual(hook["timeout"], 20)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/session_status.py", hook["command"])

    def test_names_no_project(self):
        for path in (HOOKS, SCRIPTS / "session_status.py"):
            self.assertIsNone(re.search(PROJECT_NAMES, path.read_text(encoding="utf-8"), re.I), path)


if __name__ == "__main__":
    unittest.main()
