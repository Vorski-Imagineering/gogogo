#!/usr/bin/env python3
"""Find the earlier work an issue already has: open pull requests, branches named for it, and the branch its stop marker names.

    issue_work.py <issue> [--base <branch>]

Read-only. It does not fetch: run `git fetch origin` first. The base defaults
to the profile's `integration.base`, else `main`, and is compared as
`origin/<base>` when that exists. It collects, in order:

  1. open pull requests whose base repository is `tracker.code_repo` and that
     cross-reference the issue (`Closes #<n>`, `Refs #<n>`, any branch name);
  2. branches in `refs/heads` and `refs/remotes/origin` whose name carries the
     issue number (the rule /gogogo:status uses) and that are ahead of the base;
  3. the branch (`/tree/<branch>`) or pull request (`/pull/<m>`) linked in the
     issue's newest comment carrying a `gogogo:stop v=1` marker, when that
     branch exists locally or on `origin`.

A branch and its open pull request are one candidate. Each prints as

    candidate: <branch> (<local|remote|local and remote>), <k> commit(s) ahead of <base>[, PR #<m> open][, stop marker reason=<r>]

and an open pull request from another repository as

    fork PR #<m> from <owner/repo>: cannot be continued

Exit 0 when there is no earlier work (said on stderr), 1 when lines were
printed, 2 when it cannot tell (no profile, or a `gh` or `git` call failed),
with the reason on stderr and nothing on stdout.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402
from stranded_work import base_ref, gh, git, issue_in_branch, newest_stop, stop_links  # noqa: E402

QUERY = """
query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){issue(number:$number){
  timelineItems(itemTypes:[CROSS_REFERENCED_EVENT],first:100){nodes{... on CrossReferencedEvent{source{
    __typename ... on PullRequest{number state headRefName isCrossRepository
      headRepository{nameWithOwner} baseRepository{nameWithOwner}}}}}}
  comments(last:100){nodes{body}}}}}
"""


class CannotTell(Exception):
    """A lookup failed, so "no earlier work" cannot be claimed."""


def _gh_json(*args):
    out = gh(*args)
    if out.returncode != 0:
        raise CannotTell((out.stderr.strip().splitlines() or [f"gh exited {out.returncode}"])[0])
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        raise CannotTell("gh printed something that is not JSON")


def ahead_of(base, ref):
    """Commits on `ref` that `base` lacks; a failed count is CannotTell, never "not ahead"."""
    out = git("rev-list", "--count", f"{base}..{ref}")
    if out.returncode != 0 or not out.stdout.strip():
        raise CannotTell(f"cannot count {ref} against {base}: {out.stderr.strip() or 'git failed'}")
    return out.stdout.strip()


def settings():
    path = profile_check.find_profile()
    if not path.is_file():
        raise CannotTell("no profile (.agents/dev-process.md) found")
    try:
        found, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except profile_check.ProfileError as exc:
        raise CannotTell(f"cannot read the profile: {exc}")
    tracker = found.get("tracker", {})
    if not tracker.get("issues_repo") or not tracker.get("code_repo"):
        raise CannotTell("the profile names no tracker.issues_repo or tracker.code_repo")
    return tracker["issues_repo"], tracker["code_repo"], (found.get("integration") or {}).get("base") or "main"


def branches():
    """{name: set of "local"/"remote", ...} and {name: ref to count from}."""
    out = git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin")
    if out.returncode != 0:
        raise CannotTell(f"cannot read branches: {out.stderr.strip()}")
    where, refs = {}, {}
    for ref in out.stdout.split():
        if ref.startswith("refs/heads/"):
            name, kind = ref.removeprefix("refs/heads/"), "local"
        else:
            name, kind = ref.removeprefix("refs/remotes/origin/"), "remote"
            if name == "HEAD":
                continue
        where.setdefault(name, set()).add(kind)
        if kind == "local" or name not in refs:
            refs[name] = ref
    return where, refs


def find(number, base_name):
    issues_repo, code_repo, default_base = settings()
    base_name = base_name or default_base
    owner, name = issues_repo.split("/", 1)
    data = _gh_json("api", "graphql", "-f", f"query={QUERY}", "-f", f"owner={owner}", "-f", f"name={name}",
                    "-F", f"number={number}")
    issue = ((data.get("data") or {}).get("repository") or {}).get("issue")
    if issue is None:
        raise CannotTell(f"no issue #{number} in {issues_repo}")
    where, refs = branches()
    base = base_ref(base_name)

    candidates = {}  # branch -> {"pr": n, "reason": r}, in the order found
    forks = []
    for node in issue["timelineItems"]["nodes"]:
        source = (node or {}).get("source") or {}
        if source.get("__typename") != "PullRequest" or source.get("state") != "OPEN":
            continue
        if ((source.get("baseRepository") or {}).get("nameWithOwner") or "").lower() != code_repo.lower():
            continue
        head = (source.get("headRepository") or {}).get("nameWithOwner")
        if source.get("isCrossRepository") or (head or "").lower() != code_repo.lower():
            line = f"fork PR #{source['number']} from {head or 'a deleted fork'}: cannot be continued"
            if line not in forks:
                forks.append(line)
            continue
        candidates.setdefault(source["headRefName"], {})["pr"] = source["number"]

    for branch, ref in refs.items():
        if branch != base_name and issue_in_branch(branch) == str(number):
            ahead = ahead_of(base, ref)
            if ahead != "0":
                candidates.setdefault(branch, {})

    stop = newest_stop(issue["comments"]["nodes"])
    if stop:
        linked, pulls, reason = stop_links(stop)
        for pull in pulls:
            linked.append(_gh_json("pr", "view", str(pull), "--repo", code_repo, "--json", "headRefName")
                          ["headRefName"])
        for branch in linked:
            if branch in where:
                candidates.setdefault(branch, {})["reason"] = reason or "unknown"

    lines = []
    for branch, found in candidates.items():
        kinds = where.get(branch, set())
        place = ("local and remote" if len(kinds) == 2 else next(iter(kinds))) if kinds else "not fetched"
        ahead = ahead_of(base, refs[branch]) if branch in refs else "?"
        line = f"candidate: {branch} ({place}), {ahead} commit(s) ahead of {base_name}"
        if "pr" in found:
            line += f", PR #{found['pr']} open"
        if "reason" in found:
            line += f", stop marker reason={found['reason']}"
        lines.append(line)
    return lines + forks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("issue", type=int)
    parser.add_argument("--base", default=None, help="the branch work merges into (default: integration.base, else main)")
    args = parser.parse_args(argv)
    try:
        lines = find(args.issue, args.base)
    except CannotTell as exc:
        print(f"cannot tell whether #{args.issue} has earlier work: {exc}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    if not lines:
        print(f"no earlier work for #{args.issue}", file=sys.stderr)
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
