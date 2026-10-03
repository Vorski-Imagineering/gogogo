#!/usr/bin/env python3
"""List branches and worktrees ahead of the base that no open pull request, open issue's stop marker or closed-issue rule accounts for.

    stranded_work.py [--base main]

Work that is not in the tracker does not exist: nobody picks it up. The base
compared is `origin/<base>` when it exists, else `<base>`. Local branches and
`origin`'s branches are read, one entry per name (the local one when both
exist). A branch or worktree is reported when it has commits the base lacks,
and, for a local branch, either some of those commits are on no remote branch
or the branch is checked out in a worktree (a local copy of a pushed branch is
not stranded; a branch only on `origin` is never such a copy), and one of:

  * its name carries no issue number (the same rule as /gogogo:status: a number
    right after a `/`, followed by `-` or the end, or a leading `<n>-`);
  * that number is not an open issue in the profile's tracker (checked with
    `gh issue view` when the profile names a repo);
  * the issue is open, but no open pull request in `tracker.code_repo` claims
    the branch and the issue's newest stop-marker comment does not name it
    (as `.../tree/<branch>`).

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


# The same rule as /gogogo:status (skills/status/SKILL.md): a number straight
# after a `/` and followed by `-` or the end, else a leading `<n>-`.
ISSUE_AFTER_SLASH = r"/(\d+)(?:-|$)"
ISSUE_AT_START = r"^(\d+)-"


def issue_in_branch(name):
    """The issue number in a branch name, as a string, or None."""
    match = re.search(ISSUE_AFTER_SLASH, name) or re.search(ISSUE_AT_START, name)
    return match.group(1) if match else None


def issue_view(repo, number):
    """The issue's state and comments, None with no repo to ask, or False when the lookup failed."""
    if not repo:
        return None
    out = gh("issue", "view", number, "--repo", repo, "--json", "state,comments")
    if out.returncode != 0:
        return False
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return False


STOP_MARKER = "<!-- gogogo:stop v=1"
STOP_REASON = re.compile(r"<!-- gogogo:stop v=1 [^>]*?\breason=([^\s<>]+)")
TREE_LINK = re.compile(r"/tree/([^\s)\]>\"'`]+)")
PULL_LINK = re.compile(r"github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")


def newest_stop(comments):
    """The newest comment body carrying a stop marker, or None. `comments`: oldest first."""
    for body in reversed([c if isinstance(c, str) else (c or {}).get("body") or "" for c in comments]):
        if STOP_MARKER in body:
            return body
    return None


def stop_links(body):
    """(branches linked as /tree/<branch>, (owner/repo, number) of each PR linked as /pull/<m>, reason or None)."""
    branches = [b.rstrip(".,;:") for b in TREE_LINK.findall(body)]
    reason = STOP_REASON.search(body)
    return branches, [(repo, int(n)) for repo, n in PULL_LINK.findall(body)], reason.group(1) if reason else None


def base_ref(base):
    """`origin/<base>` when it exists, else `<base>`."""
    found = git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{base}")
    return f"refs/remotes/origin/{base}" if found.returncode == 0 else base


def ahead_of(base, ref):
    """Commits on `ref` that `base` lacks, as a string ("" when git cannot say)."""
    return git("rev-list", "--count", f"{base}..{ref}").stdout.strip()


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

    heads = git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin")
    if heads.returncode != 0:
        print(f"cannot read branches: {heads.stderr.strip()}", file=sys.stderr)
        return 2
    base = base_ref(args.base)
    refs = {}
    for ref in heads.stdout.split():
        if ref.startswith("refs/heads/"):
            refs[ref.removeprefix("refs/heads/")] = ref
    for ref in heads.stdout.split():
        if ref.startswith("refs/remotes/origin/"):
            name = ref.removeprefix("refs/remotes/origin/")
            if name != "HEAD" and name not in refs:
                refs[name] = ref
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
    for branch, ref in refs.items():
        # The full ref for git, so a tag of the same name cannot shadow it.
        if branch == args.base:
            continue
        ahead = ahead_of(base, ref)
        if not ahead or ahead == "0":
            continue
        remote_only = ref.startswith("refs/remotes/")
        if skip_copies and not remote_only and ref not in worktrees:
            local = git("rev-list", "--count", ref, "--not", "--remotes")
            if local.returncode == 0 and local.stdout.strip() == "0":
                continue
        where = f" (worktree {worktrees[ref]})" if ref in worktrees else ""
        number = issue_in_branch(branch)
        issue = issue_view(repo, number) if number else None
        if number and issue is None:
            continue  # no tracker to ask
        is_open = bool(issue) and issue.get("state") == "OPEN"
        if is_open:
            stop = newest_stop(issue.get("comments") or [])
            if stop and branch in stop_links(stop)[0]:
                continue
        # With no common commit, the count is the branch's whole history.
        shared = git("merge-base", base, ref)
        ahead_part = (f"no history in common with {args.base}" if shared.returncode == 1
                      else f"{ahead} commit(s) ahead of {args.base}")
        tip = git("rev-parse", ref).stdout.strip()
        parts = []
        open_or_unknown = False  # an open PR or a failed lookup: "no open PR" would not be true
        for pr_repo in repos:
            prs, error = pull_requests(pr_repo, branch)
            if error:
                parts.append(f"pull requests in {pr_repo} not checked: {error}")
                open_or_unknown = True
                continue
            pr = chosen(prs)
            if not pr:
                continue
            if pr["state"] == "OPEN" and pr_repo == code_repo:
                local = git("rev-list", "--count", ref, "--not", "--remotes")
                if local.returncode == 0 and local.stdout.strip() == "0":
                    break  # claimed
                count = local.stdout.strip() if local.returncode == 0 else "some"
                open_or_unknown = True
                parts.append(f"PR #{pr['number']} open, but {count} commit(s) are on no remote")
                continue
            open_or_unknown = open_or_unknown or pr["state"] == "OPEN"
            parts.append(pr_part(pr, pr_repo, code_repo, tip, args.base))
        else:
            pr_parts = "".join(f"; {part}" for part in parts)
            if not number:
                stranded.append(f"{branch}: {ahead_part}, no issue number in the name{pr_parts}{where}")
            elif is_open and open_or_unknown:
                stranded.append(f"{branch}: {ahead_part}; issue #{number} is open{pr_parts}{where}")
            elif is_open:
                stranded.append(f"{branch}: {ahead_part}; issue #{number} is open, but no open PR "
                                f"and no stop marker{pr_parts}{where}")
            else:
                stranded.append(f"{branch}: {ahead_part}; issue #{number} is not open{pr_parts}{where}")

    for line in stranded:
        print(line)
    if not stranded:
        print(f"nothing stranded (no branch ahead of {args.base} without an open issue)", file=sys.stderr)
    return 1 if stranded else 0


if __name__ == "__main__":
    sys.exit(main())
