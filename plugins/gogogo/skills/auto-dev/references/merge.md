# /gogogo:auto-dev: 6. Merge, by the profile's integration strategy

Part of `/gogogo:auto-dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- The PR's checks and the merge procedure
- The link, when a merge is yours
- Verify the merge landed: never trust an exit code alone
- Cards a late-merged run PR carried

**Merging a PR.** For `pr-squash`, and for each issue's PR under
`run-branch-pr`, follow *Merging a PR* in `/gogogo:dev`'s
`references/hand-back.md`: gates, the wait for the PR's checks on **every**
merge, `merge_ready.py`'s verdict, a base that moved, and the merge pinned to
the commit you verified (`--match-head-commit`). Read it in full. In this loop, re-run the unattended-mode check
immediately before its step 7, chained so that merge is unreachable when the
check fails. The mode can change mid-session.

A `ci` or `merge` stop ends that issue only. It is handed back to
`tracker.columns.needs_human` as `/gogogo:dev` §8 says, with the stop reason,
and the run goes on to the next issue. For the run's final PR, see
`run-branch-pr` below.

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
  a PR: `gh pr create --base <run branch>`, then the merge procedure above
  (with `--require-checks`: **zero checks is a failure**, not a pass), with
  the link's body when it applies. At the end, one PR from
  the run branch to `integration.final_target` carries the whole run. When
  that final PR is a release (§Preflight 5), merge it too, with a merge
  commit, once its checks pass (the procedure's steps 4 and 5, with
  `--require-checks`); on a `ci` or `merge` outcome there, the run
  is not cleared to release: stop the whole run and ask, giving
  the outcome's reason, and leave the
  cards where they are. When it is not a release, it waits for a person.
  When the link applies, the final PR's description says it must be merged
  with a merge commit, not squashed: a squash leaves the issue commits out of
  the target's history, and the stage sync then finds no link. The close-run
  report (§9) repeats it.
  When the run does not merge the final PR, its description ends with a
  section *After merging* listing each card it carries by number and title.
  Only when the next stage has no `tag`, the link (`Ships-issue`) applies and
  the PR is to be merged with a merge commit, it also says "move them from
  <run column> to <next column>" (§7), gives for each the command
  `<tracker.tool> move <n> --from "<run column>" --to "<next column>"`, and
  promises "the next `/gogogo:auto-dev` run moves any left". Otherwise it says
  stage sync moves them (a `tag`) or a person moves them by hand, with no
  promise. The close-run report (§9) repeats this list.
- **`pr-squash`**: open the PR; then the merge procedure above, with the
  link's body when it applies.

Never hand-roll a merge around a failed integration step, and never use a
script the profile marks forbidden. A refused merge is a `merge` stop for the
issue, never a reason to try `--admin`, `--auto` or another route.

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
`/gogogo:dev` §8 says; then "cannot tell" stops the whole run, and NOT-MERGED after a merge command
that exited 0 is a `merge` stop for that issue (a merge queue holds it).

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

### Cards a late-merged run PR carried

Preflight 13. A person may merge a run's final PR after the run ended; nothing
else moves its cards then. Do these in order; each stop is silent unless it
says to report. Lines go at the top of the run report. A problem here is
reported and the run goes on.

1. The run column is the `stages` entry a run branch reaches (§7's first
   bullet); the next column is the next `stages` entry's. When that next stage
   has a `tag`, report "stage sync moves these" and stop: stage sync owns
   moves into a tagged stage.
2. `<tracker.tool> list --status "<run column>" --issues-only --open-only --json`.
   No cards: stop, saying nothing.
3. `git fetch origin`, then
   `gh pr list --repo <tracker.code_repo> --base <integration.final_target> --state merged --limit 30 --json number,headRefName,mergeCommit`.
   Keep the PRs whose `headRefName` starts with `integration.base`; other PRs
   into that base are not final PRs. `mergeCommit` is an object: use its
   `oid` (`mergeCommit.oid`) wherever `<mergeCommit>` appears below.
4. For each kept PR, the issues it carried.
   `git rev-list --parents -n 1 <mergeCommit>` must show two parents; else
   report `#<pr>: squash-merged, cards not moved` and skip it. Then
   `git log --format='%(trailers:key=Ships-issue,valueonly)' <mergeCommit>^1..<mergeCommit>`,
   keeping the links to `tracker.issues_repo`. None: report
   `#<pr>: no Ships-issue links, cards not moved`. Never move "everything in
   the column": it can hold cards of a run whose PR is still open.
5. The cards to move are those in the run column whose issue a PR carried,
   except a card also carried by an open run PR (a later run re-landed it):
   find open run PRs with
   `gh pr list --repo <tracker.code_repo> --base <integration.final_target> --state open --json number,headRefName`
   (same prefix test). An open PR has no merge commit, so step 4's read does
   not apply: for each, read its own commits with
   `gh pr view <n> --repo <tracker.code_repo> --json commits -q '.commits[].messageBody'`
   and keep the `Ships-issue:` lines that link to `tracker.issues_repo`. Leave
   and report any card so linked.
   For each such PR run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <pr> <integration.final_target> --repo <tracker.code_repo> --open <tracker.issues_repo>#<n> ...`
   for its cards. Exit 0: `<tracker.tool> move <n> --from "<run column>" --to "<next column>"`
   for each. Any other exit (merge not confirmed, an issue closed): report it
   with the PR and move none of its cards.
6. Report one line per PR: `#<pr> (merged after its run): moved #a, #b to
   <next column>`, plus each card a move refused (exit 3: it left the column
   meanwhile, so it is left alone).
