#!/usr/bin/env python3
"""Plan, and apply only what a person approved, the GitHub milestones a roadmap's sections stand for.

    roadmap_milestones.py [--profile FILE] [--file PATH] plan [--link HEADING]...
    roadmap_milestones.py [--profile FILE] [--file PATH] apply --plan PLAN.json --items 1,3,4 [--choose ID=CHOICE]...

A section of the roadmap (a `##` heading and the lines up to the next one) is a
milestone when its heading links to one:

    ## [Now: the learning loop](https://github.com/<tracker.issues_repo>/milestone/<number>)

Which sections are milestones, a milestone's title, and closing one go from the
document to GitHub only. Which milestone an issue is in goes both ways: the
side that changed last wins, and nothing changes until a person approves it.
GitHub's side is the issue's last milestone change in its timeline; the
document's side is when its row reached its section, read from the base
branch's first-parent history. Nothing else is stored.

An issue's home row is its first row, in document order, among linked
sections; its other rows are references and set nothing. An issue whose rows
are all in unlinked sections is left alone both ways. A row's issue is read as
`roadmap_status.py` reads it, in tables it tracks.

`plan` reads the document as committed at `HEAD` of its own git repo, never an
unmerged edit, and prints a JSON plan:

    {"repo", "doc", "items": [...], "skipped": [{"line", "why"}], "kept": [{"issue", "why"}], "unlinked": [...]}

Each item has `id`, `kind`, `side` (github, doc or both), `issue`, `section`,
`milestone` ({"number", "title"}, number null when not yet created), `from`,
`expect` (the state it saw) and `why`. Kinds: `link-section`,
`rename-milestone`, `close-milestone`, `set-milestone`, `clear-milestone`,
`move-row`, `add-row` and `question`, whose `choices` are `{"label", "item"}`
with `item` another kind, `remove-row` (a choice only: delete that row), or
null for "leave both". While no heading is linked, every section with a
tracked table is offered as a new milestone; after that, `--link HEADING`
offers one by name. Exit 0: nothing to do. 1: items or skipped lines. 2: the
profile, the document or a read cannot be used; nothing is printed on stdout.
With `tracker.public`, a document in another repo that is not public is
refused: milestone titles would publish its headings.

`apply` applies only the ids in `--items`, a question only with
`--choose ID=<1-based choice>`. Before each GitHub write it re-reads what the
item expected and skips it (`SKIPPED stale`) when someone changed it. It
writes by milestone number, and it never deletes a milestone. Document edits
are made in the working file, keeping every other byte. One line per item:
`APPLIED`, `SKIPPED stale` or `FAILED`. Exit 0: every item applied. 1: any
skipped or failed. 2: the plan, an id or a choice cannot be used.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_status as rs  # noqa: E402
import tracker  # noqa: E402

EXIT_OK, EXIT_ATTENTION, EXIT_UNUSABLE = 0, 1, 2

HEADING = re.compile(r"^##(?!#)\s*(?P<text>.*?)\s*$")
LINKED = re.compile(
    r"^\[(?P<text>[^\]]+)\]\((?P<url>https://github\.com/(?P<repo>[^/\s]+/[^/\s]+)/milestone/(?P<number>\d+))\)$",
    re.IGNORECASE)
GITHUB_REMOTE = re.compile(r"github\.com[:/](?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?/?$", re.IGNORECASE)
GITHUB_ORDER = ("link-section", "rename-milestone", "set-milestone", "clear-milestone", "close-milestone")
DOC_KINDS = ("move-row", "add-row", "remove-row")


class Unusable(Exception):
    """The plan cannot be made or applied; the message is printed on stderr."""


class ReadError(Exception):
    """A read from GitHub or git failed."""


# --------------------------------------------------------------------------
# the document
# --------------------------------------------------------------------------


def tables_at(lines: list[str]) -> list[tuple[int, rs.Table]]:
    """Each tracked table (outside fences, with a State column, not the legend) and its header's index.

    As `roadmap_status.find_tables` reads tables, with where each starts, so a table with no rows yet
    still belongs to its section."""
    skip = rs.fenced(lines)
    found, i = [], 0
    while i < len(lines) - 1:
        if i not in skip and lines[i].startswith("|") and rs.SEPARATOR.match(rs.content(lines[i + 1])):
            header = [c.text for c in rs.split_cells(rs.content(lines[i]))]
            rows, j = [], i + 2
            while j < len(lines) and j not in skip and lines[j].startswith("|"):
                rows.append((j, rs.split_cells(rs.content(lines[j]))))
                j += 1
            table = rs.Table(header, rows)
            if not rs.is_legend(table) and "State" in header:
                found.append((i, table))
            i = j
        else:
            i += 1
    return found


@dataclass
class Section:
    heading: str            # the heading's text, without a link
    line: int               # index of the heading line
    end: int                # index after the section's last line
    number: int | None      # the milestone it links in tracker.issues_repo
    tables: list = field(default_factory=list)   # tracked tables (roadmap_status.Table)
    rows: list = field(default_factory=list)     # (line index, table, issue)


@dataclass
class Doc:
    lines: list[str]
    sections: list[Section]
    skipped: list[dict]

    def linked(self) -> list[Section]:
        return [s for s in self.sections if s.number is not None]

    def by_number(self, number: int | None) -> Section | None:
        return next((s for s in self.sections if number is not None and s.number == number), None)

    def by_heading(self, text: str) -> Section | None:
        return next((s for s in self.sections if s.heading == text), None)


def parse_doc(text: str, repo: str) -> Doc:
    """Sections, their links and their tracked rows."""
    lines = text.splitlines(keepends=True)
    fence = rs.fenced(lines)
    starts = [i for i, line in enumerate(lines) if i not in fence and HEADING.match(rs.content(line))]
    sections, skipped = [], []
    for k, start in enumerate(starts):
        title = HEADING.match(rs.content(lines[start]))["text"]
        link, number = LINKED.match(title), None
        if link:
            title = link["text"].strip()
            if link["repo"].lower() == repo.lower():
                number = int(link["number"])
            else:
                skipped.append({"line": start + 1, "why": f"the heading links a milestone in {link['repo']}, "
                                                          "not this tracker; its section is not synced"})
        sections.append(Section(title, start, starts[k + 1] if k + 1 < len(starts) else len(lines), number))
    pattern = rs.issue_pattern(repo)
    for first, table in tables_at(lines):
        section = next((s for s in sections if s.line < first < s.end), None)
        if section is None:
            continue
        section.tables.append(table)
        for index, cells in table.rows:
            section.rows.append((index, table, rs.row_issue(table, cells, pattern)))
    return Doc(lines, sections, skipped)


def homes(doc: Doc, among: list[Section]) -> dict[int, Section]:
    """Each issue's first row, in document order, among `among`."""
    found: dict[int, Section] = {}
    for section in sorted(among, key=lambda s: s.line):
        for _, _, issue in section.rows:
            if issue and issue not in found:
                found[issue] = section
    return found


def row_line(section: Section, issue: int) -> tuple[int, object] | None:
    """The line index and table of the section's first row for `issue`."""
    return next(((i, t) for i, t, n in section.rows if n == issue), None)


# --------------------------------------------------------------------------
# readers and the writer (injectable)
# --------------------------------------------------------------------------


def _gh(*args: str) -> str:
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True)
    except OSError as exc:
        raise ReadError(f"gh: {exc}") from None
    if done.returncode != 0:
        raise ReadError(rs.first_line(done.stderr or done.stdout))
    return done.stdout


ISSUE_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number state title
      milestone { number title }
      timelineItems(itemTypes: [MILESTONED_EVENT, DEMILESTONED_EVENT], last: 1) {
        nodes { ... on MilestonedEvent { createdAt } ... on DemilestonedEvent { createdAt } }
      }
    }
  }
}
"""


class GitHub:
    """Reads milestones and issues from GitHub."""

    def milestones(self, repo: str) -> list[dict]:
        out = _gh("api", "--paginate", f"repos/{repo}/milestones?state=all&per_page=100",
                  "--jq", ".[] | {number, title, state}")
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def milestone_issues(self, repo: str, number: int) -> list[int]:
        out = _gh("api", "--paginate", f"repos/{repo}/issues?milestone={number}&state=all&per_page=100",
                  "--jq", ".[] | select(.pull_request == null) | .number")
        return [int(line) for line in out.split()]

    def issue(self, repo: str, number: int) -> dict:
        owner, name = repo.split("/", 1)
        try:
            found = tracker.graphql(ISSUE_QUERY, owner=owner, name=name, number=number)["repository"]["issue"]
        except (tracker.BoardError, KeyError, TypeError) as exc:
            raise ReadError(f"#{number}: {rs.first_line(str(exc))}") from None
        if not found:
            raise ReadError(f"#{number}: no such issue in {repo}")
        events = found["timelineItems"]["nodes"]
        return {"number": found["number"], "state": found["state"], "title": found["title"],
                "milestone": (found.get("milestone") or {}).get("number"),
                "last_event": (events[-1] or {}).get("createdAt") if events else None}

    def visibility(self, repo: str) -> str:
        return _gh("repo", "view", repo, "--json", "visibility", "-q", ".visibility").strip()


class Git:
    """The document's own git repo: the committed text at HEAD and its first-parent history."""

    def __init__(self, path: Path):
        self.dir = path.resolve().parent
        self.root = Path(self._git("rev-parse", "--show-toplevel").strip())
        self.rel = path.resolve().relative_to(self.root.resolve()).as_posix()

    def _git(self, *args: str) -> str:
        done = subprocess.run(["git", "-C", str(self.dir), *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise ReadError(f"git {args[0]}: {rs.first_line(done.stderr or done.stdout)}")
        return done.stdout

    def text_at(self, rev: str) -> str:
        done = subprocess.run(["git", "-C", str(self.root), "show", f"{rev}:{self.rel}"],
                              capture_output=True)
        if done.returncode != 0:
            raise ReadError(f"git show {rev}:{self.rel}: {rs.first_line(done.stderr.decode(errors='replace'))}")
        return done.stdout.decode("utf-8")

    def versions(self) -> list[tuple[str, str]]:
        """(sha, committer time), newest first, of each first-parent commit that touched the document."""
        out = self._git("log", "--first-parent", "--format=%H%x09%cI", "HEAD", "--", self.rel)
        return [tuple(line.split("\t", 1)) for line in out.splitlines() if line.strip()]

    def remote_repo(self) -> str | None:
        try:
            url = self._git("remote", "get-url", "origin").strip()
        except ReadError:
            return None
        found = GITHUB_REMOTE.search(url)
        return found["repo"] if found else None


class GhWriter:
    """Writes to GitHub by milestone number. It has no call that deletes a milestone."""

    def create_milestone(self, repo: str, title: str) -> int:
        return int(_gh("api", "-X", "POST", f"repos/{repo}/milestones", "-f", f"title={title}", "--jq", ".number"))

    def update_milestone(self, repo: str, number: int, **fields: str) -> None:
        args = [arg for key, value in fields.items() for arg in ("-f", f"{key}={value}")]
        _gh("api", "-X", "PATCH", f"repos/{repo}/milestones/{number}", *args, "--jq", ".number")

    def set_issue_milestone(self, repo: str, issue: int, number: int | None) -> None:
        value = "null" if number is None else str(number)
        _gh("api", "-X", "PATCH", f"repos/{repo}/issues/{issue}", "-F", f"milestone={value}", "--jq", ".number")


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------


def when(stamp: str | None) -> datetime | None:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None


def short(stamp: str | None) -> str:
    """A time as `YYYY-MM-DDTHH:MMZ`, in UTC."""
    moment = when(stamp)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if moment else "never"


class History:
    """Each version of the document, newest first, and each issue's home milestone in it."""

    def __init__(self, git, repo: str):
        self.versions = []  # (sha, time, {issue: milestone number}, linked numbers)
        for sha, time in git.versions():
            doc = parse_doc(git.text_at(sha), repo)
            home = {n: s.number for n, s in homes(doc, doc.linked()).items()}
            self.versions.append((sha, time, home, {s.number for s in doc.linked()}))
        if not self.versions:
            raise Unusable(f"the roadmap has no commit at HEAD of its repo ({git.rel}); commit it first")

    def placed(self, issue: int) -> tuple[str | None, str | None]:
        """(time, sha) when the issue's home milestone, or its absence, became what it is at HEAD.

        None when the issue was never in a linked section in any version."""
        now = self.versions[0][2].get(issue)
        if now is None and all(v[2].get(issue) is None for v in self.versions):
            return None, None
        since = self.versions[0]
        for version in self.versions:
            if version[2].get(issue) != now:
                break
            since = version
        return since[1], since[0]

    def ever_linked(self) -> set[int]:
        return set().union(*(v[3] for v in self.versions))


def item(kind: str, side: str, *, issue=None, section=None, milestone=None, frm=None, expect=None,
         why: str = "", **extra) -> dict:
    return {"kind": kind, "side": side, "issue": issue, "section": section, "milestone": milestone,
            "from": frm, "expect": expect, "why": why, **extra}


def ms(number: int | None, titles: dict[int, str], title: str | None = None) -> dict | None:
    if number is None and title is None:
        return None
    return {"number": number, "title": title if title is not None else titles.get(number)}


def plan(doc: Doc, path: str, repo: str, github, history: History, link: list[str]) -> dict:
    milestones = github.milestones(repo)
    titles = {m["number"]: m["title"] for m in milestones}
    by_title = {m["title"]: m["number"] for m in milestones}
    states = {m["number"]: m["state"] for m in milestones}
    items, skipped, kept = [], list(doc.skipped), []

    # Sections offered as new milestones.
    new: list[Section] = []
    for heading in link:
        section = doc.by_heading(heading)
        if section is None:
            raise Unusable(f"--link {heading!r}: no ## heading with that text in the roadmap")
        if section.number is None:
            new.append(section)
    if not doc.linked() and not link:
        new = [s for s in doc.sections if s.number is None and s.tables]
    for section in new:
        items.append(item("link-section", "both", section=section.heading,
                          milestone=ms(by_title.get(section.heading), titles, section.heading),
                          why="no heading links a milestone yet" if not link
                          else "asked for by name with --link"))

    # Headings and milestones: the document's side only.
    linked = doc.linked()
    for section in linked:
        if section.number not in titles:
            skipped.append({"line": section.line + 1, "why": "the milestone this heading links no longer exists"})
        elif titles[section.number] != section.heading:
            items.append(item("rename-milestone", "github", section=section.heading,
                              milestone=ms(section.number, titles, section.heading),
                              frm=titles[section.number], expect=titles[section.number],
                              why=f"the heading reads {section.heading!r}; the milestone {titles[section.number]!r}"))
    for number in sorted(history.ever_linked() - {s.number for s in linked}):
        if states.get(number) == "open":
            items.append(item("close-milestone", "github", milestone=ms(number, titles), frm="open",
                              expect="open", why="an earlier version of the roadmap linked it; none does now"))

    # Issues: rows in new sections set their milestone by title.
    home = homes(doc, linked + new)
    newly = {n: s for n, s in home.items() if s in new}
    for number, section in newly.items():
        info = github.issue(repo, number)
        target = by_title.get(section.heading)
        if target is not None and info["milestone"] == target:
            continue
        items.append(item("set-milestone", "github", issue=number, section=section.heading,
                          milestone=ms(target, titles, section.heading),
                          frm=titles.get(info["milestone"]), expect=info["milestone"],
                          why=f"first row in {section.heading!r}, a new milestone"))

    # Issues in linked sections, and issues in linked milestones.
    home = {n: s for n, s in homes(doc, linked).items() if n not in newly}
    anywhere = {n for s in doc.sections for _, _, n in s.rows if n}
    numbers = set(home)
    for section in linked:
        if section.number in titles:
            numbers.update(n for n in github.milestone_issues(repo, section.number)
                           if n not in newly and (n in home or n not in anywhere))
    for number in sorted(numbers, key=lambda n: (home[n].line if n in home else 10 ** 9, n)):
        info = github.issue(repo, number)
        found = rule(number, info, home.get(number), doc, history, titles)
        for entry in found:
            (skipped if "line" in entry and "kind" not in entry else
             kept if "issue" in entry and "kind" not in entry else items).append(entry)

    for k, entry in enumerate(items, 1):
        entry["id"] = k
    return {"repo": repo, "doc": path, "items": [{"id": e.pop("id"), **e} for e in items],
            "skipped": skipped, "kept": kept,
            "unlinked": [s.heading for s in doc.sections if s.number is None]}


def rule(number: int, info: dict, home: Section | None, doc: Doc, history: History, titles: dict) -> list[dict]:
    """The items for one issue, by the rules in order (an empty list: nothing to do)."""
    milestone = info["milestone"]
    in_milestone = doc.by_number(milestone)
    if home is not None and in_milestone is home:
        return []                                                       # 1
    if home is None and in_milestone is None:
        return []                                                       # 8
    placed, sha = history.placed(number)
    gh_time, doc_time = when(info["last_event"]), when(placed)
    newer = gh_time is not None and (doc_time is None or gh_time > doc_time)
    why = (f"{'GitHub' if newer else 'the roadmap'} newer: milestone "
           f"{'changed ' + short(info['last_event']) if info['last_event'] else 'never set'}; "
           f"row placed {short(placed) if placed else 'never'}" + (f" ({sha[:7]})" if sha else ""))
    here = ms(home.number, titles) if home else None
    there = ms(milestone, titles) if milestone is not None else None
    set_back = item("set-milestone", "github", issue=number, section=home.heading if home else None,
                    milestone=here, frm=titles.get(milestone), expect=milestone, why=why) if home else None
    if home is not None and not newer:
        return [set_back]                                               # 2
    if home is not None:
        found = row_line(home, number)
        remove = item("remove-row", "doc", issue=number, section=home.heading,
                      frm=home.heading, expect=rs.content(doc.lines[found[0]]), why=why)
        leave = {"label": "leave both", "item": None}
        if in_milestone is not None:                                    # 3
            if row_line(in_milestone, number):
                return [item("question", "both", issue=number, section=home.heading, milestone=there,
                             frm=home.heading, expect=milestone, why=why + f"; {in_milestone.heading!r} "
                             "already has a row for it", choices=[
                                 {"label": f"remove the row in {home.heading!r}", "item": remove},
                                 {"label": f"set the milestone back to {home.heading!r}", "item": set_back},
                                 leave])]
            target = in_milestone.tables[0] if in_milestone.tables else None
            if target is None or target.header != found[1].header:
                return [{"line": found[0] + 1, "why": f"#{number}: the tables differ; move it by hand "
                                                       f"from {home.heading!r} to {in_milestone.heading!r}"}]
            return [item("move-row", "doc", issue=number, section=in_milestone.heading, milestone=there,
                         frm=home.heading, expect=rs.content(doc.lines[found[0]]), why=why)]
        if milestone is None:                                           # 4
            return [item("question", "both", issue=number, section=home.heading, milestone=None,
                         frm=home.heading, expect=None, why=why + "; its milestone was cleared", choices=[
                             {"label": f"remove the row in {home.heading!r}", "item": remove},
                             {"label": f"set the milestone back to {home.heading!r}", "item": set_back},
                             leave])]
        return [item("question", "both", issue=number, section=home.heading, milestone=there,  # 5
                     frm=home.heading, expect=milestone,
                     why=why + "; its milestone is not linked from any heading", choices=[
                         {"label": f"set the milestone back to {home.heading!r}", "item": set_back}, leave])]
    if newer:                                                           # 6
        return [item("add-row", "doc", issue=number, section=in_milestone.heading, milestone=there,
                     why=why)]
    if info["state"] == "CLOSED":                                       # 7
        return [{"issue": number, "why": "closed; its milestone is never cleared"}]
    return [item("clear-milestone", "github", issue=number, milestone=there, frm=titles.get(milestone),
                 expect=milestone, why=why)]


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------


def load_plan(path: str, ids: str, choose: list[str]) -> list[dict]:
    """The approved items in apply order, each question replaced by its chosen item."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in data["items"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Unusable(f"--plan {path}: cannot be read ({exc})") from None
    try:
        wanted = [int(part) for part in ids.split(",") if part.strip()]
        chosen = {int(k): int(v) for k, v in (c.split("=", 1) for c in choose)}
    except ValueError:
        raise Unusable("--items is a comma list of ids, --choose is ID=CHOICE") from None
    picked = []
    for number in wanted:
        if number not in by_id:
            raise Unusable(f"--items: id {number} is not in the plan")
        entry = by_id[number]
        if entry["kind"] == "question":
            choices = entry.get("choices") or []
            if number not in chosen or not 1 <= chosen[number] <= len(choices):
                raise Unusable(f"--items: id {number} is a question; give --choose {number}=<1..{len(choices)}>")
            choice = choices[chosen[number] - 1]["item"]
            picked.append(dict(choice, id=number) if choice else {"id": number, "kind": "leave"})
        else:
            picked.append(entry)
    order = {kind: k for k, kind in enumerate((*GITHUB_ORDER, *DOC_KINDS, "leave"))}
    return sorted(picked, key=lambda e: order.get(e["kind"], len(order)))


def apply(entries: list[dict], repo: str, roadmap: Path, github, writer, legend) -> int:
    with open(roadmap, encoding="utf-8", newline="") as handle:
        text = handle.read()
    lines = text.splitlines(keepends=True)
    created: dict[str, int] = {}
    worst = EXIT_OK
    for entry in entries:
        tag = f"{entry['id']} {entry['kind']}" + (f" #{entry['issue']}" if entry.get("issue") else "")
        try:
            outcome = apply_one(entry, repo, lines, github, writer, legend, created)
        except (ReadError, ValueError) as exc:
            print(f"FAILED {tag}: {exc}")
            worst = EXIT_ATTENTION
            continue
        if outcome.startswith("stale"):
            print(f"SKIPPED stale {tag}: {outcome[len('stale: '):]}")
            worst = EXIT_ATTENTION
        else:
            print(f"APPLIED {tag}{': ' + outcome if outcome else ''}")
    new = "".join(lines)
    if new != text:
        with open(roadmap, "w", encoding="utf-8", newline="") as handle:
            handle.write(new)
    return worst


def section_span(lines: list[str], heading: str) -> tuple[int, int] | None:
    """(heading index, end index) of the section whose heading text is `heading`, in the working file."""
    fence = rs.fenced(lines)
    starts = [i for i, line in enumerate(lines) if i not in fence and HEADING.match(rs.content(line))]
    for k, start in enumerate(starts):
        title = HEADING.match(rs.content(lines[start]))["text"]
        link = LINKED.match(title)
        if (link["text"].strip() if link else title) == heading:
            return start, starts[k + 1] if k + 1 < len(starts) else len(lines)
    return None


def ending(line: str) -> str:
    return line[len(rs.content(line)):] or "\n"


def first_table_end(lines: list[str], span: tuple[int, int]) -> tuple[int, rs.Table] | None:
    """The index after the last row of the section's first tracked table, and the table."""
    for first, table in tables_at(lines):
        if span[0] < first < span[1]:
            return (table.rows[-1][0] if table.rows else first + 1) + 1, table
    return None


def apply_one(entry, repo, lines, github, writer, legend, created) -> str:
    kind = entry["kind"]
    milestone = entry.get("milestone") or {}
    if kind == "leave":
        return "left both as they are"
    if kind == "link-section":
        span = section_span(lines, entry["section"])
        if span is None:
            return f"stale: no heading {entry['section']!r} in the roadmap"
        number = milestone.get("number")
        current = {m["title"]: m["number"] for m in github.milestones(repo)}
        number = current.get(entry["section"], number)
        if number is None:
            number = writer.create_milestone(repo, entry["section"])
        created[entry["section"]] = number
        line = lines[span[0]]
        lines[span[0]] = f"## [{entry['section']}](https://github.com/{repo}/milestone/{number}){ending(line)}"
        return f"milestone {number}"
    if kind == "rename-milestone":
        now = {m["number"]: m for m in github.milestones(repo)}.get(milestone["number"])
        if now is None or now["title"] != entry["expect"]:
            return f"stale: the milestone now reads {now['title'] if now else 'nothing (gone)'!r}"
        writer.update_milestone(repo, milestone["number"], title=milestone["title"])
        return f"{entry['expect']!r} -> {milestone['title']!r}"
    if kind == "close-milestone":
        now = {m["number"]: m for m in github.milestones(repo)}.get(milestone["number"])
        if now is None or now["state"] != entry["expect"]:
            return f"stale: the milestone is now {now['state'] if now else 'gone'}"
        writer.update_milestone(repo, milestone["number"], state="closed")
        return f"milestone {milestone['number']} closed"
    if kind in ("set-milestone", "clear-milestone"):
        now = github.issue(repo, entry["issue"])["milestone"]
        if now != entry["expect"]:
            return f"stale: #{entry['issue']} is now in milestone {now}"
        number = None
        if kind == "set-milestone":
            number = milestone.get("number") or created.get(milestone.get("title"))
            if number is None:
                number = {m["title"]: m["number"] for m in github.milestones(repo)}.get(milestone.get("title"))
            if number is None:
                return f"stale: no milestone titled {milestone.get('title')!r} (link its section first)"
        writer.set_issue_milestone(repo, entry["issue"], number)
        return f"milestone {number}" if number is not None else "milestone cleared"
    # Document kinds.
    if kind in ("move-row", "remove-row"):
        span = section_span(lines, entry["from"])
        index = next((i for i in range(*span) if rs.content(lines[i]) == entry["expect"]), None) if span else None
        if index is None:
            return f"stale: the row is no longer in {entry['from']!r}"
        if kind == "remove-row":
            del lines[index]
            return f"row removed from {entry['from']!r}"
        row = lines.pop(index)
        span = section_span(lines, entry["section"])
        found = first_table_end(lines, span) if span else None
        if found is None:
            lines.insert(index, row)
            return f"stale: {entry['section']!r} has no table"
        at, _ = found
        if not lines[at - 1].endswith(("\n", "\r")):
            lines[at - 1] += ending(row)
        lines.insert(at, row if row.endswith(("\n", "\r")) else row + ending(lines[at - 1]))
        return f"row moved to {entry['section']!r}"
    if kind == "add-row":
        span = section_span(lines, entry["section"])
        found = first_table_end(lines, span) if span else None
        if found is None:
            return f"stale: {entry['section']!r} has no table"
        at, table = found
        title = github.issue(repo, entry["issue"])["title"].replace("|", "\\|")
        none = legend.get(rs.NONE)
        cells, work = [], False
        for name in table.header:
            if name == "Issue":
                cells.append(f"[#{entry['issue']}](https://github.com/{repo}/issues/{entry['issue']})")
            elif name == "State":
                cells.append(f"{none.mark} {none.state_cell}")
            elif not work and name.lower() not in rs.NOTE_HEADERS:
                cells.append(title)
                work = True
            else:
                cells.append("")
        last = lines[at - 1]
        if not last.endswith(("\n", "\r")):
            lines[at - 1] += "\n"
        lines.insert(at, "|" + "|".join(f" {c} " if c else " " for c in cells) + "|" + ending(lines[at - 1]))
        return f"row added to {entry['section']!r}"
    raise ValueError(f"unknown kind {kind!r}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def run(args, github, history, writer) -> int:
    _, settings, roadmap = rs.load_profile(args)
    repo = settings["tracker"]["issues_repo"]
    if args.command == "apply":
        entries = load_plan(args.plan, args.items, args.choose or [])
        lines = roadmap.read_text(encoding="utf-8").splitlines(keepends=True)
        legend = rs.read_legend(rs.find_tables(lines), settings)
        return apply(entries, repo, roadmap, github, writer, legend)

    git = history(roadmap)
    if (settings.get("tracker") or {}).get("public"):
        source = git.remote_repo()
        if source is None or (source.lower() != repo.lower() and github.visibility(source) != "PUBLIC"):
            raise Unusable(f"milestone titles would publish headings from {source or 'the roadmap’s repo'}, "
                           f"which is not public, in {repo}")
    doc = parse_doc(git.text_at("HEAD"), repo)
    found = plan(doc, str(roadmap), repo, github, History(git, repo), args.link or [])
    print(json.dumps(found, indent=2, ensure_ascii=False))
    return EXIT_ATTENTION if found["items"] or found["skipped"] else EXIT_OK


def main(argv=None, github=None, history=Git, writer=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md above this folder)")
    parser.add_argument("--file", help="the roadmap (default: roadmap.file, from the folder holding .agents/)")
    sub = parser.add_subparsers(dest="command", required=True)
    planner = sub.add_parser("plan", help="print the milestone changes as JSON; writes nothing")
    planner.add_argument("--link", action="append", metavar="HEADING", help="offer this section as a milestone")
    applier = sub.add_parser("apply", help="apply the approved ids of a plan")
    applier.add_argument("--plan", required=True)
    applier.add_argument("--items", required=True, help="comma list of ids")
    applier.add_argument("--choose", action="append", metavar="ID=CHOICE", help="a question's 1-based choice")
    args = parser.parse_args(argv)
    try:
        return run(args, github or GitHub(), history, writer or GhWriter())
    except (Unusable, rs.Unusable, ReadError) as exc:
        for line in getattr(exc, "lines", None) or [str(exc)]:
            print(line, file=sys.stderr)
        return EXIT_UNUSABLE
    except Exception:
        # A crash must read as untrusted (2), never as an answer.
        traceback.print_exc()
        return EXIT_UNUSABLE


if __name__ == "__main__":
    sys.exit(main())
