#!/usr/bin/env python3
"""Read and move cards on a repo's GitHub project board, as its profile describes.

    tracker.py [--profile FILE] list [--status "<column>"] [--open-only] [--issues-only] [--json]
    tracker.py [--profile FILE] show <issue> [--expect "<column>"]
    tracker.py [--profile FILE] move <issue> [--from "<column>"] --to "<column>" [--add-missing]
    tracker.py [--profile FILE] block <issue> --by <#B | B | owner/repo#B>
    tracker.py [--profile FILE] fields [--check]
    tracker.py [--profile FILE] views [--hide-closed]
    tracker.py [--profile FILE] tidy [--apply]

The board (owner, project number), the issues repo and the columns the skills
move cards between all come from the profile (`.agents/dev-process.md`, the
nearest one above this folder): `tracker.project_owner`,
`tracker.project_number`, `tracker.issues_repo`, `tracker.queue`,
`tracker.columns` and the `column` of each of `stages`. It meets
`references/tracker-contract.md`.

Why this exists rather than raw `gh` in a skill: two of the board operations
fail *silently* when done by hand.

  * `gh project item-list` has no ordering and no status filter, and caps at
    `--limit`. A board past the limit reads exactly like a short column: the
    newest cards are simply not in the answer.
  * The Status field/option ids change when the board is edited, and a column
    can be renamed while keeping its id. A stored id makes `item-edit` fail, or
    worse, moves a card into a column that now means something else.

So: `list` pages to the end and refuses to print a result it cannot reconcile
against `totalCount`; every id is resolved live; `move` reads the card back and
exits non-zero if the board does not agree with what it just wrote. A move to
`tracker.columns.needs_human` is refused, with nothing written, unless the
issue's newest comment carries a stop marker (`gogogo:stop`, `gogogo:skip`, or
an `auto-test v1` FAIL or NEEDS_HUMAN verdict): the skills post why before they
hand an issue to a person.

That `totalCount` guard is necessary and not sufficient. It compares the pages
received against the count the *same* connection reported, so when GitHub's
project-side index drops an item it drops it from both and the check passes
over a missing card (a real card sat in a column, unarchived, while the read
said "369 of 369"). `list` therefore asks a second, independent index (each
open issue what it belongs to) and prints any card only that side can see.

`views` and `tidy` keep the board current between runs: every view hides closed
issues, every issue closed as completed sits in Done, every issue closed as not
planned is archived (off the board, restorable from its archive: Done means
work that was done), and every open issue is on the board.
GitHub's own board workflows do this going forward once they are on; these
commands fix what is already there.

`list --json` and `show` carry each issue's GitHub dependency links
("blocked by", "blocking"). In `list --json` each `blocked_by` entry has its
`column` on this board (or null) and its `blocker_state`: `open` while it
still blocks, `merged` once it is closed as completed or its card is in a
stage column, `dropped` when it closed as not planned or as a duplicate.
`block` sets one link and confirms it from the blocker's side; it never
removes one.

Exit codes: 0 ok, 1 usage/not-found, 2 the read or write could not be trusted,
3 `show --expect` or `move --from`: the card is in a different column,
4 `move`: a move to the needs-a-person column refused because the newest
comment says no reason. `block`: 0 linked and seen from the blocker's side
(also when it was already linked), 1 a bad `--by` or a blocker that does not
exist, 2 the write or its read-back could not be trusted.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import traceback
import time
from dataclasses import dataclass

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402

# Set from the profile by configure(); module-level so the queries read them
# the way board.py's constants were read.
ORG = ""
PROJECT_NUMBER = 0
DEFAULT_REPO = ""
PAGE_SIZE = 100
STATUS_FIELD = "Status"
#: How many times graphql() tries, and how long one `gh` call may take (None:
#: no limit). A caller that must finish fast (the session-start line) lowers both.
ATTEMPTS = 3
CALL_TIMEOUT: float | None = None


class BoardError(Exception):
    """Something came back that we are not willing to act on."""


# --------------------------------------------------------------------------
# column registry: the columns the skills move cards between, from the profile
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    name: str
    meaning: str


#: Filled by configure(): tracker.queue, tracker.columns and every stage's
#: column. Keys are the roles the skills use ("queue", "in_progress",
#: "needs_human", and each stage's column name); values carry the live name.
#: `fields --check` fails when the live board lacks one of these.
COLUMNS: dict[str, Column] = {}

#: Two of the standard columns `/gogogo:setup` gives every board. They mean the
#: same on every board, so they are not profile settings.
NEW_COLUMN = "⚡️ New"
DONE_COLUMN = "Done"

#: A view whose filter has one of these hides closed issues.
OPEN_FILTERS = ("is:open", "-is:closed")

#: The reasons a `gogogo:stop` marker may give; equal to review_stats.STOPS,
#: kept here so this tool does not import it.
STOP_REASONS = ("hard-stop", "decision", "spec", "review", "tests", "mutation", "verify", "gate", "ci", "merge",
                "reverted")

#: The markers that say why an issue was handed to a person.
REASON_MARKER = re.compile(r"<!-- (gogogo:stop|gogogo:skip|auto-test v1) (.*?) -->")

NEWEST_COMMENT_QUERY = """
query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){issue(number:$number){comments(last:1){nodes{body}}}}}
"""


def has_reason(body: str) -> bool:
    """True when `body` carries a readable stop, skip or failing auto-test marker."""
    for kind, rest in REASON_MARKER.findall(body):
        parts = rest.split()
        if not parts or any("=" not in p for p in parts):
            continue
        fields = dict(p.split("=", 1) for p in parts)
        if any(not v or "<" in v or ">" in v for v in fields.values()):
            continue  # a quoted template, `reason=<hard-stop|decision>`
        if kind == "gogogo:stop" and fields.get("v") == "1" and fields.get("reason") in STOP_REASONS:
            return True
        if kind == "gogogo:skip" and fields.get("v") == "1" and fields.get("reason"):
            return True
        if kind == "auto-test v1" and fields.get("verdict") in ("FAIL", "NEEDS_HUMAN"):
            return True
    return False


class ProfileMissing(Exception):
    """No usable profile: this tool cannot know which board to read."""


def configure(profile_path: str | None = None) -> Path:
    """Read the board, repo and columns from the profile. Returns its path."""
    global ORG, PROJECT_NUMBER, DEFAULT_REPO
    path = Path(profile_path) if profile_path else profile_check.find_profile()
    if not path.is_file():
        raise ProfileMissing(f"no profile at {path}")
    try:
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except profile_check.ProfileError as exc:
        raise ProfileMissing(str(exc)) from None
    # With the format's defaults filled in: a profile without needs_human still
    # has that role, in its in_progress column.
    settings = profile_check.effective(settings)
    tracker = settings.get("tracker") or {}
    for key in ("project_owner", "project_number", "issues_repo"):
        if not tracker.get(key):
            raise ProfileMissing(f"tracker.{key}: missing in {path}")
    ORG = tracker["project_owner"]
    PROJECT_NUMBER = int(tracker["project_number"])
    DEFAULT_REPO = tracker["issues_repo"]

    COLUMNS.clear()
    if tracker.get("queue"):
        COLUMNS["queue"] = Column(tracker["queue"], "the queue the loop works")
    for role, name in (tracker.get("columns") or {}).items():
        COLUMNS[role] = Column(name, f"tracker.columns.{role}")
    for stage in settings.get("stages") or []:
        if isinstance(stage, dict) and stage.get("column"):
            COLUMNS[stage["column"]] = Column(stage["column"], f"stage: {stage.get('code_is', '')}")
    return path


def missing_columns(meta: dict, keys: list[str] | None = None) -> list[str]:
    """The profile's columns (all, or just `keys`) the live board lacks, by name."""
    live = {name.lower() for name in meta["options"]}
    wanted = [COLUMNS[k] for k in keys] if keys else list(COLUMNS.values())
    return sorted({c.name for c in wanted if c.name.lower() not in live})


def require_columns(meta: dict, keys: list[str] | None = None) -> None:
    """Raise BoardError naming each missing profile column, and how to add it."""
    missing = missing_columns(meta, keys)
    if missing:
        raise BoardError(
            "the board lacks column(s) the profile names: " + ", ".join(repr(m) for m in missing)
            + ". Add them in the board's Status field settings (the GitHub UI, not the API),"
            " or correct the profile."
        )


def column(key_or_name: str) -> str:
    """A profile role key → its column name; anything else passes through unchanged."""
    registered = COLUMNS.get(key_or_name)
    return registered.name if registered else key_or_name


# --------------------------------------------------------------------------
# gh plumbing
# --------------------------------------------------------------------------


def graphql(query: str, **variables: str | int) -> dict:
    """Run one GraphQL query through `gh`, retrying only transient failures.

    A partial `data` alongside `errors` is treated as a failure: a half-answered
    board query is the exact shape this script exists to stop.

    `int` values go through `-F` (gh's typed form, required by `Int!`); strings
    go through `-f`, which never coerces — a page cursor that happens to be all
    digits must stay a String.
    """
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        flag = "-F" if isinstance(value, int) else "-f"
        cmd += [flag, f"{key}={value}"]

    last_error = ""
    for attempt in range(ATTEMPTS):
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
        if proc.returncode == 0:
            payload = json.loads(proc.stdout)
            if payload.get("errors"):
                raise BoardError(
                    "GitHub returned errors:\n  "
                    + "\n  ".join(e.get("message", str(e)) for e in payload["errors"])
                )
            return payload["data"]

        last_error = (proc.stderr or proc.stdout).strip()
        transient = any(
            marker in last_error
            for marker in ("rate limit", "was submitted too quickly", "502", "503", "timeout")
        )
        if not transient or attempt + 1 == ATTEMPTS:
            break
        time.sleep(2 * (attempt + 1))

    raise BoardError(f"gh api graphql failed: {last_error}")


# --------------------------------------------------------------------------
# board metadata — always live, never a constant
# --------------------------------------------------------------------------

FIELDS_QUERY = """
query($org: String!, $number: Int!) {
  repositoryOwner(login: $org) {
    ... on ProjectV2Owner {
    projectV2(number: $number) {
      id
      title
      items(first: 1) { totalCount }
      fields(first: 50) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id
            name
            options { id name }
          }
        }
      }
    }
    }
  }
}
"""


def board_meta() -> dict:
    """Project id, item count, and the Status field with its current options."""
    data = graphql(FIELDS_QUERY, org=ORG, number=PROJECT_NUMBER)
    project = (data.get("repositoryOwner") or {}).get("projectV2")
    if not project:
        raise BoardError(f"project {ORG}/#{PROJECT_NUMBER} not visible to this gh login")

    status = next(
        (f for f in project["fields"]["nodes"] if f and f.get("name") == STATUS_FIELD),
        None,
    )
    if not status:
        raise BoardError(f"the board has no single-select {STATUS_FIELD!r} field")

    return {
        "project_id": project["id"],
        "title": project["title"],
        "total": project["items"]["totalCount"],
        "status_field_id": status["id"],
        "options": {o["name"]: o["id"] for o in status["options"]},
    }


def resolve_option(meta: dict, name: str) -> str:
    """Match a column name case-insensitively; list the real ones on a miss."""
    for option_name, option_id in meta["options"].items():
        if option_name.lower() == name.lower():
            return option_id
    raise BoardError(
        f"no column named {name!r} on this board. It has: "
        + ", ".join(meta["options"])
    )


# --------------------------------------------------------------------------
# list — the whole board, or nothing
# --------------------------------------------------------------------------

ITEMS_QUERY = """
query($org: String!, $number: Int!, $size: Int!, $after: String) {
  repositoryOwner(login: $org) {
    ... on ProjectV2Owner {
    projectV2(number: $number) {
      items(first: $size, after: $after,
            orderBy: {field: POSITION, direction: DESC}) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          type
          content {
            __typename
            ... on Issue {
              number title state stateReason url
              repository { nameWithOwner }
              assignees(first: 10) { nodes { login } }
              labels(first: 20) { totalCount nodes { name } }
              blockedBy(first: 20) { totalCount nodes { number state stateReason repository { nameWithOwner } } }
              blocking(first: 20) { totalCount nodes { number state repository { nameWithOwner } } }
            }
            ... on PullRequest {
              number title state url
              repository { nameWithOwner }
            }
            ... on DraftIssue { title }
          }
          fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue { name updatedAt }
          }
        }
      }
    }
    }
  }
}
"""


def fetch_items() -> list[dict]:
    """Every card on the board, newest-added first.

    Raises rather than returns if the pages do not reconcile against
    `totalCount` — a short read and an empty column look identical otherwise,
    and only one of them is a fact.
    """
    items: list[dict] = []
    cursor: str | None = None
    total: int | None = None
    pages = 0

    while True:
        variables: dict[str, str | int] = {"org": ORG, "number": PROJECT_NUMBER, "size": PAGE_SIZE}
        if cursor:
            variables["after"] = cursor
        page = graphql(ITEMS_QUERY, **variables)["repositoryOwner"]["projectV2"]["items"]

        total = page["totalCount"] if total is None else total
        items.extend(page["nodes"])
        pages += 1

        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
        if pages > 200:  # ~20k cards; a cursor that stopped advancing, in practice
            raise BoardError("pagination did not terminate — refusing to report a partial board")

    if total is not None and len(items) != total:
        raise BoardError(
            f"read {len(items)} cards but the board reports {total}. "
            "This is the short read this script exists to catch — not an empty column."
        )
    return items


def issue_labels(content: dict) -> list[str]:
    """An issue's label names. Raises rather than return a short list: a card
    whose ready label fell off a truncated read would look label-less."""
    connection = content.get("labels") or {}
    names = [n["name"] for n in connection.get("nodes") or []]
    if connection.get("totalCount", 0) > len(names):
        raise BoardError(f"labels truncated on #{content.get('number')}: "
                         f"{connection['totalCount']} labels, {len(names)} read")
    return names


def issue_links(content: dict, field: str) -> list[dict]:
    """An issue's `blockedBy` or `blocking` links. Raises rather than return a
    short list: a card whose blocker fell off a truncated read would look free."""
    connection = content.get(field) or {}
    nodes = connection.get("nodes") or []
    if connection.get("totalCount", 0) > len(nodes):
        raise BoardError(f"{field} truncated on #{content.get('number')}: "
                         f"{connection['totalCount']} links, {len(nodes)} read")
    links = []
    for node in nodes:
        link = {"number": node.get("number"),
                "repo": (node.get("repository") or {}).get("nameWithOwner"),
                "state": node.get("state")}
        if field == "blockedBy":
            link["state_reason"] = node.get("stateReason")
        links.append(link)
    return links


def ref_key(repo: str | None, number: int | None) -> str:
    """`owner/repo#n`, lower-cased: how a blocker is matched to its card."""
    return f"{repo or ''}#{number}".lower()


def stage_columns() -> list[str]:
    """The profile's stage columns: a blocker whose card is in one has merged."""
    return [c.name for c in COLUMNS.values() if c.meaning.startswith("stage")]


def blocker_state(entry: dict, cards_by_ref: dict, stages: list[str]) -> str:
    """`dropped`, `merged` or `open`: whether a `blocked_by` entry still blocks.

    Closed as not planned or as a duplicate is `dropped`: whether the blocked
    work still stands is a person's question. Closed otherwise, or open with its
    card in a stage column, is `merged`. Everything else, an open blocker not on
    this board included, is `open`.
    """
    if entry.get("state") == "CLOSED":
        return "dropped" if entry.get("state_reason") in ("NOT_PLANNED", "DUPLICATE") else "merged"
    card = cards_by_ref.get(ref_key(entry.get("repo"), entry.get("number")))
    where = _bare((card or {}).get("status") or "")
    if where and where in {_bare(s) for s in stages}:
        return "merged"
    return "open"


def annotate_blockers(cards: list[dict]) -> None:
    """Add each `blocked_by` entry's `column` (its card here, or None) and `blocker_state`."""
    by_ref = {ref_key(c.get("repo"), c.get("number")): c for c in cards if c.get("number")}
    stages = stage_columns()
    for card in cards:
        for entry in card.get("blocked_by") or []:
            found = by_ref.get(ref_key(entry.get("repo"), entry.get("number")))
            entry["column"] = (found or {}).get("status")
            entry["blocker_state"] = blocker_state(entry, by_ref, stages)


def flatten(item: dict) -> dict:
    """One card as flat fields; drafts and deleted content stay representable.

    `status_since` is when the card entered its column (the Status value's
    `updatedAt`), so a card moved back and forth starts again; `state_reason`
    is the issue's `stateReason` (`COMPLETED`, `NOT_PLANNED`, ...).
    `blocked_by` and `blocking` are GitHub's issue dependency links, empty for
    anything that is not an issue.
    """
    content = item.get("content") or {}
    value = item.get("fieldValueByName") or {}
    status = value.get("name")
    return {
        "item_id": item["id"],
        "kind": content.get("__typename") or item.get("type") or "Unknown",
        "number": content.get("number"),
        "title": content.get("title") or "(no content — draft or deleted)",
        "state": content.get("state"),
        "url": content.get("url"),
        "repo": (content.get("repository") or {}).get("nameWithOwner"),
        "status": status,
        "status_since": value.get("updatedAt"),
        "state_reason": content.get("stateReason"),
        "assignees": [a["login"] for a in (content.get("assignees") or {}).get("nodes", [])],
        "labels": issue_labels(content),
        "blocked_by": issue_links(content, "blockedBy"),
        "blocking": issue_links(content, "blocking"),
    }


REPO_ISSUE_CARDS_QUERY = """
query($owner: String!, $name: String!, $size: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(first: $size, after: $after, states: [OPEN],
           orderBy: {field: CREATED_AT, direction: DESC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number title state url
        repository { nameWithOwner }
        assignees(first: 10) { nodes { login } }
        labels(first: 20) { totalCount nodes { name } }
        blockedBy(first: 20) { totalCount nodes { number state stateReason repository { nameWithOwner } } }
        blocking(first: 20) { totalCount nodes { number state repository { nameWithOwner } } }
        projectItems(first: 10, includeArchived: true) {
          nodes {
            id
            isArchived
            project { number }
            fieldValueByName(name: "Status") {
              ... on ProjectV2ItemFieldSingleSelectValue { name updatedAt }
            }
          }
        }
      }
    }
  }
}
"""


def open_issues(repo: str):
    """Every open issue in `repo`, with its project items, newest first."""
    owner, name = repo.split("/", 1)
    cursor: str | None = None
    pages = 0
    while True:
        variables: dict[str, str | int] = {"owner": owner, "name": name, "size": PAGE_SIZE}
        if cursor:
            variables["after"] = cursor
        connection = graphql(REPO_ISSUE_CARDS_QUERY, **variables)["repository"]["issues"]
        yield from connection["nodes"]

        pages += 1
        if not connection["pageInfo"]["hasNextPage"]:
            return
        cursor = connection["pageInfo"]["endCursor"]
        if pages > 200:
            raise BoardError("issue pagination did not terminate")


def issue_side_cards(repo: str) -> list[dict]:
    """Every open issue's card on this project, asked from the *issue* side.

    The second opinion. `fetch_items` asks the project what it holds; this asks
    each issue what it belongs to. They are different indexes at GitHub's end
    and they do not always agree.
    """
    cards: list[dict] = []
    for issue in open_issues(repo):
        for node in (issue.get("projectItems") or {}).get("nodes") or []:
            if node["isArchived"] or node["project"]["number"] != PROJECT_NUMBER:
                continue
            cards.append({
                "item_id": node["id"],
                "kind": "Issue",
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"],
                "url": issue["url"],
                "repo": (issue.get("repository") or {}).get("nameWithOwner"),
                "status": (node.get("fieldValueByName") or {}).get("name"),
                "status_since": (node.get("fieldValueByName") or {}).get("updatedAt"),
                "state_reason": None,  # open issues only
                "assignees": [
                    a["login"] for a in (issue.get("assignees") or {}).get("nodes", [])
                ],
                "labels": issue_labels(issue),
                "blocked_by": issue_links(issue, "blockedBy"),
                "blocking": issue_links(issue, "blocking"),
            })
    return cards


def cards_the_board_did_not_list(board_cards: list[dict], repo: str) -> list[dict]:
    """Cards that exist issue-side and are missing from the project-side read.

    **Why a second read at all, when `fetch_items` already reconciles.** It
    reconciles the pages it got against the `totalCount` the *same* connection
    reported. When GitHub's project-side index omits an item, it omits it from
    both — so the count matches, the guard passes, and the card is simply gone.
    That is not hypothetical: an issue sat in its queue column, unarchived,
    while `list` read "369 of 369" and never showed it. `move` found it
    instantly, because `move` asks from the issue side.

    A count can only ever catch a read that came back short against its own
    idea of how long it should be. Catching an index that is wrong needs an
    index that is independently wrong, which is what the issue side is.

    Open issues only: that is what the queue is selected from, and it keeps the
    second read to two pages where enumerating everything would be five.
    """
    listed = {card["item_id"] for card in board_cards}
    return [card for card in issue_side_cards(repo) if card["item_id"] not in listed]


def list_cards(
    *,
    status: str | None = None,
    open_only: bool = False,
    issues_only: bool = False,
    repo: str = DEFAULT_REPO,
    crosscheck: bool = True,
) -> tuple[list[dict], list[dict], int]:
    """The cards matching the filters, the recovered ones, and the board total.

    The one reading of a column, for `list` and any other caller alike — so no
    caller can quietly skip the issue-side cross-check that `list` relies on.
    """
    if status:
        # A column the board does not have filters to no cards, which reads
        # exactly like an empty column. Refuse it instead (BoardError, exit 2).
        resolve_option(board_meta(), column(status))
    cards = [flatten(i) for i in fetch_items()]
    total = len(cards)

    # The project side has finished answering; now ask the issues themselves.
    # Recovered cards go to the front because they are newest-added, which is
    # the end of the list the queue is taken from — and because a card the
    # board could not name is the one a reader most needs to see.
    recovered: list[dict] = []
    if crosscheck:
        recovered = cards_the_board_did_not_list(cards, repo)
        cards = recovered + cards
    # Over the whole board, before any filter: a blocker's column is read from
    # its own card, wherever it sits.
    annotate_blockers(cards)

    if status:
        wanted = column(status).lower()
        cards = [c for c in cards if (c["status"] or "").lower() == wanted]
    if open_only:
        cards = [c for c in cards if c["state"] in (None, "OPEN")]
    if issues_only:
        cards = [c for c in cards if c["kind"] == "Issue"]
    return cards, recovered, total


def cmd_list(args: argparse.Namespace) -> int:
    cards, recovered, total = list_cards(
        status=args.status,
        open_only=args.open_only,
        issues_only=args.issues_only,
        repo=args.repo,
        crosscheck=not args.no_crosscheck,
    )

    if args.json:
        print(json.dumps(cards, indent=2))
    else:
        for card in cards:
            ref = f"#{card['number']}" if card["number"] else "(draft)"
            tags = "; " + ", ".join(card["labels"]) if card["labels"] else ""
            where = "" if args.status else f"  [{card['status'] or 'no status'}{tags}]"
            print(f"{ref:>7}{where}  {card['title']}")

    label = f"{column(args.status)!r} " if args.status else ""
    summary = f"\n{len(cards)} {label}card(s); {total} of {total} board items read"
    if args.no_crosscheck:
        summary += "; issue-side cross-check SKIPPED"
    elif recovered:
        summary += (
            f"; {len(recovered)} card(s) recovered from the issue side "
            "(GitHub's project index did not list them)"
        )
    else:
        summary += "; issue side agrees"
    print(summary + ".", file=sys.stderr)

    if recovered:
        # Every recovered card is named, whatever `--status` was asked for: the
        # filter is a question about columns, and this is a warning about the
        # board index being wrong. Each line carries its real column so the list
        # cannot be misread as "these are in the column you filtered for".
        print(
            "  cards below exist on the board but GitHub's project index "
            "omitted them; their real column is in brackets:",
            file=sys.stderr,
        )
        for card in recovered:
            print(
                f"    #{card['number']} [{card['status'] or 'no status'}] {card['title']}",
                file=sys.stderr,
            )
    return 0


# --------------------------------------------------------------------------
# show / move — one issue, asked directly, whatever the board size
# --------------------------------------------------------------------------

ISSUE_ITEMS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      title
      url
      state
      blockedBy(first: 20) { totalCount nodes { number state stateReason repository { nameWithOwner } } }
      blocking(first: 20) { totalCount nodes { number state repository { nameWithOwner } } }
      projectItems(first: 20, includeArchived: true) {
        nodes {
          id
          isArchived
          project { number title }
          fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""


def issue_card(number: int, repo: str) -> dict:
    """The issue's own card on this board — a read that ignores board size."""
    owner, name = repo.split("/", 1)
    issue = graphql(
        ISSUE_ITEMS_QUERY, owner=owner, name=name, number=number
    )["repository"]["issue"]
    if not issue:
        raise BoardError(f"{repo}#{number} does not exist")

    card = next(
        (
            node
            for node in issue["projectItems"]["nodes"]
            if node["project"]["number"] == PROJECT_NUMBER
        ),
        None,
    )
    return {"issue": issue, "card": card}


ADD_ITEM_MUTATION = """
mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) {
    item { id }
  }
}
"""

ISSUE_ID_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { issue(number: $number) { id } }
}
"""

SET_FIELD_MUTATION = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project, itemId: $item, fieldId: $field,
    value: {singleSelectOptionId: $option}
  }) { projectV2Item { id } }
}
"""


def newest_comment(number: int, repo: str) -> str:
    """The issue's newest comment body, or "" when it has none. A failed read raises BoardError."""
    owner, name = repo.split("/", 1)
    issue = (graphql(NEWEST_COMMENT_QUERY, owner=owner, name=name, number=number).get("repository") or {}).get("issue")
    if not issue:
        raise BoardError(f"{repo}#{number} does not exist (or this login cannot see it)")
    nodes = issue["comments"]["nodes"]
    return (nodes[-1].get("body") or "") if nodes else ""


def cmd_show(args: argparse.Namespace) -> int:
    if args.expect:
        # Otherwise every card "is not in" a renamed column: exit 3 for all.
        resolve_option(board_meta(), column(args.expect))
    found = issue_card(args.issue, args.repo)
    issue, card = found["issue"], found["card"]
    print(f"#{args.issue} {issue['title']}  ({issue['state'].lower()})")
    print(issue["url"])
    if not card:
        print(f"not on project #{PROJECT_NUMBER}")
        return 1 if args.expect else 0
    current = (card.get("fieldValueByName") or {}).get("name")
    status = current or "on board, no status"
    archived = "  (archived)" if card.get("isArchived") else ""
    print(f"column: {status}{archived}")
    for entry in issue_links(issue, "blockedBy"):
        blocker = issue_card(entry["number"], entry["repo"])["card"] if entry.get("repo") else None
        where = ((blocker or {}).get("fieldValueByName") or {}).get("name")
        by_ref = {ref_key(entry["repo"], entry["number"]): {"status": where}} if where else {}
        state = blocker_state(entry, by_ref, stage_columns())
        print(f"blocked by: {short_ref(entry['repo'], entry['number'], args.repo)} "
              f"({state}, {where or 'not on this board'})")
    if args.expect and (current or "").lower() != column(args.expect).lower():
        # An exit status, not a name for the caller to grep: a grep for a
        # literal column silently matches nothing after a rename.
        return 3
    return 0


def short_ref(repo: str | None, number: int, home: str) -> str:
    """`#n` for an issue in `home`, `owner/repo#n` for one elsewhere."""
    return f"#{number}" if (repo or home).lower() == home.lower() else f"{repo}#{number}"


BLOCK_REF = re.compile(r"^(?:([\w.-]+/[\w.-]+))?#?(\d+)$")


def gh_api(*args: str) -> subprocess.CompletedProcess:
    """One REST call through `gh api`."""
    return subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=CALL_TIMEOUT)


def cmd_block(args: argparse.Namespace) -> int:
    """Set "<issue> is blocked by <ref>", then confirm it from the blocker's side.

    The POST answers with the *blocked* issue, so its number is never read as
    the blocker; the claim is checked on the blocker's own `blocking` list.
    """
    match = BLOCK_REF.match(args.by.strip())
    if not match:
        print(f"tracker.py: --by {args.by!r}: give #B, B or owner/repo#B", file=sys.stderr)
        return 1
    blocker_repo, blocker = match.group(1) or args.repo, int(match.group(2))
    ref = short_ref(blocker_repo, blocker, args.repo)

    found = gh_api(f"repos/{blocker_repo}/issues/{blocker}", "--jq", ".id")
    if found.returncode != 0:
        reason = (found.stderr or found.stdout).strip()
        print(f"tracker.py: could not read {ref}: {reason}", file=sys.stderr)
        return 1 if "404" in reason or "Not Found" in reason else 2
    database_id = found.stdout.strip()
    if not database_id.isdigit():
        print(f"tracker.py: {ref} has no database id ({database_id!r})", file=sys.stderr)
        return 2

    wrote = gh_api("-X", "POST", f"repos/{args.repo}/issues/{args.issue}/dependencies/blocked_by",
                   "-F", f"issue_id={database_id}")
    already = wrote.returncode != 0 and "already" in (wrote.stderr + wrote.stdout).lower()
    if wrote.returncode != 0 and not already:
        print(f"tracker.py: could not set #{args.issue} blocked by {ref}: "
              f"{(wrote.stderr or wrote.stdout).strip()}", file=sys.stderr)
        return 2

    seen = gh_api(f"repos/{blocker_repo}/issues/{blocker}/dependencies/blocking?per_page=100")
    try:
        blocking = json.loads(seen.stdout) if seen.returncode == 0 else None
    except json.JSONDecodeError:
        blocking = None
    if not isinstance(blocking, list):
        print(f"tracker.py: wrote the link, but could not read {ref}'s blocking list back: "
              f"{(seen.stderr or seen.stdout).strip()}", file=sys.stderr)
        return 2
    confirmed = any(
        isinstance(i, dict) and i.get("number") == args.issue
        and (i.get("repository_url") or "").lower().endswith("/repos/" + args.repo.lower())
        for i in blocking
    )
    if not confirmed:
        print(f"tracker.py: wrote the link, but {ref}'s blocking list does not name #{args.issue}",
              file=sys.stderr)
        return 2
    print(f"#{args.issue} blocked by {ref}" + (" (already linked)" if already else ""))
    return 0


def cmd_move(args: argparse.Namespace) -> int:
    # Passed only when given, so a caller without `--from` calls exactly as before.
    expect_from = getattr(args, "expect_from", None)
    extra = {"expect_from": expect_from} if expect_from else {}
    return move_card(args.issue, args.repo, args.to, add_missing=args.add_missing, **extra)


def move_card(number: int, repo: str, to: str, *, add_missing: bool = False,
              meta: dict | None = None, expect_from: str | None = None) -> int:
    """Set one issue's column and read it back. Exit-code semantics of `move`.

    With `expect_from`, refuse (exit 3, nothing written) unless the card is in
    that column now. The read and the write are still two calls: this narrows
    the gap in which another session's move can be undone, it does not close it.
    """
    target = column(to)
    meta = meta or board_meta()
    if expect_from:
        # Otherwise every card "is not in" a renamed column: exit 3 for all.
        resolve_option(meta, column(expect_from))
    option_id = resolve_option(meta, target)

    needs_human = COLUMNS.get("needs_human")
    in_progress = COLUMNS.get("in_progress")
    # A profile without needs_human hands back into the in_progress column (#87): there the
    # column name is shared, so only the role key is a hand-back, and starting work is not.
    shared = needs_human and in_progress and _bare(needs_human.name) == _bare(in_progress.name)
    handing_back = to == "needs_human" if shared else needs_human and _bare(target) == _bare(needs_human.name)
    if handing_back and not has_reason(newest_comment(number, repo)):
        print(f"#{number}: refused: a move to {needs_human.name} needs the issue's newest comment to carry "
              "a stop marker (post the Needs-you comment first). Nothing written.", file=sys.stderr)
        return 4

    found = issue_card(number, repo)
    card = found["card"]

    if expect_from:
        current = ((card or {}).get("fieldValueByName") or {}).get("name")
        if not current or current.lower() != column(expect_from).lower():
            where = current or ("no column" if card else "not on the board")
            print(f"#{number} is in {where}, not {column(expect_from)}; not moved", file=sys.stderr)
            return 3

    if not card:
        if not add_missing:
            print(
                f"#{number} is not on project #{PROJECT_NUMBER}. "
                "Re-run with --add-missing to put it on the board and set the column.",
                file=sys.stderr,
            )
            return 1
        owner, name = repo.split("/", 1)
        content_id = graphql(
            ISSUE_ID_QUERY, owner=owner, name=name, number=number
        )["repository"]["issue"]["id"]
        item_id = graphql(
            ADD_ITEM_MUTATION, project=meta["project_id"], content=content_id
        )["addProjectV2ItemById"]["item"]["id"]
        print(f"added #{number} to the board")
    else:
        item_id = card["id"]

    was = (card or {}).get("fieldValueByName", {})
    was = (was or {}).get("name") or "no status"

    graphql(
        SET_FIELD_MUTATION,
        project=meta["project_id"],
        item=item_id,
        field=meta["status_field_id"],
        option=option_id,
    )

    # The mutation returning cleanly is not the claim we need; the claim is that
    # the board now reads back as the column we asked for.
    after = issue_card(number, repo)["card"]
    now = ((after or {}).get("fieldValueByName") or {}).get("name")
    if (now or "").lower() != target.lower():
        print(
            f"WROTE but board reads {now!r}, expected {target!r} — card NOT moved reliably",
            file=sys.stderr,
        )
        return 2

    print(f"#{number}: {was} -> {now}")
    return 0


def cmd_fields(args: argparse.Namespace) -> int:
    meta = board_meta()
    print(f"{meta['title']} (#{PROJECT_NUMBER}) — {meta['total']} items")
    print(f"project id:      {meta['project_id']}")
    print(f"Status field id: {meta['status_field_id']}")
    for name, option_id in meta["options"].items():
        print(f"  {option_id}  {name}")
    if args.check:
        try:
            require_columns(meta)
        except BoardError as exc:
            print(exc, file=sys.stderr)
            return 2
    return 0


# --------------------------------------------------------------------------
# keeping the board current: views, and cards left behind
# --------------------------------------------------------------------------

VIEWS_QUERY = """
query($org: String!, $number: Int!) {
  repositoryOwner(login: $org) {
    ... on ProjectV2Owner {
    projectV2(number: $number) {
      views(first: 50) { nodes { id name number filter } }
    }
    }
  }
}
"""

UPDATE_VIEW_MUTATION = """
mutation($view: ID!, $filter: String!) {
  updateProjectV2View(input: {viewId: $view, filter: $filter}) { projectV2View { id } }
}
"""


def board_views() -> list[dict]:
    """The board's views, live: id, name, number, filter."""
    project = (graphql(VIEWS_QUERY, org=ORG, number=PROJECT_NUMBER)
               .get("repositoryOwner") or {}).get("projectV2")
    if not project:
        raise BoardError(f"project {ORG}/#{PROJECT_NUMBER} not visible to this gh login")
    return project["views"]["nodes"]


#: A view whose filter has one of these is meant to show closed work: leave it alone.
CLOSED_FILTERS = ("is:closed", "-is:open")


def views_showing_closed(views: list[dict]) -> list[dict]:
    """Views whose filter lets closed issues through, other than views made to show them."""
    return [v for v in views
            if not any(token in OPEN_FILTERS + CLOSED_FILTERS for token in (v.get("filter") or "").split())]


ARCHIVE_ITEM_MUTATION = """
mutation($project: ID!, $item: ID!) {
  archiveProjectV2Item(input: {projectId: $project, itemId: $item}) { item { id } }
}
"""


def untidy(repo: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Closed issues not in Done, closed-as-not-planned ones to archive, and
    open issues in `repo` with no card here."""
    cards = [flatten(i) for i in fetch_items()]
    closed = [c for c in cards if c["kind"] == "Issue" and c["state"] == "CLOSED"]
    archive = [c for c in closed if c["state_reason"] == "NOT_PLANNED"]
    closed = [c for c in closed
              if c["state_reason"] != "NOT_PLANNED"
              and (c["status"] or "").lower() != DONE_COLUMN.lower()]
    off_board = [
        {"number": i["number"], "title": i["title"],
         "repo": (i.get("repository") or {}).get("nameWithOwner") or repo}
        for i in open_issues(repo)
        if not any((n.get("project") or {}).get("number") == PROJECT_NUMBER
                   for n in (i.get("projectItems") or {}).get("nodes") or [])
    ]
    return closed, archive, off_board


def archive_card(card: dict, meta: dict) -> int:
    """Archive one card: off the board, restorable from the board's archive. 0 done, 2 failed."""
    ref = f"{card['repo']}#{card['number']}"
    try:
        graphql(ARCHIVE_ITEM_MUTATION, project=meta["project_id"], item=card["item_id"])
    except (BoardError, KeyError, TypeError) as exc:
        print(f"FAILED {ref} -> archive: {exc}", file=sys.stderr)
        return 2
    print(f"{ref}: {card.get('status') or 'no status'} -> archived")
    return 0


def cmd_views(args: argparse.Namespace) -> int:
    views = board_views()
    for v in views:
        print(f"  view {v['number']} {v['name']!r}: filter {v.get('filter') or '(none)'!r}")
    if not args.hide_closed:
        return 0
    for v in views_showing_closed(views):
        new = f"{v.get('filter') or ''} is:open".strip()
        graphql(UPDATE_VIEW_MUTATION, view=v["id"], filter=new)
        print(f"view {v['number']} {v['name']!r}: {v.get('filter') or '(none)'!r} -> {new!r}")
    # The claim is that the views now hide closed issues, so read them back.
    still = views_showing_closed(board_views())
    if still:
        print("WROTE but these views still show closed issues: "
              + ", ".join(repr(v["name"]) for v in still), file=sys.stderr)
        return 2
    return 0


def _bare(name: str) -> str:
    return name.replace("\ufe0f", "").strip().lower()


def cmd_tidy(args: argparse.Namespace) -> int:
    closed, archive, off_board = untidy(args.repo)
    for c in closed:
        print(f"closed, not in {DONE_COLUMN}: {c['repo']}#{c['number']} ({c['status'] or 'no status'})")
    for c in archive:
        print(f"closed as not planned, to archive: {c['repo']}#{c['number']} ({c['status'] or 'no status'})")
    for i in off_board:
        print(f"open, not on the board: {i['repo']}#{i['number']} {i['title']}")
    if not (closed or archive or off_board):
        print("nothing to tidy")
    if not args.apply:
        return 0
    meta = board_meta()
    worst = 0
    for c in archive:
        worst = max(worst, archive_card(c, meta))
    # The board's own spelling of New: "⚡️ New" and "⚡ New" differ only by a variation selector.
    new = next((o for o in meta.get("options") or {} if _bare(o) == _bare(NEW_COLUMN)), NEW_COLUMN)
    moves = [(c, DONE_COLUMN, False) for c in closed] + [(i, new, True) for i in off_board]
    for item, to, add in moves:
        try:
            code = move_card(item["number"], item["repo"], to, add_missing=add, meta=meta)
        except (BoardError, KeyError, TypeError) as exc:
            # One card that cannot be moved must not leave the rest unattempted.
            print(f"FAILED {item['repo']}#{item['number']} -> {to}: {exc}", file=sys.stderr)
            code = 2
        worst = max(worst, code)
    return worst


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md above this folder)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lister = subparsers.add_parser("list", help="cards on the board, newest-added first")
    lister.add_argument("--status", help='registry key or column name, e.g. in-dev or "Dev Ready"')
    lister.add_argument("--open-only", action="store_true", help="drop closed issues/PRs")
    lister.add_argument("--issues-only", action="store_true", help="drop drafts and PRs")
    lister.add_argument("--json", action="store_true")
    lister.add_argument("--repo", default=None,
                        help="repo whose open issues the cross-check reads")
    lister.add_argument(
        "--no-crosscheck", action="store_true",
        help="skip the issue-side second opinion (faster, and loses the one "
             "guard that catches a card GitHub's project index omits)",
    )
    lister.set_defaults(func=cmd_list)

    shower = subparsers.add_parser("show", help="one issue's column")
    shower.add_argument("issue", type=int)
    shower.add_argument("--repo", default=None)
    shower.add_argument("--expect", help="profile role key or column name; exit 3 if the card is elsewhere")
    shower.set_defaults(func=cmd_show)

    mover = subparsers.add_parser(
        "move", help="set an issue's column, verified; a move to needs_human exits 4 unless the "
                     "issue's newest comment carries a stop marker")
    mover.add_argument("issue", type=int)
    mover.add_argument(
        "--from", dest="expect_from", metavar="COLUMN",
        help="profile role key or column name; exit 3, writing nothing, if the card is elsewhere. "
             "It narrows, but does not close, the gap between reading a card and moving it")
    mover.add_argument("--to", required=True, help='profile role key or column name')
    mover.add_argument("--repo", default=None)
    mover.add_argument(
        "--add-missing",
        action="store_true",
        help="add the issue to the board if it has no card there",
    )
    mover.set_defaults(func=cmd_move)

    blocker = subparsers.add_parser(
        "block", help="set GitHub's 'blocked by' link on an issue, then read it back from the blocker")
    blocker.add_argument("issue", type=int)
    blocker.add_argument("--by", required=True, help="the blocker: #B, B, or owner/repo#B")
    blocker.add_argument("--repo", default=None, help="the blocked issue's repo (default: tracker.issues_repo)")
    blocker.set_defaults(func=cmd_block)

    fields = subparsers.add_parser("fields", help="the board's Status options, live")
    fields.add_argument("--check", action="store_true",
                        help="exit 2 naming each profile column the board lacks")
    fields.set_defaults(func=cmd_fields)

    views = subparsers.add_parser("views", help="the board's views and their filters")
    views.add_argument("--hide-closed", action="store_true",
                       help="add is:open to every view that shows closed issues, then read back")
    views.set_defaults(func=cmd_views)

    tidy = subparsers.add_parser(
        "tidy", help=f"closed issues not in {DONE_COLUMN}, closed-as-not-planned ones to archive, "
                     "open issues not on the board")
    tidy.add_argument("--repo", default=None, help="repo whose open issues belong on the board")
    tidy.add_argument("--apply", action="store_true",
                      help=f"archive each not-planned one, move each other closed one to {DONE_COLUMN}, "
                           f"add each missing one to {NEW_COLUMN}")
    tidy.set_defaults(func=cmd_tidy)

    args = parser.parse_args()
    try:
        configure(args.profile)
    except ProfileMissing as exc:
        print(f"tracker.py: {exc}", file=sys.stderr)
        return 2
    if hasattr(args, "repo") and not args.repo:
        args.repo = DEFAULT_REPO
    try:
        return args.func(args)
    except BoardError as exc:
        print(f"tracker.py: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # An uncaught traceback exits 1, which `show --expect` uses for "not on
        # the board" — and a caller reads that as a card to skip. A crash must
        # read as untrusted (2), never as an answer.
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
