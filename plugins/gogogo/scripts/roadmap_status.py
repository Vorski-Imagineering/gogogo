#!/usr/bin/env python3
"""Compare a roadmap document's state marks with the tracker, and fix them.

    roadmap_status.py [--profile FILE] [--file PATH] [--write] [--open-pattern REGEX]

A roadmap document holds tables of work, one row per unit. Each row's `State`
cell starts with a mark (an emoji, then a bold state word or a bare `—`) that
says where the row's issue sits. This re-derives every mark from two facts the
tracker owns: the issue's open/closed state (with its reason, labels and body)
and its card's column on the profile's board, read through the plugin's own
`tracker.py`. A by-hand refresh guesses state from prose or from a merge, and
neither closes an issue or moves a card.

The document says what each mark means. Its legend is the one table whose
header starts `| Mark | State |`; its `Covers` column names, for each mark, the
board columns or keywords it stands for. This script holds no mark of its own.

    | Keyword       | Covers                                                  |
    | closed        | issue closed as completed (or closed with no reason)    |
    | not planned   | issue closed as not planned, or as a duplicate          |
    | ready label   | open, carrying the label tracker.ready_marker           |
    | spec          | open, its body has a Design heading                     |
    | by hand       | never derived; a person sets it (for example "blocked") |
    | none          | open, nothing above applies                             |

A row's issue is the first link to an issue in `tracker.issues_repo` in its
`Issue` cell, or in its `State` cell when the table has no `Issue` column.
`--write` replaces only the mark prefix of each mismatched `State` cell; every
other character of the file is kept, line endings included.

Exit codes: 0 every mark agrees (after --write: every mismatch was written and
nothing needs a hand fix), 1 a mismatch (without --write) or a row to fix by
hand, 2 the profile, the legend or a read cannot be used.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402
import tracker  # noqa: E402

EXIT_OK, EXIT_ATTENTION, EXIT_UNUSABLE = 0, 1, 2

CLOSED, NOT_PLANNED, READY, SPEC, BY_HAND, NONE = (
    "closed", "not planned", "ready label", "spec", "by hand", "none")
KEYWORDS = (CLOSED, NOT_PLANNED, READY, SPEC, BY_HAND, NONE)
#: States a person may still see before any card is in a working column.
PRE_COLUMN = (READY, SPEC, NONE)
NOT_PLANNED_REASONS = ("NOT_PLANNED", "DUPLICATE")

SEPARATOR = re.compile(r"^\|[-\s|:]+\|\s*$")
# `\|` inside a cell is a literal pipe, not a column break.
PIPE = re.compile(r"(?<!\\)\|")
CELL_PREFIX = re.compile(r"^(?P<mark>\S+)\s+(?:\*\*(?P<bold>[^*]+)\*\*|(?P<dash>—))")
LEGEND_STATE = re.compile(r"^\*\*(?P<words>[^*]+)\*\*$")
# What /gogogo:spec always writes: a `## Design` heading.
SPEC_PATTERN = re.compile(r"^#{1,6}\s*Design\b", re.MULTILINE)
DEFAULT_OPEN_PATTERN = "still open|not yet closed"
BARE = "—"


class Unusable(Exception):
    """The profile, the legend or the document cannot be used; carries the lines to print."""

    def __init__(self, *lines: str):
        super().__init__(lines[0] if lines else "")
        self.lines = list(lines)


class ReadError(Exception):
    """One issue could not be read; the message starts `<repo>#<n>: `."""


def strip_vs(text: str) -> str:
    """A mark may be typed with or without U+FE0F; compare without it."""
    return text.replace("️", "")


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------


@dataclass
class Cell:
    text: str   # stripped
    start: int  # span of the raw cell (between its two pipes) in the line
    end: int


def split_cells(line: str) -> list[Cell]:
    """The cells between the line's pipes, each with its span in the line."""
    pipes = [m.start() for m in PIPE.finditer(line)]
    return [Cell(line[a + 1:b].strip(), a + 1, b) for a, b in zip(pipes, pipes[1:])]


@dataclass
class Table:
    header: list[str]
    rows: list[tuple[int, list[Cell]]]  # (line index, cells)

    def cell(self, cells: list[Cell], name: str) -> Cell | None:
        if name not in self.header:
            return None
        i = self.header.index(name)
        return cells[i] if i < len(cells) else None


def content(line: str) -> str:
    return line.rstrip("\r\n")


def find_tables(lines: list[str]) -> list[Table]:
    found, i = [], 0
    while i < len(lines) - 1:
        if lines[i].startswith("|") and SEPARATOR.match(content(lines[i + 1])):
            header = [c.text for c in split_cells(content(lines[i]))]
            rows, j = [], i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append((j, split_cells(content(lines[j]))))
                j += 1
            found.append(Table(header, rows))
            i = j
        else:
            i += 1
    return found


def is_legend(table: Table) -> bool:
    return table.header[:2] == ["Mark", "State"]


# --------------------------------------------------------------------------
# the legend: the document's own definition of every mark
# --------------------------------------------------------------------------


@dataclass
class Mark:
    mark: str        # as written in the legend
    state: str       # the words, or "—"
    state_cell: str  # as written in the legend: "**words**" or "—"
    covers: list[str] = field(default_factory=list)  # lower-cased

    @property
    def key(self) -> tuple[str, str]:
        return strip_vs(self.mark), self.state

    @property
    def bare(self) -> bool:
        return self.state_cell == BARE

    @property
    def shown(self) -> str:
        return f"{strip_vs(self.mark)} {self.state}"


@dataclass
class Legend:
    marks: list[Mark]
    by_entry: dict[str, Mark]  # keyword or lower-cased column -> its mark

    def get(self, entry: str) -> Mark | None:
        return self.by_entry.get(entry)


def profile_columns() -> dict[str, str]:
    """Every column the profile names, lower-cased -> as named (after configure())."""
    return {c.name.lower(): c.name for c in tracker.COLUMNS.values()}


def read_legend(tables: list[Table], settings: dict) -> Legend:
    """The legend, or Unusable naming every problem found in it."""
    legends = [t for t in tables if is_legend(t)]
    if not legends:
        raise Unusable("legend: no | Mark | State | Means | Covers | table")
    if len(legends) > 1:
        raise Unusable(f"legend: {len(legends)} tables start | Mark | State |; keep one")
    table = legends[0]
    if "Covers" not in table.header:
        raise Unusable("legend: no Covers column; add one naming the board columns or states each mark covers")

    columns = profile_columns()
    problems: list[str] = []
    marks: list[Mark] = []
    by_entry: dict[str, Mark] = {}
    seen: dict[str, Mark] = {}
    for _, cells in table.rows:
        mark = cells[0].text if cells else ""
        state_text = cells[1].text if len(cells) > 1 else ""
        covers_cell = table.cell(cells, "Covers")
        name = mark or "(empty)"
        if not mark or re.search(r"\s", mark):
            problems.append(f"legend: '{mark}': Mark must be one token")
            continue
        bold = LEGEND_STATE.match(state_text)
        if bold:
            entry = Mark(mark, bold["words"], state_text)
        elif state_text == BARE:
            entry = Mark(mark, BARE, BARE)
        else:
            problems.append(f"legend: {name}: State must be **<words>** or —")
            continue
        if strip_vs(mark) in seen:
            problems.append(f"legend: {name}: the mark is used twice")
            continue
        seen[strip_vs(mark)] = entry
        marks.append(entry)

        written = [c.strip() for c in (covers_cell.text if covers_cell else "").split(",")]
        written = [c for c in written if c]
        if not written:
            problems.append(f"legend: {name}: Covers is empty")
            continue
        if BY_HAND in (c.lower() for c in written) and len(written) > 1:
            problems.append(f"legend: {name}: '{BY_HAND}' must be the only entry in its Covers cell")
        for shown in written:
            item = shown.lower()
            if item not in KEYWORDS and item not in columns:
                problems.append(f"legend: {name}: '{shown}' is neither a keyword nor a column in the profile")
                continue
            if item in by_entry and by_entry[item] is not entry:
                problems.append(f"legend: '{shown}' is covered by both {by_entry[item].mark} and {name}")
                continue
            by_entry[item] = entry
            entry.covers.append(item)

    tracker_settings = settings.get("tracker") or {}
    required = [CLOSED, NOT_PLANNED, NONE]
    in_progress = (tracker_settings.get("columns") or {}).get("in_progress")
    if in_progress:
        required.append(in_progress)
    for stage in settings.get("stages") or []:
        if isinstance(stage, dict) and stage.get("column"):
            required.append(stage["column"])
    for item in required:
        if item.lower() not in by_entry:
            problems.append(f"legend: nothing covers '{item}'")

    if READY in by_entry and not tracker_settings.get("ready_marker"):
        problems.append("tracker.ready_marker: the legend uses 'ready label' but the profile names no ready label")

    if problems:
        raise Unusable(*problems)
    return Legend(marks, by_entry)


# --------------------------------------------------------------------------
# reading one issue
# --------------------------------------------------------------------------


def first_line(text: str) -> str:
    return (text.strip().splitlines() or ["(no message)"])[0]


def read_issue(number: int, repo: str) -> dict:
    """State, reason, labels, body and board column of one issue."""
    try:
        proc = subprocess.run(
            ["gh", "issue", "view", str(number), "-R", repo, "--json", "state,stateReason,labels,body"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise ReadError(f"{repo}#{number}: {first_line(proc.stderr or proc.stdout)}")
        info = json.loads(proc.stdout)
        card = tracker.issue_card(number, repo)["card"]
    except (FileNotFoundError, tracker.BoardError) as exc:
        raise ReadError(f"{repo}#{number}: {first_line(str(exc))}") from None
    return {
        "state": info["state"],
        "state_reason": info.get("stateReason") or None,
        "labels": [label["name"] for label in info.get("labels") or []],
        "body": info.get("body") or "",
        "column": ((card or {}).get("fieldValueByName") or {}).get("name"),
    }


# --------------------------------------------------------------------------
# deriving and checking
# --------------------------------------------------------------------------


def derive(info: dict, legend: Legend, ready_marker: str | None) -> Mark:
    """The mark the tracker says this issue has; first match wins."""
    # Closed is decided before any column: a closed card often still sits in a
    # working column, or in a done column the profile does not name.
    if info["state"] == "CLOSED":
        if info.get("state_reason") in NOT_PLANNED_REASONS:
            return legend.get(NOT_PLANNED)
        return legend.get(CLOSED)
    column = (info.get("column") or "").lower()
    if column and legend.get(column) and column not in KEYWORDS:
        return legend.get(column)
    labels = {label.lower() for label in info.get("labels") or []}
    if legend.get(READY) and ready_marker and ready_marker.lower() in labels:
        return legend.get(READY)
    if legend.get(SPEC) and SPEC_PATTERN.search(info.get("body") or ""):
        return legend.get(SPEC)
    return legend.get(NONE)


def agrees(current: Mark, derived: Mark, legend: Legend) -> bool:
    if current is derived:
        return True
    # A by-hand mark (say "blocked") survives every pre-column state.
    pre_column = [legend.get(k) for k in PRE_COLUMN if legend.get(k)]
    if current is legend.get(BY_HAND) and derived in pre_column:
        return True
    # A spec may live in a file rather than the issue body.
    return current is legend.get(SPEC) and derived is legend.get(NONE)


def issue_pattern(repo: str) -> re.Pattern:
    owner, name = repo.split("/", 1)
    return re.compile(
        rf"https://github\.com/{re.escape(owner)}/{re.escape(name)}/issues/(\d+)", re.IGNORECASE)


def row_issue(table: Table, cells: list[Cell], link: re.Pattern) -> int | None:
    """The first link in the Issue cell; in a table without one, in the State cell."""
    cell = table.cell(cells, "Issue") if "Issue" in table.header else table.cell(cells, "State")
    found = link.search(cell.text) if cell else None
    return int(found.group(1)) if found else None


def new_line(line: str, cell: Cell, prefix: re.Match, old: Mark, new: Mark) -> str:
    """`line` with only the old mark prefix of its State cell replaced."""
    lead = len(line[cell.start:cell.end]) - len(line[cell.start:cell.end].lstrip())
    start, end = cell.start + lead + prefix.start(), cell.start + lead + prefix.end()
    replacement = f"{new.mark} {new.state_cell}"
    rest = line[end:cell.end]
    # In the bare form the dash also separates the note: keep exactly one.
    if old.bare and not new.bare and rest.strip() and not rest.startswith(" —"):
        replacement += " —"
    elif new.bare and rest.startswith(" — "):
        end += len(" —")
    return line[:start] + replacement + line[end:]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def load_profile(args) -> tuple[Path, dict, Path]:
    """(profile path, settings, roadmap path), or Unusable in the order the checks run."""
    path = Path(args.profile) if args.profile else profile_check.find_profile()
    if not path.is_file():
        raise Unusable(f"profile: no file at {path}")
    try:
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise Unusable(f"profile: cannot read {path} ({exc})") from None
    except profile_check.ProfileError as exc:
        raise Unusable(str(exc)) from None
    tracker_settings = settings.get("tracker") or {}
    if tracker_settings.get("kind") != "github-project":
        raise Unusable("tracker.kind: roadmap_status.py reads board columns; it needs a github-project tracker")
    if tracker_settings.get("tool") != "shared":
        raise Unusable("tracker.tool: roadmap_status.py reads columns through the plugin's tracker.py; "
                       'it needs tracker.tool = "shared"')
    if args.file:
        roadmap = Path(args.file)
    else:
        name = (settings.get("roadmap") or {}).get("file")
        if not name:
            raise Unusable(f"roadmap.file: not set in {path}; this repo has no roadmap document")
        roadmap = path.parent.parent / name
    if not roadmap.is_file():
        raise Unusable(f"roadmap.file: no file at {roadmap}")
    try:
        tracker.configure(str(path))
    except tracker.ProfileMissing as exc:
        raise Unusable(str(exc)) from None
    return path, settings, roadmap


def run(args, reader) -> int:
    _, settings, roadmap = load_profile(args)
    repo = settings["tracker"]["issues_repo"]
    ready_marker = settings["tracker"].get("ready_marker")
    open_pattern = re.compile(args.open_pattern, re.IGNORECASE)

    with open(roadmap, encoding="utf-8", newline="") as handle:
        lines = handle.read().splitlines(keepends=True)
    tables = find_tables(lines)
    try:
        legend = read_legend(tables, settings)
    except Unusable as exc:
        raise Unusable("The legend cannot be used. Fix it first:", *(f"  {line}" for line in exc.lines)) from None
    known = {m.key: m for m in legend.marks}

    link = issue_pattern(repo)
    tracked = []  # (line index, table, cells, issue)
    for table in tables:
        if is_legend(table) or "State" not in table.header:
            continue
        for index, cells in table.rows:
            tracked.append((index, table, cells, row_issue(table, cells, link)))
    numbers = sorted({issue for *_, issue in tracked if issue})
    if not numbers:
        raise Unusable(f"no row names an issue in {repo}; nothing was checked")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {n: pool.submit(reader, n, repo) for n in numbers}
    infos, failures = {}, []
    for number, future in futures.items():
        try:
            infos[number] = future.result()
        except ReadError as exc:
            failures.append(f"could not read {exc}")
    if failures:
        raise Unusable(*failures)

    attention, changed = 0, False
    for index, table, cells, issue in tracked:
        state = table.cell(cells, "State")
        label = re.sub(r"\s+", " ", cells[0].text if cells else "")[:60]
        where = f"line {index + 1:>3}  {label}"
        text = state.text if state else ""
        prefix = CELL_PREFIX.match(text)
        current = known.get((strip_vs(prefix["mark"]), prefix["bold"] or prefix["dash"])) if prefix else None
        if current is None:
            print(f"FIX BY HAND  {where}: State cell does not start with a known mark: {text[:60]!r}")
            attention += 1
            continue
        if issue is None:
            continue  # set by hand; nothing on the tracker to check it against

        info = infos[issue]
        wanted = derive(info, legend, ready_marker)
        facts = f"#{issue} {info['state'].lower()}, column {info.get('column') or '—'}"
        if current is legend.get(BY_HAND) and " — " not in text:
            print(f"FIX BY HAND  {where}: {current.state}, but the note does not say on what")
            attention += 1
        # Checked whether or not the mark agrees: a correct closed mark beside
        # "still open" is exactly the stale prose a refresh exists to catch.
        if wanted in (legend.get(CLOSED), legend.get(NOT_PLANNED)) and open_pattern.search(lines[index]):
            print(f"FIX BY HAND  {where}: issue is closed, but the row still says it is open")
            attention += 1
        if agrees(current, wanted, legend):
            continue

        if args.write:
            lines[index] = new_line(lines[index], state, prefix, current, wanted)
            changed = True
            print(f"WROTE        {where}: {current.shown} -> {wanted.shown}  ({facts})")
        else:
            print(f"MISMATCH     {where}: says {current.shown}, GitHub says {wanted.shown}  ({facts})")
            attention += 1

    if changed:
        with open(roadmap, "w", encoding="utf-8", newline="") as handle:
            handle.write("".join(lines))
    unchecked = sum(1 for *_, issue in tracked if issue is None)
    print(f"\n{len(tracked)} rows, {len(numbers)} issues read, {unchecked} rows name no issue, "
          f"{attention} need attention")
    return EXIT_ATTENTION if attention else EXIT_OK


def main(argv=None, reader=read_issue) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md above this folder)")
    parser.add_argument("--file", help="the roadmap to read (default: roadmap.file, from the folder holding .agents/)")
    parser.add_argument("--write", action="store_true", help="rewrite mismatched marks in place")
    parser.add_argument("--open-pattern", default=DEFAULT_OPEN_PATTERN,
                        help=f"regex, case-insensitive, that says a row is still open (default: {DEFAULT_OPEN_PATTERN!r})")
    args = parser.parse_args(argv)
    try:
        return run(args, reader)
    except Unusable as exc:
        for line in exc.lines:
            print(line, file=sys.stderr)
        return EXIT_UNUSABLE
    except Exception:
        # A crash must read as untrusted (2), never as an answer.
        traceback.print_exc()
        return EXIT_UNUSABLE


if __name__ == "__main__":
    sys.exit(main())
