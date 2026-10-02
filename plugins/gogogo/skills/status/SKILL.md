---
name: status
description: Use when asked where things stand in this repo — what is in each board column, what is queued, in progress or released, which pull requests are open, and which branches and worktrees hold work. Reads only and changes nothing; it reports positions, not problems.
---

# status: where things stand, on one screen

One read of each source, then one fixed layout, with no verdicts.

## First: read this repo's profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for status --show
```

Exit 0 prints the settings; use them wherever this skill says *the profile*.
Its `profile ok for status: <path>` line names the profile file the report's
`profile:` line shows. Any other exit: **stop and report the line it printed**.
A setting this skill names that the profile does not set is left out of the
report, never printed empty, unless this skill gives a fallback for it.

## It reads only

Status writes nothing: not to the repo, the board, the tracker or a remote. It
does not fetch, move a card, edit an issue, push, switch branches, or clean
anything up. Ahead and behind counts are therefore as last fetched, and the
header says so. A stale number, labelled as stale, is still a position; a
fetch would be a write.

## Positions only

The report gives no verdicts: no "stranded", "stale" or "should", and no
"behind" offered as a problem. It offers no fixes and asks no questions about
fixing. Print large numbers as they are, without explaining them. If the user
asks what to do about something, point them to `/gogogo:wrap-up`,
`/gogogo:setup` or `/gogogo:dev`, and do not do it within status.

## Gather

Run these in this order. Each one that fails prints its own `unreadable` line
in its place in the report, and the others still run.

1. **Header.**
   ```bash
   git rev-parse --show-toplevel        # its basename is <repo>
   git branch --show-current            # empty on a detached HEAD
   git rev-parse --short HEAD
   git status --porcelain               # count the lines
   git for-each-ref --format='%(upstream:short)|%(upstream:track)' refs/heads/<branch>
   git rev-list --left-right --count @{u}...HEAD
   ```
   The `for-each-ref` line gives `<upstream>`. The last command prints
   `<behind> <ahead>`; run it only when the upstream is set and not `[gone]`.
   Otherwise the header ends `· no upstream` (none set), `· <upstream> gone`
   (`[gone]`), or, on a detached HEAD, shows `detached` for the branch and
   ends after the uncommitted count.
2. **Board**, only when `tracker.tool` is `shared`:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" fields
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" list --json
   ```
   `fields` gives the column order; `list --json` gives the cards, each with
   `number`, `title`, `state`, `repo`, `status` and `kind`. If either exits
   non-zero, the BOARD block is one line and prints no counts:
   `BOARD  unreadable: tracker.py exited <n>: <its last stderr line>`.
   An unreadable board is not an empty one. When `tracker.tool` is missing or
   names another tool, the BOARD block is one line:
   `BOARD  not shown: status reads the board only through the shared tracker (tracker.tool = "shared")`.
3. **Pull requests.**
   ```bash
   gh pr list --repo <tracker.code_repo> --state open --json number,title,headRefName,isDraft --limit 100
   ```
   When it returns 100, the limit, there may be more: the `+N more` after the
   list reads `+N or more`.
4. **Branches and worktrees.** The base is `integration.base` when the profile
   sets it; otherwise the branch `git symbolic-ref --short refs/remotes/origin/HEAD`
   names, without `origin/`; otherwise `main`.
   ```bash
   git for-each-ref refs/heads --format='%(refname:short)|%(upstream:short)|%(upstream:track)'
   git rev-list --count <base>..<branch>      # each branch other than the base
   git worktree list --porcelain
   ```
   Keep a branch only when its count is above 0.

## Shape

These rules apply, in order.

- **Columns.** Order and names come from `fields`. Every column is shown, with
  0 where it is empty. Cards with no column are counted as `no status`, after
  the rest.
- **Listed columns.** Cards are listed, not just counted, only in
  `tracker.queue`, `tracker.columns.in_progress`, and each `stages[].column`,
  in that order, each once. A stage column carries its `environment` in
  parentheses when the stage names one. Each list holds at most 10 cards, in
  `list --json` order, then `+N more`. Every other column gets a count only.
- **A card** reads `#<number> <title>`, the title cut to 70 characters. It is
  `<repo>#<number>` when its `repo` is not `tracker.issues_repo` (two repos on
  one board can share a number). It ends with ` (closed)` when its `state`
  is set and not `OPEN` (a merged pull request too). A card with no
  `number` is a draft or deleted content: it reads `(draft) <title>`, with
  no repo and never `(closed)`.
- **A pull request** reads `#<n> <headRefName>`, then ` → <issue>` when the
  branch name carries an issue number (next rule), then ` (draft)` if it is
  one. At most 10, then `+N more`, or `none`.
- **An issue number in a branch name** is a number straight after a `/` and
  followed by a `-` or the end of the name: the first match of
  `/(\d+)(?:-|$)` in the whole name (`fix/6-status` is 6,
  `claude/q3xh50` has none), or else of `^(\d+)-` (`6-status` is 6). It shows
  as `#n [<column>]` when that issue's card is on the board (matched on
  `tracker.issues_repo`), or `#n (not on board)` when it is not. A name with no
  match shows nothing.
- **A branch** reads
  `<name>  <k> ahead  <pushed | <m> unpushed | upstream gone | local only>  <worktree path or ->  <issue, if any>`.
  `pushed` means the upstream is set, not `[gone]`, and the branch is not
  ahead of it; `upstream gone` is a `[gone]` track; `local only` has no
  upstream. Show worktree paths under the home directory as `~/…`.
- **Worktrees** on a detached HEAD are listed under `Worktrees, detached:` with
  their path and short commit. The main worktree is not listed.

## Template

The report follows this layout line for line. A section with nothing to show
prints `none`. `Worktrees, detached:` is left out when there are none.

```
<repo> · <branch> @ <short sha> · <n> uncommitted · <a> ahead / <b> behind <upstream>, as last fetched
profile: <profile path, relative to the repo root>

BOARD  <n> cards
  <column> <count> · <column> <count> · … · no status <count>
  <queue column>:  <card> · <card> · …
  <in-progress column>:  <card> · …
  <stage column> (<environment>):  <card> · …

CODE
  Pull requests:  <pr> · <pr> · …
  Branches ahead of <base>:
    <branch line>
  Worktrees, detached:
    <path> @ <short sha>
```

Print the report once, in one fenced block, with nothing before it. After
it comes only the pointer of *Positions only*, when the user asked what to do.
