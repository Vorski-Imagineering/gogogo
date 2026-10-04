# /gogogo:auto-dev: 6. Merge, by the profile's integration strategy

Part of `/gogogo:auto-dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- The PR's checks and the merge procedure
- The link, when a merge is yours
- Verify the merge landed: never trust an exit code alone

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
