#!/usr/bin/env python3
"""One line of board counts when a session opens: the plugin's SessionStart hook.

    session_status.py        (run by hooks/hooks.json; reads CLAUDE_PROJECT_DIR)

Prints exactly one JSON object, `{"systemMessage": "<line>"}`, which Claude Code
shows to the person and never adds to Claude's context. The line counts the
cards in each column the profile names (`tracker.queue`,
`tracker.columns.in_progress`, `tracker.columns.needs_human`, each
`stages[].column`), then the open pull requests:

    gogogo · <folder>: Dev Ready 3 · In progress 1 · … · 2 PRs open — /gogogo:status for detail

With no profile at or above the folder it prints nothing. A broken profile, or
a read that fails or outlasts the 15-second budget, gives one
`gogogo: status unavailable: …` line. It always exits 0, and errors go to
stderr: a hook must never get in the way of opening a session.

Standard library only; imports `profile_check` from this folder, so a vendored
copy works when the files sit side by side.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile_check  # noqa: E402

BUDGET = 15  # seconds for every read together; hooks.json's timeout (20) is the outer bound
UNAVAILABLE = "gogogo: status unavailable: "


class ReadFailed(Exception):
    """A read that failed or ran out of time; the text names the read and why."""


def _one_line(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _read(which, cmd, run, clock, deadline):
    """stdout of `cmd`, given whatever is left of the budget."""
    remaining = deadline - clock()
    if remaining <= 0:
        raise ReadFailed(f"{which} timed out after {BUDGET} s")
    try:
        done = run(cmd, capture_output=True, text=True, timeout=remaining)
    except subprocess.TimeoutExpired:
        raise ReadFailed(f"{which} timed out after {BUDGET} s") from None
    except OSError as exc:
        raise ReadFailed(f"{which} unreadable: {cmd[0]}: {exc.strerror or exc}") from None
    if done.returncode != 0:
        name = Path(cmd[1]).name if cmd[0] == sys.executable else cmd[0]
        reason = _one_line(done.stderr)
        raise ReadFailed(f"{which} unreadable: {name} exited {done.returncode}"
                         + (f": {reason}" if reason else ""))
    return done.stdout


def profile_columns(settings):
    """The columns to count, in the profile's order, each name once."""
    tracker = settings.get("tracker") or {}
    roles = tracker.get("columns") or {}
    names = [tracker.get("queue"), roles.get("in_progress"), roles.get("needs_human")]
    names += [s.get("column") for s in settings.get("stages") or [] if isinstance(s, dict)]
    out = []
    for name in names:
        if isinstance(name, str) and name and name not in out:
            out.append(name)
    return out


def board_columns(fields_output):
    """The Status options `tracker.py fields` prints, one per indented `<id>  <name>` line."""
    names = set()
    for line in fields_output.splitlines():
        if line.startswith("  ") and len(line.split(None, 1)) == 2:
            names.add(line.split(None, 1)[1].strip())
    return names


def status_line(profile, settings, run, clock):
    deadline = clock() + BUDGET
    tracker = settings.get("tracker") or {}
    parts = []
    if tracker.get("tool") == "shared":
        tool = [sys.executable, str(HERE / "tracker.py"), "--profile", str(profile)]
        on_board = board_columns(_read("board", [*tool, "fields"], run, clock, deadline))
        listing = _read("board", [*tool, "list", "--json"], run, clock, deadline)
        try:
            statuses = [card.get("status") for card in json.loads(listing)]
        except (json.JSONDecodeError, AttributeError, TypeError):
            raise ReadFailed("board unreadable: tracker.py list printed no card list") from None
        for name in profile_columns(settings):
            parts.append(f"{name} {statuses.count(name)}" if name in on_board else f"{name} ?")
    repo = tracker.get("code_repo")
    if not repo:
        raise ReadFailed("pull requests unreadable: tracker.code_repo is not set")
    prs = _read("pull requests", ["gh", "pr", "list", "--repo", repo, "--state", "open",
                                  "--json", "number", "-q", "length"], run, clock, deadline).strip()
    if not prs.isdigit():
        raise ReadFailed(f"pull requests unreadable: gh printed {prs[:40]!r}")
    parts.append(f"{prs} PRs open")
    return f"gogogo · {profile.parent.parent.name}: " + " · ".join(parts) + " — /gogogo:status for detail"


def message(profile, run, clock):
    """The line to show for the profile at `profile`."""
    try:
        settings, _ = profile_check.split_profile(profile.read_text(encoding="utf-8"))
    except (profile_check.ProfileError, OSError, UnicodeDecodeError) as exc:
        return UNAVAILABLE + (str(exc).strip().splitlines() or [type(exc).__name__])[0]
    try:
        return status_line(profile, settings, run, clock)
    except ReadFailed as exc:
        return UNAVAILABLE + str(exc)


def main(start=None, run=None, clock=None):
    """Print the systemMessage (or nothing) and return 0, whatever happens."""
    profile = line = None
    try:
        found = profile_check.find_profile(start or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
        if found.is_absolute():  # not found: find_profile answers with the bare relative default
            profile = found
            line = message(profile, run or subprocess.run, clock or time.monotonic)
    except Exception as exc:  # never a traceback on stdout, never a non-zero exit
        traceback.print_exc()
        if profile is not None:
            line = UNAVAILABLE + f"{type(exc).__name__}: {_one_line(str(exc))}"
    if line is not None:
        try:
            print(json.dumps({"systemMessage": line}), flush=True)
        except OSError:  # stdout closed: say so on stderr, and keep shutdown from failing on it too
            traceback.print_exc()
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return 0


if __name__ == "__main__":
    main()
