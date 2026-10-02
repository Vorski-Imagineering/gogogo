# Branches, pull requests and merges

How the gogogo skills use git in a repo that adopts them: where a branch is
cut from, what it is called, who commits and pushes, how a change becomes a
pull request and a merge, and how a merge is checked and traced to a release.

The rules here are the same in every repo. What differs is a few settings in
the repo's profile, `.agents/dev-process.md`
([`profile-schema.md`](../plugins/gogogo/references/profile-schema.md)):

| Setting | What it decides |
|---|---|
| `integration.base` | The branch every issue branch is cut from. |
| `integration.strategy` | How a finished issue reaches the base: `pr-squash`, `run-branch-pr` or `merge-script`. |
| `integration.final_target` | For `run-branch-pr`: the branch the run's final PR targets. |
| `integration.command` | For `merge-script`: the repo's own merge command. |
| `integration.ci_before_merge` | Whether CI must pass on each issue's PR before it merges. |
| `integration.mode_check` | A command that proves the session can run without prompts, in place of the plugin's check. |
| `gates.always`, `gates.when` | Checks run before every merge, and extra ones by path. |
| `stages` | Where a merged change goes next, and which board column says so. |

## The shape

```
 main ─────●──────────────────●──────────────────●────────► (integration.base)
            \                / squash            \
             fix/42-empty-state                   fix/57-login-loop ──► …
             (branch → PR → checks → merge → verify → card moves)
```

One issue, one branch, one pull request, one squash commit on the base. The
next issue starts from the base that now holds the previous merge.

## Branches

**Cut from a fresh base, every time.**

```bash
git switch <integration.base> && git pull --ff-only
git switch -c fix/<issue-number>-<short-slug>
```

A branch cut from a stale base silently reverts the previous issue's work when
it is squashed back. `--ff-only` refuses a base that has diverged rather than
merging into it.

**The name carries the issue number**: `fix/<n>-<slug>`, for a bug or a
feature alike. The number is what ties the branch back to the tracker:

- `stranded_work.py` reports a branch or worktree that is ahead of the base,
  holds work on no remote or sits in a worktree, and names no open issue;
- `/gogogo:status` links each branch to its issue by that number;
- `stage_sync.py trailer --branch fix/<n>-<slug>` reads the issue from it.

A branch whose name has no issue number is, to the process, work nobody owns.

**Pushed early.** `/gogogo:auto-dev` pushes the branch as soon as it has its
first commit, so the work survives a run that dies.

**One issue at a time.** The loop does not keep several branches in flight.
It finishes an issue (merged, or stopped and handed back), returns to the base
and cuts the next.

**A checkout of its own.** An unattended run switches branches. Give it a
clone or worktree nobody else is working in, so it never shares a working tree
with a person.

**Branches left behind on purpose.** An issue that stops before its merge
keeps its branch, pushed and unmerged, and its card moves to the
`needs_human` column with a link to it. The last commit message says why:

- *unreviewed*: a fix no review round has looked at;
- *known defect*: a finding that meets `/gogogo:dev` §5's tests 1 to 4 and that the agent could not fix, named;
- *stopped*: a Hard Stop or a missing decision found mid-change, with the
  question;
- *abandoned*: verification failed three times, each attempt on a different
  theory.

No skill deletes, merges or rebases these. A person reads the branch and
decides.

## Who commits, pushes and merges

| Skill | Git |
|---|---|
| `/gogogo:dev` | Changes the working tree only. Commits, pushes or opens a PR only when asked, and says which branch the change is on. |
| `/gogogo:auto-dev` | Branches, commits, pushes, opens PRs and merges. Running it is the authorisation for the branch switching it does; a `CLAUDE.md` rule against switching branches still holds outside the loop. |
| `/gogogo:setup` | Commits its setup changes on the default branch and pushes. If the branch is protected, it opens a PR instead and merges once the user approves. |
| `/gogogo:wrap-up` | Reports uncommitted and unpushed work, stashes, worktrees and stranded branches. Never commits, stashes or pushes to make the tree look clean. |
| `/gogogo:status` | Reads only: no fetch, no switch, no push. |

## Before a PR merges

Every issue goes through the same checks, in this order, before its merge:

1. **Tests.** The new regression test is seen failing first (stash the change,
   run the one test, see red, pop), then every lane in the profile passes.
2. **Review.** `/code-review`, applying a finding only on evidence, with three
   attempts per finding and two rounds per prose file, until a round applies
   nothing (a person after 13 rounds). See
   [when-is-enough-enough.md](when-is-enough-enough.md).
3. **Verify.** The path the issue describes is run on real data in the
   pre-merge environment. A green suite alone counts as "written", not "done".
4. **Gates.** The profile's `gates.always`, and each `gates.when` whose path
   pattern the change touches.
5. **Unattended mode**, re-checked immediately before every merge and chained
   to it, so the merge cannot run if the check fails.
6. **The PR's CI checks**, when the merge is a release or
   `integration.ci_before_merge` is true. The loop watches them, then judges
   each check's state, never the watch command's exit code. Every check
   passing or skipped, with at least one passing, is a pass. A failed,
   cancelled or still-pending check is a failure. No checks at all means
   nothing ran: a failure where CI is required.

A failure at any step stops that issue at its branch or open PR and hands it
back. The loop never hand-rolls a merge around a failed step.

## Three ways to merge

`integration.strategy` picks one.

### `pr-squash`: one PR per issue, squashed into the base

```
fix/42-… ──PR──► main      (squash, branch deleted)
fix/57-… ──PR──► main
```

Open a PR from the issue branch to `integration.base`, wait for its checks
when they are required, then
`gh pr merge <pr> --squash --delete-branch`. Each issue becomes one commit on
the base. gogogo itself uses it.

### `run-branch-pr`: issues collect on a run branch, one PR carries the run

```
fix/42-… ──PR──► run branch (dated) ──┐
fix/57-… ──PR──► run branch (dated) ──┤
                                      └──final PR──► integration.final_target  (merge commit)
```

The run's first issue creates the run branch from the main line, named from
`integration.base` with the date; issue branches are cut from it. Each
issue merges into it by its own PR, squashed and its branch deleted, and **a
PR with zero checks is a failure**, not a pass. At the end, one PR from the run
branch to `integration.final_target` carries the whole run.

- When that final PR is a release, the loop merges it once its checks pass. A
  failure there stops the run and leaves every card where it is.
- When it is not a release, it waits for a person.
- It is merged with a **merge commit, never squashed**: a squash would leave
  the issue commits, and the `Ships-issue` links in them, out of the target's
  history. The PR's description says so.

It suits a repo where a person reviews a whole run as one PR before it
reaches the main line.

### `merge-script`: the repo's own command

The loop runs `integration.command` for the issue. The script owns the merge,
and writes the `Ships-issue` link itself; the skills never write one around
it. If the script does not run the test suite, the loop's own test step was
the only thing between a broken suite and the base, and the profile should
say so.

## The squash commit carries the link

When a skill merges a PR itself with `gh`, and the profile uses the link
(`handback.reporter = "trailer"`, or any stage has a `tag`), the squash
commit's body ends with a `Ships-issue` trailer naming the issue, and the
reporter who should confirm the fix:

```
Show a message when the dashboard is empty (#58)

* show a message when there is nothing yet
* test it

Ships-issue: owner/issues-repo#42 reporter=jdoe
Co-Authored-By: Someone <someone@example.org>
```

The body is the branch's commit subjects, a blank line, and the trailer
paragraph that `stage_sync.py trailer` builds, with nothing after it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stage_sync.py" --profile <profile> trailer \
  --issue <n>[=<reporter>] --verify --co-authors-from origin/<base>..HEAD > trailers.txt
{ git log --reverse --format='* %s' origin/<base>..HEAD; echo; cat trailers.txt; } > squash-body.txt
gh pr merge <pr> --squash --delete-branch --body-file squash-body.txt
```

- Git reads trailers only from the final paragraph, and only when every line
  in it is a trailer. One prose line after it and the link is silently lost,
  so the paragraph is always generated, never typed.
- It is `Ships-issue`, not `Fixes` or `Closes`: those are GitHub's closing
  keywords, and would close the issue at merge, before anyone has seen the fix
  running.

The trailer is how a tag later finds the issues it ships
([stage-sync.md](../plugins/gogogo/references/stage-sync.md)).

## After the merge

**Check that it landed.** A merge command's exit code is not proof:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <pr> <base> [--ships owner/repo#<n>]
```

It asks GitHub for the PR's merge commit and asks git whether the remote base
contains it. It checks the merge commit, not the local branch: after a squash
the branch's own commits are never on the base. Nothing is commented and no
card moves until it prints `MERGED`. `NOT-MERGED`, or "cannot tell", stops the
whole run. Exit 3 means merged but the `Ships-issue` link is missing: the issue
is handed back as merged, and the report says its card must be moved by hand
when its tag ships.

**Move the card only as far as the code has got.** A verified merge moves the
card to the first of the profile's `stages`: for example "In Dev" when the base
is served by a dev site, or "Released" when the base is production. A later
stage is reached by a deploy or a promotion, not by the loop. The issue stays
open, and no skill moves a card to Done: a person confirms the fix.

## Releases and tags

**A merge is a release** when the stage it reaches has an environment with the
`production` role. For `pr-squash` and `merge-script` that is the first stage;
for `run-branch-pr`, the stage `integration.final_target` reaches, so only the
run's final PR is a release. A repo with no `pre-production` environment ships
straight to production: every merge to the base is a release, and the agent
verifies before the merge only.

A release merge goes ahead only when the issue cleared every check above,
including its PR's CI. Anything else stays unmerged at its branch or open PR,
and the run report says which gate it failed.

**Tags.** A repo with a `[release]` table in its profile tags each production
deploy with an annotated `deploy-<build>` tag, the build being the commit count
on the base ([versioning.md](../plugins/gogogo/references/versioning.md)):

- `release.py tag` cuts it after the deploy succeeds, only on a commit that is
  on `origin/<integration.base>`, and never from a shallow clone;
- the tag's message lists the issues shipped since the previous `deploy-*`
  tag, read from the `Ships-issue` trailers;
- the repo's CI runs `stage_sync.py sync` on the tag push, which moves each
  card whose linked commits are all in the tag to the next stage and comments
  where the fix is live.

## What stops the whole run

On the git side, the loop stops and asks when:

- the working tree is not clean before it starts (uncommitted changes are not
  its to commit or discard);
- the base is red before it starts, or the run branch goes red mid-run;
- a merge conflicts;
- the merge check says NOT-MERGED or cannot tell;
- a `run-branch-pr` final PR that is a release fails its checks;
- the unattended-mode check fails, at the start or before any merge.

A missing approval, a failed review or a verification that gave up stops only
that issue: its branch is pushed and left, and the loop goes on to the next.

Stranded work found at the start (branches and worktrees no open issue claims)
is listed at the top of the run report, and never deleted, merged or rebased.

## In this repo

gogogo runs its own process, with `pr-squash` onto `main`
([`.agents/dev-process.md`](../.agents/dev-process.md)):

- **A change to skill behaviour, the profile format or what a script writes**
  (the Hard Stops in [`CLAUDE.md`](../CLAUDE.md)) goes through a PR. Docs and
  evidence are small commits pushed to `main`.
- **CI** (`.github/workflows/tests.yml`) runs the unit tests and the
  project-name grep on every PR and every push to `main`;
  `ci_before_merge` is on.
- **`main` is production.** A merge reaches every adopting repo on its next
  plugin update, so a merge here is always a release.
- **`/gogogo:auto-dev` on this repo** runs the plugin from this checkout, so it
  never switches branches or pulls in that tree. Each issue gets its own
  worktree from a freshly fetched base instead:
  ```bash
  git fetch origin && git worktree add -b fix/<n>-<slug> <path> origin/main
  ```
