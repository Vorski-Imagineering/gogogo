---
name: dev
description: Use when asked to fix, build or work one tracker issue given a number or URL — read it, find the real cause, change the code, review, verify on real data, report on the issue and move its card. Also when deciding whether an issue is ready to be worked at all. The unattended loop over a queue is auto-dev, which calls this for each issue.
---

# dev: one issue, end to end

The loop is: **read → triage → locate → change → review → verify → report →
hand back.** Do not skip verify, and do not skip the hand-back: an issue that is
done but still sits in its old column reads as untouched.

`auto-dev` runs this skill unattended over a queue and does not repeat it. When
it does, it says which parts change; everything else here holds.

## First: read this repo's profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for dev --show
```

Exit 0 prints the settings; use them wherever this skill says *the profile*.
Any other exit: **stop and report the line it printed**. Do not guess a
tracker, a test command, an environment or a column.

Then read the profile's sections before touching code: `## Recon traps`,
`## Lane constraints`, and any section it names for reading real state,
verifying, or handing back. The repo's Hard Stop rules are at
`hard_stops.source`. `CLAUDE.md` applies in full; nothing here relaxes it.

Board commands go through the profile's `tracker.tool`, which meets
`references/tracker-contract.md` in this plugin. When `tracker.tool` is
`shared`, the tool is this plugin's own:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py"`. Wherever this skill says
`<tracker.tool>`, run that. Never `gh project item-edit`
by hand: it prints nothing on success and nothing on a write that went
nowhere, and its ids change when the board is edited.

## 1. Read the issue

```bash
gh issue view <n> --repo <tracker.issues_repo> --comments
```

Reporters describe what they *saw*, in their own words. The words in the title
are rarely the string in the codebase.

**Is the report already stale?** The profile's `report.staleness_source` says
how to tell which build a report came from (a commit hash in the body, an
error tracker's release). Check whether that build already contains a fix:
`git merge-base --is-ancestor <commit> origin/<base> && echo "already shipped"`.

When the profile has `observability`, look for an error event behind the report
before reading code. A human writes "it's broken"; the error tracker has the
exception, the stack, and how many people hit it. No event usually means a UX
or data problem, not a thrown error, which itself narrows the search.

## 2. Triage: is this workable at all?

Stop and say so, rather than guessing, when the issue:

- names an **open product decision** nobody has answered;
- needs a **Hard Stop** under the repo's rules with no recorded approval;
- is a feature with no analysis pass. Those need a spec first, via
  `/gogogo:spec`, not an improvised implementation.

**An issue carrying a spec in its body is the ready case.** Its `## Approvals`
table records every decision the user made, and it is what licenses
implementation, including of a Hard Stop when a row names that specific change.

- **The sign-off must be in the body.** A comment does not count, even from the
  repo owner.
- **A row approving one Hard Stop does not license another.** If the work turns
  out to need a Hard Stop the table does not name, treat it as unapproved.
- **An "every item is no" verdict is not a sign-off** for a Hard Stop you then
  discover; it is evidence the spec did not anticipate one. Stop and say so.
- **A two-licence change needs both rows** (the profile's
  `hard_stops.two_licence`): approving the design is not approving applying it
  to a shared environment. With only the design row, build it and stop before
  applying it.

## 3. Locate the real cause: expect data and state, not just code

`rg` for the literal string first. **A miss is information.** Much of what shows
on screen is data: user-editable names and labels, configuration records. A
label the reporter quotes may not exist in the tree at all.

Read a safe copy of real state freely, the way the profile's `state.read` says.
Never write anything the profile's `state.forbidden` lists, and never write to
an environment whose `writes` does not allow it. When the cause turns out to be
data or configuration, say so, and still change what code can: the confusing
presentation, the missing empty state, the jargon where a human word belongs.
"It's just data" does not resolve an issue on its own.

The profile's `## Recon traps` lists what this codebase specifically hides.

## 4. Change

- `CLAUDE.md` is not relaxed because a change is small. Reuse first; follow
  existing patterns.
- **Thread a change through every consumer.** If you change a value, a flag or
  a rule, find every place that reads it and every path that re-renders it. A
  partial thread is the "two things must agree, nothing enforces it" failure.
- **A Hard Stop, or a decision that belongs to a person and is not in the
  issue body, discovered mid-change → stop** and present the repo's proposal
  format. Do not negotiate with yourself about whether it is "small". Hand
  back as *stopped for a person* (§8).
- **Do not commit or push unless asked.** Leave the change in the working tree
  and say which branch it is on. (`auto-dev` overrides this.)

## 5. Review

```
/code-review high
```

Run it on the working tree before reporting anything. Apply findings
deliberately rather than with `--fix`, then **review the corrections**: rounds
of corrections are where defects enter. Render findings as markdown, never raw
JSON. How many rounds depends on what the change is:

- **Code** is any change that is not prose only, including configuration
  inside a Markdown file (a profile's settings block). Review at `high`. Review
  each round's corrections, round after round, until a round applies nothing:
  it found nothing, or every finding was declined with a reason. Nothing merges
  unreviewed. There is no round limit.
- **Prose only** means every changed file is Markdown or plain text and no
  configuration in it changed. Review at `medium`, because prose always has
  another ambiguity to find. **Two rounds at most**: the change, then its
  corrections. After the second round, apply nothing except a correctness fix;
  its other findings are listed in the report as follow-ups. If it found a
  correctness defect, fix it and **stop before merging**: the change goes to a
  person with the fix marked unreviewed, handed back as *stopped for a person*
  (§8). Do not start a third round.
- A change that mixes the two is code.
- Findings you disagree with may be declined, with the reason. Correctness
  findings may not: fix them, or stop and hand back as *stopped for a person*
  (§8).
- When the spec moves content unchanged, findings about that content are not
  part of the move: list them in the report as follow-ups. A correctness
  finding there still means fix or stop.

## 6. Verify: an executed path, not a green suite

Work through the profile's `verify.rungs` in order, in the environments
`verify.agent` names. Each rung sees something the one below it cannot. Two are
always required:

**The new test, seen failing.** The regression test must be watched going red.
Stash the change, run the test, confirm red, restore:

```bash
git stash push -- <changed files>
<the lane's `focused` command for the new test>      # expect FAIL
git stash pop
```

**Never revert with `git checkout -- <file>`.** Until the branch has a commit,
`HEAD` is still the base, so `git checkout` on a tracked file you have been
editing silently discards the whole change. Stash and pop, or copy the file
aside first. After any revert experiment, `grep` for something you wrote to
confirm it survived.

Report how many of the new tests went red. Guards that were already true are
fine; name them as guards. Then run every lane's `run` command that applies.

**The real thing, on real data.** Drive the path the issue describes in the
pre-merge environment and confirm the reported behaviour is gone. Hard-reload
rather than trusting a cached bundle. Read back real content (text, an
attribute, an element's presence), never a screenshot. Close anything you
opened that holds a resource (a room, a camera, a browser left running).

"Done" means an executed path. A green suite alone is "written", not "done".

## 7. Report on the issue

Comment in the reporter's language, not the codebase's:

- **What was happening**: the mechanism, one short paragraph, in their terms.
- **What changed**: user-visible effects, as bullets.
- **How it was verified**: which rungs ran, how many new tests went red, what
  the real run showed.
- **How it was reviewed**: code or prose only (§5), the review level, and the
  number of rounds. Then one line per round: how many findings were applied
  and how many declined, and the most important applied finding in a few words
  (say "correctness" when it was one). End the comment with the record on one
  line, with no spaces inside a value:
  `<!-- gogogo:review pr=<n|none> kind=<code|prose> level=<high|medium> rounds=<n> applied=<a1,a2,…> declined=<d1,d2,…> correctness=<c1,c2,…> stopped=<yes|no> -->`
  `pr` is the pull request the change went through, or `none` when there is
  none yet. `applied`, `declined` and `correctness` have one number per round,
  in order; `correctness` counts the applied findings that were correctness
  defects. `stopped=yes` only when the review stopped the change before merging (§5).
- **Anything they still own**: data, configuration, a decision left open.
- **Where it is now, and only what is true when you post**: in the working
  tree, on a branch, or merged. Name the stage in the repo's words (the
  profile's `stages`), and say when the person who confirms fixes
  (`verify.human`) will be able to see it.

When `tracker.public` is true, the comment is published: no credentials,
internal hostnames, personal data or infrastructure detail.

Write the body to a file and pass `--body-file`; inline `--body` mangles markdown.

## 8. Hand back: move the card as far as the code has got

The card moves to the column of the **stage the code has actually reached**,
and no further. Take the first case that fits:

- **stopped for a person**: a review fix no round has reviewed, a correctness
  finding you could not fix, a decision or Hard Stop found mid-change (§4), a
  gate you could not make pass, or verification that gave up →
  `tracker.columns.needs_human`, whether or not
  the work sits on a branch or PR. The §7 report's first line is
  `**Needs you:**` and one sentence saying what the person must do, followed
  by the branch or PR link: for example, read commit `<sha>` and merge; decide
  `<question>`; read the attempts and re-spec or requeue. When nothing is
  committed (this skill commits only when asked, §4), ask the person whether
  to commit and push the work first, so the card links to something; if they
  decline, say "in the working tree of <path>";
- not committed, or on a branch or PR awaiting review, or stopped at an open
  PR only because the merge is a release or a two-licence apply row is
  missing → `tracker.columns.in_progress`;
- merged → the first of the profile's `stages`, and only after the merge is
  verified (`verify_merged.py`, below).

Nothing sweeps cards out of `tracker.columns.needs_human`, and no run takes an
issue from there: a person moves it on once they have done what it asked, or
starts `/gogogo:dev` on it, which then moves the card as for any issue. Also
remove `tracker.ready_marker` from an issue you move to `needs_human`
(`gh issue edit <n> --repo <tracker.issues_repo> --remove-label "<label>"`):
the ready label means the issue needs nothing from anyone. The person puts it
back when the issue is ready again. In a session with the person present, a
question they answer there is not a stop once the answer is in the issue body (§2: a sign-off in
chat or a comment does not count): record it with `/gogogo:spec`, then carry
on.

```bash
<tracker.tool> move <n> --to "<column>"
```

`<column>` is a role key (`in_progress`, `needs_human`) or a stage column's
name. Pass the role key, not the name, for those two: a `!` in a name, as in
`Human!Help!`, is expanded by an interactive shell inside double quotes.

A zero exit is the confirmation: the tool read the card back. Anything else is
a failed move; say so, do not retry blind.

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

Every issue a `CLOSED` line names, whatever the exit, is reopened
(`gh issue reopen <n> --repo <tracker.issues_repo>`) and confirmed with
`gh issue view <n> --repo <tracker.issues_repo> --json state -q .state`, which
must read `OPEN`. Exit 4 means the merge landed and closed the issue (or
something else did): after the reopen, hand back as merged; when the output
also names a missing `Ships-issue`, also do what exit 3 says (below). Say in
the §7 report that the merge closed the issue and it was reopened. If the
reopen fails, still hand back as merged, with `**Needs you:** reopen #<n>` as
the report's first line.

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

## Do not

- Write to anything `state.forbidden` lists, or to production data.
- Report "fixed" on a green suite alone.
- Commit, push, or open a PR unless asked (outside `auto-dev`).
- Move a card ahead of the code, or to Done.

## Working alongside superpowers

`superpowers:systematic-debugging` fits step 3 and may be used there. Do not use
`superpowers:using-git-worktrees`, `superpowers:subagent-driven-development` or
`superpowers:finishing-a-development-branch` for tracker work: implementation
and integration follow this skill and the repo's merge path. See the profile's
`## superpowers boundary`.

## Claude-specific

- `/code-review high` is Claude Code's review command.
- Browser checks use the `claude-in-chrome` tools; load the ones you need in one
  `ToolSearch` call.
