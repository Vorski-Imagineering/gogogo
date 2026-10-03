#!/usr/bin/env python3
"""Say how many cards wait for a person in each stage column, and how old the oldest is.

    waiting.py [--profile FILE] [--hook]

A stage column (`stages[].column` in the profile) holds work that has shipped
and waits for someone to confirm it. Nothing prompts anyone to look, so cards
sit there for days. This prints one line per stage column that holds open
issue cards:

    <N> card(s) wait for you in <column>, oldest <age>: run /gogogo:status

The age is how long the oldest card has been in that column (the time it
entered it, so a card moved out and back starts again): `<d> days`,
`<h> hours` or `under an hour`, with `1 day` and `1 hour` singular. Closed
issues, pull requests and drafts are not counted.

`--hook` is the plugin's SessionStart hook (`hooks/hooks.json`). It runs at
every session start in every repo that installs the plugin, before the first
answer, so it does one board read with no retries and no second index, and it
never fails visibly: it prints `{"systemMessage": "<the lines joined by "; ">"}`
when something waits, and otherwise nothing at all, also on any error, with no
profile, or when `tracker.tool` is not `shared`. It always exits 0.

Without `--hook`: the plain lines; exit 0 when nothing waits, 1 when something
does, 2 when it cannot tell (the reason on stderr).

Reads only. Board reads go through `tracker.py`'s functions, from this folder.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile_check  # noqa: E402
import tracker  # noqa: E402

#: One `gh` call may take this long in the hook; the hook's own timeout is 20s.
HOOK_CALL_TIMEOUT = 15


class Unreadable(Exception):
    """No answer to give: the reason is the message."""


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def age(since: str, now: datetime) -> str:
    """`since` (ISO 8601, as GitHub gives it) to now, in whole days, else whole hours."""
    then = datetime.fromisoformat(since.replace("Z", "+00:00"))
    seconds = (now - then).total_seconds()
    if seconds >= 86400:
        return _plural(int(seconds // 86400), "day")
    if seconds >= 3600:
        return _plural(int(seconds // 3600), "hour")
    return "under an hour"


def stage_columns(settings: dict) -> list[str]:
    """Each stage's column, in stage order, each once."""
    columns: list[str] = []
    for stage in settings.get("stages") or []:
        name = stage.get("column") if isinstance(stage, dict) else None
        if name and name.lower() not in (c.lower() for c in columns):
            columns.append(name)
    return columns


def waiting_lines(columns: list[str], cards: list[dict], now: datetime) -> list[str]:
    lines = []
    for name in columns:
        here = [c for c in cards
                if c.get("kind") == "Issue" and c.get("state") == "OPEN"
                and (c.get("status") or "").lower() == name.lower()]
        if not here:
            continue
        times = sorted(c["status_since"] for c in here if c.get("status_since"))
        oldest = f", oldest {age(times[0], now)}" if times else ""
        lines.append(f"{len(here)} card(s) wait for you in {name}{oldest}: run /gogogo:status")
    return lines


def read(profile: str | None, now: datetime) -> list[str]:
    path = Path(profile) if profile else profile_check.find_profile()
    if not path.is_file():
        raise Unreadable(f"no profile at {path}")
    try:
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except (OSError, profile_check.ProfileError) as exc:
        raise Unreadable(f"{path}: {exc}") from None
    if (settings.get("tracker") or {}).get("tool") != "shared":
        raise Unreadable('the board is read only through the shared tracker (tracker.tool = "shared")')
    columns = stage_columns(settings)
    if not columns:
        return []
    tracker.configure(str(path))
    cards, _recovered, _total = tracker.list_cards(
        open_only=True, issues_only=True, repo=tracker.DEFAULT_REPO, crosscheck=False)
    return waiting_lines(columns, cards, now)


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    hook = "--hook" in (sys.argv[1:] if argv is None else argv)
    now = now or datetime.now(timezone.utc)
    if not hook:
        parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
        parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md)")
        parser.add_argument("--hook", action="store_true", help="the SessionStart hook: JSON or nothing, exit 0")
        args = parser.parse_args(argv)
        try:
            lines = read(args.profile, now)
        except Exception as exc:  # noqa: BLE001 - any failure is "cannot tell", exit 2
            print(f"waiting.py: {exc}", file=sys.stderr)
            return 2
        for line in lines:
            print(line)
        return 1 if lines else 0

    # The hook: nothing it does may reach the session as an error, so every
    # failure, a bad argument included, ends in silence and exit 0.
    saved = (tracker.ATTEMPTS, tracker.CALL_TIMEOUT)
    try:
        with redirect_stderr(io.StringIO()):
            parser = argparse.ArgumentParser(add_help=False)
            parser.add_argument("--profile")
            parser.add_argument("--hook", action="store_true")
            args = parser.parse_args(argv)
            tracker.ATTEMPTS, tracker.CALL_TIMEOUT = 1, HOOK_CALL_TIMEOUT
            lines = read(args.profile, now)
        if lines:
            print(json.dumps({"systemMessage": "; ".join(lines)}))
    except BaseException:  # noqa: BLE001 - SystemExit from argparse included
        pass
    finally:
        tracker.ATTEMPTS, tracker.CALL_TIMEOUT = saved
    return 0


if __name__ == "__main__":
    sys.exit(main())
