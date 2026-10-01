---
name: roadmap
description: Use when asked to update, refresh or sync the repo's roadmap document against the tracker, when its status marks look out of date, or when /gogogo:roadmap is invoked. Re-derives every row's mark from the issue's state and board column, fixes the marks and the prose they make false, and commits the document.
---

# Keeping a roadmap document in step with the board

A roadmap document holds tables of work, one row per unit. Each row's `State` cell
starts with a mark (an emoji and a bold state word, or a bare `—`) that says where the
row's issue sits right now. Left alone, the marks drift within days: closed issues keep
reading "approved" or "still open".

**The rule: never set a mark from prose, from memory, or from a merge.** A merge does not
close an issue or move its card. Every mark comes from `roadmap_status.py`, which reads
the issue's state and its card's column from the tracker.

**This skill reads the tracker and never writes to it**: no card move, no label, no
comment. Its one write is the roadmap document.

## First: read this repo's profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for roadmap --show
```

- Exit 0 prints the settings. Use them wherever this skill says *the profile*.
- Any other exit: **stop and report the line it printed.** It names the missing field.
- `roadmap.file` unset: **stop** and say this repo has no roadmap document. Setting it is
  described in `references/profile-schema.md` § Roadmap.

The document is at `roadmap.file`, from the folder holding `.agents/`. It may sit in
another git repo checked out inside this one.

## The legend

The document says what each mark means, in one table whose header is
`| Mark | State | Means | Covers |`. The script holds no mark of its own; it reads this
table on every run. `State` is `**<words>**`, or a bare `—`. `Covers` is a comma list of
board columns (as the profile names them, any case) and these keywords:

| Keyword | Covers |
|---|---|
| `closed` | the issue is closed as completed, or closed with no recorded reason |
| `not planned` | the issue is closed as not planned, or as a duplicate |
| `ready label` | open, and carries the label `tracker.ready_marker` |
| `spec` | open, and its body has a `## Design` heading (what `/gogogo:spec` writes) |
| `by hand` | never derived: a person sets it (for example "blocked") |
| `none` | open, and nothing above applies |

The script refuses the legend (exit 2) unless:

- `closed`, `not planned` and `none` are each covered;
- `tracker.columns.in_progress` and each column in `stages` are each covered;
- no keyword or column is covered by two marks (each exactly once);
- `by hand` is the only entry in its cell;
- every entry is a keyword or a column the profile names.

**How a mark is derived**, first match wins: closed (as not planned or duplicate, else
as completed) before any column; then the card's column, if a mark covers it; then the
ready label; then a Design heading in the body; then `none`. A column no mark covers
(the queue, say) falls through to the steps after it.

**When a row agrees without matching:** a `by hand` mark survives while the derived mark
covers `ready label`, `spec` or `none`, and loses as soon as the card reaches a covered
column or the issue closes. A `spec` mark survives a derived `none`, because a spec may
live in a file rather than the issue body.

A repo starting a legend can begin from this one:

```
| Mark | State | Means | Covers |
|---|---|---|---|
| ⚪ | — | not started | none |
| 🟣 | **spec** | the issue body has a Design section | spec |
| ⛔ | **blocked** | held back; the note names what on | by hand |
| 🔵 | **ready** | carries the ready label | ready label |
| 🟡 | **in progress** | being built | In progress |
| 🟠 | **released** | on its last stage, not yet closed | Released |
| ✅ | **Closed** | closed as completed | closed |
| ⚫ | **dropped** | closed as not planned | not planned |
```

Replace `In progress` with the profile's `tracker.columns.in_progress`, and `Released`
with each column in `stages` (a mark may cover several, comma-separated). To change what
a mark means, edit its `Covers` cell; the script reads it on every run.

## 1. Sync the document's repo first

`D` is the directory holding the document.

```bash
git -C "$D" rev-parse --show-toplevel
git rev-parse --show-toplevel
```

- **They differ: the document is in another repo.** `git -C "$D" fetch`, then
  `git -C "$D" status -sb`. Stop and report if the document has uncommitted changes
  (another session's edit), or the branch has no upstream. If it is behind,
  `git -C "$D" pull --ff-only`; stop and report if that refuses.
- **The same repo:** `git fetch`, then `git status -sb`. The current branch must be
  `integration.base` (or the default branch when it is unset): stop and report if it is
  another branch, or if the document has uncommitted changes. Then `git pull --ff-only`;
  stop and report if that refuses. The run starts from that up-to-date checkout.

## 2. Report

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roadmap_status.py"
```

- Exit 0: report "every mark agrees" and stop.
- Exit 2: **stop and quote its lines.** The profile or the legend needs a person, or the
  tracker could not be read.
- Exit 1: go on.

| Line | What to do |
|---|---|
| `MISMATCH` | step 3 writes the new mark |
| `FIX BY HAND ... does not start with a known mark` | the `State` cell has no mark from the legend; give it one, from the issue if the row names one |
| `FIX BY HAND ... the note does not say on what` | a `by hand` mark with no ` — ` note; find what it waits on and write it, or derive the mark if nothing does |
| `FIX BY HAND ... still says it is open` | the issue is closed but the row's text says otherwise; correct the text (step 3) |

## 3. Write the marks

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roadmap_status.py" --write
```

It replaces only the mark at the start of each mismatched `State` cell. After each `WROTE`
line, read that row's note and correct it from what actually happened:

```bash
gh issue view <n> -R <tracker.issues_repo> --comments
git log origin/<integration.base> --grep "#<n>"
```

(With no `integration.base`, use the default branch.)

## 4. Fix the prose the marks contradict

The paragraphs after each table, blockquotes, and other cells that state something about
the tracker. Fix only what the new state makes false; add no reasoning.

## 5. Rows the script cannot check

Rows that name no issue in `tracker.issues_repo` are counted ("rows name no issue") and
not checked. A `spec` mark there claims a spec exists: check that it does. A `by hand`
mark stays only while its note's blocker is still true. When a row gets its own issue,
put the link in the `Issue` column, or first in the `State` cell when the table has none.

## 6. Rerun until clean

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roadmap_status.py"
```

It must print `0 need attention` and exit 0. Anything else: back to the step its lines
point at.

## 7. Commit

- **Another repo:**
  ```bash
  git -C "$D" add <file>
  git -C "$D" commit -m "roadmap: refresh marks from the tracker (<#n A → B>, ...)"
  git -C "$D" push
  ```
- **The same repo:** from the up-to-date checkout of step 1, carrying the edits,
  `git switch -c roadmap-refresh-<YYYY-MM-DD>`, commit the document there, push the
  branch, and report it for the repo's own integration path (`integration.strategy`).
  This skill never merges into the base itself.

## 8. Report

What moved (`#n A → B`), which prose changed, which rows were left for a person and why,
and the commit or the branch.
