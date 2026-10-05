#!/usr/bin/env python3
"""Read the cards in the Human!Help! column, and the authorisation an issue body carries.

    human_help.py [--profile FILE] list [--json]
    human_help.py authorised BODY_FILE

Read-only. `list` gathers, for each open issue in `tracker.columns.needs_human`,
oldest card first: its stop reason (the newest `gogogo:stop` marker, or `skip`
for a `gogogo:skip` marker, or `none`), the `**Needs you:**` line of that
comment, the branch it names, the comments after it by someone with write
access, and how many `gogogo:requeue` markers with the same reason the issue
has. Write access is GitHub's permission call for each comment's author, read
once per author: `admin`, `maintain` or `write` is a writer, a 404 is not, and
any other failure is exit 2 (an org member with no access to the repo is not a
writer). Exit 0 when listed (also when empty), 2 when the board, an issue or an
author's permission cannot be read, with the reason on stderr and nothing on
stdout.

`authorised` prints the newest `authorised:` row of an Approvals table as
`review=until-clean model=<m> effort=<e>` (only the keys present), or nothing.
Exit 0 either way, 2 on an unreadable file or a row with an unknown key or value.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STOP = re.compile(r"<!-- gogogo:stop v=1 reason=([a-z-]+)(?: [^>]*)? -->")
SKIP = re.compile(r"<!-- gogogo:skip v=\d+ ")
REQUEUE = re.compile(r"<!-- gogogo:requeue v=1 reason=([a-z-]+) -->")
NEEDS_YOU = re.compile(r"^\*\*Needs you:\*\*\s*(.*)$", re.M)
BRANCH = re.compile(r"/tree/([^\s)>\"]+)")
WRITE_PERMISSIONS = {"admin", "maintain", "write"}

MODELS = {"fable", "opus", "sonnet", "inherit"}
EFFORTS = {"high", "xhigh", "max"}
AUTH_KEYS = {"review", "model", "effort"}


class CannotRead(Exception):
    """The board or an issue could not be read: a failed read is never an empty column."""


def stop_reason(body):
    """The reason of the newest stop or skip marker in a comment body, or None."""
    found = STOP.findall(body)
    if found:
        return found[-1]
    return "skip" if SKIP.search(body) else None


def card(number, title, url, comments, labels):
    """One card from its issue's comments (oldest first), as a dict, or None if it has no stop marker.

    `comments` are dicts with `body`, `url`, `author` and `writer` (the author has write access), in order."""
    last = None
    for index, comment in enumerate(comments):
        reason = stop_reason(comment["body"])
        if reason:
            last = (index, reason)
    if last is None:
        index, reason = -1, "none"
    else:
        index, reason = last
    stop = comments[index] if index >= 0 else None
    needs = NEEDS_YOU.search(stop["body"]) if stop else None
    branch = BRANCH.search(stop["body"]) if stop else None
    answers = [
        {"author": c["author"], "url": c["url"], "body": c["body"]}
        for c in comments[index + 1:]
        if c.get("writer") is True and not REQUEUE.search(c["body"])
    ]
    requeued = sum(1 for c in comments if (m := REQUEUE.search(c["body"])) and m.group(1) == reason)
    return {
        "number": number,
        "title": title,
        "url": url,
        "reason": reason,
        "needs_you": needs.group(1).strip() if needs else None,
        "branch": branch.group(1) if branch else None,
        "answers": answers,
        "requeued": requeued,
        "labels": labels,
    }


def authorised(body):
    """The settings of the newest `authorised:` Approvals row, as a dict; {} when there is none.

    Raises ValueError on an unknown key or value in that row."""
    rows = [line for line in body.splitlines() if re.search(r"\|\s*authorised:", line)]
    if not rows:
        return {}
    cells = [c.strip() for c in rows[-1].strip().strip("|").split("|")]
    chosen = next((c for c in cells if c.startswith("authorised:")), "")
    settings = {}
    for token in chosen[len("authorised:"):].split():
        key, sep, value = token.partition("=")
        if not sep or key not in AUTH_KEYS:
            raise ValueError(f"unknown authorisation key {token!r}")
        if key == "review" and value != "until-clean":
            raise ValueError(f"unknown review value {value!r}")
        if key == "model" and value not in MODELS:
            raise ValueError(f"unknown model {value!r}")
        if key == "effort" and value not in EFFORTS:
            raise ValueError(f"unknown effort {value!r}")
        settings[key] = value
    return settings


def _gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise CannotRead((out.stderr.strip().splitlines() or [f"gh exited {out.returncode}"])[0])
    return out.stdout


def writer(repo, login, known):
    """True when `login` has write access to `repo`, by GitHub's permission call, read once per login.

    A 404 (not a collaborator) is False; any other failure raises CannotRead naming the login:
    an unreadable permission is never counted either way."""
    if login not in known:
        try:
            level = _gh("api", f"repos/{repo}/collaborators/{login}/permission", "-q", ".permission").strip()
        except CannotRead as exc:
            if "404" not in str(exc) and "Not Found" not in str(exc):
                raise CannotRead(f"could not read {login}'s permission: {exc}") from None
            level = "none"
        known[login] = level in WRITE_PERMISSIONS
    return known[login]


def cmd_list(args):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import profile_check
    import tracker

    path = Path(args.profile) if args.profile else profile_check.find_profile()
    settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    repo = settings["tracker"]["issues_repo"]
    column = settings["tracker"]["columns"]["needs_human"]
    try:
        board, _recovered, _total = tracker.list_cards(status=column, open_only=True, issues_only=True,
                                                       repo=repo)
    except (tracker.BoardError, OSError, SystemExit) as exc:
        print(f"could not read the board: {exc}", file=sys.stderr)
        return 2
    cards = []
    known = {}
    for item in sorted(board, key=lambda i: i.get("status_since") or ""):
        try:
            view = json.loads(_gh("issue", "view", str(item["number"]), "--repo", repo, "--json", "comments"))
        except CannotRead as exc:
            print(f"could not read #{item['number']}: {exc}", file=sys.stderr)
            return 2
        try:
            comments = [{"body": c["body"], "url": c["url"], "author": c["author"]["login"],
                         "writer": writer(repo, c["author"]["login"], known)} for c in view["comments"]]
        except CannotRead as exc:
            print(str(exc), file=sys.stderr)
            return 2
        cards.append(card(item["number"], item["title"], item["url"], comments, item.get("labels") or []))
    if args.json:
        print(json.dumps(cards, indent=2))
    else:
        for c in cards:
            print(f"#{c['number']} {c['title']} — reason: {c['reason']}, requeued {c['requeued']}")
    return 0


def cmd_authorised(args):
    try:
        body = Path(args.body_file).read_text(encoding="utf-8")
        settings = authorised(body)
    except (OSError, ValueError) as exc:
        print(f"authorised: {exc}", file=sys.stderr)
        return 2
    if settings:
        print(" ".join(f"{k}={v}" for k, v in (("review", settings.get("review")), ("model", settings.get("model")),
                                                  ("effort", settings.get("effort"))) if v))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--json", action="store_true")
    auth = sub.add_parser("authorised")
    auth.add_argument("body_file")
    args = parser.parse_args(argv)
    if args.command == "authorised":
        return cmd_authorised(args)
    return cmd_list(args)


if __name__ == "__main__":
    sys.exit(main())
