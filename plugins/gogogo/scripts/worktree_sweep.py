#!/usr/bin/env python3
"""Remove the worktrees whose issue's work is finished, and keep the rest.

    worktree_sweep.py [--apply] [--only PATH] [--profile FILE]

For every worktree in `git worktree list --porcelain` except the main one (the
first entry) and the one holding the current directory, or only `--only PATH`,
the first of these that applies decides:

  1. locked                                  -> keep, `locked`
  2. detached                                -> keep, `detached HEAD`
  3. no issue number in the branch           -> keep, `no issue number in <branch>`
  4. `git status --porcelain` not empty      -> keep, `uncommitted changes`
  5. commits on no remote                    -> keep, `<k> commit(s) on no remote`
  6. a same-repo pull request MERGED         -> remove, `PR #<m> merged`
  7. the issue is closed                     -> remove, `issue #<n> closed`
  8. otherwise                               -> keep, `issue #<n> open, work not merged`

Any `git` or `gh` failure for a worktree keeps it, `cannot tell: <message>`:
no evidence never removes work. Prints `remove <path> (<branch>): <reason>` or
`keep <path> (<branch>): <reason>`, one line per worktree.

With `--apply`, each `remove` runs `git worktree remove <path>` (never
`--force`, so git refuses a dirty one too) and, only when its pull request
merged, `git branch -D <branch>` (a squash merge leaves the branch's commits
off the base, so `-d` would refuse). A failure is printed and the worktree
counts as kept. Then `git worktree prune` clears entries whose folder is gone.

Exit 0 when no worktree is kept, 1 when any is, 2 when the worktree list
cannot be read. The pull request and issue repos are the profile's
`tracker.code_repo` and `tracker.issues_repo`.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402
from stranded_work import gh, issue_in_branch, issue_view, pull_requests  # noqa: E402,F401


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _first_line(out, what):
    return (out.stderr.strip().splitlines() or [f"{what} exited {out.returncode}"])[0]


def worktrees():
    """[{path, branch, locked, detached}], main worktree first; None when git cannot list them."""
    out = git("worktree", "list", "--porcelain")
    if out.returncode != 0:
        return None
    found, entry = [], None
    for line in out.stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            entry = {"path": line[len("worktree "):], "branch": None, "locked": False, "detached": False}
        elif entry is None:
            continue
        elif line.startswith("branch "):
            entry["branch"] = line[len("branch "):].removeprefix("refs/heads/")
        elif line == "detached":
            entry["detached"] = True
        elif line == "locked" or line.startswith("locked "):
            entry["locked"] = True
        elif not line:
            found.append(entry)
            entry = None
    return found


def repos(profile):
    """(issues_repo, code_repo) from the profile, each None when it cannot be read."""
    path = Path(profile) if profile else profile_check.find_profile()
    try:
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except (OSError, profile_check.ProfileError):
        return None, None
    tracker = settings.get("tracker") or {}
    return tracker.get("issues_repo"), tracker.get("code_repo")


def decide(tree, issues_repo, code_repo):
    """("remove" | "keep", reason, merged) for one worktree."""
    branch = tree["branch"]
    if tree["locked"]:
        return "keep", "locked", False
    if tree["detached"] or not branch:
        return "keep", "detached HEAD", False
    number = issue_in_branch(branch)
    if number is None:
        return "keep", f"no issue number in {branch}", False
    status = git("-C", tree["path"], "status", "--porcelain")
    if status.returncode != 0:
        return "keep", f"cannot tell: {_first_line(status, 'git status')}", False
    if status.stdout.strip():
        return "keep", "uncommitted changes", False
    ahead = git("rev-list", "--count", branch, "--not", "--remotes")
    if ahead.returncode != 0:
        return "keep", f"cannot tell: {_first_line(ahead, 'git rev-list')}", False
    if int(ahead.stdout.strip() or 0) > 0:
        return "keep", f"{ahead.stdout.strip()} commit(s) on no remote", False
    if not code_repo or not issues_repo:
        return "keep", "cannot tell: the profile names no tracker.code_repo or tracker.issues_repo", False
    prs, error = pull_requests(code_repo, branch)
    if error:
        return "keep", f"cannot tell: {error}", False
    merged = [p for p in prs if p.get("state") == "MERGED"]
    if merged:
        return "remove", f"PR #{merged[0]['number']} merged", True
    issue = issue_view(issues_repo, number)
    if not issue:
        return "keep", f"cannot tell: the lookup of issue #{number} failed", False
    if issue.get("state") != "OPEN":
        return "remove", f"issue #{number} closed", False
    return "keep", f"issue #{number} open, work not merged", False


def _inside(path, folder):
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except ValueError:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Remove worktrees whose issue's work is finished.")
    parser.add_argument("--apply", action="store_true", help="remove what the sweep says to remove")
    parser.add_argument("--only", metavar="PATH", help="consider only this worktree")
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md)")
    args = parser.parse_args(argv)

    trees = worktrees()
    if trees is None:
        print("worktree_sweep: cannot list the worktrees (git worktree list failed)", file=sys.stderr)
        return 2
    here = Path.cwd()
    candidates = [t for t in trees[1:] if not _inside(here, t["path"])]
    if args.only:
        candidates = [t for t in candidates if Path(t["path"]).resolve() == Path(args.only).resolve()]
    issues_repo, code_repo = repos(args.profile)

    kept = 0
    for tree in candidates:
        verdict, reason, merged = decide(tree, issues_repo, code_repo)
        label = tree["branch"] or "detached"
        print(f"{verdict} {tree['path']} ({label}): {reason}")
        if verdict == "keep":
            kept += 1
            continue
        if not args.apply:
            continue
        out = git("worktree", "remove", tree["path"])
        if out.returncode != 0:
            print(f"  not removed: {_first_line(out, 'git worktree remove')}")
            kept += 1
            continue
        if merged:
            out = git("branch", "-D", tree["branch"])
            if out.returncode != 0:
                print(f"  branch {tree['branch']} kept: {_first_line(out, 'git branch -D')}")
    if args.apply:
        git("worktree", "prune")
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main())
