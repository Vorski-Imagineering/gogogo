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
| a lane's `mutate` | The command that mutation-tests the lines a change made; every mutant its tests miss is killed or accounted for before the merge. |
| `stages` | Where a merged change goes next, and which board column says so. |
| `independence` | Which decisions Claude asks about and which it takes itself: `junior-dev` (default), `tech-lead` or `product-owner`. |

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

**In the checkout, or in a worktree per issue.** The profile's
`integration.workspace` says where the branch goes, and `/gogogo:setup` asks
you, recommending the checkout. With `checkout` (or no setting), the commands
above run in the folder you work in, so the work in progress is where you
look. With `worktree`, each issue gets its own folder beside the main one,
cut from a freshly fetched base, and the main folder never switches branches:

```bash
git fetch origin && git worktree add -b fix/<issue-number>-<short-slug> ../<repo>-wt-<n> origin/<integration.base>
```

That is for several sessions working one repo at once, or a checkout that
something live runs from (a plugin sessions load with `--plugin-dir`, a hook
that runs a file inside it). Setup recommends moving the live thing to an
installed copy first, so the checkout stays possible. Worktree support is in
development. A profile that sets nothing while its `## Lane constraints`
mention a worktree makes dev and auto-dev stop before branching and point at
`/gogogo:setup`.

**Unless the issue already has work.** Before cutting a branch,
`issue_work.py <n>` looks for an open pull request that claims the issue (its branch carries the number, `#<n>` is in its title, or a body line starts with `Refs`, `Fixes`, `Closes` or `Resolves` and names it; a pull request that only mentions it is noted, not continued),
a local or `origin` branch named for it that is ahead of the base, and the
branch its stop-marker comment names. With exactly one, the skills continue on
it instead, updated with `git merge origin/<base>` (never a rebase or a force
push), and reuse its pull request. `/gogogo:dev` asks first; `/gogogo:auto-dev`
continues without asking, and skips an issue with two or more candidates or a
pull request from a fork.

**The name carries the issue number**: `fix/<n>-<slug>`, for a bug or a
feature alike. The number is what ties the branch back to the tracker:

- `stranded_work.py` reports a branch or worktree, local or on `origin`, that
  is ahead of `origin`'s base and names no open issue, or names an open issue
  but has no open pull request and no stop marker naming it (a local branch
  only when it holds work on no remote or sits in a worktree);
- `/gogogo:status` links each branch to its issue by that number;
- `worktree_sweep.py` removes an issue's worktree once its pull request has
  merged or its issue is closed, and keeps any with uncommitted changes or
  commits on no remote; dev runs it after each verified merge, and auto-dev
  at the start of each run;
- `stage_sync.py trailer --branch fix/<n>-<slug>` reads the issue from it.

A branch whose name has no issue number is, to the process, work nobody owns.

**Pushed early.** `/gogogo:auto-dev` pushes the branch as soon as it has its
first commit, so the work survives a run that dies.

**One issue at a time.** The loop does not keep several branches in flight.
It finishes an issue (merged, or stopped and handed back), returns to the base
and cuts the next.

**A checkout of its own.** An unattended run with
`integration.workspace = "checkout"` switches branches in the folder it runs
in. Don't work in that folder while the run goes; give the run a clone of its
own if you need to.

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

`/gogogo:auto-dev` branches, commits, pushes and merges on its own
([§3 to §6](../plugins/gogogo/skills/auto-dev/SKILL.md#3-branch-from-a-fresh-base));
`/gogogo:dev` creates the issue's `fix/<n>-<slug>` branch before its first edit,
and commits, pushes or merges only when asked
([§4](../plugins/gogogo/skills/dev/SKILL.md#4-change),
[§8](../plugins/gogogo/skills/dev/references/hand-back.md#name-the-issue-without-closing-it));
the other skills say in their own text what, if anything, they write.

## Before a PR merges

Every issue goes through the same checks, in this order, before its merge:

1. **Tests.** The new regression test is seen failing first (stash the change,
   run the one test, see red, pop), then every lane in the profile passes.
   Where a lane has a `mutate` command, its mutants on the changed lines are
   then killed by a test or declined with a fixed reason.
2. **Spec check.** Before the review, a reader that has not seen how the
   change was made answers every numbered item of the spec against it
   (`spec_check.py`). A missing piece is built, a difference is matched or,
   when small, declared in the report, and anything larger goes to a person.
3. **Review.** `/code-review`, applying a finding only on evidence, with three
   attempts per finding and two rounds per prose file, and one more for a fix made in the second, until a round applies
   nothing (a person after 13 rounds). See
   [when-is-enough-enough.md](when-is-enough-enough.md).
4. **Verify.** The path the issue describes is run on real data in the
   pre-merge environment. A green suite alone counts as "written", not "done".
5. **Gates.** The profile's `gates.always`, and each `gates.when` whose path
   pattern the change touches.
6. **Unattended mode**, re-checked immediately before every merge and chained
   to it, so the merge cannot run if the check fails.
7. **The PR's CI checks**, when the merge is a release or
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

**Check that it landed.** A merge command's exit code is not proof.
`verify_merged.py` reads the PR's merge commit back from the remote base, and
can also confirm the `Ships-issue` link and that the issue is still open;
nothing is commented and no card moves until it prints `MERGED`. What each
exit means, and what the loop does next, is in
[`/gogogo:auto-dev` § Verify the merge landed](../plugins/gogogo/skills/auto-dev/references/merge.md#verify-the-merge-landed-never-trust-an-exit-code-alone).

**Move the card only as far as the code has got.** A verified merge moves the
card to the first of the profile's `stages`: for example "In Dev" when the base
is served by a dev site, or "Released" when the base is production. Under
`run-branch-pr`, when the loop sees the run's final PR merge, it moves every
card the run landed to the next stage. Any other later stage is reached by a
deploy or a promotion. The issue stays open. No skill that writes code moves a
card to Done: a person confirms the fix, or, where the repo runs
`/gogogo:auto-test`, a PASS moves the card to `auto_test.pass_column` (Done, in
some repos) and closes the issue when `auto_test.pass_closes` is true.

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

The loop stops and asks for the reasons in
[`/gogogo:auto-dev` § Stop the whole run and ask when](../plugins/gogogo/skills/auto-dev/SKILL.md#stop-the-whole-run-and-ask-when),
and before the first issue when its preflight fails, a browser not logged in to the pre-merge environment among them; a missing approval, a failed review or a verification that gave up stops only that issue.

## In this repo

gogogo runs its own process, with `pr-squash` onto `main`
([`.agents/dev-process.md`](../.agents/dev-process.md)):

- **A change to skill behaviour, the profile format or what a script writes**
  (the Hard Stops in [`CLAUDE.md`](../CLAUDE.md)) goes through a PR. Docs and
  evidence are small PRs too: `main` refuses a direct push until its `tests`
  check has passed.
- **CI** (`.github/workflows/tests.yml`) runs the unit tests and the
  project-name grep on every PR and every push to `main`;
  `ci_before_merge` is on.
- **`main` is production.** A merge reaches every adopting repo on its next
  plugin update, so a merge here is always a release.
- **`/gogogo:auto-dev` on this repo** runs the plugin from this checkout, so it
  never switches branches or pulls in that tree. The profile sets
  `integration.workspace = "worktree"` (the owner's choice, 2026-10-03), so
  each issue gets its own worktree, `../gogogo-wt-<n>`, from a freshly fetched
  base.
