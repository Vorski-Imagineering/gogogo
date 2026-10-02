#!/usr/bin/env python3
"""Is this pull request's merge commit on the target branch?

    verify_merged.py <pr> <branch> [--repo owner/name] [--ships owner/repo#n ...]
                     [--open owner/repo#n ...] [--profile FILE]

Prints MERGED or NOT-MERGED and exits 0 or 1; exits 2 when it cannot tell;
exits 4 when it merged but an `--open` issue is closed; exits 3 when it merged
but the merge commit lacks a `--ships` link. When several apply, the first of
2, 4, 3 wins, and every problem is printed.

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
is why `--ships` reads the profile (`--profile`, default the nearest one). An
unreadable profile only loses the short form; full-form links still check.

`--open` checks that the merge left the issue open. A closing keyword
(`Fixes #n`) in the PR's body or in a commit the merge brings onto the default
branch closes the issue a few seconds after the merge, so a single read can
pass before the close lands. When the PR or those commits name the issue with
a closing keyword, the script waits up to CLOSE_WAIT seconds for the close;
when nothing does, it reads the state once. A short-form `#n` names the PR's
own repo: `--repo`, else the profile's `tracker.code_repo`. It only reads;
reopening is the skill's job.
"""
import argparse
import json
import re
import subprocess
import sys
import time
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


CLOSE_WAIT = 60  # seconds to wait for a close a closing reference will bring
CLOSE_STEP = 5

_CLOSER = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+"
                     r"(?:(?P<repo>[A-Za-z0-9-]+/[A-Za-z0-9._-]+))?#(?P<number>\d+)(?!\d)", re.IGNORECASE)


def closes(text, link, this_repo):
    """Does `text` name `link` after a GitHub closing keyword?"""
    for match in _CLOSER.finditer(text):
        repo = match["repo"] or this_repo
        if repo and repo.lower() == link.repo.lower() and int(match["number"]) == link.number:
            return True
    return False


def default_branch(repo):
    out = run("gh", "repo", "view", *([repo] if repo else []), "--json", "defaultBranchRef",
              "-q", ".defaultBranchRef.name")
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def issue_state(link):
    out = run("gh", "issue", "view", str(link.number), "--repo", link.repo, "--json", "state", "-q", ".state")
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def closed_links(links, sha, branch, pr_repo, this_repo, closing_refs):
    """(lines, problems): a line per `--open` link that is closed, and a reason per one it cannot tell."""
    default = default_branch(pr_repo)
    if default is None:
        return [], ["gh repo view could not read the default branch"]
    log = run("git", "log", "--format=%B", f"{sha}^1..{sha}")
    if log.returncode != 0:
        return [], [f"git could not read the messages of {sha[:12]}: {log.stderr.strip()}"]
    messages = log.stdout
    urls = {(ref.get("url") or "").lower() for ref in closing_refs or []}
    lines, problems = [], []
    for link in links:
        will_close = default == branch and (
            f"https://github.com/{link.repo}/issues/{link.number}".lower() in urls
            or closes(messages, link, this_repo))
        deadline = time.monotonic() + CLOSE_WAIT
        state = issue_state(link)
        while will_close and state == "OPEN" and time.monotonic() < deadline:
            time.sleep(CLOSE_STEP)
            state = issue_state(link)
        if state is None:
            problems.append(f"gh issue view could not read the state of {link.ref()}")
        elif state == "OPEN" and will_close:
            problems.append(f"{link.ref()} is named by a closing reference in this merge "
                            f"and is still open after {CLOSE_WAIT}s")
        elif state != "OPEN":
            how = "by this merge" if will_close else "(not by a closing reference in this merge)"
            lines.append(f"CLOSED {how}: {link.ref()}")
    return lines, problems


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
    parser.add_argument("--open", action="append", default=[], type=ships_ref, metavar="OWNER/REPO#N",
                        help="also require this issue to be open after the merge")
    parser.add_argument("--profile", help="profile file, read with --ships and --open (default: the "
                                          "nearest .agents/dev-process.md)")
    args = parser.parse_args(argv)
    known, code_repo = {}, None
    if args.ships or args.open:
        try:
            profile = stage_sync.load_profile(args.profile)
            known, code_repo = profile.known, profile.tracker.get("code_repo")
        except stage_sync.SyncError as exc:
            # Without the profile only the short form is lost: full-form links
            # are still checked, and a short-form reference simply does not count.
            print(f"warning: {exc}; a short-form reference cannot count", file=sys.stderr)

    view = ["gh", "pr", "view", args.pr, "--json", "state,mergeCommit,closingIssuesReferences"]
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
        missing = []
        if args.ships:
            missing = missing_links(sha, args.ships, known)
            if missing is None:
                print(f"cannot tell: git could not read the trailers of {sha[:12]}", file=sys.stderr)
                return 2
        closed, problems = [], []
        if args.open:
            closed, problems = closed_links(args.open, sha, args.branch, args.repo, args.repo or code_repo,
                                           data.get("closingIssuesReferences"))
        no_link = [f"no Ships-issue: {', '.join(link.ref() for link in missing)}"] if missing else []
        if problems:
            # Merged, but an issue's state is unknown: no MERGED line, which a
            # reader would take as the all-clear.
            for problem in problems:
                print(f"cannot tell: {sha[:12]} is on origin/{args.branch}, but {problem}", file=sys.stderr)
            print("\n".join(no_link + closed))
            return 2
        merged = f"MERGED {sha[:12]} on origin/{args.branch}"
        print("\n".join([", but ".join([merged, *no_link]), *closed]))
        return 4 if closed else 3 if missing else 0
    if contains.returncode == 1:
        print(f"NOT-MERGED: {sha[:12]} is not on origin/{args.branch}")
        return 1
    print(f"cannot tell: {contains.stderr.strip()}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
