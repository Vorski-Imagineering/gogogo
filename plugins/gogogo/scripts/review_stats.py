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
SPEC_CHECK_COUNTS = ("items", "met", "missing", "differs", "na", "outside", "runs", "fixed", "declared")
AUTO_TEST = re.compile(r"<!-- auto-test v1 (.*?) -->")
APPLIED_AS = ("spec", "regression", "bug", "risk", "added")
DECLINED_AS = ("hypothetical", "style", "settled", "reversal", "beyond", "late")
ENDS = ("clean", "third-attempt", "reversal", "unfixable", "prose", "breaker")
OLD_COVERAGE = {"high": "broad", "medium": "precise", "max": "exhaustive"}
VERDICTS = {"PASS": "pass", "FAIL": "fail", "NEEDS_HUMAN": "needs-human"}
COLUMNS = ("issue", "pr", "kind", "coverage", "rounds", "applied", "declined", "refix", "end", "outcome",
           "escaped", "spec_items", "spec_unmet", "spec_declared")


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


def parse_review(text: str) -> dict | None:
    """The first review record in `text` as a dict, or None when it does not parse."""
    match = REVIEW.search(text)
    fields = _fields(match.group(1)) if match else None
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
                      "escaped_from": None, "escaped_as": None, "impl": None, "reviewer": None}
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
                  "impl": fields["impl"], "reviewer": fields["reviewer"]}
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


def collect(repo: str, since: str | None) -> tuple[list[dict], int, dict[int, str], dict[int, dict]]:
    """(records, unreadable markers, latest auto-test verdict by issue, issue data by number)."""
    url = f"repos/{repo}/issues/comments?per_page=100"
    if since:
        url += f"&since={since}T00:00:00Z"
    pages = json.loads(_gh(["api", "--paginate", "--slurp", url]) or "[]")
    records, unreadable, verdicts = [], 0, {}
    for comment in (c for page in pages for c in page):
        issue = int(str(comment.get("issue_url", "")).rsplit("/", 1)[-1])
        body = comment.get("body") or ""
        spec_marker = SPEC_CHECK.search(body)
        spec_check = parse_spec_check(spec_marker.group(0)) if spec_marker else None
        if spec_marker and spec_check is None:
            unreadable += 1
        read = 0
        for match in REVIEW.finditer(body):
            record = parse_review(match.group(0))
            if record is None:
                unreadable += 1
            else:
                records.append({**record, "issue": issue, "spec_check": spec_check})
                read += 1
        if spec_check is not None and not read:
            unreadable += 1
        for match in AUTO_TEST.finditer(body):
            fields = _fields(match.group(1)) or {}
            if fields.get("verdict") in VERDICTS:
                verdicts[issue] = VERDICTS[fields["verdict"]]
    issues = {}
    for n in dict.fromkeys(r["issue"] for r in records):
        issues[n] = json.loads(_gh(["api", f"repos/{repo}/issues/{n}"]))
    return records, unreadable, verdicts, issues


def outcome(n: int, verdicts: dict[int, str], issue: dict) -> str:
    if n in verdicts:
        return verdicts[n]
    if issue.get("state") == "closed":
        return "confirmed" if issue.get("state_reason") == "completed" else "dropped"
    return "waiting"


def build(records, unreadable, verdicts, issues) -> dict:
    rows = []
    for r in records:
        rows.append({"issue": r["issue"], "title": issues.get(r["issue"], {}).get("title"),
                     "format": "old" if r["v"] == 1 else "v2", "consistent": r["consistent"], "pr": r["pr"],
                     "kind": r["kind"], "coverage": r["coverage"], "rounds": r["rounds"],
                     "applied": r["applied"], "declined": r["declined"], "refix": r["refix"], "end": r["end"],
                     "outcome": outcome(r["issue"], verdicts, issues.get(r["issue"], {})), "escaped": [],
                     "impl": r["impl"], "reviewer": r["reviewer"]})
        spec = r.get("spec_check")
        rows[-1].update(spec_items=spec["items"] if spec else None,
                        spec_unmet=spec["missing"] + spec["differs"] if spec else None,
                        spec_declared=spec["declared"] if spec else None)
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
    }
    return {"rows": rows, "summary": summary}


def _cell(row: dict, column: str) -> str:
    value = row[column]
    if column == "issue":
        return f"#{value}" + ("" if row["consistent"] else "!")
    if isinstance(value, list):
        return ",".join(map(str, value)) if column != "escaped" else ("; ".join(value) or "-")
    return "-" if value is None else str(value)


def render(repo: str, data: dict) -> str:
    s = data["summary"]
    lines = [f"{repo}: {s['repo_records']} review records ({s['old_format']} old format, "
             f"{s['unreadable']} unreadable skipped)", ""]
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
    spec = s["spec_check"]
    if spec["records"]:
        lines += [f"spec check: {spec['records']} records, {spec['items']} items, {spec['missing']} missing, "
                  f"{spec['differs']} differs, {spec['fixed']} fixed, {spec['declared']} declared",
                  "spec check ended: " + ", ".join(f"{k} {v}" for k, v in spec["ends"].items())]
    else:
        lines.append("spec check: 0 records")
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
        records, unreadable, verdicts, issues = collect(repo, args.since)
    except (GhError, json.JSONDecodeError, ValueError) as exc:
        print(f"cannot read {repo}: {exc}", file=sys.stderr)
        return 2
    if not records:
        print(f"0 review records in {repo}" + (f" ({unreadable} unreadable skipped)" if unreadable else ""))
        return 1
    data = build(records, unreadable, verdicts, issues)
    print(json.dumps(data, indent=2) if args.json else render(repo, data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
