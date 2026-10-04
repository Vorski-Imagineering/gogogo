#!/usr/bin/env python3
"""May this pull request be merged now, and if not, why?

    merge_ready.py <pr> [--repo owner/name] [--require-checks]

Prints one line, `<outcome>: <detail>`, and exits 0 for `ready`, 1 for any
other outcome, 2 when the PR cannot be read (the `gh` message goes to stderr
and nothing to stdout). The first outcome that fits wins:

    not-open         the PR's state is not OPEN
    draft            the PR is a draft
    conflict         it conflicts with its base
    checks-failed    a check failed (named in the detail)
    checks-pending   a check has not finished
    no-checks        no check ran, and --require-checks was given
    behind           its branch is behind its base
    review-required  a review is required, or changes were requested
    blocked          a branch rule blocks it for another reason
    unknown          GitHub has not worked out whether it merges
    ready            none of the above; the detail names the head commit

Checks that all skipped count as none. GitHub computes `mergeable` after a
push, so while it reads UNKNOWN the PR is read again, up to 3 more times, 10
seconds apart. The branch is judged by the fields GitHub returns, never by the
wording of a `gh` refusal. Read-only: it changes nothing. The merge itself is
the skill's step, pinned to the head this prints (`--match-head-commit`).
"""
import argparse
import json
import subprocess
import sys
import time

FIELDS = "state,isDraft,mergeable,mergeStateStatus,reviewDecision,headRefOid,baseRefName,statusCheckRollup"
REREADS = 3
REREAD_WAIT = 10
FAILED = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def read(pr, repo):
    """(data, None), or (None, the gh message)."""
    out = run("gh", "pr", "view", pr, *(["--repo", repo] if repo else []), "--json", FIELDS)
    if out.returncode != 0:
        return None, out.stderr.strip() or f"gh exited {out.returncode}"
    try:
        return json.loads(out.stdout), None
    except ValueError as exc:
        return None, f"gh printed something that is not JSON: {exc}"


def verdicts(rollup):
    """(failed names, pending names, ran): a check run's conclusion, or a status context's state."""
    failed, pending, ran = [], [], 0
    for check in rollup or []:
        name = check.get("name") or check.get("context") or "unnamed check"
        if "state" in check and "status" not in check:  # a commit status
            result = check.get("state") or ""
            finished = result not in ("PENDING", "EXPECTED", "")
        else:  # a check run
            result = check.get("conclusion") or ""
            finished = check.get("status") == "COMPLETED"
        if finished and result in FAILED:
            failed.append(name)
        elif not finished or result not in PASSED:
            pending.append(name)
        elif result != "SKIPPED":
            ran += 1
    return failed, pending, ran


def judge(data, require_checks):
    if data.get("state") != "OPEN":
        return "not-open", f"the PR is {data.get('state')}"
    if data.get("isDraft"):
        return "draft", "the PR is a draft"
    merge_state = data.get("mergeStateStatus")
    if data.get("mergeable") == "CONFLICTING" or merge_state == "DIRTY":
        return "conflict", "the branch conflicts with its base"
    failed, pending, ran = verdicts(data.get("statusCheckRollup"))
    if failed:
        return "checks-failed", ", ".join(failed)
    if pending:
        return "checks-pending", ", ".join(pending)
    if not ran and require_checks:
        return "no-checks", "no check ran"
    if merge_state == "BEHIND":
        return "behind", f"the branch is behind {data.get('baseRefName')}"
    if data.get("reviewDecision") in ("REVIEW_REQUIRED", "CHANGES_REQUESTED"):
        return "review-required", data["reviewDecision"].lower().replace("_", " ")
    if merge_state == "BLOCKED":
        return "blocked", "a branch rule blocks the merge"
    if data.get("mergeable") == "UNKNOWN" or merge_state == "UNKNOWN":
        return "unknown", "GitHub has not worked out whether it merges"
    return "ready", data.get("headRefOid") or "no head commit"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pr")
    parser.add_argument("--repo", help="owner/name, when the PR is not in this checkout's repo")
    parser.add_argument("--require-checks", action="store_true",
                        help="a PR on which no check ran is not ready")
    args = parser.parse_args(argv)
    for attempt in range(REREADS + 1):
        data, error = read(args.pr, args.repo)
        if data is None:
            print(f"cannot read PR {args.pr}: {error}", file=sys.stderr)
            return 2
        settling = (data.get("state") == "OPEN" and not data.get("isDraft")
                    and "UNKNOWN" in (data.get("mergeable"), data.get("mergeStateStatus")))
        if not settling or attempt == REREADS:
            break
        time.sleep(REREAD_WAIT)
    name, detail = judge(data, args.require_checks)
    print(f"{name}: {detail}")
    return 0 if name == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
