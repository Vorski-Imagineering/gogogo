#!/usr/bin/env python3
"""List the test hunks a change touched, and check a reader's verdicts on them.

    test_guard.py list   --base REF [--profile FILE] [--json]
    test_guard.py verify BODY_FILE ANSWERS_FILE --base REF [--profile FILE] [--json]

A change can get green by weakening its tests: deleting one, adding a skip,
loosening an assertion. This finds *where* the tests changed; a reader that
did not make the change judges *whether* each change made them weaker. It
names no language or test framework.

The test files are the union of every lane's `tests` patterns in the profile
(`--profile`, default the nearest `.agents/dev-process.md`), matched against
repo-relative paths with `fnmatch`, so `*` also matches `/`. When no lane has
`tests`, or the patterns match no tracked file, both commands print
`tests: not checked (...)` and exit 3: no evidence is never a pass.

`list` diffs the merge base of REF and HEAD against the working tree, with
rename detection, and prints one item per test hunk: `H<k>  deleted  <path>`
for a test file deleted since the base, or `H<k>  changed  <path>:<old line>
<enclosing>` for any other hunk in a test file that existed at the base,
followed by its `-` and `+` lines. `<enclosing>` is the innermost enclosing
line of the file at the base (the test's own `def`, in most languages; for a
line added just above a definition, that definition), or git's function
context when there is none. Lines at column 0 are skipped while a more
indented enclosing line exists. A pure rename and a file new since
the base list nothing. The last line is `test-guard: hunks=<n>`.

`verify` reads ANSWERS_FILE, one line per item, `H<k><TAB><same|stronger|
weaker><TAB><reason>`, and the issue body in BODY_FILE. A `weaker` item is
licensed when a line of the body's `## Test cases` or `## Design` holds a
backticked token and says "remove" or "rewrit": a token `path` licenses every
item in that test file, and `path::name` the hunks whose enclosing lines,
function context or removed lines contain `name` as a whole word; `name` may
hold further `::`-separated parts, each of which must occur. It prints each
`weaker` item as `licensed` or `NOT LICENSED`, then `test-guard: hunks=<n> same=<n> stronger=<n> weaker=<n>
licensed=<n> unlicensed=<n>`.

`/gogogo:dev` §6 runs this once every lane is green. It only reads git and
files.

Exit codes: 0 listed, or nothing unlicensed; 1 (`verify`) an unlicensed
weaker item; 2 a `git` call failed, a file could not be read, or the answers
were refused; 3 not checked.

Standard library only; imports `profile_check` and `spec_lint` from this folder.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402
from spec_lint import split_sections  # noqa: E402

VERDICTS = ("same", "stronger", "weaker")
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@ ?(.*)$")
TOKEN = re.compile(r"`([^`\s]+)`")
LICENSING = re.compile(r"remove|rewrit", re.I)


class GitError(Exception):
    """A `git` call failed."""


class NotChecked(Exception):
    """The profile names no test files, or its patterns match none."""


def _git(args: list[str]) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise GitError((out.stderr.strip().splitlines() or [f"git exited {out.returncode}"])[0])
    return out.stdout


def patterns(profile: str | None) -> list[str]:
    path = Path(profile) if profile else profile_check.find_profile()
    settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    found = []
    for lane in settings.get("lanes") or []:
        if isinstance(lane, dict):
            found += [p for p in lane.get("tests") or [] if isinstance(p, str) and p]
    if not found:
        raise NotChecked("no lane names its test files")
    return found


def is_test(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def _hunks(fork: str, paths: list[str]) -> list[dict]:
    """The `@@` hunks of one file's diff, with its `-` and `+` lines."""
    diff = _git(["--literal-pathspecs", "diff", "-M", "--unified=0", "--no-color", "--no-ext-diff",
                 fork, "--", *paths])
    hunks: list[dict] = []
    for line in diff.splitlines():
        match = HUNK.match(line)
        if match:
            hunks.append({"line": int(match.group(1)), "context": match.group(2).strip(),
                          "minus": [], "plus": []})
        elif hunks and line.startswith("-"):
            hunks[-1]["minus"].append(line[1:])
        elif hunks and line.startswith("+"):
            hunks[-1]["plus"].append(line[1:])
    return hunks


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip())


def enclosing(old_lines: list[str], line: int, content_indent: int) -> list[str]:
    """The lines enclosing a hunk in the file at the base, innermost first. Walking up
    from `line`, take each non-blank line indented more than 0 and less than the hunk's
    content and every line already taken, then the first line at indentation 0 whose
    next non-blank line is indented more than 0 and no deeper than the last one taken,
    so text written at the margin is passed over. When nothing above 0 is taken: each
    line less indented than the hunk and the lines taken, up to one at indentation 0."""
    above = old_lines[:max(line, 0)]
    found, limit, last = [], content_indent, None
    for i in range(len(above) - 1, -1, -1):
        text = above[i]
        if text.strip() and 0 < _indent(text) < limit:
            found.append(text.strip())
            limit, last = _indent(text), i
    if found:
        for i in range(last - 1, -1, -1):
            text = above[i]
            if not text.strip() or _indent(text) != 0:
                continue
            below = next((t for t in old_lines[i + 1:] if t.strip()), None)
            if below is not None and 0 < _indent(below) <= limit:
                found.append(text.strip())
                break
        return found
    limit = content_indent
    for text in reversed(above):
        if not text.strip():
            continue
        if _indent(text) < limit:
            found.append(text.strip())
            limit = _indent(text)
            if limit == 0:
                break
    return found


def _definition_below(old_lines: list[str], hunk: dict, content_indent: int) -> str | None:
    """The definition directly below a hunk whose lines all sit at its content
    indentation, such as a decorator added above a method: the old line after the
    hunk, when it is at that indentation and the next non-blank line is deeper."""
    lines = hunk["minus"] + hunk["plus"]
    if any(t.strip() and _indent(t) != content_indent for t in lines):
        return None
    last = (hunk["plus"] or hunk["minus"])[-1:]
    if not last or not last[0].strip():
        return None
    after = hunk["line"] + len(hunk["minus"]) if hunk["minus"] else hunk["line"] + 1
    if not 1 <= after <= len(old_lines):
        return None
    candidate = old_lines[after - 1]
    if not candidate.strip() or _indent(candidate) != content_indent:
        return None
    below = next((t for t in old_lines[after:] if t.strip()), None)
    if below is None or _indent(below) <= content_indent:
        return None
    return candidate.strip()


def _content_indent(hunk: dict) -> int:
    """The least indentation among the hunk's non-blank lines, so a hunk that runs
    into the next definition is not taken as inside the one it starts in."""
    return min((_indent(t) for t in hunk["minus"] + hunk["plus"] if t.strip()), default=0)


def _base_lines(fork: str, path: str) -> list[str]:
    """The file at the base, split on newlines only, as git numbers its lines."""
    out = subprocess.run(["git", "show", f"{fork}:{path}"], capture_output=True)
    if out.returncode != 0:
        err = out.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GitError((err or [f"git exited {out.returncode}"])[0])
    return out.stdout.decode("utf-8").split("\n")


def items(base: str, globs: list[str]) -> list[dict]:
    fork = _git(["merge-base", base, "HEAD"]).strip()
    tracked = set(_git(["ls-files", "-z"]).split("\0"))
    tracked |= set(_git(["ls-tree", "-r", "-z", "--name-only", fork]).split("\0"))
    files = sorted(p for p in tracked if p and is_test(p, globs))
    if not files:
        raise NotChecked(f"no file matches {', '.join(globs)}")
    # Limited to the test files at the base and now, so a test file moved out
    # of the patterns reads as deleted, not as a rename that lists nothing.
    fields = _git(["--literal-pathspecs", "diff", "-M", "--name-status", "-z", fork, "--", *files]).split("\0")
    found: list[dict] = []
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status[0] in "RC":
            old, new = fields[i + 1], fields[i + 2]
            i += 3
        else:
            old = new = fields[i + 1]
            i += 2
        if status[0] == "A" or status[0] == "C":
            continue  # new since the base: it cannot weaken anything
        if status[0] == "D":
            found.append({"kind": "deleted", "path": old, "line": None, "context": "", "enclosing": [],
                          "minus": [], "plus": []})
            continue
        if status == "R100":
            continue
        renamed_from = old if status[0] == "R" else None
        hunks = _hunks(fork, [old, new] if renamed_from else [new])
        old_lines = _base_lines(fork, old) if hunks else []
        for hunk in hunks:
            indent = _content_indent(hunk)
            hunk["enclosing"] = enclosing(old_lines, hunk["line"], indent)
            below = _definition_below(old_lines, hunk, indent)
            if below is not None:
                hunk["enclosing"].insert(0, below)
            found.append({"kind": "changed", "path": new, "renamed_from": renamed_from, **hunk})
    for k, item in enumerate(found, 1):
        item["id"] = f"H{k}"
    return found


def describe(item: dict) -> str:
    if item["kind"] == "deleted":
        return f"{item['id']}  deleted  {item['path']}"
    shown = item["enclosing"][0] if item["enclosing"] else item["context"] or "-"
    text = f"{item['id']}  changed  {item['path']}:{item['line']}  {shown}"
    if item.get("renamed_from"):
        text += f"  (renamed from {item['renamed_from']})"
    return text


def licences(body: str) -> list[str]:
    _, sections = split_sections(body)
    tokens = []
    for title, _, lines in sections:
        if title not in ("Test cases", "Design"):
            continue
        for line in lines:
            if LICENSING.search(line):
                tokens += TOKEN.findall(line)
    return tokens


def _same_file(path: str, named: str) -> bool:
    return path == named or path.endswith("/" + named)


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])", text) is not None


def licensed(item: dict, tokens: list[str]) -> bool:
    for token in tokens:
        if "::" in token:
            named, rest = token.split("::", 1)
            segments = [part for part in rest.split("::") if part]
            texts = [item["context"], *item["enclosing"], *item["minus"]]
            if item["kind"] == "changed" and _same_file(item["path"], named) and segments and all(
                    any(_has_word(t, part) for t in texts) for part in segments):
                return True
        elif _same_file(item["path"], token):
            return True
    return False


def read_answers(text: str, found: list[dict]) -> tuple[list[str], dict[str, tuple[str, str]]]:
    ids = [i["id"] for i in found]
    errors, answers, refused = [], {}, set()
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        parts = raw.split("\t", 2)
        id_ = parts[0].strip()
        verdict = parts[1].strip() if len(parts) > 1 else ""
        reason = parts[2].strip() if len(parts) > 2 else ""
        if id_ not in ids:
            errors.append(f"line {number}: {id_} is not an item")
        elif id_ in answers:
            errors.append(f"line {number}: {id_} is answered twice")
        elif verdict not in VERDICTS:
            errors.append(f"line {number}: {id_}: verdict {verdict!r} is not one of {', '.join(VERDICTS)}")
            refused.add(id_)
        elif verdict == "weaker" and not reason:
            errors.append(f"line {number}: {id_}: weaker needs a reason")
            refused.add(id_)
        else:
            answers[id_] = (verdict, reason)
    errors += [f"{i}: no answer" for i in ids if i not in answers and i not in refused]
    return errors, answers


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "verify"):
        p = sub.add_parser(name)
        if name == "verify":
            p.add_argument("body", help="file holding the issue body")
            p.add_argument("answers", help="file holding the reader's verdicts")
        p.add_argument("--base", required=True, help="the branch the change merges into")
        p.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md)")
        p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        globs = patterns(args.profile)
        found = items(args.base, globs)
        body = Path(args.body).read_text(encoding="utf-8") if args.command == "verify" else ""
        answer_text = Path(args.answers).read_text(encoding="utf-8") if args.command == "verify" else ""
    except NotChecked as exc:
        print(f"tests: not checked ({exc})")
        return 3
    except (OSError, UnicodeDecodeError, GitError, profile_check.ProfileError) as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.command == "list":
        if args.json:
            print(json.dumps({"items": found, "hunks": len(found)}, indent=2))
            return 0
        for item in found:
            print(describe(item))
            for line in item["minus"]:
                print(f"    -{line}")
            for line in item["plus"]:
                print(f"    +{line}")
        print(f"test-guard: hunks={len(found)}")
        return 0

    errors, answers = read_answers(answer_text, found)
    if errors:
        for line in errors:
            print(f"error: {line}", file=sys.stderr)
        return 2
    tokens = licences(body)
    counts = {v: 0 for v in VERDICTS}
    lic = unlic = 0
    weaker = []
    for item in found:
        verdict, reason = answers[item["id"]]
        counts[verdict] += 1
        if verdict == "weaker":
            ok = licensed(item, tokens)
            lic += ok
            unlic += not ok
            weaker.append({"id": item["id"], "licensed": ok, "reason": reason, "item": describe(item)})
    summary = (f"test-guard: hunks={len(found)} same={counts['same']} stronger={counts['stronger']} "
               f"weaker={counts['weaker']} licensed={lic} unlicensed={unlic}")
    if args.json:
        print(json.dumps({"items": found, "weaker": weaker, **counts, "licensed": lic,
                          "unlicensed": unlic, "hunks": len(found)}, indent=2))
    else:
        for w in weaker:
            print(f"{w['id']}  {'licensed' if w['licensed'] else 'NOT LICENSED'}  {w['reason']}")
        print(summary)
    return 1 if unlic else 0


if __name__ == "__main__":
    sys.exit(main())
