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
from datetime import datetime, timedelta, timezone
from unittest import mock
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
    # A pull request on the board is not counted, as /gogogo:status leaves it out.
    return ([{"number": i, "kind": "Issue", "status": col} for col, n in counts.items() for i in range(n)]
            + [{"number": 99, "kind": "PullRequest", "status": "Released"}])


def fields_output(columns):
    lines = ["Board (#5) — 21 items", "project id:      P", "Status field id: F"]
    return "\n".join([*lines, *(f"  {i:08x}  {name}" for i, name in enumerate(columns))]) + "\n"


class Board:
    """Stands in for subprocess.run: fields, list --json and gh pr list."""

    def __init__(self, columns=COLUMNS, list_exit=0, raise_on=None, exc=None, answers=None):
        self.columns, self.list_exit, self.raise_on, self.exc = columns, list_exit, raise_on, exc
        self.answers = answers or {}  # which read -> (exit, stdout, stderr), overriding the rest
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        which = "gh" if cmd[0] == "gh" else cmd[-2] if cmd[-1] == "--json" else cmd[-1]
        if which == self.raise_on:
            raise self.exc
        if which in self.answers:
            return subprocess.CompletedProcess(cmd, *self.answers[which])
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
                               "--limit", "1000", "--json", "number", "-q", "length"]])
        self.assertEqual([c[:2] for c in tracker_cmds], [[sys.executable, str(SCRIPTS / "tracker.py")]] * 2)
        for _, kw in board.calls:
            self.assertGreater(kw["timeout"], 0)
            self.assertLessEqual(kw["timeout"], 15)
            self.assertIs(kw["capture_output"], True)
            self.assertIs(kw["text"], True)

    def test_columns_match_without_regard_to_case(self):
        repo = repo_with_profile()
        board = Board(columns=[c.upper() if c == "Dev Ready" else c for c in COLUMNS])
        code, out, _ = run_main(repo, board)
        self.assertEqual(code, 0)
        self.assertIn("Dev Ready 3 ·", json.loads(out)["systemMessage"])

    def test_a_python_without_tomllib_says_nothing(self):
        # macOS's own python3 is 3.9: the hook must not show an error in every session.
        code = ("import sys, runpy; sys.modules['tomllib'] = None; sys.argv = ['x']; "
                f"runpy.run_path({str(SCRIPTS / 'session_status.py')!r}, run_name='__main__')")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo_with_profile()))
        run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual((run.returncode, run.stdout, run.stderr), (0, "", ""))

    def test_main_without_profile_check_returns_0_at_once(self):
        with mock.patch.object(session_status, "profile_check", None):
            self.assertEqual(session_status.main(start=repo_with_profile(), run=Board()), 0)

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

    def test_a_column_named_twice_is_counted_once(self):
        repo = repo_with_profile()
        text = PROFILE.format(tool="shared").replace('column = "Released"', 'column = "Dev Ready"')
        (repo / ".agents" / "dev-process.md").write_text(text, encoding="utf-8")
        _, out, _ = run_main(repo, Board())
        self.assertEqual(message(out), "gogogo · myrepo: Dev Ready 3 · In progress 1 · Human!Help! 2 · "
                         "2 PRs open — /gogogo:status for detail")

    def test_board_columns_are_only_the_option_lines(self):
        self.assertEqual(session_status.board_columns(fields_output(["New", "Dev Ready"])),
                         {"New", "Dev Ready"})

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


NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def aged_board():
    """Two issue cards in Released, entered 2 and 5 days before NOW; Dev Ready cards with ages too."""
    def since(days):
        return (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    listing = [{"number": 1, "kind": "Issue", "status": "Released", "status_since": since(2)},
               {"number": 2, "kind": "Issue", "status": "Released", "status_since": since(5)},
               {"number": 3, "kind": "Issue", "status": "Dev Ready", "status_since": since(9)}]
    return Board(answers={"list": (0, json.dumps(listing), "")})


class OldestCard(unittest.TestCase):
    """Approvals row 9 of #89: the one session-start line gives each stage column's oldest card's age."""

    def test_stage_column_gets_its_oldest_age_and_the_board_is_read_once(self):
        repo = repo_with_profile()
        board = aged_board()
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            session_status.main(start=repo, run=board, clock=Clock(), now=NOW)
        line = message(out.getvalue())
        self.assertIn("Released 2 (oldest 5 days)", line)
        self.assertIn("Dev Ready 1 ·", line)
        self.assertNotIn("Dev Ready 1 (oldest", line)
        self.assertEqual(sum(1 for c, _ in board.calls if c[-2:] == ["list", "--json"]), 1)

    def test_no_age_when_the_column_is_empty_or_has_no_times(self):
        repo = repo_with_profile()
        _, out, _ = run_main(repo, Board())  # cards() carries no status_since
        self.assertNotIn("(oldest", message(out))
        listing = [{"number": 1, "kind": "Issue", "status": "Dev Ready", "status_since": "2026-10-01T00:00:00Z"}]
        _, out, _ = run_main(repo, Board(answers={"list": (0, json.dumps(listing), "")}))
        self.assertIn("Released 0 ·", message(out))
        self.assertNotIn("(oldest", message(out))

    def profile_file(self, repo):
        return repo / ".agents" / "dev-process.md"

    def run_at(self, repo, listing, columns=COLUMNS, now=None):
        board = Board(columns=columns, answers={"list": (0, json.dumps(listing), "")})
        out = io.StringIO()
        kw = {"now": now} if now else {}
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            session_status.main(start=repo, run=board, clock=Clock(), **kw)
        return message(out.getvalue())

    def test_a_card_with_no_column_is_not_counted_in_a_column_named_like_a_placeholder(self):
        repo = repo_with_profile()
        path = self.profile_file(repo)
        path.write_text(path.read_text(encoding="utf-8").replace('column = "Released"', 'column = "Xxxx"'),
                        encoding="utf-8")
        line = self.run_at(repo, [{"number": 1, "kind": "Issue"}], columns=[*COLUMNS, "Xxxx"])
        self.assertIn("Xxxx 0", line)

    def test_a_stage_with_no_column_does_not_break_the_line(self):
        repo = repo_with_profile()
        path = self.profile_file(repo)
        path.write_text(path.read_text(encoding="utf-8").replace(
            'code_is = "merged"\n', 'code_is = "merged"\n\n[[stages]]\ncode_is = "other"\n'), encoding="utf-8")
        _, out, _ = run_main(repo, Board())
        self.assertEqual(message(out), LINE.format(name="myrepo"))

    def test_a_card_with_an_empty_column_time_is_skipped_when_finding_the_oldest(self):
        def since(days):
            return (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        listing = [{"number": 1, "kind": "Issue", "status": "Released", "status_since": ""},
                   {"number": 2, "kind": "Issue", "status": "Released", "status_since": None},
                   {"number": 3, "kind": "Issue", "status": "Released", "status_since": since(2)}]
        line = self.run_at(repo_with_profile(), listing, now=NOW)
        self.assertIn("Released 3 (oldest 2 days)", line)

    def test_the_age_is_counted_to_the_time_it_is_given_else_to_now(self):
        later = datetime(2030, 1, 1, tzinfo=timezone.utc)
        listing = [{"number": 1, "kind": "Issue", "status": "Released", "status_since": "2029-12-25T00:00:00Z"}]
        self.assertIn("Released 1 (oldest 7 days)", self.run_at(repo_with_profile(), listing, now=later))
        real = (datetime.now(timezone.utc) - timedelta(days=3, minutes=5)).isoformat().replace("+00:00", "Z")
        listing = [{"number": 1, "kind": "Issue", "status": "Released", "status_since": real}]
        self.assertIn("Released 1 (oldest 3 days)", self.run_at(repo_with_profile(), listing))


class HooksJson(unittest.TestCase):
    def test_no_hook_runs_waiting(self):
        text = HOOKS.read_text(encoding="utf-8")
        self.assertNotIn("waiting.py", text)
        hooks = [h for e in json.loads(text)["hooks"]["SessionStart"] for h in e["hooks"]]
        self.assertEqual([h["type"] for h in hooks], ["command"])


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


def unavailable(board, tool="shared", clock=None, profile_edit=None):
    repo = repo_with_profile(tool)
    if profile_edit:
        path = repo / ".agents" / "dev-process.md"
        path.write_text(profile_edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    code, out, err = run_main(repo, board, clock)
    assert code == 0
    return message(out)


class Reasons(unittest.TestCase):
    """Each failed read names itself and why, on one line."""

    U = "gogogo: status unavailable: "

    def test_board_exit_with_and_without_a_reason(self):
        self.assertEqual(unavailable(Board(list_exit=2)), self.U + "board unreadable: tracker.py exited 2: tracker.py: no board")
        self.assertEqual(unavailable(Board(answers={"list": (2, "", "")})), self.U + "board unreadable: tracker.py exited 2")
        self.assertEqual(unavailable(Board(answers={"fields": (1, "", "x\nlast line\n")})),
                         self.U + "board unreadable: tracker.py exited 1: last line")

    def test_list_that_is_not_a_card_list(self):
        self.assertEqual(unavailable(Board(answers={"list": (0, "oops", "")})),
                         self.U + "board unreadable: tracker.py list printed no card list")

    def test_pull_request_failures(self):
        self.assertEqual(unavailable(Board(answers={"gh": (1, "", "HTTP 401\n")})),
                         self.U + "pull requests unreadable: gh exited 1: HTTP 401")
        missing = FileNotFoundError(2, "No such file or directory")
        self.assertEqual(unavailable(Board(raise_on="gh", exc=missing)),
                         self.U + "pull requests unreadable: gh: No such file or directory")
        self.assertEqual(unavailable(Board(raise_on="gh", exc=PermissionError("denied"))),
                         self.U + "pull requests unreadable: gh: denied")
        noise = "x" * 50
        self.assertEqual(unavailable(Board(answers={"gh": (0, noise, "")})),
                         self.U + f"pull requests unreadable: gh printed {noise[:40]!r}")

    def test_no_code_repo(self):
        self.assertEqual(unavailable(Board(), profile_edit=lambda t: t.replace('code_repo = "o/r"\n', "")),
                         self.U + "pull requests unreadable: tracker.code_repo is not set")

    def test_a_spent_budget_reads_nothing_more(self):
        for spent, calls in ((15, 1), (14.5, 3)):
            clock, board = Clock(), Board()

            def timed(cmd, **kw):
                clock.now += spent if not board.calls else 0
                return board(cmd, **kw)

            line = unavailable(timed, clock=clock)
            self.assertEqual(len(board.calls), calls, spent)
            if spent == 15:
                self.assertEqual(line, self.U + "board timed out after 15 s")
            else:
                self.assertEqual(board.calls[1][1]["timeout"], 0.5)

    def test_unexpected_exception_names_itself(self):
        self.assertEqual(unavailable(Board(raise_on="list", exc=RuntimeError("boom\nmore"))),
                         self.U + "RuntimeError: more")

    def test_exception_before_a_profile_is_found_prints_nothing(self):
        tmp = Path(tempfile.mkdtemp()).resolve()
        (tmp / ".git").mkdir()
        from unittest import mock
        with mock.patch.object(session_status.profile_check, "find_profile", side_effect=RuntimeError("x")):
            code, out, err = run_main(tmp, Board())
        self.assertEqual((code, out), (0, ""))
        self.assertIn("RuntimeError", err)


class AsAProcess(unittest.TestCase):
    def test_reads_the_project_dir_not_the_current_folder(self):
        repo = repo_with_profile()
        (repo / ".agents" / "dev-process.md").write_text("broken\n", encoding="utf-8")
        elsewhere = Path(tempfile.mkdtemp()).resolve()
        (elsewhere / ".git").mkdir()
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
        done = subprocess.run([sys.executable, str(SCRIPTS / "session_status.py")],
                              capture_output=True, text=True, env=env, cwd=elsewhere, timeout=30)
        self.assertEqual(done.returncode, 0)
        self.assertTrue(message(done.stdout).startswith("gogogo: status unavailable: settings:"))

    def test_importing_it_runs_nothing(self):
        repo = repo_with_profile()
        (repo / ".agents" / "dev-process.md").write_text("broken\n", encoding="utf-8")
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "PYTHONPATH": str(SCRIPTS)}
        done = subprocess.run([sys.executable, "-c", "import session_status"],
                              capture_output=True, text=True, env=env, cwd=repo, timeout=30)
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_closed_stdout_still_exits_0(self):
        repo = repo_with_profile()
        (repo / ".agents" / "dev-process.md").write_text("broken\n", encoding="utf-8")
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
        read_end, write_end = os.pipe()
        os.close(read_end)  # nobody reads: the line's write fails with a broken pipe
        try:
            done = subprocess.run([sys.executable, str(SCRIPTS / "session_status.py")],
                                  stdout=write_end, stderr=subprocess.PIPE, text=True,
                                  env=env, cwd=repo, timeout=30)
        finally:
            os.close(write_end)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("BrokenPipeError", done.stderr)

    def test_imports_profile_check_from_its_own_folder(self):
        import importlib.util
        decoy = Path(tempfile.mkdtemp())
        (decoy / "profile_check.py").write_text("DECOY = True\n", encoding="utf-8")
        saved_path, saved = list(sys.path), sys.modules.pop("profile_check")
        try:
            sys.path[:] = [str(decoy)] + [p for p in saved_path if Path(p).resolve() != SCRIPTS]
            spec = importlib.util.spec_from_file_location("session_status_fresh", SCRIPTS / "session_status.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertFalse(hasattr(module.profile_check, "DECOY"))
        finally:
            sys.path[:] = saved_path
            sys.modules["profile_check"] = saved


if __name__ == "__main__":
    unittest.main()
