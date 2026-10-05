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
report, never printed empty: an unset `tracker.queue` or
`tracker.columns.in_progress` has no line. Where a rule below says what an
unset setting does (`integration.base`, `tracker.tool`,
`stages[].environment`, `independence`), that rule applies instead.

Any `warning:` line the check printed goes, verbatim, at the top of your report to the person; if it printed none, the report says so.

## It reads only

Status writes nothing: not to the repo, the board, the tracker or a remote. It
does not fetch, move a card, edit an issue, push, switch branches, or clean
anything up. Ahead and behind counts are therefore as last fetched, and the
header says so. A stale number, labelled as stale, is still a position; a
fetch would be a write.

## Positions only

The report gives no verdicts: no "stranded", "stale" or "should", and no
"behind" offered as a problem. It offers no fixes and asks no questions about
fixing. The one exception is the BOARD block's pull-request-card line
(*Shape*), which names where the filter is set and that `/gogogo:setup`
archives them. Print large numbers as they are, without explaining them. If the user
asks what to do about something, point them to `/gogogo:wrap-up`,
`/gogogo:setup` or `/gogogo:dev`, and do not do it within status.

## Gather

Run these in this order. Each one that fails prints its own `unreadable` line
in its place in the report, and the others still run.

1. **Header.**
   ```bash
   git rev-parse --show-toplevel        # its basename is <repo>
   git --no-optional-locks status --porcelain=v2 --branch
   ```
   Its `# branch.head` line is `<branch>` (`(detached)` on a detached HEAD,
   printed as is), `# branch.oid` the commit (its first 7 characters),
   `# branch.upstream` `<upstream>`, and `# branch.ab +<a> -<b>` the counts.
   Every line not starting `#` is one uncommitted change. After
   `<n> uncommitted`, the first line ends, by the first case that fits:
   - `(detached)`: nothing more;
   - `branch.ab` present: ` · <a> ahead / <b> behind <upstream>, as last fetched`;
   - `branch.upstream` present without it: ` · <upstream> gone`;
   - neither: ` · no upstream`.

   `--no-optional-locks` keeps `git status` from taking the index lock, which
   would be a write and could block a run working in the same checkout.
2. **Board**, only when `tracker.tool` is `shared`:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" fields
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" list --json
   ```
   `fields` gives the column order; `list --json` gives the cards, each with
   `number`, `title`, `state`, `repo`, `status`, `status_since` (when it
   entered its column), `kind`, `blocked_by` (each blocker with its
   `blocker_state`) and `blocking` (each issue it blocks, with its `state`).
   Only when a card
   is an own-repo pull request (*Shape*), also read the board's URL:
   ```bash
   gh project view <tracker.project_number> --owner <tracker.project_owner> --format json -q .url
   ```
   Its failure prints no `unreadable` line; *Shape* says what replaces the
   URL. If `fields` or `list` exits
   non-zero, the BOARD block is one line and prints no counts:
   `BOARD  unreadable: tracker.py exited <n>: <its last stderr line>`.
   An unreadable board is not an empty one. When `tracker.tool` is missing or
   names another tool, the BOARD block is one line:
   `BOARD  not shown: status reads the board only through the shared tracker (tracker.tool = "shared")`.
   Then, only when `fields` and `list` both exited 0 and the profile has
   `stages`, the shipped fixes since reverted (it reads; without `--apply` it
   writes nothing):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stage_sync.py" reverts
   ```
   Exit 1: its lines are the REVERTED block. Exit 0: no block. Exit 2:
   `REVERTED  unreadable: stage_sync.py exited 2: <its last stderr line>`.
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
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/worktree_sweep.py"
   ```
   Keep a branch only when its count is above 0. `worktree_sweep.py` runs
   without `--apply`, so it removes nothing; show its lines under
   `Worktrees, sweep:`, `remove branch <name>: …` lines (a local branch whose
   merged pull request's head is its tip) included. Its exit 1 means it kept
   a worktree, not that it failed; only exit 2 is an `unreadable` line.

## Shape

These rules apply, in order.

- **Independence.** `<level>` is the profile's `independence`; when the
  profile does not set it, `junior-dev (not set)`. It is printed in both
  places, in exactly that form. This overrides the unset-setting rule in
  *First*: an unset `independence` is never left out.
- **Columns.** Order and names come from `fields`. Every column is shown, with
  0 where it is empty. Cards with no column are counted as `no status`, after
  the rest. Columns and their lists count only cards whose `kind` is not
  `PullRequest` (drafts and unreadable cards are counted as before), and so
  does the `<n>` in `BOARD  <n> cards`.
- **Listed columns.** Cards are listed, not just counted, only in
  `tracker.queue`, `tracker.columns.in_progress`, and each `stages[].column`,
  in that order, each once. A stage column carries its `stages[].environment`
  in parentheses when the stage names one, and then, when any of its open
  cards has a `status_since`, `, oldest <age>`: how long its oldest open card
  has been in the column, as `<d> days`, `<h> hours` or `under an hour`
  (`1 day`, `1 hour`). Each list holds at most 10 cards,
  in `list --json` order, then `+N more`. Every other column gets a count
  only.
- **A card** reads `#<number> <title>`, the title cut to 70 characters. It is
  `<repo>#<number>` when its `repo` is not `tracker.issues_repo` (two repos on
  one board can share a number). It ends with ` (closed)` when its `state`
  is set and not `OPEN`. A card with no
  `number` is a draft or deleted content: it reads `(draft) <title>`, with
  no repo and never `(closed)`.
- **Links between issues.** In every listed column, a card's line then ends
  with ` — blocked by <ref>[, <ref>…]`, one ref per `blocked_by` entry whose
  `blocker_state` is `open`, and then with ` — blocks <ref>[, <ref>…]`, one
  ref per `blocking` entry whose `state` is `OPEN`. A ref is `#n`, or
  `<repo>#n` when its repo is not `tracker.issues_repo`. A card with neither
  ends as before.
- **Pull-request cards.** When any card's `kind` is `PullRequest` and its
  `repo` is `tracker.issues_repo` or `tracker.code_repo` (compared ignoring
  case), the BOARD block ends with one line:
  `<N> pull-request card(s) on the board: set Auto-add to project's filter to is:issue is:open at <workflows URL>; /gogogo:setup archives them.`
  The URL is the board's own, read in Gather step 2 (`/orgs/<owner>/projects/<n>`
  or `/users/<owner>/projects/<n>`), followed by `/workflows`, so it reads
  `…/projects/<n>/workflows`. When that read fails, the line names
  `the board's ⋯ → Workflows` instead.
  No line when there are none.
- **REVERTED** follows the BOARD block, one line per line `reverts` printed,
  as it printed it, against the base as last fetched. It is left out when
  `reverts` found none, and when the board was not read.
- **A pull request** reads `#<n> <headRefName>`, then ` → <issue>` when the
  branch name carries an issue number (next rule), then ` (draft)` if it is
  one. At most 10, then `+N more`, or `none`.
- **An issue number in a branch name** is a number straight after a `/` and
  followed by a `-` or the end of the name: the first match of `/(\d+)(?:-|$)`
  in the whole name (`fix/6-status` is 6, `claude/q3xh50` has none), or else
  of `^(\d+)-` (`6-status` is 6). It shows as `#n [<column>]` (`[no status]`
  for a card with no column) when that issue's card is on the board (matched
  on `tracker.issues_repo`), or `#n (not on board)` when it is not. When the
  board was not read (BOARD is `unreadable` or `not shown`), it is `#n` alone.
  A name with no match shows nothing.
- **A branch** reads
  `<name>  <k> ahead  <pushed | <m> unpushed | upstream gone | local only>  <worktree path or ->  <issue, if any>`.
  `pushed` means the upstream is set, not `[gone]`, and the branch is not
  ahead of it; `upstream gone` is a `[gone]` track; `local only` has no
  upstream. Show worktree paths under the home directory as `~/…`.
- **Worktrees** on a detached HEAD are listed under `Worktrees, detached:` with
  their path and short commit. The main worktree is not listed.

## Template

The report follows this layout line for line. It shows the full case, and
every rule above wins over it where the two differ: for example the first
line's ending (Gather step 1), BOARD as its one line (step 2) and `+N more`.
A section or listed column with nothing to show prints `none`.
`Worktrees, detached:` and `Worktrees, sweep:` are left out when there are none.

```
<repo> · <branch> @ <short sha> · <n> uncommitted · <a> ahead / <b> behind <upstream>, as last fetched
profile: <profile path, relative to the repo root>
independence: <level>

BOARD  <n> cards
  <column> <count> · <column> <count> · … · no status <count>
  <queue column>:  <card> · #11 Go live — blocked by #136 · #136 Refresh the runtime — blocks #11 · …
  <in-progress column>:  <card> · …
  <stage column> (<environment>), oldest <age>:  <card> · …
  <N> pull-request card(s) on the board: set Auto-add to project's filter to is:issue is:open at <workflows URL>; /gogogo:setup archives them.

REVERTED
  #<n>: shipped by <sha7>, reverted by <sha7> (<subject>)

CODE
  Pull requests:  <pr> · <pr> · …
  Branches ahead of <base>:
    <branch line>
  Worktrees, detached:
    <path> @ <short sha>
  Worktrees, sweep:
    <keep | remove> <path> (<branch>): <reason>
```

Print, in this order: the check's `warning:` lines (or the sentence saying
there were none), then one line `**Independence: <level>**`, then the report
once, in one fenced block, with nothing else before it. After
it comes at most one line: the pointer of *Positions only*, naming only the
skill, when the user asked what to do.
