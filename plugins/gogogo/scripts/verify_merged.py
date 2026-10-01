#!/usr/bin/env python3
"""Is this pull request's merge commit on the target branch?

    verify_merged.py <pr> <branch> [--repo owner/name]

Prints MERGED or NOT-MERGED and exits 0 or 1; exits 2 when it cannot tell.

A merge command returning 0 is not the same claim as "the commit is on the
branch". This asks GitHub for the PR's merge commit and then asks git whether
the remote branch contains it. It checks the merge commit, not local HEAD:
after a squash merge the branch's own commits are never on the target, so a
HEAD-based check reports NOT-MERGED after every successful squash.
"""
import argparse
import json
import subprocess
import sys


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pr")
    parser.add_argument("branch")
    parser.add_argument("--repo", help="owner/name, when the PR is not in this checkout's repo")
    args = parser.parse_args(argv)

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
        print(f"MERGED {sha[:12]} on origin/{args.branch}")
        return 0
    if contains.returncode == 1:
        print(f"NOT-MERGED: {sha[:12]} is not on origin/{args.branch}")
        return 1
    print(f"cannot tell: {contains.stderr.strip()}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
