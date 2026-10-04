---
name: roadmap
description: Use when asked to update, refresh or sync the repo's roadmap document against the tracker, when its status marks look out of date, or when /gogogo:roadmap is invoked. Re-derives every row's mark from the issue's state and board column, fixes the marks and the prose they make false, and commits the document, opening a PR for it when the document shares the repo.
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
comment. Its one write is the roadmap document, and, when the document shares the repo,
the refresh branch and the PR that carries it (step 7).

## First: read this repo's profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for roadmap --show
```

- Exit 0 prints the settings. Use them wherever this skill says *the profile*.
- Any other exit: **stop and report the line it printed.** It names the missing field.
- `roadmap.file` unset: **stop** and say this repo has no roadmap document. Setting it is
  described in `references/profile-schema.md` § Roadmap.

Any `warning:` line the check printed goes, verbatim, at the top of your report to the person; if it printed none, the report says so.

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
- `tracker.columns.in_progress`, `tracker.columns.needs_human` and each column
  in `stages` are each covered;
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
| 🆘 | **needs you** | stopped; waiting for a person | Human!Help! |
| 🟢 | **released** | on its last stage, not yet closed | Released |
| ✅ | **Closed** | closed as completed | closed |
| ⚫ | **dropped** | closed as not planned | not planned |
```

Replace `In progress` with the profile's `tracker.columns.in_progress`, `Human!Help!`
with its `tracker.columns.needs_human` (or drop that row when the profile has none), and `Released`
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
- **The same repo:** in order.
  1. `git fetch`. Stop and report if the document has uncommitted changes.
  2. **An earlier refresh still open?**
     ```bash
     gh pr list --state open --limit 100 --json number,headRefName,url \
       --jq '.[] | select(.headRefName | startswith("roadmap-refresh-")) | "#\(.number) \(.headRefName) \(.url)"'
     ```
     Any line printed: **stop and report it** as "merge or close #N first; a new refresh
     cut from `<B>` would conflict with it". The checkout is untouched. A non-zero exit
     is a stop too: report its error, since a list it could not read is not an empty one.
  3. **Cut the refresh branch in a worktree**, from the remote base `B`, so the
     checkout is never switched (other sessions may be working in it):
     ```bash
     git worktree add -b roadmap-refresh-<YYYY-MM-DD-HHMM> <scratch>/roadmap-refresh-<YYYY-MM-DD-HHMM> origin/<B>
     ```
     `<scratch>` is the session's scratch or temp directory (where `roadmap-pr.md` goes).
     `B` is `integration.final_target` when `integration.strategy` is `run-branch-pr`,
     otherwise `integration.base` (or the default branch when it is unset). Stop and
     report if this fails, a branch of that name already existing included (name it).
     `W` is that path joined with the session folder's path relative to the repo root.
     Steps 2 to 7 run with `W` as the working directory, so the script finds the same
     profile there. The worktree is made from `origin/<B>`: it sees the committed
     document, not an edit in the checkout.

**Stopping early (the same repo).** Any stop between the cut and §7's push (step 2's
"every mark agrees", its exit 2, or a stop a later step asks for) ends, when
`git -C <W> status --porcelain -- <file>` and `git -C <W> log --oneline origin/<B>..HEAD`
both print nothing, with these run from the session's own folder, never from inside the
worktree:

```bash
git worktree remove <scratch>/roadmap-refresh-<YYYY-MM-DD-HHMM>
git branch -D roadmap-refresh-<YYYY-MM-DD-HHMM>
```

and the report says the worktree and branch were removed; nothing was pushed, so nothing
is lost. Otherwise (an uncommitted change to the document, or a commit that was not
pushed, as after a refused push in step 7) leave both, and the report names the worktree
path and the branch and says which holds the change. A temp folder the system cleaned
leaves a stale entry; `git worktree prune` clears it.

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
| `FIX BY HAND ... the note does not say on what` | a `by hand` mark with no note: neither ` — <text>` after the mark nor a non-empty `Note` or `Notes` cell (a bare `—` there is not a note); find what it waits on and write it, or derive the mark if nothing does |
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

Then link every issue the document names, not only in the `Issue` column: in `Note` and
`Notes` cells, after a mark, in other cells and in prose. A bare `#<n>` becomes
`[#<n>](https://github.com/<tracker.issues_repo>/issues/<n>)`, and `<owner>/<repo>#<n>`
links to that repo's issue. Leave code spans, fenced blocks and existing links as they
are. One exception: in a table with no `Issue` column, the script reads the first link in
the `State` cell as the row's own issue, so in a row that has none, leave references in
that cell unlinked.

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
- **The same repo:** in `W`, on the refresh branch step 1 cut, in order:
  ```bash
  git add <file>
  git commit -m "roadmap: refresh marks from the tracker (<#n A → B>, ...)"
  git push -u origin roadmap-refresh-<YYYY-MM-DD-HHMM>
  gh pr create --base <B> --head roadmap-refresh-<YYYY-MM-DD-HHMM> \
    --title "roadmap: refresh marks from the tracker" --body-file <scratch>/roadmap-pr.md
  ```
  then, from the session's own folder (never from inside the worktree):
  ```bash
  git worktree remove <scratch>/roadmap-refresh-<YYYY-MM-DD-HHMM>
  git branch -d roadmap-refresh-<YYYY-MM-DD-HHMM>
  ```
  Stop and report at the first command that fails, except the one case below; the
  worktree and branch are kept and named, as in "Stopping early", and a pushed branch is
  a person's to open the PR from. The body file holds step 8's account of what moved,
  which prose changed and which rows were left for a person; the PR's number comes after
  it. When `gh pr create` says a PR already exists for the branch, read it with
  `gh pr list --head roadmap-refresh-<YYYY-MM-DD-HHMM> --json number,url` and carry on.
  The PR is how the refresh lands under every `integration.strategy`; a person merges it
  the way the repo lands PRs. This skill never merges into the base itself.
  `git branch -d` removes only the local copy; the branch stays on origin inside the PR.

## 8. Report

What moved (`#n A → B`), which prose changed, which rows were left for a person and why,
and then: in another repo, the commit; in the same repo, the PR as the thing still to
do, "merge #N to land the refresh" with its URL, and that the checkout was not switched. A kept worktree is named with
its path and branch.
