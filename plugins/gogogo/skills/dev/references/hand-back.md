# /gogogo:dev: 8. Hand back: move the card as far as the code has got

Part of `/gogogo:dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- The stop marker
- Name the issue without closing it
- When you merge with `gh`: the squash body carries the link
- Merging a PR: gates, CI, a base that moved, and what each refusal does

The card moves to the column of the **stage the code has actually reached**,
and no further. Take the first case that fits:

- **stopped for a person**: a review that ended for a person (§5 rule 8: a
  defect in a finding's third attempt, a reversal the spec does not settle, a
  finding you could not fix, a defect in the round that reviews a prose file's second-round fix, or the breaker
  at round 13), a spec check that stopped (§5: two parts of the spec
  disagree, a difference that is not small, a piece that could not be built,
  or items left after the third reading), a weakened test the change could
  not pass without (§6), mutation testing that stopped (§6: a run that failed
  twice, or survivors left after the third run), a decision or Hard Stop found
  mid-change (§4), a gate you could not make pass, or verification that gave up →
  `tracker.columns.needs_human`, whether or not
  the work sits on a branch or PR. The §7 report's first line is
  `**Needs you:**` and one sentence saying what the person must do, followed
  by the branch or PR link: for example, read commit `<sha>` and merge; decide
  `<question>`; read the attempts and re-spec or requeue. Directly under that
  line goes the stop marker (below). When nothing is
  committed (this skill commits only when asked, §4), ask the person whether
  to commit and push the work first, so the card links to something; if they
  decline, say "in the working tree of <path>";
- not committed, or on a branch or PR awaiting review, or stopped at an open
  PR only because the merge is a release or a two-licence apply row is
  missing → `tracker.columns.in_progress`;
- merged → the first of the profile's `stages`, and only after the merge is
  verified (`verify_merged.py`, below).

**The stop marker.** Every hand-back to `tracker.columns.needs_human` carries
one, on its own line directly under the `**Needs you:**` line, and no other
report does (the reopen line below is not a stop), except a triage skip from
`/gogogo:auto-dev`, which carries the skip marker instead:

`<!-- gogogo:stop v=1 reason=<hard-stop|decision|spec|review|tests|mutation|verify|gate|ci|merge> session=<id|unknown> -->`

| reason | when |
|---|---|
| `hard-stop` | a Hard Stop found mid-change with no Approvals row (§4) |
| `decision` | a decision of a kind the level asks about that is not in the body (§2, §4), or a comment §2 could not fold |
| `spec` | a fold that failed the lint (§2), or the spec check stopped (§5: two parts of the spec disagree, a difference that is not small, a piece that could not be built, or items left after the third reading) |
| `review` | the review ended for a person (§5 rule 8; the record's `end` says which ending) |
| `tests` | a weakened test the change could not pass without (§6, after the third restore attempt) |
| `mutation` | mutation testing stopped (§6: a run that failed twice, or survivors left after the third run) |
| `verify` | verification gave up (`/gogogo:auto-dev` §4's bound) |
| `gate` | a gate that could not be made to pass (`/gogogo:auto-dev` §5) |
| `ci` | the PR's checks failed or could not be read (*Merging a PR*, below) |
| `merge` | the merge was refused or could not complete: draft, review required, branch rule, merge queue, permission, or the base kept moving (*Merging a PR*, below) |

Nothing sweeps cards out of `tracker.columns.needs_human`, and no run takes an
issue from there: a person moves it on once they have done what it asked, or
starts `/gogogo:dev` on it, which then moves the card as for any issue. Also
remove `tracker.ready_marker` from an issue you move to `needs_human`
(`gh issue edit <n> --repo <tracker.issues_repo> --remove-label "<label>"`):
the ready label means the issue needs nothing from anyone. The person puts it
back when the issue is ready again. In a session with the person present, a
question they answer there is not a stop once the answer is in the issue body (§2: a sign-off in
chat does not count; one in a comment by someone with write access does, once
folded in): record it with `/gogogo:spec`, then carry
on.

```bash
<tracker.tool> move <n> --to "<column>"
```

`<column>` is a role key (`in_progress`, `needs_human`) or a stage column's
name. Pass the role key, not the name, for those two: a `!` in a name, as in
`Human!Help!`, is expanded by an interactive shell inside double quotes.

A zero exit is the confirmation: the tool read the card back. Anything else is
a failed move; say so, do not retry blind.

Exit 4 from the shared tool on a move to `needs_human` means the issue's
newest comment carries no stop marker. When the §7 report was posted and a
later comment came after it, post the `**Needs you:**` line and its stop
marker again as a short comment, then move once more. When the report was
never posted, post it first. Never move the card some other way.

Follow the profile's `handback.reporter`: `trailer` means each merge writes a
`Ships-issue` trailer naming the reporter, and stage sync assigns them when the
card enters a stage with a `tag`; `assign` means assign them now; `none` means
leave assignees alone. Leave the issue **open**, and never move a card to Done
yourself. Close only when asked.

### Name the issue without closing it

A closing keyword (`Fixes`, `Closes`, `Resolves` and their forms) in front of
an issue reference closes the issue when the merge reaches the default branch,
against "leave it open", and the board may then move the card to Done.

- In every pull request title and body, commit message and squash body, name
  the issue as `Refs #<n>` (`Refs <tracker.issues_repo>#<n>` when it differs
  from `tracker.code_repo`). Never put a closing keyword in front of an issue
  reference, and never link the pull request to the issue in its Development
  sidebar.
- Before `gh pr merge`, this must print `[]`:
  ```bash
  gh pr view <pr> [--repo <code_repo>] --json closingIssuesReferences -q '[.closingIssuesReferences[].number]'
  ```
  If it does not, rewrite the body (`gh pr edit <pr> --body-file`) and read it
  again. If it is still not `[]` (a sidebar link), merge anyway: the check
  after the merge reopens the issue.

When you did merge, confirm it landed, and that the issue is still open, before
commenting or moving anything:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <pr> <base branch> [--repo <code_repo>] --open <tracker.issues_repo>#<n>
```

Whatever the exit, reopen every issue a `CLOSED` line names
(`gh issue reopen <n> --repo <tracker.issues_repo>`) and confirm that
`gh issue view <n> --repo <tracker.issues_repo> --json state -q .state` reads
`OPEN`. Exit 4 means the merge landed and the issue was closed: hand back as
merged, and say in the §7 report how it was closed (the `CLOSED` line's own
words) and that it was reopened. If the reopen fails, still hand back as
merged, with `**Needs you:** reopen #<n>` as that report's first line. When the
output also names a missing `Ships-issue`, also do what exit 3 says (below).

Once the merge is confirmed, when the issue's work was in a worktree, remove it
from the main worktree, never from inside the one being removed:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/worktree_sweep.py" --apply --only <that worktree's path>
```

Put the line it prints in the §7 report. It never forces: a worktree with
uncommitted changes or commits on no remote is kept, and the line says why;
its exit 1 then means only that, not a failed merge.

### When you merge with `gh`: the squash body carries the link

Applies when you merge a PR yourself with `gh` (`integration.strategy` is
`pr-squash` or `run-branch-pr`) **and** `handback.reporter` is `trailer` or any
of the profile's `stages` has a `tag`. A `merge-script` repo's script writes
the link itself; never write one around it. Otherwise merge as before.

1. The final paragraph. `<profile>` is the path `profile_check.py` printed;
   `<base>` is the PR's base branch:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stage_sync.py" --profile <profile> trailer \
     --issue <n>[=<reporter-login>] --verify --co-authors-from origin/<base>..HEAD > <scratch>/trailers.txt
   ```
   Add `=<reporter-login>` only when `handback.reporter` is `trailer`: the login
   the profile's sections say how to find, else the issue's author
   (`gh issue view <n> --repo <tracker.issues_repo> --json author -q .author.login`).
   Exit 3: that login cannot be assigned. Run it again without `=<login>`, and
   say in the hand-back that nobody will be asked to confirm automatically.
   Exit 2: do not merge; report it.
2. The body: the branch's commit subjects, a blank line, the trailer file, and
   nothing after it. Git reads trailers only from the final paragraph.
   ```bash
   { git log --reverse --format='* %s' origin/<base>..HEAD; echo; cat <scratch>/trailers.txt; } > <scratch>/squash-body.txt
   gh pr merge <pr> --squash --delete-branch --match-head-commit <verified sha> --body-file <scratch>/squash-body.txt
   ```
3. Verify with `--profile <profile> --ships <tracker.issues_repo>#<n>` added
   to the `verify_merged.py` call, next to its `--open`. Exit 4 is handled as
   above. Exit 3 means the merge landed but the link did not
   survive: hand back as merged, and say in the report that this card will not
   move on its own when its tag ships.

### Merging a PR: gates, CI, a base that moved, and what each refusal does

The one procedure for every merge you make with `gh` (`integration.strategy`
`pr-squash`, and each issue's PR under `run-branch-pr`), in `/gogogo:dev` when
the person asks you to merge and in `/gogogo:auto-dev` §6. A `merge-script`
repo's own command merges instead, and its own checks stand. In order:

1. **Gates.** `gates.always` and each `gates.when` that matches the change
   pass, in dev too.
2. **Record what was verified.** After a fresh `git fetch origin`, the branch
   must contain the base as it is now, which this command checks:
   `git merge-base --is-ancestor origin/<base> HEAD`. When it fails, the base
   moved while the issue was built: do *The base moved*, below, before recording anything. Once it
   holds, with the verification and gates passed: `<verified sha>` =
   `git rev-parse HEAD`, `<verified base>` = `git rev-parse origin/<base>`.
3. **Closing references.** The check under *Name the issue without closing it*.
4. **Wait for the checks, on every PR merge**, in the foreground:
   `gh pr checks <pr> --watch --fail-fast`, with the longest timeout your tool
   allows. Every re-run below is `sleep 30; <the same command>`, as one
   command. By what it printed:
   - cut off by the tool's time limit while checks still run: re-run it;
   - `no checks reported` (CI may not have registered yet): re-run it until
     checks appear, for up to three minutes;
   - any other error from `gh` (an HTTP, network or auth message): re-run it,
     at most three times;
   - otherwise (the checks finished, or one failed and `--fail-fast` ended
     the watch), or once a budget above is spent: go on.
5. **Ask for the verdict.** `git fetch origin`. When `origin/<base>` is not
   `<verified base>`, the base moved: see *The base moved*, below. Otherwise:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/merge_ready.py" <pr> [--repo <code_repo>] [--require-checks]
   ```
   Add `--require-checks` when the merge is a release (a stage whose
   environment has the `production` role), the strategy is `run-branch-pr`, or
   `integration.ci_before_merge` is true: a PR on which no check ran then does
   not merge. Otherwise it merges on the suite you ran. Judge by this line,
   never by the watch's exit code or by `gh`'s wording.
6. **By the outcome** (the word before the colon):
   - exit 2 (the PR could not be read; nothing on stdout, and empty output is
     never `ready`): run it again, up to three times, 10 seconds apart; still 2:
     stop reason `ci`, detail "could not be read";
   - `ready`: the sha after it must be `<verified sha>`. When it is not,
     someone pushed after verification, and those commits are not in your
     checkout. Read the PR's branch name (`gh pr view <pr> --json
     headRefName -q .headRefName`), run `git fetch origin <headRefName>`, and
     merge the pushed commits in with `git merge origin/<headRefName>` (no
     rebase, no force push). Re-run every lane's `run` command and the gates
     (and review, mutation and verification, as *The base moved* does), then
     go back to step 2, which records the local HEAD, now including those
     commits. A conflict you cannot resolve, or work you cannot re-verify, is
     stop reason `merge`, detail "the head changed after verification". When
     it matches, go on to 7;
   - `behind` or `conflict`: *The base moved*, below;
   - `checks-failed`, `checks-pending` (once the wait's budget is spent) or
     `no-checks`: stop reason `ci`;
   - `draft`, `review-required`, `blocked`, `not-open` or `unknown`: stop reason
     `merge`.
7. **Merge only what was checked.** In `/gogogo:auto-dev`, chain the merge to
   the unattended-mode check. When the `Ships-issue` link applies (the
   subsection above), build the squash body from a fresh `origin/<base>` and
   merge with it:
   ```bash
   gh pr merge <pr> --squash --delete-branch --match-head-commit <verified sha> --body-file <scratch>/squash-body.txt
   ```
   When it does not apply, no body file:
   ```bash
   gh pr merge <pr> --squash --delete-branch --match-head-commit <verified sha>
   ```
   Never `--admin`, never `--auto`, never `--disable-auto`, whatever a refusal
   says: they bypass or defer the rules the repo set.
8. **After the command.** A tool call the session refused (a permission check
   such as "Merge Without Review" is a tool result, not an exit code): stop
   reason `merge`; do not try the merge another way. A non-zero exit can still
   follow a merge GitHub made (a local branch that could not be deleted or
   switched), so run `verify_merged.py` as above on any exit. MERGED: carry on
   as merged, and mention the exit in the report. NOT-MERGED: after a non-zero
   exit, stop reason `merge` with `gh`'s message; after exit 0 the merge sits in
   a queue, stop reason `merge`, detail `in the merge queue`. "Cannot tell" is
   not a `merge` stop: it stops the whole run in `/gogogo:auto-dev`.

**The final PR of a `run-branch-pr` run** goes through steps 4 and 5 with
`--require-checks`, `<verified sha>` being its head recorded after its checks
passed, and merges with a merge commit, with no body file:
```bash
gh pr merge <pr> --merge --match-head-commit <verified sha>
```
A refusal, a refused tool call or a queue is read as step 8 reads it, but here
it stops the whole run, not one issue.

**The base moved** (`behind`, `conflict`, or `origin/<base>` is not
`<verified base>`). Merge `origin/<base>` into the branch (`git merge
origin/<base>`: no rebase, no force push), resolving a conflict as a code
change, and push. Re-run every lane's `run` command and the gates. When
`git diff --name-only <verified base> origin/<base>` shares a path with the
files this issue changed (`git diff --name-only <verified base>...HEAD`, read
before the update), also run review, mutation and verification again. Then go
back to step 2. At most 3 updates per issue: a fourth, or a conflict you
cannot resolve, is stop reason `merge` (detail: the base keeps moving, or the
conflicting files).

**A `merge` or `ci` stop** hands the card to `tracker.columns.needs_human` as
above: the `**Needs you:**` line names the PR link and the outcome (the
refusal, or the checks). In `/gogogo:auto-dev` the run goes on with the next
issue. In interactive `/gogogo:dev`, a refused tool call's line says: merge the
PR yourself, or run `/gogogo:auto-dev` in bypass mode.
