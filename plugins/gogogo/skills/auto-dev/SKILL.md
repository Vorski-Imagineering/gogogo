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
reason, citing the Approvals row or the missing decision. A card without the
ready label whose spec passed the lint (§1) is `take (no ready label; spec lint
passed; the label would be added)`; one that failed is `skip` with §1's reason.
Create no branch, move no card, add no label, post nothing, send no message.

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
7. **Messages.**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/notify.py" status
   ```
   Exit 0 with `notify: off`: say nothing. Exit 0 otherwise: messages will
   send. Any other exit: put its line once at the top of the run report and
   go on. Messages are a convenience, never a reason to stop.
8. **A logged-in browser on the pre-merge environment** (`verify.session_url`,
   or the first `verify.agent` environment's `session_url`). A redirect to a
   login page → stop the whole run and ask. Do not decide that other coverage
   stands in for it; that decision belongs to whoever answers. Note which user
   the session is.
9. **Stranded work, reported, not acted on:**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stranded_work.py" --base <integration.base>
   ```
   List what it prints at the top of the run report. Never delete, merge or
   rebase any of it.
10. **The profile's `preflight.extra`**, each as it says. A check that says
   "report only" is reported and never acted on.

## 1. Select the queue

```bash
<tracker.tool> list --status "<tracker.queue>" --issues-only --open-only --json
```

A non-zero exit is a **stop**, never an empty column: the tool refuses to print
a list it could not reconcile. Outside triage-only mode, the first time this
list is read successfully in a run, send the *run started* message (§8),
counting every row, labelled or not. Work only rows that are issues. Take them in the
order the user gave; absent one, live user-facing bugs first, refactors after,
anything large last so it cannot absorb the run.

Each row's `labels` decides its path. A row carrying `tracker.ready_marker`
(compared without regard to case) goes on to §2. A row without it was put in
the column without passing through `/gogogo:spec`'s lint, so lint it now:

```bash
gh issue view <n> --repo <tracker.issues_repo> --json body -q .body > <scratch>/issue-<n>-body.md
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_lint.py" <scratch>/issue-<n>-body.md
```

- Exit 0 and a last line `label: apply`: on to §2, marked *label-less, lint
  passed*.
- Exit 1, or a last line `label: withhold (<reason>)`: **skip**, with the
  reason `no ready label; spec lint: <its first error: line, or the withhold
  reason>`. Outside triage-only mode, hand it back as §2's *Hand back a skip*
  says, with reason `lint`.
- Exit 2: **stop the whole run** with the line it printed. Preflight already
  read the profile, so this is the environment, not the issue.

## 2. Triage each issue before touching it

Per `/gogogo:dev` §2. An issue is workable here only if every decision it
depends on was made by a person and is **in the body**. Skip and record, never
guess, when it has an open product decision, a Hard Stop no Approvals row
names, or a two-licence change whose apply row is missing (that one is
buildable: build and test it, then stop that issue before applying).

**Hand back a skip.** Every skip from §1's lint and from this section, outside
triage-only mode, once per issue per run: a later pass that reads the issue
again reports the skip and writes nothing more. Never the *could not add the
ready label* skip below (the tracker failing, not the spec: reported, nothing
written, the card left for the next run), and never a two-licence change whose
apply row is missing, which is built and then stopped (§4), not skipped:

1. Post one comment on the issue:
   `gh issue comment <n> --repo <tracker.issues_repo> --body-file <scratch>/skip-<n>.md`.
   Its first line is `**Needs you:**` and one sentence saying what is missing
   and what the person does next (for example: re-spec with `/gogogo:spec`,
   then put the card back in `<tracker.queue>` with the ready label).
   Directly under it, on its own line:

   `<!-- gogogo:skip v=1 reason=<lint|nospec|decision|hard-stop> session=<id|unknown> -->`

   | reason | when |
   |---|---|
   | `lint` | no ready label, and `spec_lint.py` failed or withheld it (§1) |
   | `nospec` | a feature with no analysis pass (`/gogogo:dev` §2) |
   | `decision` | an open product decision not answered in the body |
   | `hard-stop` | a Hard Stop no Approvals row names |

   No review record and no stop marker on this comment: a skip is not a stop.
   The comment names no hostname.
2. Then remove `tracker.ready_marker` when the issue has it
   (`gh issue edit <n> --repo <tracker.issues_repo> --remove-label "<tracker.ready_marker>"`).
3. Then `<tracker.tool> move <n> --to needs_human` (the role key, so the card
   moves to `tracker.columns.needs_human`). Moving last means a card is never
   there without the comment that says why.

A non-zero exit from any of the three: say so in the next report to the
person, with the command's line, and go on. Do not retry blind.

Autonomy is over *approved* work, never over the approval. A skipped issue is a
reported outcome, not a failure. Record which row licensed each Hard Stop you
proceed with, so a reader can check the call.

**Label what was taken.** For an issue marked *label-less, lint passed* that
§2 takes, outside triage-only mode, before §3 branches: run
`gh issue edit <n> --repo <tracker.issues_repo> --add-label "<tracker.ready_marker>"`,
then read it back with `gh issue view <n> --repo <tracker.issues_repo> --json labels`.
A non-zero exit, or a read-back without the label: **skip** that issue with
`could not add the ready label: <the message>`. Otherwise record *label added
by the run* for §8 and §9.

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
- **Mutation testing** as `/gogogo:dev` §6 says, for every lane with a `mutate`
  command, to its end, in the foreground or polled. When it stops the issue (a
  run that failed twice, or survivors left after the third run): commit
  everything the change produced, and nothing else, to its branch and push it,
  leave it unmerged, hand the card back to `tracker.columns.needs_human` as
  `/gogogo:dev` §8 says with the failed run or the surviving mutants under the
  Needs-you line, record the stop for the run report, and carry on with the
  next.
- **The spec check** as `/gogogo:dev` §5 says, before the review. When it
  stops the issue: commit everything the change produced, and nothing else,
  to its branch and push it, leave it unmerged, hand the card back to
  `tracker.columns.needs_human` as `/gogogo:dev` §8 says with the items left
  under the Needs-you line, record the stop for the run report, and carry on
  with the next.
- Review as `/gogogo:dev` §5 says. The run commits, so each correction
  round's target is the correction commits' range. The number of rounds
  never stops an issue except through §5's own endings.
- **When the review stops an issue** (one of `/gogogo:dev` §5 rule 8's
  endings for a person: `third-attempt`, `reversal`, `unfixable`, `prose` or
  `breaker`): commit
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
- **A weakened test** that `/gogogo:dev` §6 cannot restore within its bound
  stops **that issue**, as for verification that gave up: commit the attempts
  to its branch, marked stopped in the commit message, push it, leave it
  unmerged, hand the card back as `/gogogo:dev` §8 says, and go on.
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
   - otherwise (the checks finished, or one failed and `--fail-fast` ended the
     watch), or once a budget above is spent: go on to Judge.
2. **Judge** by each check's state, never by the watch's exit code:
   `gh pr checks <pr> --json name,bucket`. When it exits non-zero with any
   message other than `no checks reported`, re-run it, at most three times.
   - Every check `pass` or `skipping`, and at least one `pass`: passed.
   - `no checks reported`, or every check `skipping`: no CI ran. A failure
     under `run-branch-pr` or when `integration.ci_before_merge` is true;
     otherwise the PR merges on the suite §4 ran.
   - A check in `fail` (a check failed), in `cancel` (a check was
     cancelled), in `pending` (CI still running), or `gh` still erroring (the
     checks cannot be read): a failure. Name every reason that applies.

A failure stops that issue at its PR, handed back to
`tracker.columns.needs_human` as `/gogogo:dev` §8 says for a gate you could not
make pass, with stop reason `ci`. For the run's final PR, see `run-branch-pr` below.

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
  the Judge step's reasons, and leave the
  cards where they are. When it is not a release, it waits for a person.
  When the link applies, the final PR's description says it must be merged
  with a merge commit, not squashed: a squash leaves the issue commits out of
  the target's history, and the stage sync then finds no link. The close-run
  report (§9) repeats it.
- **`pr-squash`**: open the PR; when a merge is a release, wait for its checks
  (above); then squash-merge it, with the link's body when it applies.

Never hand-roll a merge around a failed integration step, and never use a
script the profile marks forbidden.

Every PR body, commit message and squash body in the run names its issue as
`/gogogo:dev` §8 says (`Refs #<n>`, never a closing keyword), the run's final
PR included, and checks the PR's closing references before `gh pr merge`.

### Verify the merge landed: never trust an exit code alone

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <pr> <base branch> [--repo <code_repo>] --open <tracker.issues_repo>#<n>
```

Confirm **MERGED** before commenting on the issue or moving any card. A run
that reports six merges and delivered five is worse than one that stops at the
first failure: the board says done, the branch says otherwise, and nobody looks
again. Whatever the exit, first reopen every issue a `CLOSED` line names, as
`/gogogo:dev` §8 says; then NOT-MERGED, or "cannot tell", stops the whole run.

When the link was written, add it to the check:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <pr> <base branch> [--repo <code_repo>] --profile <profile> --ships <tracker.issues_repo>#<n> --open <tracker.issues_repo>#<n>
```

Exit 3
(merged, link missing) does **not** stop the run: hand back as merged, and list
the issue in the between-issues log and the close-run report as one whose card
must be moved by hand when its tag ships.

Exit 4 (merged, the issue closed) does **not** stop the run either: hand back
as merged, as `/gogogo:dev` §8 says (with a missing link named too, also as
for exit 3 above), and list the issue in the
between-issues log (§8) and the close-run report as one that was closed and reopened.

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
not the merge command's exit), first check that every issue it landed is still
open, with one `--open` for each, and treat its exits as in *Verify the
merge landed*:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <final pr> <integration.final_target> [--repo <code_repo>] --open <tracker.issues_repo>#<n> ...
```

Then move every card the run landed to the next stage's column and read the
board back. An opened-but-unmerged PR leaves the
cards where they are.

## 8. Between issues

Report before starting the next one, a few lines: issue, what changed, how many
new tests went red, what review found, what the real run showed, the merge
commit, the card's new column, and *label added by the run* when §2 added it. The user is not watching every step; this log is
how they stay able to stop you. Then return to §1: the board may have moved.

Send one short message per change of state, only **after** the thing is true.
Pass the text on stdin through a quoted heredoc, never inside a quoted
argument: titles are user-written, and `$(…)` or a stray `"` in one must stay
text. The heredoc expands nothing, so fill in every value (the hostname from
`hostname`, the counts, the titles) before writing it.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/notify.py" send <<'MSG'
<message>
MSG
```

The script does nothing when the profile's `notify` is off or this machine has
no credentials, so call it the same way in every repo. One plain-text line
each, `<repo>` being the name part of `tracker.code_repo`:

- once preflight has passed and §1 has read the queue: `<repo> auto-dev: run started on <hostname>, <k> issues in "<tracker.queue>"`;
- the first time an issue is skipped in this run, not on later passes: `<repo> #<n> skipped -> <tracker.columns.needs_human>: <reason>` when *Hand back a skip* moved the card, else `<repo> #<n> skipped: <reason>` (the label failure, or a failed move);
- `<repo> #<n> started: <title>`;
- after the issue's merge is verified: `<repo> #<n> merged (<short sha>) -> <column>`;
- `<repo> #<n> needs you -> <tracker.columns.needs_human>: <the Needs-you line>`, for an issue taken and then stopped, never for a triage skip (its skip line says it);
- *run closed*, from §9 only: `<repo> auto-dev: run closed: <a> merged, <b> need you, <c> skipped`, where `<b>` counts issues taken and stopped, and `<c>` the triage skips, each issue once.

A `send` that exits non-zero is a `notify failed: <its line>`, and the run
goes on. Each is given once, in the next report to the person in this session
(a between-issues report, §9's report, or a stop's question), never in a
tracker comment. Never put a token on a command line or in a report.

## 9. Close the run

In a run that tried to send *run started*, first send *run closed* (§8). Then
one report, opening with the notify line preflight item 7 put there, if any:
every issue taken with its outcome and merge commit (and *label added by
the run* for each one §2 labelled), every issue skipped with the reason and its column, anything left half-done with its branch, every other card
moved to `tracker.columns.needs_human` (taken, then stopped) with its Needs-you line, the stranded
work from preflight, anything the profile's `stop.extra` checks raised, and
the `notify failed` lines §8 says are due.

## Stop the whole run and ask when

- the unattended-mode check fails, at the start or before any merge;
- the base is red before you start, or the run branch goes red mid-run, or
  a `run-branch-pr` final PR that is a release fails §6's checks step;
- a merge conflicts, or the merge check says NOT-MERGED or cannot tell (after
  the reopen *Verify the merge landed* asks for);
- a two-licence apply fails or half-applies;
- the same change fails verification after the bound on two issues in a row
  (the environment, not the issues, is the likely cause);
- anything the profile's `stop.extra` names;
- anything wants to touch production data or an environment whose `writes`
  forbids it.

When you stop and ask, also give the `notify failed` lines §8 says are due.

A Hard Stop with no approval stops **that issue**, not the run.

## Working alongside superpowers

Do not use `superpowers:using-git-worktrees`,
`superpowers:subagent-driven-development` or
`superpowers:finishing-a-development-branch` in this loop: branching,
integration and merging follow this skill and the profile. See the profile's
`## superpowers boundary`.

## Claude-specific

- `require_unattended.sh` reads the session transcript for `bypassPermissions`.
- **Launching.** A skill cannot name the session it runs in; only `-n` at
  launch does. Start an unattended run with:
  ```bash
  claude -n "$(basename "$(git rev-parse --show-toplevel)")-autodev" --permission-mode bypassPermissions "/gogogo:auto-dev"
  ```
  The name is what `/resume` and the terminal title show.
- The review command and its level for each coverage, and the
  `claude-in-chrome` tools, as in `/gogogo:dev`'s `## Claude-specific`.
- In the skip marker (§2, *Hand back a skip*), `session` is
  `$CLAUDE_CODE_SESSION_ID`, as in `/gogogo:dev`'s record, and `unknown`
  when it is unset.
