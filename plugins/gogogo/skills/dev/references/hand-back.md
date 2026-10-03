# /gogogo:dev: 8. Hand back: move the card as far as the code has got

Part of `/gogogo:dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- The stop marker
- Name the issue without closing it
- When you merge with `gh`: the squash body carries the link

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

`<!-- gogogo:stop v=1 reason=<hard-stop|decision|spec|review|tests|mutation|verify|gate|ci> session=<id|unknown> -->`

| reason | when |
|---|---|
| `hard-stop` | a Hard Stop found mid-change with no Approvals row (§4) |
| `decision` | a decision that belongs to a person and is not in the body (§4), or a comment §2 could not fold |
| `spec` | a fold that failed the lint (§2), or the spec check stopped (§5: two parts of the spec disagree, a difference that is not small, a piece that could not be built, or items left after the third reading) |
| `review` | the review ended for a person (§5 rule 8; the record's `end` says which ending) |
| `tests` | a weakened test the change could not pass without (§6, after the third restore attempt) |
| `mutation` | mutation testing stopped (§6: a run that failed twice, or survivors left after the third run) |
| `verify` | verification gave up (`/gogogo:auto-dev` §4's bound) |
| `gate` | a gate that could not be made to pass (`/gogogo:auto-dev` §5) |
| `ci` | the PR's checks failed or could not be read (`/gogogo:auto-dev` §6, *Judge*) |

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
   gh pr merge <pr> --squash --delete-branch --body-file <scratch>/squash-body.txt
   ```
3. Verify with `--profile <profile> --ships <tracker.issues_repo>#<n>` added
   to the `verify_merged.py` call, next to its `--open`. Exit 4 is handled as
   above. Exit 3 means the merge landed but the link did not
   survive: hand back as merged, and say in the report that this card will not
   move on its own when its tag ships.
