# /gogogo:auto-dev: 6. Merge, by the profile's integration strategy

Part of `/gogogo:auto-dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- The PR's checks, when a merge is a release
- Wait
- Judge
- The link, when a merge is yours
- Verify the merge landed: never trust an exit code alone

Re-run the unattended-mode check immediately before every merge, chained so
the merge is unreachable when it fails. The mode can change mid-session.

**The PR's checks, when a merge is a release** (§Preflight 5). Before the `gh`
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
  that final PR is a release (§Preflight 5), merge it too, with a merge
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
