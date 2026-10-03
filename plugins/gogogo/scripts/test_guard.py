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
<function context>` for any other hunk in a test file that existed at the base,
followed by its `-` and `+` lines. A pure rename and a file new since the base
list nothing. The last line is `test-guard: hunks=<n>`.

`verify` reads ANSWERS_FILE, one line per item, `H<k><TAB><same|stronger|
weaker><TAB><reason>`, and the issue body in BODY_FILE. A `weaker` item is
licensed when a line of the body's `## Test cases` or `## Design` holds a
backticked token and says "remove" or "rewrit": a token `path` licenses every
item in that test file, and `path::name` the hunks whose function context or
removed lines contain `name`. It prints each `weaker` item as `licensed` or
`NOT LICENSED`, then `test-guard: hunks=<n> same=<n> stronger=<n> weaker=<n>
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


def _unquote(path: str) -> str:
    return path[2:] if path[:2] in ("a/", "b/") else path


def items(base: str, globs: list[str]) -> list[dict]:
    tracked = _git(["ls-files"]).splitlines()
    if not any(is_test(p, globs) for p in tracked):
        raise NotChecked(f"no file matches {', '.join(globs)}")
    fork = _git(["merge-base", base, "HEAD"]).strip()
    diff = _git(["-c", "core.quotepath=off", "diff", "-M", "--unified=0", "--no-color", fork])
    found: list[dict] = []
    for block in re.split(r"^diff --git ", diff, flags=re.M)[1:]:
        lines = block.splitlines()
        old = new = None
        deleted = created = False
        renamed_from = None
        for line in lines[1:]:
            if line.startswith("@@"):
                break
            if line.startswith("deleted file mode"):
                deleted = True
            elif line.startswith("new file mode"):
                created = True
            elif line.startswith("rename from "):
                renamed_from = line[len("rename from "):]
            elif line.startswith("rename to "):
                new = line[len("rename to "):]
            elif line.startswith("--- ") and line != "--- /dev/null":
                old = _unquote(line[4:])
            elif line.startswith("+++ ") and line != "+++ /dev/null":
                new = _unquote(line[4:])
        old = renamed_from or old
        if created or old is None or not (is_test(old, globs) or (new and is_test(new, globs))):
            continue
        if deleted:
            found.append({"kind": "deleted", "path": old, "line": None, "context": "", "minus": [], "plus": []})
            continue
        path = new or old
        current = None
        for line in lines:
            match = HUNK.match(line)
            if match:
                current = {"kind": "changed", "path": path, "line": int(match.group(1)),
                           "context": match.group(2).strip(), "minus": [], "plus": [],
                           "renamed_from": renamed_from}
                found.append(current)
            elif current is not None and line.startswith("-"):
                current["minus"].append(line[1:])
            elif current is not None and line.startswith("+"):
                current["plus"].append(line[1:])
    for k, item in enumerate(found, 1):
        item["id"] = f"H{k}"
    return found


def describe(item: dict) -> str:
    if item["kind"] == "deleted":
        return f"{item['id']}  deleted  {item['path']}"
    text = f"{item['id']}  changed  {item['path']}:{item['line']}  {item['context'] or '-'}"
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


def licensed(item: dict, tokens: list[str]) -> bool:
    for token in tokens:
        if "::" in token:
            named, name = token.split("::", 1)
            if item["kind"] == "changed" and _same_file(item["path"], named) and name and (
                    name in item["context"] or any(name in m for m in item["minus"])):
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
