#!/usr/bin/env python3
"""Check an issue body written by spec before it is posted.

    spec_lint.py BODY_FILE [--profile FILE] [--json]
    spec_lint.py - < body.md

It checks what can be checked mechanically: the sections and their order, the
Approvals table, that the Hard-stop verdict agrees with its own answers, that
the human check names real URLs, and that Design and Test cases number their
items (`1.` or `**1.**` at the start of the line) and Files groups its paths,
which `spec_check.py` reads. It cannot judge whether the design is right; the
skill's pre-post check does that.

Output: one `error:` or `warning:` line per finding, then `label: apply` or
`label: withhold (<reason>)`, which is whether the ready label may go on.

Exit codes: 0 no errors, 1 errors found, 2 the profile is missing or unusable.

Standard library only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402

REPORT = "Original report"
SPEC_SECTIONS = [
    "Verify by hand",
    "Approvals",
    "Context",
    "Design",
    "Test cases",
    "Files",
    "Verification",
    "Hard-stop check",
]

# Phrases the skill's red-flag table lists. Each is a warning: a person reads
# the line and decides.
RED_FLAGS = [
    (r"\bchoose between\b", "unresolved fork; ask the user"),
    (r"\beither approach works\b", "unresolved fork; ask the user"),
    (r"\brationale for the (split|choice)\b", "a product decision made on the user's behalf"),
    (r"\badd appropriate tests\b", "name the cases and what each guards"),
    (r"\bshould be straightforward\b", "the code has not been read"),
    (r"\bconsider whether\b", "hands over your uncertainty"),
    (r"\bblocked on user answers\b", "only an external unknown may block; a decision is asked, not listed"),
    (r"\b(verify|check) (that )?it works\b", "name the clicks and what appears"),
]

OPEN_QUESTIONS = re.compile(r"^#{1,6}\s*(open|outstanding|unresolved)\s+questions?\b", re.I)
# A placeholder inside a URL or path ("/holon/<slug>/"). "<the code>" in prose is
# a value the reader gets at runtime, and is fine.
PLACEHOLDER = re.compile(r"(?<=/)<[A-Za-z][A-Za-z0-9 _-]*>")
NUMBERED = re.compile(r"^\s*\*{0,2}\d+[.)]\*{0,2}\s+\S")
VERDICT = re.compile(r"^\**\s*verdict\b", re.I)
ROW = re.compile(r"\brows?\b", re.I)
COVERS_ALL = re.compile(r"\b(both|either|all|each|every|two|three)\b", re.I)
APPROVED = re.compile(r"\bapproved\b", re.I)
AWAITS = re.compile(r"\bproposal\b|\bawaits? approval\b|\bnot approved\b", re.I)
ITEM = re.compile(r"^\*{0,2}(\d+)[.)]\*{0,2}\s+\S")
GROUP = re.compile(r"^(?:-\s+)?\*\*(create|edit|explicitly not in scope)\b[^*]*\*\*:?\s*", re.I)
GROUP_KEYS = {"create": "create", "edit": "edit", "explicitly not in scope": "not_in_scope"}


def norm(text):
    """Lowercase letters and digits only, single-spaced, for loose matching."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def split_sections(body):
    """Return [(title, first_line_number, [lines])] for each ## heading.

    Headings inside code fences or blockquotes are text, not structure; that is
    what lets a quoted report carry its own headings.
    """
    sections, fenced = [], False
    preamble = ("", 1, [])
    current = preamble
    for number, line in enumerate(body.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            current = (line[3:].strip().strip("`"), number, [])
            sections.append(current)
        else:
            current[2].append(line)
    return preamble, sections


def table_rows(lines):
    """Data rows of the first markdown table in lines, as lists of cells."""
    rows = []
    for line in lines:
        text = line.strip()
        if not text.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in text.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else []  # drop the header


def numbered_items(lines):
    """(number written, line) for each item numbered at the first column, outside code fences."""
    items, fenced = [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        match = None if fenced else ITEM.match(line)
        if match:
            items.append((int(match.group(1)), line))
    return items


def file_groups(lines):
    """The non-blank lines under each **Create**, **Edit** and **Explicitly not in scope**
    marker, up to the next marker, keyed create, edit and not_in_scope. The text after
    a marker on its own line is the group's first line."""
    groups, key = {}, None
    for line in lines:
        match = GROUP.match(line)
        if match:
            key = GROUP_KEYS[match.group(1).lower()]
            groups.setdefault(key, [])
            line = line[match.end():]
        if key and line.strip():
            groups[key].append(line)
    return groups


def _numbering(title, lines, what):
    numbers = [n for n, _ in numbered_items(lines)]
    if not numbers:
        return [f"## {title}: no numbered items; number each {what} 1., 2., 3. at the start of a line"]
    if numbers != list(range(1, len(numbers) + 1)):
        return [f"## {title}: items are numbered {', '.join(map(str, numbers))}; number them 1, 2, 3 in "
                "order through the section"]
    return []


def lint(body, settings):
    errors, warnings = [], []
    preamble, sections = split_sections(body)
    titles = [t for t, _, _ in sections]
    by_title = {t: (n, lines) for t, n, lines in reversed(sections)}

    # --- layout -----------------------------------------------------------
    if any(line.strip() for line in preamble[2]):
        errors.append("layout: text before the first ## heading; the body starts with "
                      f"## {REPORT} (or ## {SPEC_SECTIONS[0]} when the issue had no report)")

    if REPORT in titles:
        if titles[0] != REPORT:
            errors.append(f"layout: ## {REPORT} must be the first section")
        _, lines = by_title[REPORT]
        content = [ln for ln in lines if ln.strip()]
        rule_at = next((i for i, ln in enumerate(content) if ln.strip() == "---"), None)
        quoted = content if rule_at is None else content[:rule_at]
        if not quoted:
            errors.append(f"## {REPORT}: empty; quote the reporter's words or drop the section")
        if any(not ln.lstrip().startswith(">") for ln in quoted):
            errors.append(f"## {REPORT}: every line must be a blockquote (prefix each with '> ')")
        if rule_at is None:
            errors.append(f"## {REPORT}: no --- rule between the report and the spec")
    else:
        warnings.append(f"layout: no ## {REPORT}; correct only if the issue body was empty")

    found = [t for t in titles if t in SPEC_SECTIONS]
    for title in SPEC_SECTIONS:
        if title not in found:
            errors.append(f"## {title}: section missing")
    for title in set(found):
        if found.count(title) > 1:
            errors.append(f"## {title}: appears {found.count(title)} times")
    present_in_order = [t for t in SPEC_SECTIONS if t in found]
    if [t for t in dict.fromkeys(found)] != present_in_order:
        errors.append("layout: sections out of order; expected " + " → ".join(SPEC_SECTIONS))
    extra = [t for t in titles if t != REPORT and t not in SPEC_SECTIONS]
    for title in extra:
        warnings.append(f"## {title}: not one of the spec's sections")

    # --- whole-spec phrases (the quoted report is the reporter's, skip it) --
    fenced = False
    for number, line in enumerate(body.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if fenced or line.lstrip().startswith(">"):
            continue
        if OPEN_QUESTIONS.match(line):
            errors.append(f"line {number}: the spec lists open questions; ask them, then record the "
                          "answers in Approvals")
        for pattern, meaning in RED_FLAGS:
            if re.search(pattern, line, re.I):
                warnings.append(f"line {number}: \"{re.search(pattern, line, re.I).group(0)}\": {meaning}")

    # --- Verify by hand ---------------------------------------------------
    if "Verify by hand" in by_title:
        _, lines = by_title["Verify by hand"]
        steps = [ln for ln in lines if NUMBERED.match(ln)]
        if not steps:
            errors.append("## Verify by hand: no numbered steps")
        elif len(steps) > 15:
            warnings.append(f"## Verify by hand: {len(steps)} steps; more than ten usually means "
                            "the issue is too big")
        for line in lines:
            for token in PLACEHOLDER.findall(line):
                errors.append(f"## Verify by hand: placeholder {token}; use a real record and a "
                              "full URL")
        where = settings.get("verify", {}).get("human", "")
        env = profile_check.environment(settings, where) or {}
        base = env.get("url", "")
        text = "\n".join(lines)
        if base.startswith("http") and base.rstrip("/") not in text:
            warnings.append(f"## Verify by hand: no URL under {base} ({where}, where a person "
                            "confirms a fix in this repo)")

    # --- Approvals --------------------------------------------------------
    approvals_text = ""
    if "Approvals" in by_title:
        _, lines = by_title["Approvals"]
        approvals_text = "\n".join(lines)
        header = next((ln for ln in lines if ln.strip().startswith("|")), "")
        columns = norm(header)
        if not all(word in columns for word in ("date", "question", "chosen", "rejected")):
            errors.append("## Approvals: no table with the columns Date | Question put to the "
                          "user | Chosen | Rejected")
        elif not table_rows(lines):
            errors.append("## Approvals: the table has no rows; when nothing needed approval the "
                          "row says \"None — every Hard Stop item is no, implement directly.\"")
        if not re.search(r"^\**\s*not approved\s*:", approvals_text, re.I | re.M):
            errors.append("## Approvals: no closing \"Not approved:\" line (write \"Not approved: "
                          "none\" when there is nothing)")

    # --- numbered items and file groups (what spec_check.py reads) ----------
    if "Design" in by_title:
        errors.extend(_numbering("Design", by_title["Design"][1], "artefact"))
    if "Test cases" in by_title:
        errors.extend(_numbering("Test cases", by_title["Test cases"][1], "case"))
    if "Files" in by_title:
        groups = file_groups(by_title["Files"][1])
        if not any("`" in line for key in ("create", "edit") for line in groups.get(key, [])):
            errors.append("## Files: no **Create** or **Edit** group naming a file in backticks")
        if "not_in_scope" not in groups:
            errors.append("## Files: no **Explicitly not in scope** group")

    # --- Test cases -------------------------------------------------------
    if "Test cases" in by_title:
        _, lines = by_title["Test cases"]
        text = norm("\n".join(lines))
        for lane in settings.get("lanes", []):
            name = lane.get("name", "")
            if name and norm(name) not in text:
                warnings.append(f"## Test cases: lane \"{name}\" has no case and no reason for "
                                "skipping it")

    # --- Hard-stop check --------------------------------------------------
    # Specs answer the items as a table ("| Item | **No.** why |") or as a list
    # ("1. **Item?** No. why"). Both are read; what matters is that every item
    # is answered and the verdict agrees with the answers.
    label = None
    if "Hard-stop check" in by_title:
        _, lines = by_title["Hard-stop check"]
        answers, answered_on = {}, {}
        for item in settings.get("hard_stops", {}).get("items", []):
            wanted = norm(item)
            found = None
            for index, line in enumerate(lines):
                text = line.strip()
                if text.startswith("|"):
                    cells = [c.strip() for c in text.strip("|").split("|")]
                    if wanted in norm(cells[0]):
                        found = (norm(cells[1]).split(" ")[:1] if len(cells) > 1 else [], text)
                        break
                elif wanted in norm(text):
                    # A list item's answer runs on over its wrapped lines.
                    rest = []
                    for more in lines[index + 1:]:
                        if not more.strip() or re.match(r"\s*([-*]|\d+[.)])\s", more) or VERDICT.match(more.strip()):
                            break
                        rest.append(more.strip())
                    whole = " ".join([text, *rest])
                    found = (norm(whole).split(wanted, 1)[1].split()[:3], whole)
                    break
            if found is None:
                errors.append(f"## Hard-stop check: no answer for \"{item}\"")
                continue
            answer = next((w for w in found[0] if w in ("yes", "no")), None)
            if answer is None:
                errors.append(f"## Hard-stop check: \"{item}\" must be answered yes or no")
                continue
            answers[item], answered_on[item] = answer, found[1]

        start = next((i for i, ln in enumerate(lines) if VERDICT.match(ln.strip())), None)
        yes_items = [i for i, a in answers.items() if a == "yes"]
        if start is None:
            errors.append("## Hard-stop check: no \"**Verdict: …**\" line")
        else:
            end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
            verdict = " ".join(lines[start:end])
            said = norm(verdict)
            if not yes_items and answers:
                if "implement directly" in said:
                    pass
                elif AWAITS.search(verdict):
                    errors.append("## Hard-stop check: the verdict calls the spec a proposal, but "
                                  "every item is answered no")
                else:
                    errors.append("## Hard-stop check: every item is answered no, so the verdict "
                                  "says \"implement directly\"")
            for item in yes_items:
                named = len(yes_items) == 1 or COVERS_ALL.search(verdict) or any(
                    word in said.split() for word in norm(item).split() if len(word) > 3)
                if ROW.search(answered_on[item]) or (ROW.search(verdict) and named):
                    continue  # an Approvals row licenses it
                if AWAITS.search(verdict) or AWAITS.search(answered_on[item]):
                    label = "a Hard Stop awaits approval"
                elif APPROVED.search(answered_on[item]) or (APPROVED.search(verdict) and named):
                    warnings.append(f"## Hard-stop check: \"{item}\" is called approved without "
                                    "naming the Approvals row; say which row")
                else:
                    errors.append(f"## Hard-stop check: \"{item}\" is answered yes, but the "
                                  "verdict neither names the Approvals row that approves it nor "
                                  "calls the spec a proposal")

    # --- two-licence changes ----------------------------------------------
    for entry in settings.get("hard_stops", {}).get("two_licence", []):
        change = entry.get("change", "")
        if change and re.search(rf"\b{re.escape(change)}", approvals_text, re.I) \
                and not re.search(r"\bappl(y|ies|ying|ied)\b", approvals_text, re.I):
            warnings.append(f"## Approvals: mentions a {change} but has no row about applying it "
                            f"({entry.get('apply', 'apply')}); the unattended run will build it "
                            "and then stop")

    if re.search(r"external unknown", approvals_text, re.I):
        label = label or "an external unknown is open"
    if errors:
        label = "lint errors"
    return errors, warnings, label


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a spec body before posting.")
    parser.add_argument("body", help="file holding the issue body, or - for stdin")
    parser.add_argument("--profile", help="profile file (default: the nearest one above this folder)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.profile) if args.profile else profile_check.find_profile()
    if not path.is_file():
        print(f"profile: no file at {path}", file=sys.stderr)
        return 2
    try:
        settings, sections = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except profile_check.ProfileError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    problems, _ = profile_check.check(settings, sections, profile_check.SPEC)
    if problems:
        for line in problems:
            print(f"profile error: {line}", file=sys.stderr)
        return 2

    body = sys.stdin.read() if args.body == "-" else Path(args.body).read_text(encoding="utf-8")
    errors, warnings, withheld = lint(body, settings)
    label = f"withhold ({withheld})" if withheld else "apply"
    if args.json:
        json.dump({"errors": errors, "warnings": warnings, "label": label}, sys.stdout, indent=2)
        print()
    else:
        for line in errors:
            print(f"error: {line}")
        for line in warnings:
            print(f"warning: {line}")
        print(f"label: {label}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
