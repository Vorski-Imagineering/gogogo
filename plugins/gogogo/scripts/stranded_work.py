#!/usr/bin/env python3
"""List local branches and worktrees ahead of the base, with work on no remote, that no open issue claims.

    stranded_work.py [--base main]

Work that is not in the tracker does not exist: nobody picks it up. A branch
or worktree is reported when it has commits the base lacks, and either some of
those commits are on no remote branch or the branch is checked out in a
worktree (a local copy of a pushed branch is not stranded), and either its name
carries no issue number, or that number is not an open issue in the profile's
tracker (checked with `gh issue view` when the profile names a repo).

Exit 0 when nothing is stranded, 1 when something is (each on its own line),
2 when it cannot read the repo.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def issue_open(repo, number):
    if not repo:
        return None
    out = subprocess.run(["gh", "issue", "view", number, "--repo", repo, "--json", "state"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return False
    return json.loads(out.stdout).get("state") == "OPEN"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="main")
    args = parser.parse_args(argv)

    repo = None
    path = profile_check.find_profile()
    if path.is_file():
        try:
            settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
            repo = settings.get("tracker", {}).get("issues_repo")
        except profile_check.ProfileError:
            pass

    heads = git("for-each-ref", "--format=%(refname)", "refs/heads")
    if heads.returncode != 0:
        print(f"cannot read branches: {heads.stderr.strip()}", file=sys.stderr)
        return 2
    listed = git("worktree", "list", "--porcelain")
    # A pushed branch in an unseen worktree would look like a copy, so without
    # the list no copy is skipped: every branch ahead of the base is reported.
    skip_copies = listed.returncode == 0
    if not skip_copies:
        reason = listed.stderr.strip() or f"git exited {listed.returncode}"
        print(f"cannot read worktrees, so copies of pushed branches are reported too: {reason}", file=sys.stderr)
    worktrees = {}
    for block in listed.stdout.split("\n\n"):
        lines = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        if "branch" in lines:
            worktrees[lines["branch"]] = lines.get("worktree", "")

    stranded = []
    for ref in heads.stdout.split():
        # The full ref for git, so a tag of the same name cannot shadow it.
        branch = ref.removeprefix("refs/heads/")
        if branch == args.base:
            continue
        ahead = git("rev-list", "--count", f"{args.base}..{ref}").stdout.strip()
        if not ahead or ahead == "0":
            continue
        if skip_copies and ref not in worktrees:
            local = git("rev-list", "--count", ref, "--not", "--remotes")
            if local.returncode == 0 and local.stdout.strip() == "0":
                continue
        where = f" (worktree {worktrees[ref]})" if ref in worktrees else ""
        number = re.search(r"(?:^|[/_-])(\d{1,6})(?:[/_-]|$)", branch)
        if not number:
            stranded.append(f"{branch}: {ahead} commit(s) ahead of {args.base}, no issue number in the name{where}")
            continue
        state = issue_open(repo, number.group(1))
        if state is False:
            stranded.append(f"{branch}: {ahead} commit(s) ahead of {args.base}; issue #{number.group(1)} is not open{where}")

    for line in stranded:
        print(line)
    if not stranded:
        print(f"nothing stranded (no branch ahead of {args.base} without an open issue)", file=sys.stderr)
    return 1 if stranded else 0


if __name__ == "__main__":
    sys.exit(main())
