#!/usr/bin/env python3
"""Draft one month's section of docs/changes.md from main's first-parent commits.

    python3 tools/changes.py <YYYY-MM> [--ref origin/main]

Prints `## <Month YYYY>`, then the month's commits on the ref's first-parent
line (by commit date), each as `- <subject>, [#<issue>](<link>)`: the subject
without its `(Refs #N, ...)` and trailing `(#PR)`, linked to the issue it names
(`(Refs #N)`, or the older `(#issue) (#PR)`), or to its pull request when it
names none. Each commit goes in the first group
its changed paths fit: New skills (adds a skill's SKILL.md), Settings (changes
profile-schema.md), Skill changes, Scripts, Other. Empty groups are left out.
A month with no commits prints `no changes in <YYYY-MM>` and exits 1.

gogogo's own tool, read-only: it reads git and writes nothing. A person adds
the section to the top of docs/changes.md through a PR, with a one-line
summary above each group.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/Vorski-Imagineering/gogogo"
SKILLS = "plugins/gogogo/skills/"
NEW_SKILL = re.compile(r"^plugins/gogogo/skills/[^/]+/SKILL\.md$")
SCHEMA = "plugins/gogogo/references/profile-schema.md"
SCRIPTS = "plugins/gogogo/scripts/"
GROUPS = ("New skills", "Settings", "Skill changes", "Scripts", "Other")
REFS = re.compile(r"\s*\(Refs #(\d+)[^)]*\)")
PR = re.compile(r"\s*\(#(\d+)\)\s*$")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def _paths(root: Path, sha: str) -> list[tuple[str, str]]:
    """(status, path) for each path the commit changed against its first parent."""
    parents = _git(root, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    if parents:
        out = _git(root, "diff", "--name-status", "--no-renames", parents[0], sha)
    else:
        out = _git(root, "diff-tree", "-r", "--root", "--no-commit-id", "--name-status", "--no-renames", sha)
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]


def group(paths: list[tuple[str, str]]) -> str:
    if any(status == "A" and NEW_SKILL.match(path) for status, path in paths):
        return "New skills"
    if any(path == SCHEMA for _, path in paths):
        return "Settings"
    if any(path.startswith(SKILLS) for _, path in paths):
        return "Skill changes"
    if any(path.startswith(SCRIPTS) for _, path in paths):
        return "Scripts"
    return "Other"


def line(subject: str) -> str:
    issue = REFS.search(subject)
    text = REFS.sub("", subject)
    pr = PR.search(text)
    text = PR.sub("", text)
    if pr and not issue:
        # The older form `<subject> (#issue) (#PR)`.
        issue = PR.search(text)
        text = PR.sub("", text)
    text = text.strip()
    if issue:
        return f"- {text}, [#{issue.group(1)}]({REPO}/issues/{issue.group(1)})"
    if pr:
        return f"- {text}, [#{pr.group(1)}]({REPO}/pull/{pr.group(1)})"
    return f"- {text}"


def main(argv=None, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("month", help="YYYY-MM")
    ap.add_argument("--ref", default="origin/main")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{2}", a.month):
        ap.error("month must be YYYY-MM")
    log = _git(root, "log", "--first-parent", "--reverse", "--format=%H%x00%cs%x00%s", a.ref)
    grouped: dict[str, list[str]] = {g: [] for g in GROUPS}
    for entry in log.splitlines():
        sha, day, subject = entry.split("\x00", 2)
        if day.startswith(a.month + "-"):
            grouped[group(_paths(root, sha))].append(line(subject))
    if not any(grouped.values()):
        print(f"no changes in {a.month}")
        return 1
    year, month = (int(x) for x in a.month.split("-"))
    print(f"## {date(year, month, 1):%B %Y}")
    for name in GROUPS:
        if grouped[name]:
            print(f"\n### {name}\n")
            print("\n".join(grouped[name]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
