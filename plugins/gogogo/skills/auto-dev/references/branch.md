# /gogogo:auto-dev: 3. Branch from a fresh base

Part of `/gogogo:auto-dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

Where the branch goes is the profile's `integration.workspace` (preflight 2
has already stopped a run whose profile leaves it unset while
`## Lane constraints` mention a worktree):

- `checkout`, or absent: here, with the `git switch` commands below.
- `worktree`: in a git worktree of its own, and this folder never switches
  branches or pulls. The main worktree is the first `worktree` entry of
  `git worktree list --porcelain`, and `<path>` is
  `<its parent>/<its folder name>-wt-<issue-number>`, never relative to the
  session's folder. Each `git switch` below has its worktree form beside it.
  Make the worktree from the main worktree; once it exists, do every edit,
  command and test for the issue in `<path>`, and name the path in
  the run report. `/gogogo:dev` §8 removes it after the merge is verified.

First look for the issue's earlier work, from a fresh base:

```bash
git switch <integration.base> && git pull --ff-only
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_work.py" <issue-number>
```

For `worktree`, `git fetch origin` replaces the first line.

`issue_work.py` (after `git fetch origin`, which the pull does) says whether
the issue already has work:

- Exit 0: take the card and branch, below.
- Exactly one `candidate:` line and no `fork PR` line: take the card, below,
  then **continue on it**, without asking. Check it out (`git switch <branch>`,
  or `git switch --track origin/<branch>` when it is only on `origin`; for
  `worktree`, `git worktree add <path> <branch>`, or
  `git worktree add --track -b <branch> <path> origin/<branch>`), then
  `git merge origin/<integration.base>` (in `<path>` for `worktree`), never a
  rebase or a force push.
  Resolve a conflict as a code change. Push to that branch, and merge its
  open PR when it has one rather than opening another. The whole process
  (spec check, review, tests compared, mutation, verify, gates, merge) runs
  on the updated branch, and the run report and the issue's report name the
  branch continued and its PR. A conflict you cannot resolve: hand the card
  back to `tracker.columns.needs_human` as `/gogogo:dev` §8 says, stop
  reason `gate`, the Needs-you line naming the conflicting files.
- Two or more `candidate:` lines, or any `fork PR` line: **skip** the issue
  with the reason `earlier work: <each line, joined by "; ">`, and leave its
  card where it is. Never build a competing version of a contributor's PR.
- Exit 2: **skip** with the reason `could not check for earlier work: <the reason>`.

Then take the card, before any branch exists, so anyone glancing at the board
sees which issue is live and a card another session took since §1 read the
queue is not taken twice:

```bash
<tracker.tool> move <n> --from "<tracker.queue>" --to in_progress
```

- Exit 3: another session took the issue meanwhile. **Skip** it with
  `taken meanwhile: the card is in <column>` (the column the refusal names),
  create no branch, and leave the card where it is: this skip is not handed
  back (§2), and the card in `tracker.columns.in_progress` is the other
  session's take, never this run's. It is not taken again in this run (§4).
- Any other non-zero exit: **skip** the issue with `could not move the
  card: <its message>`, leave the card where it is, and go on.

Then branch, unless you continue on earlier work:

```bash
git switch -c fix/<issue-number>-<short-slug>
```

For `worktree`:

```bash
git fetch origin && git worktree add -b fix/<issue-number>-<short-slug> <path> origin/<integration.base>
```

A `<path>` that already exists (an earlier stopped run, say) is a failed
branch, below: never reuse or delete it.

Always from a fresh base: the previous iteration merged into it, and branching
from a stale one silently reverts that work in the squash. The branch name
carries the issue number, so the work is never stranded.

When branching, or checking out the earlier work, fails, first put the card back with
`<tracker.tool> move <n> --from in_progress --to "<tracker.queue>"`, then
**skip** the issue with `could not branch: <its message>` and go on.

Push the branch as soon as it has its first commit (`git push -u origin
<branch>`), so the work survives a run that dies.
