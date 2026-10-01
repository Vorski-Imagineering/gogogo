#!/usr/bin/env python3
"""Is this pull request's merge commit on the target branch?

    verify_merged.py <pr> <branch> [--repo owner/name] [--ships owner/repo#n ...] [--profile FILE]

Prints MERGED or NOT-MERGED and exits 0 or 1; exits 2 when it cannot tell;
exits 3 when it merged but the merge commit lacks a `--ships` link.

A merge command returning 0 is not the same claim as "the commit is on the
branch". This asks GitHub for the PR's merge commit and then asks git whether
the remote branch contains it. It checks the merge commit, not local HEAD:
after a squash merge the branch's own commits are never on the target, so a
HEAD-based check reports NOT-MERGED after every successful squash.

`--ships` also reads the merge commit's `Ships-issue` trailers: GitHub writes
the squash commit from the body it was handed, and only the commit itself
proves the link survived. The trailers are read by `stage_sync.py`'s reader,
so both accept exactly the same forms: the legacy short form
(`<repo name>#<n>`) counts only for the profile's issues and code repos, which
is why `--ships` reads the profile (`--profile`, default the nearest one).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_sync  # noqa: E402


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def ships_ref(value):
    try:
        return stage_sync.parse_trailer(value, {})
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected <owner/repo>#<n>, got {value!r}") from None


def missing_links(sha, expected, known):
    """The expected links no `Ships-issue` trailer on `sha` names, or None when git cannot tell."""
    out = run("git", "log", "-1", f"--format=%(trailers:key={stage_sync.TRAILER_KEY},valueonly,separator=%x1f)",
              sha)
    if out.returncode != 0:
        return None
    found = set()
    for value in filter(None, (v.strip() for v in out.stdout.strip().split("\x1f"))):
        try:
            found.add(stage_sync.parse_trailer(value, known).key)
        except ValueError:
            print(f"warning: {sha[:8]} has an unreadable {stage_sync.TRAILER_KEY}: {value!r}", file=sys.stderr)
    return [link for link in expected if link.key not in found]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pr")
    parser.add_argument("branch")
    parser.add_argument("--repo", help="owner/name, when the PR is not in this checkout's repo")
    parser.add_argument("--ships", action="append", default=[], type=ships_ref, metavar="OWNER/REPO#N",
                        help="also require a Ships-issue trailer naming this issue on the merge commit")
    parser.add_argument("--profile", help="profile file, read with --ships (default: the nearest "
                                          ".agents/dev-process.md)")
    args = parser.parse_args(argv)
    known = {}
    if args.ships:
        try:
            known = stage_sync.load_profile(args.profile).known
        except stage_sync.SyncError as exc:
            print(f"cannot tell: {exc}", file=sys.stderr)
            return 2

    view = ["gh", "pr", "view", args.pr, "--json", "state,mergeCommit"]
    if args.repo:
        view += ["--repo", args.repo]
    out = run(*view)
    if out.returncode != 0:
        print(f"cannot tell: gh pr view failed: {out.stderr.strip()}", file=sys.stderr)
        return 2
    data = json.loads(out.stdout)
    sha = (data.get("mergeCommit") or {}).get("oid")
    if data.get("state") != "MERGED" or not sha:
        print(f"NOT-MERGED (PR state {data.get('state')})")
        return 1
    fetch = run("git", "fetch", "--quiet", "origin", args.branch)
    if fetch.returncode != 0:
        print(f"cannot tell: git fetch origin {args.branch} failed: {fetch.stderr.strip()}", file=sys.stderr)
        return 2
    contains = run("git", "merge-base", "--is-ancestor", sha, f"origin/{args.branch}")
    if contains.returncode == 0:
        if args.ships:
            missing = missing_links(sha, args.ships, known)
            if missing is None:
                print(f"cannot tell: git could not read the trailers of {sha[:12]}", file=sys.stderr)
                return 2
            if missing:
                refs = ", ".join(link.ref() for link in missing)
                print(f"MERGED {sha[:12]} on origin/{args.branch}, but no Ships-issue: {refs}")
                return 3
        print(f"MERGED {sha[:12]} on origin/{args.branch}")
        return 0
    if contains.returncode == 1:
        print(f"NOT-MERGED: {sha[:12]} is not on origin/{args.branch}")
        return 1
    print(f"cannot tell: {contains.stderr.strip()}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
