#!/usr/bin/env python3
"""Check a draft's title and body for the names of the repo it came from, before anything is posted.

    name_check.py [--profile FILE] --title TITLE_FILE BODY_FILE

Read-only. For text that will be published somewhere other than the repo's own
tracker, so the names of the repo it was written in must not be in it. The
names are derived, then matched in the title file and the body file:

  - the profile's `tracker.issues_repo` and `tracker.code_repo`, each as
    `owner/name`, `owner` and `name`;
  - the `owner/name` of each git remote of the repo holding the profile;
  - the folder name of that repo and of its main worktree;
  - the host of each `environments[].url`;
  - each string in `publish.private_names`.

The target's own names (`Vorski-Imagineering/gogogo` and its two parts) and any
name under three characters are dropped. A name matches ignoring case, with
each `-`, `_`, space or `.` in it standing for any one of those, and only on
word boundaries. A match inside a path token (one with a `/`) is exempt when
that path, or that path less a leading `plugins/gogogo/`, exists under the
plugin: a name that happens to be a script's name is not a leak, an invented
path is.

The title file holds exactly one non-empty line: the title that will be posted.

Prints `<file>:<line>: <matched text>` for each hit and exits 1. With none it
prints `name-check: clean (<k> names; <title file>, <body file>)` and exits 0.
Exit 2, nothing on stdout and the reason on stderr: the title file is missing,
empty or has more than one non-empty line; the body cannot be read; there is no
profile; or there is no name to check (no evidence never passes).

The check cannot see a name nobody listed: a product name, a host quoted in
output, another repo the session touched. `publish.private_names` is for those.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TARGET = {"vorski-imagineering/gogogo", "vorski-imagineering", "gogogo"}
SEPARATORS = "-_ ."
EDGE = " \t`'\"()[]{}<>,;:!?*."


class Refused(Exception):
    """The check cannot be made; the message goes to stderr and the exit is 2."""


def _git(root, *args):
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def _remote_names(url):
    """`owner/name` from a remote URL (ssh, scp-like or https), else None."""
    path = urlparse(url).path if "://" in url else url.split(":", 1)[-1]
    parts = [p for p in path.strip("/").removesuffix(".git").split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else None


def derive(settings, root):
    """The names to look for, in order, without duplicates."""
    found = []
    tracker = settings.get("tracker") if isinstance(settings.get("tracker"), dict) else {}
    for key in ("issues_repo", "code_repo"):
        repo = tracker.get(key)
        if isinstance(repo, str) and repo:
            found += [repo, *repo.split("/")]
    for line in _git(root, "remote", "-v").splitlines():
        fields = line.split()
        if len(fields) >= 2 and (name := _remote_names(fields[1])):
            found.append(name)
    found.append(Path(_git(root, "rev-parse", "--show-toplevel").strip() or root).name)
    first = next((ln for ln in _git(root, "worktree", "list", "--porcelain").splitlines()
                  if ln.startswith("worktree ")), None)
    if first:
        found.append(Path(first[len("worktree "):]).name)
    for env in settings.get("environments") or []:
        host = urlparse(env.get("url") or "").hostname if isinstance(env, dict) else None
        if host:
            found.append(host)
    publish = settings.get("publish") if isinstance(settings.get("publish"), dict) else {}
    found += [n for n in publish.get("private_names") or [] if isinstance(n, str)]
    names, seen = [], set()
    for name in found:
        name = name.strip()
        if len(name) < 3 or name.lower() in TARGET or name.lower() in seen:
            continue
        seen.add(name.lower())
        names.append(name)
    return names


def pattern(name):
    """Case-insensitive; each run of `-`, `_`, space or `.` matches any one of them; on word boundaries."""
    parts = re.split(f"[{re.escape(SEPARATORS)}]", name)
    body = f"[{re.escape(SEPARATORS)}]".join(re.escape(p) for p in parts)
    return re.compile(f"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.I)


def _plugin_path(token):
    """True when the token names an existing path under the plugin."""
    token = token.strip(EDGE)
    # Only a relative path: an absolute or home path, or one that climbs with `..`, can carry a
    # private name in the part that is not the plugin's.
    if "/" not in token or token.startswith(("/", "~")) or ".." in token.split("/") or "\\" in token:
        return False
    for candidate in (token, token.removeprefix("plugins/gogogo/")):
        try:
            path = (PLUGIN_ROOT / candidate).resolve()
        except (OSError, ValueError):
            continue
        if path.exists() and (path == PLUGIN_ROOT or PLUGIN_ROOT in path.parents):
            return True
    return False


def _exempt(line, start, end):
    return any(m.start() <= start and end <= m.end() and _plugin_path(m.group())
               for m in re.finditer(r"\S+", line))


def hits(path, text, patterns):
    """[(file, line number, start, matched text)] for what the patterns match and is not exempt."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        spans = [(m.start(), m.end()) for p in patterns for m in p.finditer(line) if not _exempt(line, m.start(), m.end())]
        # A shorter match inside a longer one on the same line is the same hit.
        for start, end in sorted(set(spans)):
            if not any(s <= start and end <= e and (s, e) != (start, end) for s, e in spans):
                found.append((path, number, start, line[start:end]))
    return found


def check(title_file, body_file, profile=None):
    """(hits, number of names); raises Refused when the check cannot be made."""
    try:
        title_text = Path(title_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Refused(f"cannot read the title file {title_file}: {getattr(e, 'strerror', None) or e}")
    if len([ln for ln in title_text.splitlines() if ln.strip()]) != 1:
        raise Refused(f"the title file {title_file} must hold exactly one non-empty line")
    try:
        body_text = Path(body_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Refused(f"cannot read the body file {body_file}: {getattr(e, 'strerror', None) or e}")
    try:
        path = Path(profile) if profile else profile_check.find_profile()
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, profile_check.ProfileError) as e:
        raise Refused(f"cannot read the profile: {e}")
    root = path.resolve().parent.parent
    names = derive(settings, root)
    if not names:
        raise Refused("no names to check: the profile and the checkout name nothing but gogogo's own")
    patterns = [pattern(n) for n in names]
    return hits(title_file, title_text, patterns) + hits(body_file, body_text, patterns), len(names)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a draft for the names of the repo it came from.")
    parser.add_argument("--profile", help="the profile file (default: the nearest one)")
    parser.add_argument("--title", required=True, metavar="TITLE_FILE", help="a file holding the one-line title")
    parser.add_argument("body", metavar="BODY_FILE")
    args = parser.parse_args(argv)
    try:
        found, count = check(args.title, args.body, args.profile)
    except Refused as e:
        print(f"name_check: {e}", file=sys.stderr)
        return 2
    for path, number, _, text in found:
        print(f"{path}:{number}: {text}")
    if found:
        return 1
    print(f"name-check: clean ({count} names; {args.title}, {args.body})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
