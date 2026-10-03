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

- **Put the work on the issue's branch, before the first edit.** The default
  branch is `integration.base` when the profile sets it, else
  `gh repo view <tracker.code_repo> --json defaultBranchRef -q .defaultBranchRef.name`.
  When `git branch --show-current` prints that name, run
  `git switch -c fix/<issue-number>-<short-slug>` (the slug: two to five
  lowercase words from the issue's title, joined by `-`, letters and digits
  only). Uncommitted changes come along; never stash, reset or pull to do it.
  On any other branch, or a detached HEAD, stay where you are and say so.
  When that name already exists, stop and ask which branch to use; never
  reuse or reset it. When the profile's `## Lane constraints` say where to
  branch (a worktree, say), do that instead. When the default branch can't be
  read, create nothing and say why.
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

Review the change before reporting anything, with the review command named in
`## Claude-specific`. Apply findings deliberately, one at a time, never with
the review command's own fix option, and render them as markdown, never raw
JSON. Nothing merges unreviewed. Configuration inside a Markdown file (a
profile's settings block) is code, not prose.

**First, the change against its spec.** Before round 1, every numbered item of
the issue's spec is answered against the change, so a piece never built, or
built another way than the spec says, is found before the review reads the
change for bugs. In order:

- **List the items.** Save the issue body to a file and run
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_check.py" items <body file> --base origin/<base>
  ```
  from the change's working tree, where `<base>` is the branch the change
  merges into (`integration.base`, or the repo's default branch when the
  profile has none); `git fetch origin` first, so files other changes already
  merged are not counted as this change's. Exit 1 means the body has no spec:
  skip the rest of this step, and say so in §7. An `unlisted:` line names a
  section the check could not list item by item; say so in §7.
- **A reader answers them.** Give a reader that has not seen how the change
  was made three things and nothing else: where the spec is (the issue
  number), the item list, and the change (the working tree and its difference
  from `<base>`). It writes one line per `V`, `A`, `D`, `T` and `N` item to an
  answers file, as `<id> | <status> | <evidence> | <note>`, and edits nothing.
  It is told:
  - `met`: the change does what the item says. Evidence is where: a file
    (`path`), a file and one line (`path:line`, a single line number, never
    a range), or a file and the test's name (`path::name`); several are
    separated by `, `. Paths are relative to the working tree.
  - `missing`: nothing in the change does it. `differs`: the change does it
    another way than the item says; the note gives the spec's words and what
    the change has.
  - `na`: only for what cannot be seen in the change (a run in a lane no test
    reaches, another repo), with the reason.
  - `met` and `differs` on a `D`, `T` or `A` item always have evidence. An
    `A` row whose Chosen is carried out on the tracker, not in the change
    (a comment on another issue, an issue body left alone), is `na`, with
    that as its reason.
  - An item holding several exact rules takes the worst status among them,
    and the note names each part that is not met.
  - A `V` step is `met` when the change makes what the step says you will see
    true. A `T` case is `met` only when a test exists and asserts what the
    case says. An `A` row is `met` when the change does what was Chosen and
    nothing that was Rejected. An `N` item is `met` when the change leaves it
    alone.
  - It does not judge quality, look for bugs or propose changes.

  When no such reader can be started, answer the list yourself and record
  `reader=self`.
- **Check the answers.** Run `spec_check.py verify <body file> <answers file>
  --base origin/<base>`. On exit 2, give the reader the `error:` lines and have it
  answer again.
- **Handle what is not `met`**, each by the first case that fits:
  - two parts of the spec disagree, so that meeting one item breaks another →
    the issue stops for a person (§8);
  - `missing` → build it. An `F:` item that is `missing` → make the change the
    spec lists for that file;
  - `differs` → change it to match the spec;
  - `differs`, and matching the spec is not possible or would be wrong, and
    the difference is small (it touches no Hard Stop item, adds no
    user-visible behaviour, setting or message the spec does not have, and
    stays inside the files the spec lists) → keep it and declare it in §7;
  - any other `differs`, and a `missing` item that cannot be built → the
    issue stops for a person (§8);
  - an `outside` file → take it out of the change, or keep it when a spec
    item cannot be met without it and declare it in §7 with that item;
  - `na` → listed in §7.
- **A misreading.** An answer you believe is a misreading: give the reader the
  file and line for that item and ask once more. Its second answer stands.
- **Again, at most three times.** After changing anything, have the reader
  answer the items that were not `met` again, replacing their lines in the
  answers file and keeping the rest, and run `verify` again. At most
  three reader runs. An item still `missing`, or `differs` and not declared,
  after the third → the issue stops for a person (§8).
- **Then round 1 starts.** What this step changed is part of the change the
  review reads. The spec check is not run again after the review.

Then the review, by these rules:

1. **A round.** Round 1 reviews the whole change against the issue's spec, at
   the profile's `review.coverage` (`broad` when unset); a change whose files
   are all prose is reviewed at `precise`. Every later round reviews only what
   the previous round's corrections changed, at `precise`: in a run that
   commits, the correction commits' range; otherwise name the changed files
   and what each correction changed. Every round, tell the review where the
   spec is (the issue number) and to report only where the change fails the
   spec or a rule in `CLAUDE.md`, breaks something that worked, or has a bug
   with a concrete triggering case. From round 2, also give it the findings
   already declined, one line each, and tell it not to raise them again.
2. **Which findings are applied.** Take the first test a finding meets. A
   reviewer's own label ("correctness", a severity) does not change which
   test that is.

   | # | The finding shows | What happens | Recorded as |
   |---|---|---|---|
   | 1 | the change fails the spec or a rule in `CLAUDE.md` | applied | `spec` |
   | 2 | the change breaks something that worked before it | applied, with the case | `regression` |
   | 3 | a bug, with a concrete case | applied. Code: write the test that fails first, see it fail, then fix. What no test reaches (prose, configuration, a script's output): the exact situation or input and the wrong result, reproduced or traced to a `file:line` | `bug` |
   | 4 | a consequence that would be a security hole, lost or corrupted data, or a change the repo's Hard Stop rules require approval for that no Approvals row covers | no concrete case needed: fixed, or the issue stops for a person; an unapproved Hard Stop always stops (§4) | `risk` |
   | 5 | behaviour the spec does not have | applied only when small: touches no Hard Stop item, adds no new user-visible behaviour, setting or message, stays inside the files the spec lists, and has a test. Named in the report under *Added beyond the spec*. Otherwise declined and listed as a follow-up | `added`, or declined as `beyond` |
   | 6 | anything else | declined, with one line saying why | `hypothetical` (a setup or input no real repo or run has), `style` (wording, naming, tidiness, speed with no wrong result), `settled` (the spec, an Approvals row or an earlier round decided it), `reversal`, `late` |

   Test 4 is read by consequence, not by file: a finding on a file a Hard
   Stop covers is not test 4 unless its consequence is. A finding that meets
   tests 1 to 4 and cannot be fixed stops the issue for a person (§8).
3. **Three attempts per finding.** From round 2, a finding that meets tests 1
   to 4 means a correction was wrong; it belongs to the finding that
   correction was for. The second attempt says what the first got wrong and
   takes a different approach, not a patch on the patch. A third attempt does
   the same. When a round finds such a defect in the third attempt, the issue
   stops for a person, with the three attempts and what each got wrong in the
   report.
4. **No flip-flops.** A finding that would undo a correction made in an
   earlier round: when it meets no test from 1 to 4, it is declined as
   `reversal`. When it does, and the spec or `CLAUDE.md` says which way is
   right, that way is applied once and stands, and later findings against it
   are `settled`. When it does and the spec is silent, nothing is changed and
   the issue stops for a person, who decides.
5. **Late findings.** From round 2, a finding about something no correction
   touched is declined as `late` and listed as a follow-up, unless it meets
   test 2, 3 or 4, in which case it is a new finding with its own three
   attempts.
6. **A small addition that goes wrong is removed.** When a later round finds a
   defect in something applied as `added`, the addition is taken out and
   listed as a follow-up.
7. **Prose, per file.** A file is prose when it is Markdown or plain text and
   no configuration in it changed. A prose file gets two rounds at most, in
   any change: the round that reviews it and the round that reviews its
   corrections. After its second round it changes only to fix a finding that
   meets tests 1 to 4, and such a fix sends the issue to a person, marked
   unreviewed, once the code files' review has ended. Its other findings
   from the second round on are declined and listed as follow-ups. Code files
   follow rules 3 to 6.
8. **How a review ends.** `clean`: a round applies nothing. For a person
   (§8): `third-attempt` (rule 3), `reversal` (rule 4), `unfixable` (a
   finding that meets tests 1 to 4 and cannot be fixed), `prose` (rule 7).
   And `breaker`: when round 13 ends and the review has not, the issue stops
   for a person and the report says the loop itself misbehaved. There is no
   other limit on rounds.

When the spec moves content unchanged, findings about that content are not
part of the move: list them in the report as follow-ups. A finding there that
meets tests 1 to 4 still means fix or stop.

## 6. Verify: an executed path, not a green suite

Work through the profile's `verify.rungs` in order, in the environments
`verify.agent` names. Each rung sees something the one below it cannot. Two are
always required, and a third when a lane in the profile has a `mutate`
command:

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

**A lane passes on its command's own exit status** (its `run` command; a
`mutate` run is judged by its `mutants:` line, below). Save its output and read
the status:

```bash
<the lane's run command> > <scratch>/<lane>.log 2>&1; echo "exit=$?"
```

`exit=0` is green; anything else is red, whatever the log says. Read the
summary from the log afterwards. Never put a filter (`| grep`, `| tail`,
`| head`) between the command and a decision: a pipeline's status is its last
command's, so `| grep -E 'OK|FAILED'` passes a failed run. The `echo` itself always
succeeds, so read the printed `exit=` value before any commit, push or merge;
never chain one onto the `echo`.

**The tests the change touched, compared.** Once every lane is green, check
that the change did not get there by weakening a test. In order:

1. Run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/test_guard.py" list --base origin/<base>`
   from the change's working tree, after `git fetch origin`, where `<base>` is
   the branch the change merges into (`integration.base`, or the repo's
   default branch when the profile has none).
2. Exit 3: say "tests not checked" and why in §7, write the record with
   `checked=no end=unchecked`, and go on. Exit 2: fix the call. `hunks=0`: the
   record is `checked=yes hunks=0 end=clean`.
3. Otherwise give a reader that has not seen how the change was made only the
   `list` output and the issue body. It writes an answers file, one line per
   item, `H<k><TAB><same|stronger|weaker><TAB><reason>`: `same` when the hunk
   guards the same claim, `stronger`, or `weaker` when it guards less (a test or
   case gone, a new skip or expected-failure marker, an assertion removed or
   loosened).
4. Run `test_guard.py verify <body file> <answers file> --base origin/<base>`.
   On exit 2, give the reader the errors and have it answer again.
5. Exit 1: for each `NOT LICENSED` item, restore what the test guarded (put
   back the base version of that hunk, or the deleted file) and make the change
   pass with it. Then run the lanes and steps 1 to 4 again. Up to three
   attempts, each naming a hypothesis different from the last. After the
   third, the issue stops for a person (§8), with the stop marker's reason
   `tests` and each unlicensed item named in §7.
6. Run steps 1 to 4 again after any later step of this section that changed a
   test file.

**The real thing, on real data.** Drive the path the issue describes in the
pre-merge environment and confirm the reported behaviour is gone. Hard-reload
rather than trusting a cached bundle. Read back real content (text, an
attribute, an element's presence), never a screenshot. Close anything you
opened that holds a resource (a room, a camera, a browser left running).

**The changed lines, mutated.** For each lane whose profile entry has a
`mutate` command. In order:

1. It runs last in §6, once every applicable lane's `run` command is green and
   the real run has been made. When no lane has a `mutate` command, nothing
   runs and §7 says so.
2. Run the lane's `mutate` command, after `git fetch origin`, with `<base>`
   replaced by `origin/<branch>`, where `<branch>` is the branch the change
   merges into (`integration.base`, or the repo's default branch when the
   profile has none), and let it finish: there is no time limit.
3. A run whose output has no `mutants:` line is a failed run, never a pass.
   Run it once more. A second failed run stops the issue for a person (§8).
4. `mutants: 0` means nothing on the changed lines can be mutated in this
   lane. It is reported and is not a failure.
5. Each survivor is handled by the first of these that applies, and nothing
   else is a reason (not "unlikely", "hard to test" or "the review covered
   it"):
   - **Kill it.** Add a test, or tighten an assertion, so the lane's tests
     fail with the mutant in place. Such a change only adds or tightens: it
     never deletes, skips or loosens a test.
   - **Decline it** as `equivalent`: no input makes the mutated code behave
     differently from the original.
   - **Decline it** as `text`: the mutant changes only wording a person reads
     (a message, help text, a label, how much of an id is shown) and the spec
     does not fix that wording.
   - **Decline it** as `outside`: the difference shows only outside what this
     lane's tests can observe (what is handed to an external program or
     service the tests replace with a stand-in, a wait or retry interval),
     **and** the real run in this section executed that line. When the real
     run did not execute it, kill it: assert what is handed over.
6. When the test written to kill a survivor also fails on the unmutated code,
   the survivor found a bug. Fix the code. That fix is a correction: it goes
   back through §5 as a new round on the fix, then through §6 again.
7. After killing, run the command again. A survivor counts as killed only
   when a run reports it killed. At most three runs that give counts per
   lane. A survivor that is neither killed nor declined after the third
   stops the issue for a person (§8), named in the report.
8. Tests added or tightened here are not reviewed again: their evidence is the
   run that reports the mutant killed. After the last such change, run every
   applicable lane's `run` command once more and see it green.

"Done" means an executed path. A green suite alone is "written", not "done".

## 7. Report on the issue

Comment in the reporter's language, not the codebase's:

- **What was happening**: the mechanism, one short paragraph, in their terms.
- **What changed**: user-visible effects, as bullets.
- **How it matches the spec** (§5's spec check). With no spec in the body,
  the one sentence "This issue has no spec in its body, so the change was not
  checked against one." Otherwise: how many items were checked and how many
  were `met`, `missing` and `differs` at the first reading; what was built or
  changed to match afterwards; **Differs from the spec**, one line per
  declared difference with the item, what the spec says, what the change does,
  why, and any *Verify by hand* step that now reads differently, written out
  as it now reads (or "Differs from the spec: nothing."); each `outside` file
  kept, with the item it serves; each `na` item with its reason. A stop names
  the items left. Put this record on its own line before the review record
  and before any mutation record, with no spaces inside a value:
  `<!-- gogogo:spec-check v=1 items=<n> met=<n> missing=<n> differs=<n> na=<n> outside=<n> runs=<n> fixed=<n> declared=<n> reader=<fresh|self|none> end=<clean|declared|stopped|nospec> -->`
  - `items`, `met`, `missing`, `differs`, `na` and `outside` are the first
    valid `spec-check:` line `verify` printed. `items` is the sum of the four
    statuses.
  - `runs` is the number of reader runs. `fixed` is the number of items not
    `met` at first and `met` at the last run. `declared` is the number of
    differences and `outside` files kept and listed.
  - `end` is `clean` when nothing was declared and nothing is left,
    `declared` when at least one difference or file was declared, `stopped`
    when the check stopped the issue, and `nospec` when the body has no spec
    (then every count is 0 and `reader=none`).
- **How it was verified**: which rungs ran, how many new tests went red, what
  the real run showed.
- **How the tests were tested** (§6's mutation step). When no lane has a
  `mutate` command, the one sentence "No lane in this repo's profile has a
  mutation command." and no record. Otherwise, per lane that has one: how many
  mutants ran, how many the tests caught, how many timed out and how many
  survived on the first run; how many survivors were then killed by added or
  tightened tests; and **Declined survivors**, one line each with the file and
  line, the change in a few words and its reason word, inside a `<details>`
  block when there are more than five. A stop names what is left. Then the
  record, one line per lane that has a `mutate` command, on its own line
  after any spec-check record and directly before the review record, with no
  spaces inside a value (a space in the lane's name is written as `-`):
  `<!-- gogogo:mutation v=1 lane=<name> mutants=<n> killed=<n> survived=<n> timeout=<n> runs=<n> added=<n> declined_as=equivalent:<n>,text:<n>,outside:<n> end=<clean|survivors|failed> -->`
  - `mutants`, `killed`, `survived` and `timeout` are the first run's counts:
    what the tests caught as the change was written. `mutants` is the sum of
    the other three.
  - `runs` is the number of runs that gave counts.
  - `added` is the number of survivors killed by tests added or tightened
    afterwards. `declined_as` is the number declined, by reason.
  - `end` is `clean` when every survivor was killed or declined (then `added`
    plus the `declined_as` total equals `survived`), `survivors` when rule 7
    stopped the issue, and `failed` when rule 3 did (all counts 0).
- **How it was reviewed**: the kind (code, prose, or mixed: code with prose
  files, §5 rule 7) and the coverage. One line per round: how many findings
  were applied and how many declined, and the most important applied finding
  in a few words. **Added beyond the spec**, when anything was (§5 test 5).
  **Declined**: one line per declined finding with its reason word from §5's
  table, inside a `<details>` block when there are more than five. The
  follow-ups. How the review ended (§5 rule 8). When §3 found that the bug
  this issue fixes was introduced by the change made for an earlier issue in
  this tracker, say so in one sentence. End the comment with the record on one
  line, with no spaces inside a value:
  `<!-- gogogo:review v=2 pr=<n|none> kind=<code|prose|mixed> coverage=<precise|broad|exhaustive> rounds=<n> applied=<a1,a2,…> declined=<d1,d2,…> refix=<f1,f2,…> applied_as=spec:<n>,regression:<n>,bug:<n>,risk:<n>,added:<n> declined_as=hypothetical:<n>,style:<n>,settled:<n>,reversal:<n>,beyond:<n>,late:<n> followups=<n> end=<clean|third-attempt|reversal|unfixable|prose|breaker> escaped_from=<n|none> escaped_as=<declined|missed|none> impl=<model> reviewer=<model> session=<id|unknown> t_branch=<YYYY-MM-DDTHH:MMZ|unknown> t_verified=<YYYY-MM-DDTHH:MMZ|unknown> -->`
  - `pr` is the pull request the change went through, or `none` when there
    is none yet. `coverage` is round 1's.
  - `applied`, `declined` and `refix` have one number per round, in order.
    `refix` counts the applied findings that fixed an earlier correction (§5
    rule 3); its first number is always 0.
  - `applied_as` and `declined_as` are totals over the whole review by the
    *Recorded as* words; each adds up to the sum of its per-round list.
  - `followups` is the number of follow-ups the report lists.
  - `escaped_from` is set when §3 found that the bug this issue fixes was
    introduced by the change made for an earlier issue in this tracker: that
    issue's number, found from the commit that introduced the defect.
    `escaped_as` is `declined` when that earlier issue's report lists the
    defect among its declined findings or follow-ups, and `missed` when it
    does not. Otherwise both are `none`.
  - `impl` and `reviewer` are the model that made the change and the model
    that reviewed it, as the agent's tool names them, or `unknown`.
  - `session` is the id of the agent session that made the change, as
    `## Claude-specific` says, or `unknown` when it cannot be read. It is
    never made up.
  - `t_branch` is when the issue's branch was created, UTC to the minute,
    from git's reflog:
    `TZ=UTC git reflog show --date=format-local:%Y-%m-%dT%H:%MZ --format='%gd %gs' <branch> | tail -1`.
    It is the date inside `@{…}` when that line's text starts
    `branch: Created from`, and `unknown` otherwise.
  - `t_verified` is when the last rung of §6 passed: the output of
    `date -u +%Y-%m-%dT%H:%MZ`, run at that moment and kept for the record. It
    is `unknown` when verification did not finish (a stop before or during §6).
  - The time the review ended is when the report was posted, and the merge
    time is the PR's; neither is written in the record, and the record is
    never edited after it is posted.
- **How the tests were compared** (§6): how many test hunks were checked, and
  how many were `weaker`, `licensed` and restored, or "tests not checked" and
  why. End the comment with this record on its own line, after the review
  record, with no spaces inside a value:
  `<!-- gogogo:tests v=1 checked=<yes|no> hunks=<n> weaker=<n> licensed=<n> restored=<n> attempts=<n> end=<clean|restored|stopped|unchecked> -->`
  - `weaker`, `licensed` and `restored` are from the first `verify`.
    `attempts` counts restore attempts (0 when none was needed).
  - `end` is `clean` when nothing was unlicensed, `restored` when every
    unlicensed item was restored and the change passes, `stopped` after the
    third attempt, and `unchecked` with `checked=no`.
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

- **stopped for a person**: a review that ended for a person (§5 rule 8: a
  defect in a finding's third attempt, a reversal the spec does not settle, a
  finding you could not fix, a prose file's second-round fix, or the breaker
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
| `decision` | a decision that belongs to a person and is not in the body (§4) |
| `spec` | the spec check stopped (§5: two parts of the spec disagree, a difference that is not small, a piece that could not be built, or items left after the third reading) |
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

## Do not

- Write to anything `state.forbidden` lists, or to production data.
- Report "fixed" on a green suite alone.
- Chain a commit, push or merge on anything but the run's own exit status: output piped through a filter, or the `echo "exit=$?"` after it.
- Commit, push, or open a PR unless asked (outside `auto-dev`).
- Move a card ahead of the code, or to Done.

## Working alongside superpowers

`superpowers:systematic-debugging` fits step 3 and may be used there. Do not use
`superpowers:using-git-worktrees`, `superpowers:subagent-driven-development` or
`superpowers:finishing-a-development-branch` for tracker work: implementation
and integration follow this skill and the repo's merge path. See the profile's
`## superpowers boundary`.

## Claude-specific

- The review command is `/code-review <level> <target and brief>`. The level
  follows the coverage: `precise` is `medium`, `broad` is `high`,
  `exhaustive` is `max`. The target is the change in round 1 (the working
  tree, or the branch against its base) and the corrections in later rounds
  (their commit range, or the files named); the brief is §5 rule 1's.
- The spec check's reader (§5) is a subagent started with the `Agent` tool,
  which does not see this conversation. Its prompt is §5's brief for the
  reader and the item list, and it writes the answers file.
- A mutation run (§6) can outlast the shell tool's foreground limit: start it
  with `run_in_background` and poll it as `/gogogo:auto-dev`'s
  *Claude-specific* says; in an auto-dev run never end the turn to wait for it.
- In the record, `impl` is the session's model id; `reviewer` is
  `$CLAUDE_CODE_SUBAGENT_MODEL` when it is set, else the same as `impl`.
- In the record and the stop marker, `session` is `$CLAUDE_CODE_SESSION_ID`, the variable
  `require_unattended.sh` also reads, and `unknown` when it is unset.
- Browser checks use the `claude-in-chrome` tools; load the ones you need in one
  `ToolSearch` call.
