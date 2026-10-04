#!/usr/bin/env python3
"""Remove the worktrees whose issue's work is finished, and keep the rest.

    worktree_sweep.py [--apply] [--only PATH]

For every worktree in `git worktree list --porcelain` except the main one (the
first entry) and the one holding the current directory, or only `--only PATH`,
the first of these that applies decides:

  1. locked                                  -> keep, `locked`
  2. detached                                -> keep, `detached HEAD`
  3. no issue number in the branch           -> keep, `no issue number in <branch>`
  4. `git status --porcelain` not empty      -> keep, `uncommitted changes`
  5. commits on no remote, unless a merged    -> keep, `<k> commit(s) on no remote`
     pull request's head contains them
  6. a same-repo pull request MERGED whose   -> remove, `PR #<m> merged`
     head contains the branch's tip
  7. the issue is closed                     -> remove, `issue #<n> closed`
  8. otherwise                               -> keep, `issue #<n> open, work not merged`

Any `git` or `gh` failure for a worktree keeps it, `cannot tell: <message>`:
no evidence never removes work. Prints `remove <path> (<branch>): <reason>` or
`keep <path> (<branch>): <reason>`, one line per worktree.

A whole sweep leaves out the main worktree and the one holding the current
directory without a word. `--only PATH` never ends silent: PATH that is the
main worktree prints `keep <path> (<branch>): the main worktree is never
removed`; PATH holding the current directory prints `keep <path> (<branch>):
the current directory is inside it; run this from <main worktree>`; PATH that
is no worktree of this repo prints `worktree_sweep: <path> is not a worktree of
this repo` on stderr. Nothing is removed in any of the three.

With `--apply`, each `remove` runs `git worktree remove <path>` (never
`--force`, so git refuses a dirty one too) and, only when its pull request
merged, `git branch -D <branch>` (a squash merge leaves the branch's commits
off the base, so `-d` would refuse). A failure is printed and the worktree
counts as kept. Then `git worktree prune` clears entries whose folder is gone.

Exit 0 when no worktree is kept, 1 when any is, 2 when the worktree list
cannot be read or `--only` names no worktree. The pull request and issue repos are the profile's
`tracker.code_repo` and `tracker.issues_repo`.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402
from stranded_work import issue_in_branch, issue_view, pull_requests  # noqa: E402


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _first_line(out, what):
    return (out.stderr.strip().splitlines() or [f"{what} exited {out.returncode}"])[0]


def worktrees():
    """[{path, branch, locked}], main worktree first, branch None when detached;
    None when git cannot list them."""
    out = git("worktree", "list", "--porcelain")
    if out.returncode != 0:
        return None
    found = []
    for block in out.stdout.split("\n\n"):
        lines = block.splitlines()
        if not lines or not lines[0].startswith("worktree "):
            continue
        branch = next((ln[len("branch refs/heads/"):] for ln in lines if ln.startswith("branch refs/heads/")), None)
        locked = any(ln == "locked" or ln.startswith("locked ") for ln in lines)
        found.append({"path": lines[0][len("worktree "):], "branch": branch, "locked": locked})
    return found


def repos():
    """(issues_repo, code_repo) from the nearest profile, each None when it cannot be read."""
    path = profile_check.find_profile()
    try:
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except (OSError, profile_check.ProfileError):
        return None, None
    tracker = settings.get("tracker") or {}
    return tracker.get("issues_repo"), tracker.get("code_repo")


KEEP, REMOVE, REMOVE_WITH_BRANCH = "keep", "remove", "remove with branch"


def decide(tree, issues_repo, code_repo):
    """(KEEP | REMOVE | REMOVE_WITH_BRANCH, reason) for one worktree."""
    branch = tree["branch"]
    if tree["locked"]:
        return KEEP, "locked"
    if branch is None:
        return KEEP, "detached HEAD"
    number = issue_in_branch(branch)
    if number is None:
        return KEEP, f"no issue number in {branch}"
    status = git("-C", tree["path"], "status", "--porcelain")
    if status.returncode != 0:
        return KEEP, f"cannot tell: {_first_line(status, 'git status')}"
    if status.stdout.strip():
        return KEEP, "uncommitted changes"
    ref = f"refs/heads/{branch}"
    tip = git("rev-parse", "--verify", "-q", ref)
    ahead = git("rev-list", "--count", ref, "--not", "--remotes", "--")
    if tip.returncode != 0 or ahead.returncode != 0:
        return KEEP, f"cannot tell: {_first_line(ahead if tip.returncode == 0 else tip, 'git rev-list')}"
    if not code_repo or not issues_repo:
        return KEEP, "cannot tell: the profile names no tracker.code_repo or tracker.issues_repo"
    prs, error = pull_requests(code_repo, branch)
    if error:
        return KEEP, f"cannot tell: {error}"
    # A squash merge leaves the branch's commits off the base, and a pruned
    # remote branch leaves them on no remote: a merged PR whose head contains
    # this tip carried them. A merged PR from an older tip does not cover newer work.
    merged = [p for p in prs if p.get("state") == "MERGED" and _contains(p.get("headRefOid") or "", tip.stdout.strip())]
    if int(ahead.stdout) > 0 and not merged:
        return KEEP, f"{ahead.stdout.strip()} commit(s) on no remote"
    if merged:
        return REMOVE_WITH_BRANCH, f"PR #{merged[0]['number']} merged"
    issue = issue_view(issues_repo, number)
    if not issue:
        return KEEP, f"cannot tell: the lookup of issue #{number} failed"
    if issue.get("state") != "OPEN":
        return REMOVE, f"issue #{number} closed"
    return KEEP, f"issue #{number} open, work not merged"


def _contains(head, tip):
    """True when `head` is `tip` or has it in its history; when git does not
    have `head` (never fetched), only equality counts."""
    if head == tip:
        return True
    return git("merge-base", "--is-ancestor", tip, head).returncode == 0


def _inside(path, folder):
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except ValueError:
        return False


def remove(tree, verdict):
    """Remove the worktree, and its branch for REMOVE_WITH_BRANCH; False when the worktree stays."""
    out = git("worktree", "remove", tree["path"])
    if out.returncode != 0:
        print(f"  not removed: {_first_line(out, 'git worktree remove')}")
        return False
    if verdict == REMOVE_WITH_BRANCH:
        out = git("branch", "-D", tree["branch"])
        if out.returncode != 0:
            print(f"  branch {tree['branch']} kept: {_first_line(out, 'git branch -D')}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Remove worktrees whose issue's work is finished.")
    parser.add_argument("--apply", action="store_true", help="remove what the sweep says to remove")
    parser.add_argument("--only", metavar="PATH", help="consider only this worktree")
    args = parser.parse_args(argv)

    trees = worktrees()
    if trees is None:
        print("worktree_sweep: cannot list the worktrees (git worktree list failed)", file=sys.stderr)
        return 2
    here = Path.cwd()
    candidates = [t for t in trees[1:] if not _inside(here, t["path"])]
    if args.only:
        target = Path(args.only).resolve()
        named = [t for t in trees if Path(t["path"]).resolve() == target]
        if not named:
            print(f"worktree_sweep: {target} is not a worktree of this repo", file=sys.stderr)
            return 2
        tree = named[0]
        label = f"keep {tree['path']} ({tree['branch'] or 'detached'})"
        if tree is trees[0]:
            print(f"{label}: the main worktree is never removed")
            return 1
        if _inside(here, tree["path"]):
            print(f"{label}: the current directory is inside it; run this from {trees[0]['path']}")
            return 1
        candidates = [tree]
    issues_repo, code_repo = repos()

    kept = False
    for tree in candidates:
        verdict, reason = decide(tree, issues_repo, code_repo)
        word = KEEP if verdict == KEEP else REMOVE
        print(f"{word} {tree['path']} ({tree['branch'] or 'detached'}): {reason}")
        if verdict == KEEP:
            kept = True
        elif args.apply and not remove(tree, verdict):
            kept = True
    if args.apply:
        git("worktree", "prune")
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main())
