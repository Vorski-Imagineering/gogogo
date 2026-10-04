#!/usr/bin/env python3
"""Read back the review records /gogogo:dev leaves on issues, and sum them up.

    review_stats.py [--profile FILE] [--since YYYY-MM-DD] [--json]

Every report /gogogo:dev §7 posts ends with a `<!-- gogogo:review … -->`
record. This lists one row per record (issue, pull request, kind, coverage,
rounds, findings applied and declined per round, re-fixes, how the review
ended, what became of the issue, and any later bug that escaped from it), then
a summary: median rounds, endings, the re-fix rate, the reasons findings were
applied and declined, outcomes, and escaped bugs. The attempt limit, the
breaker and the default coverage in /gogogo:dev §5 change only on these
numbers.

Records written before gogogo#33 carry no `v` key; they are read as the old
format (`level` high is coverage broad, medium is precise; `stopped` gives the
ending) and have no re-fixes, reasons, models or escape fields. A marker whose
values do not parse, such as a quoted template, is skipped and counted. A
record whose per-round lists are not `rounds` long, or whose reason totals do
not add up to them, is shown with `!` after its issue and left out of the
reason totals.

A report may also carry a `<!-- gogogo:spec-check v=1 … -->` record, from the
spec check /gogogo:dev §5 runs before the review (gogogo#44). It is attached to
the review records of the same comment: each row gains `spec_items` (items
checked), `spec_unmet` (missing plus differs at the first reading) and
`spec_declared` (differences and outside files kept and declared), `-` when
the comment has none. The summary adds a `spec check:` line with the totals,
and a `spec check ended:` line with how many checks ended clean, declared,
stopped or nospec. A spec-check marker that does not parse, or whose `items`
is not the sum of its four statuses, or that sits in a comment with no
readable review record, is counted as unreadable.

A report may also carry `<!-- gogogo:mutation v=1 … -->` records, one per
lane whose `mutate` command /gogogo:dev §6 ran (gogogo#45). They are attached
to the review records of the same comment: each row gains `mutants`,
`survived` and `added` (summed over its lanes; `-` when none), and the
summary adds a `mutation:` line (records, mutants, survived and its share,
survivors killed by added tests), a `mutation declined by reason:` line and a
`mutation ended:` line. A mutation marker that does not parse or add up, or
that sits in a comment with no readable review record, counts as unreadable.

Since gogogo#62 a v2 record may end with `session=<id>`, `t_branch=<time>` and
`t_verified=<time>` (UTC, `YYYY-MM-DDTHH:MMZ`); each may be `unknown`, and a
record without them still parses. A value that is neither `unknown` nor a
session id or time is left out and the record counted as having malformed
fields, as is a record whose `t_verified` is before its `t_branch`. Each row
gains those three and `posted`, the comment's time, and the summary adds a
`phase times:` line (records with both times; median minutes from branch to
verified, and from verified to the report being posted, `-` when none, rounded
half up to whole minutes in the text (the JSON keeps them unrounded)) and a
`session ids:` line. A hand-back to a person carries
`<!-- gogogo:stop v=1 reason=<reason> -->` under its Needs-you line; the
summary counts them by reason in a `stops:` line. Only a marker alone on its
own line is read (gogogo#82); a mention inside a sentence is ignored. An
own-line marker that does not parse, or names an unknown reason, counts as
unreadable. Stop markers
alone are not review records: zero records still exits 1.

Since gogogo#63 a stop marker may end with `session=<id|unknown>`, and a card
`/gogogo:auto-dev` skips at triage is handed back with
`<!-- gogogo:skip v=1 reason=<lint|nospec|decision|hard-stop> session=<id|unknown> -->`.
The summary counts skips by reason in a `skips:` line (read only on its own
line, as a stop is; one with an unknown reason, or that does not parse, is
unreadable), and a `sessions:` block
rebuilds each run from the review records, stops and skips sharing a session
id: its first and last time, the distinct issues it took (records and stops),
the distinct issues it handed to a person (stops), and its skips. `unknown`,
or anything that is not a full session id, is no session; those markers are
counted apart.

The outcome of a row is the verdict of the latest `<!-- auto-test v1 … -->`
marker on the issue (pass, fail, needs-human); else `confirmed` when the issue
is closed as completed, `dropped` when it is closed otherwise, else `waiting`.

The repo is the profile's `tracker.issues_repo` (`--profile`, default the
nearest `.agents/dev-process.md`). It only reads.

Exit codes: 0 at least one record was read; 1 none was (zero records is not a
clean result); 2 the profile is missing or unusable, or a `gh` call failed.

Standard library only; imports `profile_check` from this folder.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile_check  # noqa: E402

REVIEW = re.compile(r"<!-- gogogo:review (.*?) -->")
SPEC_CHECK = re.compile(r"<!-- gogogo:spec-check (.*?) -->")
SPEC_CHECK_ENDS = ("clean", "declared", "stopped", "nospec")
SPEC_CHECK_READERS = ("fresh", "self", "none")
TESTS = re.compile(r"<!-- gogogo:tests (.*?) -->")
MUTATION = re.compile(r"<!-- gogogo:mutation (.*?) -->")
MUTATION_DECLINED_AS = ("equivalent", "text", "outside")
MUTATION_ENDS = ("clean", "survivors", "failed")
MUTATION_COUNTS = ("mutants", "killed", "survived", "timeout", "runs", "added")
TESTS_KEYS = ("v", "checked", "hunks", "weaker", "licensed", "restored", "attempts", "end")
TESTS_ENDS = ("clean", "restored", "stopped", "unchecked")
SPEC_CHECK_COUNTS = ("items", "met", "missing", "differs", "na", "outside", "runs", "fixed", "declared")
AUTO_TEST = re.compile(r"<!-- auto-test v1 (.*?) -->")
STOP = re.compile(r"^[ \t]*<!-- gogogo:stop (.*?) -->[ \t\r]*$", re.M)
STOPS = ("hard-stop", "decision", "spec", "review", "tests", "mutation", "verify", "gate", "ci", "merge", "reverted")
SKIP = re.compile(r"^[ \t]*<!-- gogogo:skip (.*?) -->[ \t\r]*$", re.M)
SKIPS = ("lint", "nospec", "decision", "hard-stop")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
APPLIED_AS = ("spec", "regression", "bug", "risk", "added")
DECLINED_AS = ("hypothetical", "style", "settled", "reversal", "beyond", "late")
ENDS = ("clean", "third-attempt", "reversal", "unfixable", "prose", "breaker")
OLD_COVERAGE = {"high": "broad", "medium": "precise", "max": "exhaustive"}
VERDICTS = {"PASS": "pass", "FAIL": "fail", "NEEDS_HUMAN": "needs-human"}
COLUMNS = ("issue", "pr", "kind", "coverage", "rounds", "applied", "declined", "refix", "end", "outcome",
           "escaped", "mutants", "survived", "added", "spec_items", "spec_unmet", "spec_declared", "weaker")


class GhError(Exception):
    """A `gh` call failed."""


def _gh(args: list[str]) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise GhError((out.stderr.strip().splitlines() or [f"gh exited {out.returncode}"])[0])
    return out.stdout


def _fields(body: str) -> dict[str, str] | None:
    parts = body.split()
    if not parts or any("=" not in p for p in parts):
        return None
    fields = dict(p.split("=", 1) for p in parts)
    if any(not v or "<" in v or ">" in v for v in fields.values()):
        return None  # a quoted template, `pr=<n|none>`
    return fields


def _ints(value: str) -> list[int]:
    return [int(x) for x in value.split(",")]


def _reasons(value: str, names: tuple[str, ...]) -> dict[str, int]:
    counts = dict(part.split(":", 1) for part in value.split(","))
    if set(counts) != set(names):
        raise ValueError(value)
    return {name: int(counts[name]) for name in names}


def _real(key: str, value: str) -> bool:
    """A time that names a real minute (`T25:00Z` matches TIME but is not one); any session id is real."""
    if key == "session":
        return True
    try:
        datetime.datetime.strptime(value, "%Y-%m-%dT%H:%MZ")
    except ValueError:
        return False
    return True


def parse_review(text: str) -> dict | None:
    """The first review record in `text` as a dict, or None when it does not parse."""
    match = REVIEW.search(text)
    # An empty gogogo#62 key (`session=`, from an unset variable) is malformed, never an unreadable record.
    parts = match.group(1).split() if match else []
    blank = ("session=", "t_branch=", "t_verified=")
    empty = [p[:-1] for p in parts if p in blank]
    fields = _fields(" ".join(p for p in parts if p not in blank)) if match else None
    if fields is None:
        return None
    try:
        if "v" not in fields:
            record = {"v": 1, "pr": fields["pr"], "kind": fields["kind"],
                      "coverage": OLD_COVERAGE.get(fields["level"], fields["level"]),
                      "rounds": int(fields["rounds"]), "applied": _ints(fields["applied"]),
                      "declined": _ints(fields["declined"]), "refix": None, "applied_as": None,
                      "declined_as": None, "followups": None,
                      "end": {"no": "clean", "yes": "stopped"}[fields["stopped"]],
                      "escaped_from": None, "escaped_as": None, "impl": None, "reviewer": None,
                      "session": None, "t_branch": None, "t_verified": None, "malformed": []}
            record["consistent"] = all(len(record[k]) == record["rounds"] for k in ("applied", "declined"))
            return record
        if fields["v"] != "2":
            return None
        record = {"v": 2, "pr": fields["pr"], "kind": fields["kind"], "coverage": fields["coverage"],
                  "rounds": int(fields["rounds"]), "applied": _ints(fields["applied"]),
                  "declined": _ints(fields["declined"]), "refix": _ints(fields["refix"]),
                  "applied_as": _reasons(fields["applied_as"], APPLIED_AS),
                  "declined_as": _reasons(fields["declined_as"], DECLINED_AS),
                  "followups": int(fields["followups"]), "end": fields["end"],
                  "escaped_from": None if fields["escaped_from"] == "none" else int(fields["escaped_from"]),
                  "escaped_as": None if fields["escaped_as"] == "none" else fields["escaped_as"],
                  "impl": fields["impl"], "reviewer": fields["reviewer"], "malformed": []}
        for key, shape in (("session", UUID), ("t_branch", TIME), ("t_verified", TIME)):
            value = fields.get(key)
            record[key] = value if value and shape.fullmatch(value) and _real(key, value) else None
            if value not in (None, "unknown") and record[key] is None:
                record["malformed"].append(key)
        record["malformed"] += empty
    except (KeyError, ValueError):
        return None
    record["consistent"] = (all(len(record[k]) == record["rounds"] for k in ("applied", "declined", "refix"))
                            and sum(record["applied_as"].values()) == sum(record["applied"])
                            and sum(record["declined_as"].values()) == sum(record["declined"]))
    return record


def parse_spec_check(text: str) -> dict | None:
    """The first spec-check record in `text` as a dict, or None when it does not parse or add up."""
    match = SPEC_CHECK.search(text)
    fields = _fields(match.group(1)) if match else None
    if fields is None or fields.get("v") != "1":
        return None
    try:
        record = {k: int(fields[k]) for k in SPEC_CHECK_COUNTS}
        record.update(reader=fields["reader"], end=fields["end"])
    except (KeyError, ValueError):
        return None
    if record["end"] not in SPEC_CHECK_ENDS or record["reader"] not in SPEC_CHECK_READERS:
        return None
    if record["items"] != record["met"] + record["missing"] + record["differs"] + record["na"]:
        return None
    return record


def parse_mutation(text: str) -> dict | None:
    """The first mutation record in `text` (one lane's run, /gogogo:dev §6), or None when it does not parse or add up."""
    match = MUTATION.search(text)
    fields = _fields(match.group(1)) if match else None
    if fields is None or fields.get("v") != "1":
        return None
    try:
        record = {k: int(fields[k]) for k in MUTATION_COUNTS}
        record.update(lane=fields["lane"], end=fields["end"],
                      declined_as=_reasons(fields["declined_as"], MUTATION_DECLINED_AS))
    except (KeyError, ValueError):
        return None
    if record["end"] not in MUTATION_ENDS:
        return None
    if record["mutants"] != record["killed"] + record["survived"] + record["timeout"]:
        return None
    if record["end"] == "clean" and record["added"] + sum(record["declined_as"].values()) != record["survived"]:
        return None
    return record


def parse_tests(text: str) -> dict | None:
    """The first tests record in `text` (from test_guard.py, /gogogo:dev §6), or None."""
    match = TESTS.search(text)
    fields = _fields(match.group(1)) if match else None
    if fields is None or fields.get("v") != "1" or set(fields) != set(TESTS_KEYS):
        return None
    try:
        record = {k: int(fields[k]) for k in ("hunks", "weaker", "licensed", "restored", "attempts")}
    except ValueError:
        return None
    if fields["checked"] not in ("yes", "no") or fields["end"] not in TESTS_ENDS:
        return None
    return {**record, "checked": fields["checked"], "end": fields["end"]}


def _repo(profile: str | None) -> str:
    path = Path(profile) if profile else profile_check.find_profile()
    if not path.is_file():
        raise SystemExit(f"no profile at {path}")
    try:
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except (OSError, profile_check.ProfileError) as exc:
        raise SystemExit(f"{path}: {exc}") from None
    repo = (settings.get("tracker") or {}).get("issues_repo") or ""
    if "/" not in repo:
        raise SystemExit(f"tracker.issues_repo: missing or not owner/name in {path}")
    return repo


def _date(value: str) -> str:
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from None
    return value


def _session(fields: dict) -> str | None:
    """A marker's session id, or None when it is `unknown`, missing or not a full id."""
    value = fields.get("session") or ""
    return value if UUID.fullmatch(value) else None


def collect(repo: str, since: str | None) -> tuple:
    """(records, unreadable markers, latest auto-test verdict by issue, issue data by number,
    stop markers, unreadable stop markers, skip markers, unreadable skip markers)."""
    url = f"repos/{repo}/issues/comments?per_page=100"
    if since:
        url += f"&since={since}T00:00:00Z"
    pages = json.loads(_gh(["api", "--paginate", "--slurp", url]) or "[]")
    records, unreadable, verdicts, stops, unreadable_stops, skips, unreadable_skips = [], 0, {}, [], 0, [], 0
    for comment in (c for page in pages for c in page):
        issue = int(str(comment.get("issue_url", "")).rsplit("/", 1)[-1])
        body = comment.get("body") or ""
        spec_marker = SPEC_CHECK.search(body)
        spec_check = parse_spec_check(spec_marker.group(0)) if spec_marker else None
        if spec_marker and spec_check is None:
            unreadable += 1
        tests_marker = TESTS.search(body)
        tests = parse_tests(tests_marker.group(0)) if tests_marker else None
        if tests_marker and tests is None:
            unreadable += 1
        mutations = []
        for match in MUTATION.finditer(body):
            mutation = parse_mutation(match.group(0))
            if mutation is None:
                unreadable += 1
            else:
                mutations.append(mutation)
        read = 0
        for match in REVIEW.finditer(body):
            record = parse_review(match.group(0))
            if record is None:
                unreadable += 1
            else:
                records.append({**record, "issue": issue, "spec_check": spec_check, "tests": tests,
                                "mutation": mutations, "posted": comment.get("created_at")})
                read += 1
        if spec_check is not None and not read:
            unreadable += 1
        if tests is not None and not read:
            unreadable += 1
        if not read:
            unreadable += len(mutations)
        for match in STOP.finditer(body):
            fields = _fields(match.group(1))
            if fields and fields.get("v") == "1" and fields.get("reason") in STOPS:
                stops.append({"issue": issue, "reason": fields["reason"], "session": _session(fields),
                              "posted": comment.get("created_at")})
            else:
                unreadable_stops += 1
        for match in SKIP.finditer(body):
            fields = _fields(match.group(1))
            if fields and fields.get("v") == "1" and fields.get("reason") in SKIPS:
                skips.append({"issue": issue, "reason": fields["reason"], "session": _session(fields),
                              "posted": comment.get("created_at")})
            else:
                unreadable_skips += 1
        for match in AUTO_TEST.finditer(body):
            fields = _fields(match.group(1)) or {}
            if fields.get("verdict") in VERDICTS:
                verdicts[issue] = VERDICTS[fields["verdict"]]
    issues = {}
    for n in dict.fromkeys(r["issue"] for r in records):
        issues[n] = json.loads(_gh(["api", f"repos/{repo}/issues/{n}"]))
    return records, unreadable, verdicts, issues, stops, unreadable_stops, skips, unreadable_skips


def _minutes(start: str, end: str) -> float:
    def at(value):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (at(end) - at(start)).total_seconds() / 60


def outcome(n: int, verdicts: dict[int, str], issue: dict) -> str:
    if n in verdicts:
        return verdicts[n]
    if issue.get("state") == "closed":
        return "confirmed" if issue.get("state_reason") == "completed" else "dropped"
    return "waiting"


def sessions(records, stops, skips) -> list[dict]:
    """One run per session id: its time span, distinct issues taken and handed back, and its skips."""
    runs = {}
    for kind, items in (("record", records), ("stop", stops), ("skip", skips)):
        for item in items:
            if item.get("session"):
                run = runs.setdefault(item["session"], {"taken": set(), "needs_you": set(), "skipped": 0,
                                                        "times": []})
                if kind in ("record", "stop"):
                    run["taken"].add(item["issue"])
                if kind == "stop":
                    run["needs_you"].add(item["issue"])
                if kind == "skip":
                    run["skipped"] += 1
                if item.get("posted"):
                    run["times"].append(item["posted"])
    out = [{"session": sid, "first": min(r["times"]) if r["times"] else None,
            "last": max(r["times"]) if r["times"] else None, "taken": len(r["taken"]),
            "needs_you": len(r["needs_you"]), "skipped": r["skipped"]} for sid, r in runs.items()]
    return sorted(out, key=lambda r: (r["first"] is None, r["first"] or ""))


def build(records, unreadable, verdicts, issues, stops=(), unreadable_stops=0, skips=(), unreadable_skips=0) -> dict:
    rows = []
    for r in records:
        rows.append({"issue": r["issue"], "title": issues.get(r["issue"], {}).get("title"),
                     "format": "old" if r["v"] == 1 else "v2", "consistent": r["consistent"], "pr": r["pr"],
                     "kind": r["kind"], "coverage": r["coverage"], "rounds": r["rounds"],
                     "applied": r["applied"], "declined": r["declined"], "refix": r["refix"], "end": r["end"],
                     "outcome": outcome(r["issue"], verdicts, issues.get(r["issue"], {})), "escaped": [],
                     "impl": r["impl"], "reviewer": r["reviewer"], "session": r["session"],
                     "t_branch": r["t_branch"], "t_verified": r["t_verified"], "posted": r.get("posted")})
        spec = r.get("spec_check")
        rows[-1].update(spec_items=spec["items"] if spec else None,
                        spec_unmet=spec["missing"] + spec["differs"] if spec else None,
                        spec_declared=spec["declared"] if spec else None,
                        weaker=r["tests"]["weaker"] if r.get("tests") else None)
        lanes = r.get("mutation") or []
        rows[-1].update({k: sum(m[k] for m in lanes) if lanes else None for k in ("mutants", "survived", "added")})
    escaped = Counter()
    for r in records:
        if r["escaped_from"] is not None and r["escaped_as"] in ("declined", "missed"):
            escaped[r["escaped_as"]] += 1
            for row in rows:
                if row["issue"] == r["escaped_from"]:
                    row["escaped"].append(f"#{r['issue']} ({r['escaped_as']})")
    new = [r for r in records if r["v"] == 2]
    counted = [r for r in new if r["consistent"]]
    applied_total = sum(sum(r["applied"]) for r in new)
    checks = [r["spec_check"] for r in records if r.get("spec_check")]
    guarded = [r["tests"] for r in records if r.get("tests")]
    mutated = [m for r in records for m in r.get("mutation") or []]
    both = [r for r in new if r["t_branch"] and r["t_verified"]]
    timed = [r for r in both if _minutes(r["t_branch"], r["t_verified"]) >= 0]
    reported = [r for r in timed if r.get("posted") and _minutes(r["t_verified"], r["posted"]) >= 0]
    summary = {
        "repo_records": len(records), "old_format": sum(r["v"] == 1 for r in records), "unreadable": unreadable,
        "median_rounds": statistics.median(r["rounds"] for r in records),
        "ends": dict(Counter(r["end"] for r in records)),
        "refix_rate": sum(sum(r["refix"]) for r in new) / applied_total if applied_total else None,
        "applied_as": {k: sum(r["applied_as"][k] for r in counted) for k in APPLIED_AS},
        "declined_as": {k: sum(r["declined_as"][k] for r in counted) for k in DECLINED_AS},
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "escaped": {"declined": escaped["declined"], "missed": escaped["missed"]},
        "spec_check": {"records": len(checks),
                       **{k: sum(c[k] for c in checks) for k in ("items", "missing", "differs", "fixed", "declared")},
                       "ends": {e: sum(c["end"] == e for c in checks) for e in SPEC_CHECK_ENDS},
                       "readers": {w: sum(c["reader"] == w for c in checks) for w in SPEC_CHECK_READERS}},
        "mutation": {"records": len(mutated),
                     **{k: sum(m[k] for m in mutated) for k in ("mutants", "killed", "survived", "timeout", "added")},
                     "declined_as": {k: sum(m["declined_as"][k] for m in mutated) for k in MUTATION_DECLINED_AS},
                     "ends": {e: sum(m["end"] == e for m in mutated) for e in MUTATION_ENDS}},
        "tests": {"records": len(guarded), "checked": sum(t["checked"] == "yes" for t in guarded),
                  "not_checked": sum(t["checked"] == "no" for t in guarded),
                  **{k: sum(t[k] for t in guarded) for k in ("weaker", "licensed", "restored")},
                  "stopped": sum(t["end"] == "stopped" for t in guarded)},
        "with_session": sum(r["session"] is not None for r in new),
        "timed": len(timed),
        "median_branch_to_verified": (statistics.median(_minutes(r["t_branch"], r["t_verified"]) for r in timed)
                                      if timed else None),
        "median_verified_to_report": (statistics.median(_minutes(r["t_verified"], r["posted"]) for r in reported)
                                      if reported else None),
        "malformed": sum(bool(r["malformed"]) or (r in both and r not in timed) for r in records),
        "stops": {k: sum(s["reason"] == k for s in stops) for k in STOPS},
        "unreadable_stops": unreadable_stops,
        "skips": {k: sum(s["reason"] == k for s in skips) for k in SKIPS},
        "unreadable_skips": unreadable_skips,
        "sessions": sessions(records, stops, skips),
        "without_session": sum(not x.get("session") for x in (*records, *stops, *skips)),
    }
    return {"rows": rows, "summary": summary}


def _cell(row: dict, column: str) -> str:
    value = row[column]
    if column == "issue":
        return f"#{value}" + ("" if row["consistent"] else "!")
    if isinstance(value, list):
        return ",".join(map(str, value)) if column != "escaped" else ("; ".join(value) or "-")
    return "-" if value is None else str(value)


def _span(first: str | None, last: str | None) -> str:
    """`YYYY-MM-DD HH:MM–HH:MM`, the end date added when it differs; `-` when unknown."""
    if not first or not last:
        return "-"
    start, end = first.replace("Z", "").split("T"), last.replace("Z", "").split("T")
    tail = end[1][:5] if end[0] == start[0] else f"{end[0]} {end[1][:5]}"
    return f"{start[0]} {start[1][:5]}–{tail}"


def render(repo: str, data: dict) -> str:
    s = data["summary"]
    malformed = f", {s['malformed']} with malformed fields" if s["malformed"] else ""
    lines = [f"{repo}: {s['repo_records']} review records ({s['old_format']} old format, "
             f"{s['unreadable']} unreadable skipped{malformed})", ""]
    table = [list(COLUMNS)] + [[_cell(row, c) for c in COLUMNS] for row in data["rows"]]
    widths = [max(len(r[i]) for r in table) for i in range(len(COLUMNS))]
    lines += ["  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in table]
    rate = "-" if s["refix_rate"] is None else f"{s['refix_rate']:.0%}"
    lines += ["",
              f"median rounds: {s['median_rounds']}",
              "ended: " + ", ".join(f"{k} {v}" for k, v in sorted(s["ends"].items())),
              f"refix rate (new records): {rate}",
              "applied by reason: " + ", ".join(f"{k} {v}" for k, v in s["applied_as"].items()),
              "declined by reason: " + ", ".join(f"{k} {v}" for k, v in s["declined_as"].items()),
              "outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(s["outcomes"].items())),
              f"escaped bugs: {s['escaped']['declined']} declined, {s['escaped']['missed']} missed"]
    new = s["repo_records"] - s["old_format"]

    def median(value):
        return "-" if value is None else str(int(value + 0.5))
    lines += [f"phase times: {s['timed']} of {new} new records (median branch→verified "
              f"{median(s['median_branch_to_verified'])} min, verified→report "
              f"{median(s['median_verified_to_report'])} min)",
              f"session ids: {s['with_session']} of {new} new records"]
    counted = ", ".join(f"{k} {v}" for k, v in s["stops"].items() if v) or "none recorded"
    unread = f" ({s['unreadable_stops']} unreadable)" if s["unreadable_stops"] else ""
    lines.append(f"stops: {counted}{unread}")
    counted = ", ".join(f"{k} {v}" for k, v in s["skips"].items() if v) or "none recorded"
    unread = f" ({s['unreadable_skips']} unreadable)" if s["unreadable_skips"] else ""
    lines.append(f"skips: {counted}{unread}")
    if s["sessions"]:
        lines.append(f"sessions: {len(s['sessions'])} with a session id ({s['without_session']} records without one)")
        for run in s["sessions"]:
            lines.append(f"  {run['session'][:8]} {_span(run['first'], run['last'])}  {run['taken']} taken, "
                         f"{run['needs_you']} needs you, {run['skipped']} skipped")
    else:
        lines.append(f"sessions: none recorded ({s['without_session']} records without one)")
    m = s["mutation"]
    if m["records"]:
        pct = f"{m['survived'] / m['mutants']:.0%}" if m["mutants"] else "-"
        lines += [f"mutation: {m['records']} records, {m['mutants']} mutants, {m['survived']} survived ({pct}), "
                  f"{m['added']} killed by added tests",
                  "mutation declined by reason: " + ", ".join(f"{k} {v}" for k, v in m["declined_as"].items()),
                  "mutation ended: " + ", ".join(f"{k} {v}" for k, v in m["ends"].items())]
    else:
        lines.append("mutation: 0 records")
    spec = s["spec_check"]
    if spec["records"]:
        lines += [f"spec check: {spec['records']} records, {spec['items']} items, {spec['missing']} missing, "
                  f"{spec['differs']} differs, {spec['fixed']} fixed, {spec['declared']} declared",
                  "spec check ended: " + ", ".join(f"{k} {v}" for k, v in spec["ends"].items())]
    else:
        lines.append("spec check: 0 records")
    t = s["tests"]
    lines.append(f"tests: {t['checked']} checked, {t['not_checked']} not checked, {t['weaker']} weaker "
                 f"({t['licensed']} licensed, {t['restored']} restored), {t['stopped']} stopped"
                 if t["records"] else "tests: no records")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md)")
    parser.add_argument("--since", type=_date, help="only comments updated on or after this date")
    parser.add_argument("--json", action="store_true", help="print {rows, summary} as JSON")
    args = parser.parse_args(argv)
    try:
        repo = _repo(args.profile)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        records, unreadable, verdicts, issues, stops, unreadable_stops, skips, unreadable_skips = collect(
            repo, args.since)
    except (GhError, json.JSONDecodeError, ValueError) as exc:
        print(f"cannot read {repo}: {exc}", file=sys.stderr)
        return 2
    if not records:
        print(f"0 review records in {repo}" + (f" ({unreadable} unreadable skipped)" if unreadable else ""))
        return 1
    data = build(records, unreadable, verdicts, issues, stops, unreadable_stops, skips, unreadable_skips)
    print(json.dumps(data, indent=2) if args.json else render(repo, data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
