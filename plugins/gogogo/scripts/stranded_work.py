#!/usr/bin/env python3
"""List local branches and worktrees ahead of the base, with work on no remote, that no open issue or open pull request claims.

    stranded_work.py [--base main]

Work that is not in the tracker does not exist: nobody picks it up. A branch
or worktree is reported when it has commits the base lacks, and either some of
those commits are on no remote branch or the branch is checked out in a
worktree (a local copy of a pushed branch is not stranded), and either its name
carries no issue number, or that number is not an open issue in the profile's
tracker (checked with `gh issue view` when the profile names a repo).

An open pull request in the profile's `tracker.code_repo` claims its branch,
unless the branch has commits on no remote. Pull requests in the checkout's
other GitHub remotes, and closed or merged ones, only add to the line: what
became of the branch's pull request. A branch that shares no history with the
base says so in place of a commit count, which would be its whole history.

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


def gh(*args):
    """`gh`, where a missing or unrunnable `gh` is a failed call, never a crash."""
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True)
    except OSError as exc:
        return subprocess.CompletedProcess(["gh", *args], 127, "", f"cannot run gh: {exc.strerror}")


def issue_open(repo, number):
    if not repo:
        return None
    out = gh("issue", "view", number, "--repo", repo, "--json", "state")
    if out.returncode != 0:
        return False
    return json.loads(out.stdout).get("state") == "OPEN"


GITHUB_URL = re.compile(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$")


def github_repos(code_repo):
    """owner/name of `code_repo`, then of each GitHub remote, without repeats."""
    repos = [code_repo]
    remotes = git("remote", "-v")
    for line in remotes.stdout.splitlines() if remotes.returncode == 0 else []:
        parts = line.split()
        if len(parts) < 3 or parts[2] != "(fetch)":
            continue
        match = GITHUB_URL.search(parts[1])
        if match:
            repo = f"{match.group(1)}/{match.group(2)}"
            if repo.lower() not in (r.lower() for r in repos):
                repos.append(repo)
    return repos


def pull_requests(repo, branch):
    """(this repo's PRs from `branch`, None), or (None, why the lookup failed)."""
    out = gh("pr", "list", "--repo", repo, "--head", branch, "--state", "all",
             "--json", "number,state,headRefOid,headRepository", "--limit", "20")
    if out.returncode != 0:
        return None, (out.stderr.strip().splitlines() or [f"gh exited {out.returncode}"])[0]
    try:
        prs = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None, "gh printed something that is not JSON"
    # A fork's branch of the same name is someone else's PR.
    return [p for p in prs if ((p.get("headRepository") or {}).get("nameWithOwner") or "").lower()
            == repo.lower()], None


def chosen(prs):
    """The open PR, else the newest."""
    if not prs:
        return None
    return next((p for p in prs if p.get("state") == "OPEN"), None) or max(prs, key=lambda p: p["number"])


_archived = {}


def archived(repo):
    if repo not in _archived:
        out = gh("repo", "view", repo, "--json", "isArchived")
        try:
            _archived[repo] = json.loads(out.stdout).get("isArchived") if out.returncode == 0 else None
        except json.JSONDecodeError:
            _archived[repo] = None
    return _archived[repo]


def pr_part(pr, repo, code_repo, tip, base):
    where = (f" in {repo}" if repo != code_repo else "") + (" (archived)" if archived(repo) else "")
    if pr["state"] == "OPEN":
        return f"PR #{pr['number']} open{where}"
    moved = (f" (the PR's head was {pr['headRefOid'][:7]}; the branch has moved since)"
             if pr.get("headRefOid") != tip else "")
    if pr["state"] == "MERGED":
        return f"PR #{pr['number']} merged{where}{moved}, so its content may already be in {base}"
    return f"PR #{pr['number']} closed without merging{where}{moved}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="main")
    args = parser.parse_args(argv)

    repo = code_repo = None
    path = profile_check.find_profile()
    if path.is_file():
        try:
            settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
            repo = settings.get("tracker", {}).get("issues_repo")
            code_repo = settings.get("tracker", {}).get("code_repo")
        except profile_check.ProfileError:
            pass
    repos = github_repos(code_repo) if code_repo else []

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
        if number and issue_open(repo, number.group(1)) is not False:
            continue
        # With no common commit, the count is the branch's whole history.
        shared = git("merge-base", args.base, ref)
        ahead_part = (f"no history in common with {args.base}" if shared.returncode == 1
                      else f"{ahead} commit(s) ahead of {args.base}")
        tip = git("rev-parse", ref).stdout.strip()
        parts = []
        for pr_repo in repos:
            prs, error = pull_requests(pr_repo, branch)
            if error:
                parts.append(f"pull requests in {pr_repo} not checked: {error}")
                continue
            pr = chosen(prs)
            if not pr:
                continue
            if pr["state"] == "OPEN" and pr_repo == code_repo:
                local = git("rev-list", "--count", ref, "--not", "--remotes")
                if local.returncode == 0 and local.stdout.strip() == "0":
                    break  # claimed
                count = local.stdout.strip() if local.returncode == 0 else "some"
                parts.append(f"PR #{pr['number']} open, but {count} commit(s) are on no remote")
                continue
            parts.append(pr_part(pr, pr_repo, code_repo, tip, args.base))
        else:
            pr_parts = "".join(f"; {part}" for part in parts)
            if not number:
                stranded.append(f"{branch}: {ahead_part}, no issue number in the name{pr_parts}{where}")
            else:
                stranded.append(f"{branch}: {ahead_part}; issue #{number.group(1)} is not open{pr_parts}{where}")

    for line in stranded:
        print(line)
    if not stranded:
        print(f"nothing stranded (no branch ahead of {args.base} without an open issue)", file=sys.stderr)
    return 1 if stranded else 0


if __name__ == "__main__":
    sys.exit(main())
