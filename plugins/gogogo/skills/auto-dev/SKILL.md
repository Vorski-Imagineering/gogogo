---
name: auto-dev
description: Use when asked to work the ready queue autonomously — take each issue in the queue column in turn, branch, build, test, review, verify, merge, move the card, and go on to the next without stopping for approval on each step. Also for a triage-only preview of what such a run would take and skip. For one issue at a time, use dev.
---

# auto-dev: the ready queue, end to end

Takes every issue in the profile's queue column and carries each one as far as
the repo's merge path goes, **one at a time**. The per-issue craft (reading the
report, finding the real cause, verifying, the hand-back comment) is in
**`/gogogo:dev`**. Read it; this skill does not repeat it. What is here is the
loop around it, and the places where running unattended changes what you must
do.

The loop is: **select → triage → branch → change → test → review → verify →
gates → merge → verify the merge → report → next.**

## Triage-only mode

When invoked with `--triage-only` (or asked for a preview), do the preflight
checks that read (not the ones that need a browser or bypass mode), run §1 and
§2, and stop. Report every issue in the queue with **take** or **skip** and the
reason, citing the Approvals row or the missing decision. Create no branch, move
no card, post nothing.

## Before anything: preflight

Read the profile first, as `/gogogo:dev` does:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for auto-dev --show
```

`<tracker.tool>` below means the profile's `tracker.tool`; when that is
`shared`, it is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py"`.

Then confirm all of these before touching an issue. Discovering a gap mid-run
means finished work sits unverified while you go and ask.

1. **The tree is clean.** Uncommitted changes are not yours to commit or
   discard. Stop and ask.
2. **Say which branch the session was on.** Running this skill **is** the
   authorisation for the branch switching it describes; any `CLAUDE.md` rule
   against switching branches still holds for anything outside this loop.
3. **The base is healthy.** Run the profile's lanes that are cheap enough, or
   read the base branch's CI. A red base makes every verdict in the run
   meaningless. An empty CI result is **not** a pass: it means nothing ran.
4. **What a merge deploys.** Read the profile's `stages`. A merge is a release
   when the stage it reaches has an environment whose roles include
   `production`: the first stage for `pr-squash` and `merge-script`; for
   `run-branch-pr`, the stage `integration.final_target` reaches, so only the
   run's final PR is a release. The run still releases, but only issues that
   §4 and §5 did not stop and, for a merge through a PR, whose PR's checks
   cleared §6. Any other issue stays unmerged, on its branch or open PR, and
   the run report says which gate it failed. Say in the run report which
   merges released.
5. **Unattended mode.** Every run that may merge runs this,
   straight-to-production repos included. If the profile sets
   `integration.mode_check`, run it and stop the whole run on a non-zero exit;
   otherwise run the plugin's check:
   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/require_unattended.sh"
   ```
   It fails closed. Do not look for a way around it. On a failure, stop before
   any issue and tell the user to restart the session with
   `claude --permission-mode bypassPermissions`.
6. **The board has the columns this run moves cards into:**
   `<tracker.tool> fields --check` must exit 0, and every column in the
   profile's `stages` and `tracker.columns` must be in its output. A missing
   column would make every hand-back fail after its merge.
7. **A logged-in browser on the pre-merge environment** (`verify.session_url`,
   or the first `verify.agent` environment's `session_url`). A redirect to a
   login page → stop the whole run and ask. Do not decide that other coverage
   stands in for it; that decision belongs to whoever answers. Note which user
   the session is.
8. **Stranded work, reported, not acted on:**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stranded_work.py" --base <integration.base>
   ```
   List what it prints at the top of the run report. Never delete, merge or
   rebase any of it.
9. **The profile's `preflight.extra`**, each as it says. A check that says
   "report only" is reported and never acted on.

## 1. Select the queue

```bash
<tracker.tool> list --status "<tracker.queue>"
```

A non-zero exit is a **stop**, never an empty column: the tool refuses to print
a list it could not reconcile. Work only rows that are issues. Take them in the
order the user gave; absent one, live user-facing bugs first, refactors after,
anything large last so it cannot absorb the run.

## 2. Triage each issue before touching it

Per `/gogogo:dev` §2. An issue is workable here only if every decision it
depends on was made by a person and is **in the body**. Skip and record, never
guess, when it has an open product decision, a Hard Stop no Approvals row
names, or a two-licence change whose apply row is missing (that one is
buildable: build and test it, then stop that issue before applying).

Autonomy is over *approved* work, never over the approval. A skipped issue is a
reported outcome, not a failure. Record which row licensed each Hard Stop you
proceed with, so a reader can check the call.

## 3. Branch from a fresh base

```bash
git switch <integration.base> && git pull --ff-only
git switch -c fix/<issue-number>-<short-slug>
```

Always from a fresh base: the previous iteration merged into it, and branching
from a stale one silently reverts that work in the squash. The branch name
carries the issue number, so the work is never stranded.

Then move the card to `tracker.columns.in_progress`, before the change starts,
so anyone glancing at the board sees which issue is live.

Push the branch as soon as it has its first commit (`git push -u origin
<branch>`), so the work survives a run that dies.

## 4. Change, test, review, verify

`/gogogo:dev` §3–6, with these differences because nobody is watching:

- **Every rung in `verify.rungs` is mandatory** for every issue.
- The regression test must be seen failing, then the whole suite green. Record
  how many new tests went red.
- `/code-review` as `/gogogo:dev` §5 says. **Code**: review each round's
  corrections until a round applies nothing; there is no round limit, so the
  number of rounds never stops the issue. **Prose only**: `medium`, two rounds
  at most.
- **When the review stops an issue** (a correctness finding you cannot fix,
  or, for prose, a correctness defect in the second round, fixed): commit
  everything the change produced, and nothing else, to its branch and push it,
  leave the branch unmerged, hand the card back to
  `tracker.columns.needs_human` as `/gogogo:dev` §8 says (the Needs-you line,
  and the ready label removed), and carry on with the next. The
  commit message
  says each that applies: *unreviewed* for a fix no round has reviewed, and
  *known defect* with the finding for one you could not fix. Name the finding
  in the issue's `/gogogo:dev` §7 report, within its rule for a public
  tracker, and record the stop for the run report.
- A Hard Stop, or a decision that belongs to a person and is not in the body,
  discovered mid-change → stop **that issue**: commit what the change has so
  far, and nothing else, to its branch, marked as stopped and naming the
  question in the commit message within the rule for a public tracker, push it, leave it unmerged, hand the card back to
  `tracker.columns.needs_human` as `/gogogo:dev` §8 says, record it, carry on
  with the next.
- **When verification fails, fix forward, bounded.** Up to three attempts, and
  each must name a hypothesis that differs from the last. If you cannot say what
  is different about an attempt, stop there, whatever budget remains. After the
  bound: commit the attempts, and nothing else, to the branch, marked
  abandoned in the commit message, push it and leave it unmerged. Hand the
  card back to `tracker.columns.needs_human` as `/gogogo:dev` §8 says, with
  what each attempt ruled out in the issue report under the Needs-you line,
  and go on to the next issue. One stubborn issue does not end the run. **An issue abandoned or
  skipped in this run is not taken again in the same run**, even when §1 lists
  it again.
- A change that needs a two-licence apply (for example a migration on a shared
  environment) is applied only with its apply row, by the profile's procedure
  for it, never improvised.
- **In a headless run (for example `claude -p`), never end a turn to wait for
  background work**: ending the turn ends the process, and the work is lost.
  Run verification in the foreground, or poll until it has finished.

## 5. Gates

Run the profile's `gates.always`, and each `gates.when` entry whose pattern the
change touches, before merging. A gate failure is a finding: fix it rather than
raise a budget, or stop the issue and hand its card back to
`tracker.columns.needs_human` as `/gogogo:dev` §8 says.

## 6. Merge, by the profile's integration strategy

Re-run the unattended-mode check immediately before every merge, chained so
the merge is unreachable when it fails. The mode can change mid-session.

**The PR's checks, when a merge is a release** (§Preflight 4). Before the `gh`
merge, two steps. Every re-run in them is `sleep 30; <the same command>`, as
one command.

1. **Wait**, in the foreground (§4): `gh pr checks <pr> --watch --fail-fast`,
   with the longest timeout your tool allows. Then, by what it printed:
   - cut off by the tool's time limit while checks still run: re-run it;
   - `no checks reported` (CI may not have registered yet): re-run it until
     checks appear, for up to three minutes;
   - any other error from `gh` (an HTTP, network or auth message): re-run it,
     at most three times;
   - the watch ended on its own, or a budget above is spent: go on to Judge.
2. **Judge** by each check's state, never by the watch's exit code:
   `gh pr checks <pr> --json name,bucket`. When it exits non-zero with any
   message other than `no checks reported`, re-run it, at most three times.
   - Every check `pass` or `skipping`, and at least one `pass`: passed.
   - `no checks reported`, or every check `skipping`: no CI ran. A failure
     under `run-branch-pr` or when `integration.ci_before_merge` is true;
     otherwise the PR merges on the suite §4 ran.
   - A check in `fail` (a check failed), in `cancel` (a check was
     cancelled), in `pending`
     (CI still running), or `gh` still erroring (the checks cannot be read):
     a failure, for that reason.

A failure stops that issue at its PR, handed back to
`tracker.columns.needs_human` as `/gogogo:dev` §8 says for a gate you could not
make pass. For the run's final PR, see `run-branch-pr` below.

**The link, when a merge is yours.** When you merge with `gh` and the profile
uses the `Ships-issue` link (`/gogogo:dev`'s *When you merge with `gh`*
subsection says when), the squash body ends with the output of the same
command `/gogogo:dev` runs:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stage_sync.py" --profile <profile> trailer \
  --issue <n>[=<reporter-login>] --verify --co-authors-from origin/<base>..HEAD > <scratch>/trailers.txt
```

and the merge is `gh pr merge ... --body-file` with the body built as
`/gogogo:dev` builds it.

- **`merge-script`**: run `integration.command` for this issue. Know what the
  script does and does not check (the profile says); if it does not run the
  suite, §4 was the only thing standing between a broken suite and the base.
- **`run-branch-pr`**: the first issue creates the run branch
  (`integration.base`, dated) from the main line. Each issue merges into it by
  a PR: `gh pr create --base <run branch>`, `gh pr checks --watch`, then
  `gh pr merge --squash --delete-branch`, with the link's body when it
  applies. **Zero checks is a failure**, not a pass. At the end, one PR from
  the run branch to `integration.final_target` carries the whole run. When
  that final PR is a release (§Preflight 4), merge it too, with a merge
  commit, once its checks pass (above); on a failure there (above), the run
  is not cleared to release: stop the whole run and ask, giving
  the Judge step's reason, and leave the
  cards where they are. When it is not a release, it waits for a person.
  When the link applies, the final PR's description says it must be merged
  with a merge commit, not squashed: a squash leaves the issue commits out of
  the target's history, and the stage sync then finds no link. The close-run
  report (§9) repeats it.
- **`pr-squash`**: open the PR; when a merge is a release, wait for its checks
  (above); then squash-merge it, with the link's body when it applies.

Never hand-roll a merge around a failed integration step, and never use a
script the profile marks forbidden.

### Verify the merge landed: never trust an exit code alone

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <pr> <base branch> [--repo <code_repo>]
```

Confirm **MERGED** before commenting on the issue or moving any card. A run
that reports six merges and delivered five is worse than one that stops at the
first failure: the board says done, the branch says otherwise, and nobody looks
again. NOT-MERGED, or "cannot tell", stops the whole run.

When the link was written, add it to the check:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <pr> <base branch> [--repo <code_repo>] --profile <profile> --ships <tracker.issues_repo>#<n>
```

Exit 3
(merged, link missing) does **not** stop the run: hand back as merged, and list
the issue in the between-issues log and the close-run report as one whose card
must be moved by hand when its tag ships.

## 7. Report and hand back

`/gogogo:dev` §7–8. Move the card to the stage the code has **actually**
reached, read from the profile's `stages`:

- merged into a run branch that no site serves → that stage's column;
- merged into the base that an environment serves → that stage's column;
- the next stage (a deploy, a promotion) is someone else's move: the deploy's,
  or a person's. Never move a card there yourself. A stage with a `tag` is
  moved by the repo's stage sync when a matching tag is pushed, never by this
  run.

For `run-branch-pr`: when the run's final PR has **merged** (check its state,
not the merge command's exit), move every card the run landed to the next
stage's column and read the board back. An opened-but-unmerged PR leaves the
cards where they are.

## 8. Between issues

Report before starting the next one, a few lines: issue, what changed, how many
new tests went red, what review found, what the real run showed, the merge
commit, the card's new column. The user is not watching every step; this log is
how they stay able to stop you. Then return to §1: the board may have moved.

When the profile has `notify`, send one short message per change of state (a
skip, an issue started, a merge verified, a retreat, the run closed), only
**after** the thing is true. A failed send never stops the run and is never
silent. Never echo a token.

## 9. Close the run

One report: every issue taken with its outcome and merge commit, every issue
skipped with the reason, anything left half-done with its branch, every card
moved to `tracker.columns.needs_human` with its Needs-you line, the stranded
work from preflight, and anything the profile's `stop.extra` checks raised.

## Stop the whole run and ask when

- the unattended-mode check fails, at the start or before any merge;
- the base is red before you start, or the run branch goes red mid-run, or
  a `run-branch-pr` final PR that is a release fails §6's checks step;
- a merge conflicts, or the merge check says NOT-MERGED or cannot tell;
- a two-licence apply fails or half-applies;
- the same change fails verification after the bound on two issues in a row
  (the environment, not the issues, is the likely cause);
- anything the profile's `stop.extra` names;
- anything wants to touch production data or an environment whose `writes`
  forbids it.

A Hard Stop with no approval stops **that issue**, not the run.

## Working alongside superpowers

Do not use `superpowers:using-git-worktrees`,
`superpowers:subagent-driven-development` or
`superpowers:finishing-a-development-branch` in this loop: branching,
integration and merging follow this skill and the profile. See the profile's
`## superpowers boundary`.

## Claude-specific

- `require_unattended.sh` reads the session transcript for `bypassPermissions`.
- `/code-review high` and the `claude-in-chrome` tools, as in `/gogogo:dev`.
