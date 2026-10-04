#!/usr/bin/env python3
"""List a spec's items, and check that a reader answered every one against the change.

    spec_check.py items BODY_FILE [--base REF] [--json]
    spec_check.py verify BODY_FILE ANSWERS_FILE [--base REF] [--json]

`items` prints one line per item of the spec in BODY_FILE (an issue body, or
`-` for stdin): `V<k>` each numbered step of Verify by hand, `A<k>` each
Approvals row and `A0` the Not approved line, `D<k>` each numbered Design item
and `T<k>` each numbered test case (both count items numbered `1.` or `**1.**`
at the start of a line), `N<k>` each bullet under Explicitly not in scope, and
`F:<path>` each backticked path under Create and Edit; a path holding
`{a,b}` groups is expanded to one item per combination.
Under Edit, a backticked name with no `/` counts only when a tracked or
unignored file in the working tree equals it or ends with `/` + it (a setting
such as `preflight.extra` is not a file); under Create every backticked path
counts. So a name with no / under Edit counts only when a file by that name
exists in the working tree. Ids are by position. A
Design or Test cases section with no numbered item is one item, `D0` or `T0`,
and is printed as `unlisted:`; so is Files when it is missing or has no Create
or Edit group naming a path. With `--base`, each `F:` item is `met` when the change
touches that file and `missing` when it does not, and each changed file no
`F:` item names is printed as `outside:` (not when Files is unlisted: there is
no list to be outside of).

`verify` reads a reader's answers, one line per `V`, `A`, `D`, `T` and `N`
item: `<id> | <met|missing|differs|na> | <evidence> | <note>`. Evidence is
`path`, `path:line`, `path::name`, or for a test inside a class
`path::Class.name` or `path::Class::name` (each part found in the file after
the one before), several separated by `, `, or `-`; every
one must resolve to a file in the working tree, by a path relative to it. It refuses an answer list that skips an
item, answers one twice, names an unknown id, gives `met` or `differs` on a
`D`, `T` or `A` item with no evidence, or leaves a note empty where one is
needed. Otherwise it prints what is not `met`, then
`spec-check: items=<n> met=<n> missing=<n> differs=<n> na=<n> outside=<n>`.

`/gogogo:dev` §5 runs this before the review. It only reads: the body, the
answers, the working tree and `git`.

Exit codes: `items` 0 listed, 1 the body has no spec; `verify` 0 every item
met and no outside file, 1 something missing, differing or outside; both 2 on
refused answers, an unreadable file or a failed `git` call.

Standard library only; imports `spec_lint` from this folder.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spec_lint import file_groups, numbered_items, split_sections, table_rows  # noqa: E402

STATUSES = ("met", "missing", "differs", "na")
NEEDS_EVIDENCE = ("D", "T", "A")
PATH = re.compile(r"`([^`\s]*(?:/[^`\s]*|\.[A-Za-z0-9]{1,5}))`")
PARENS = re.compile(r"\([^()]*\)")
BULLET = re.compile(r"^[-*]\s+(\S.*)")
NOT_APPROVED = re.compile(r"^\**\s*not approved\s*:\**\s*(.*)", re.I)


class GitError(Exception):
    """A `git` call failed."""


def _git(args: list[str]) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise GitError((out.stderr.strip().splitlines() or [f"git exited {out.returncode}"])[0])
    return out.stdout


def _strip_number(line: str) -> str:
    return re.sub(r"^\*{0,2}\d+[.)]\*{0,2}\s+", "", line.strip())


def _tree() -> list[str]:
    """Every tracked or unignored file, named from the repo top wherever this runs."""
    out = _git(["ls-files", "-z", "--full-name", "--cached", "--others", "--exclude-standard", "--", ":/"])
    return [p for p in out.split("\0") if p]


BRACES = re.compile(r"\{([^{}]*,[^{}]*)\}")


def _expand(path: str) -> list[str]:
    """Every combination of the `{a,b}` groups in path, the first group varying
    slowest. A path with no group, an unmatched or nested brace, or a group
    with no comma comes back as it is."""
    rest = BRACES.sub("", path)
    if "{" in rest or "}" in rest or not BRACES.search(path):
        return [path]
    out, last = [""], 0
    for m in BRACES.finditer(path):
        out = [o + path[last:m.start()] + alt for o in out for alt in m.group(1).split(",")]
        last = m.end()
    return [o + path[last:] for o in out]


def _paths(lines: list[str], tree=None) -> list[str]:
    """Backticked paths in lines. With tree (a callable listing the working tree's
    files, called at most once), a name with no `/` is kept only when a file
    equals it or ends with `/` + it."""
    found, files = [], None
    for line in lines:
        while PARENS.search(line):
            line = PARENS.sub("", line)
        for path in (p for found_path in PATH.findall(line) for p in _expand(found_path)):
            if tree is not None and "/" not in path:
                if files is None:
                    files = tree()
                if not any(f == path or f.endswith("/" + path) for f in files):
                    continue
            found.append(path)
    return list(dict.fromkeys(found))


def list_items(body: str, changed: list[str] | None = None, tree=None) -> dict | None:
    """{items: [{id, text, status?}], unlisted: [...], outside: [...]}, or None when there is no spec."""
    _, sections = split_sections(body)
    by_title = {title: lines for title, _, lines in reversed(sections)}
    if not any(t in by_title for t in ("Design", "Test cases", "Files")):
        return None
    items, unlisted = [], []

    def add(id_, text):
        items.append({"id": id_, "text": text.strip()[:100]})

    for k, (_, line) in enumerate(numbered_items(by_title.get("Verify by hand", [])), 1):
        add(f"V{k}", _strip_number(line))
    if "Approvals" in by_title:
        lines = by_title["Approvals"]
        rows = [r for r in table_rows(lines) if len(r) > 1 and not r[1].startswith("None")]
        for k, row in enumerate(rows, 1):
            add(f"A{k}", row[1])
        for line in lines:
            match = NOT_APPROVED.match(line.strip())
            if match and match.group(1).strip().rstrip(".").lower() != "none":
                add("A0", match.group(1))
                break
    for title, letter in (("Design", "D"), ("Test cases", "T")):
        if title not in by_title:
            continue
        numbered = numbered_items(by_title[title])
        if not numbered:
            add(f"{letter}0", " ".join(ln.strip() for ln in by_title[title] if ln.strip()))
            unlisted.append(title)
        for k, (_, line) in enumerate(numbered, 1):
            add(f"{letter}{k}", _strip_number(line))
    groups = file_groups(by_title.get("Files", []))
    bullets = [m.group(1) for m in map(BULLET.match, groups.get("not_in_scope", [])) if m]
    for k, text in enumerate(bullets, 1):
        add(f"N{k}", text)
    outside = []
    paths = list(dict.fromkeys(_paths(groups.get("create", [])) + _paths(groups.get("edit", []), tree)))
    if not paths:
        unlisted.append("Files")
    for path in paths:
        add(f"F:{path}", path)
    if changed is not None:
        def touches(path):
            return [f for f in changed if f == path or f.endswith("/" + path)]
        for item in items:
            if item["id"].startswith("F:"):
                item["status"] = "met" if touches(item["text"]) else "missing"
        if paths:
            outside = [f for f in changed if not any(f == p or f.endswith("/" + p) for p in paths)]
    return {"items": items, "unlisted": unlisted, "outside": outside}


def _fork(base: str) -> str:
    return _git(["merge-base", base, "HEAD"]).strip()


def _tree_at(rev: str) -> list[str]:
    """Every file in commit rev, named from the repo top."""
    return [p for p in _git(["ls-tree", "-r", "-z", "--name-only", "--full-tree", rev]).split("\0") if p]


def changed_files(base: str) -> list[str]:
    fork = _fork(base)
    names = _git(["diff", "--name-only", fork]).splitlines()
    names += _git(["ls-files", "--others", "--exclude-standard"]).splitlines()
    return list(dict.fromkeys(n for n in names if n))


def _in_order(name: str, text: str) -> bool:
    """A `Class.name` or `Class::name` form: two or more non-empty parts, each
    found in text after the end of the one before."""
    parts = re.split(r"::|\.", name)
    if len(parts) < 2 or not all(parts):
        return False
    end = 0
    for part in parts:
        at = text.find(part, end)
        if at < 0:
            return False
        end = at + len(part)
    return True


def _resolves(evidence: str) -> str | None:
    """None when every part of the evidence resolves, else what does not."""
    for part in (p.strip() for p in evidence.split(", ")):
        path, line, name = part, None, None
        if "::" in part:
            path, name = part.split("::", 1)
        elif re.search(r":\d+$", part):
            path, line = part.rsplit(":", 1)
        file = Path(path)
        if not path or file.is_absolute() or not file.resolve().is_relative_to(Path.cwd().resolve()):
            return f"{part}: not a path inside the working tree"
        if not file.is_file():
            return f"{part}: no such file"
        text = file.read_text(encoding="utf-8", errors="replace")
        if line is not None and not 1 <= int(line) <= len(text.splitlines()):
            return f"{part}: past the end of the file"
        if name is not None and (not name or name not in text) and not _in_order(name, text):
            return f"{part}: not in the file"
    return None


def check_answers(listed: dict, answers: str) -> tuple[list[str], list[dict]]:
    """(errors, answers as dicts in item order)."""
    ids = [i["id"] for i in listed["items"] if not i["id"].startswith("F:")]
    errors, seen = [], {}
    for number, raw in enumerate(answers.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|", 3)]
        if len(parts) != 4:
            errors.append(f"line {number}: expected <id> | <status> | <evidence> | <note>")
            continue
        id_, status, evidence, note = parts
        if id_ not in ids:
            errors.append(f"line {number}: {id_} is not an item")
            continue
        if id_ in seen:
            errors.append(f"line {number}: {id_} is answered twice")
            continue
        seen[id_] = {"id": id_, "status": status, "evidence": evidence, "note": note, "line": line}
        if status not in STATUSES:
            errors.append(f"line {number}: {id_}: status {status!r} is not one of {', '.join(STATUSES)}")
            continue
        if evidence in ("", "-"):
            if status in ("met", "differs") and id_[0] in NEEDS_EVIDENCE:
                errors.append(f"line {number}: {id_}: {status} needs evidence")
        else:
            problem = _resolves(evidence)
            if problem:
                errors.append(f"line {number}: {id_}: evidence {problem}")
        if status != "met" and not note:
            errors.append(f"line {number}: {id_}: {status} needs a note")
    for id_ in ids:
        if id_ not in seen:
            errors.append(f"{id_}: no answer")
    return errors, [seen[i] for i in ids if i in seen]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("items", "verify"):
        p = sub.add_parser(name)
        p.add_argument("body", help="file holding the issue body, or - for stdin")
        if name == "verify":
            p.add_argument("answers", help="file holding the reader's answers")
        p.add_argument("--base", help="the branch the change merges into")
        p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        body = sys.stdin.read() if args.body == "-" else Path(args.body).read_text(encoding="utf-8")
        answers = Path(args.answers).read_text(encoding="utf-8") if args.command == "verify" else ""
        changed = changed_files(args.base) if args.base else None
        # An Edit file exists before the change: with a base, the tree at the fork
        # counts too, so a file the change deletes or renames is still found.
        listed = list_items(body, changed, (lambda: _tree() + _tree_at(_fork(args.base))) if args.base else _tree)
    except (OSError, UnicodeDecodeError, GitError) as exc:
        print(exc, file=sys.stderr)
        return 2
    if listed is None:
        print("no spec in this body")
        return 1

    if args.command == "items":
        if args.json:
            print(json.dumps(listed, indent=2))
            return 0
        for item in listed["items"]:
            print(f"{item['id']}\t{item['text']}" + (f"\t{item['status']}" if "status" in item else ""))
        for title in listed["unlisted"]:
            print(f"unlisted: {title}")
        for name in listed["outside"]:
            print(f"outside: {name}")
        return 0

    errors, answered = check_answers(listed, answers)
    if errors:
        for line in errors:
            print(f"error: {line}", file=sys.stderr)
        return 2
    files = [i for i in listed["items"] if i["id"].startswith("F:")]
    statuses = [a["status"] for a in answered] + [f.get("status", "na") for f in files]
    counts = {s: statuses.count(s) for s in STATUSES}
    summary = (f"spec-check: items={len(statuses)} met={counts['met']} missing={counts['missing']} "
               f"differs={counts['differs']} na={counts['na']} outside={len(listed['outside'])}")
    unmet = [a["line"] for a in answered if a["status"] != "met"]
    unmet += [f"{f['id']}\t{f.get('status', 'na')}" for f in files if f.get("status") != "met"]
    if args.json:
        print(json.dumps({"unmet": unmet, "outside": listed["outside"], "counts": counts,
                          "items": len(statuses), "summary": summary}, indent=2))
    else:
        for line in unmet:
            print(line)
        for name in listed["outside"]:
            print(f"outside: {name}")
        print(summary)
    return 1 if counts["missing"] or counts["differs"] or listed["outside"] else 0


if __name__ == "__main__":
    sys.exit(main())
