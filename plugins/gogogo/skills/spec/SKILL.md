---
name: spec
description: Use when turning a tracker issue, or an idea not yet filed as one, into a specification another agent will implement (also a list of issues or a board column, such as "spec these five" or "spec everything in New", specced one at a time), when triaging whether an issue is ready to hand off, or when an agent came back blocked on an issue that looked fully specified.
---

# spec

## Overview

Produce a spec and make it the **description of the issue it specifies**. No
`specs/` file, and not a comment: the issue body is the single artifact. The
reporter's original words stay at the top of that body, above the spec.

**The spec goes in the body, never in a comment.** Implementing agents read the
issue body for the `## Approvals` table and the `## Hard-stop check` verdict,
and correctly refuse to act on a Hard Stop they cannot see there. A spec posted
as a comment reads as unapproved no matter how complete it is.

**Core principle: a spec is ready when an agent with no memory of this
conversation can execute it without making one judgement call you could have
made for them.** Specs do not fail by being short. They fail by containing an
unresolved fork, and the agent's guess is worse than its question.

The dangerous failure is not an obviously thin spec. It is a thorough, confident
spec that silently decided a product question on the user's behalf.

## First: read this repo's profile

This skill holds the rules that are the same in every repo. What differs here
(the tracker, the Hard Stop test, the test lanes, the environments and where a
person checks a fix, what this codebase hides) is in the repo's profile. The
profile is the nearest `.agents/dev-process.md` at or above the folder you are
working in; run the command below from that folder's repo root.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for spec --show
```

- Exit 0 prints the settings. Use them wherever this skill says *the profile*.
- Any other exit: **stop and report the line it printed.** It names the missing
  field. Do not guess a tracker, a label, a test command or a URL.

Then read the profile's `## Recon traps` and `## Lane constraints` sections, and
the Hard Stop rules at `hard_stops.source`. They are required reading before
you write anything, and nothing here repeats them.

Every tracker command targets `tracker.issues_repo`. When it differs from
`tracker.code_repo`, pass `--repo <issues_repo>` on every `gh issue` call.

## Several issues in one run

1. **When it applies.** The user gives more than one issue (numbers, `#n`,
   issue URLs, in any mix) or a board column ("everything in New"). One issue
   works exactly as before, and none of this section applies.
2. **The list is fixed at the start.** Keep issue numbers in the order given.
   For a column, match the user's words against the board's columns from
   `<tracker.tool> fields`: use the single column whose name contains them,
   ignoring case and any emoji. When none or several match, ask which column,
   naming the matches. Then read it once:
   ```bash
   <tracker.tool> list --status "<column>" --issues-only --open-only --json
   ```
   and keep the order it prints. A column needs `tracker.tool`; without it,
   say the tracker has no columns to read, and ask for issue numbers. Say the
   list and its order in one line before starting. An issue filed during the
   run, such as a split-off, is never added; it goes in the final report
   (rule 8).
3. **Skip before starting an issue**, and record why: it is closed; it is a
   pull request; or it is ready already, which means it carries
   `tracker.ready_marker` (compared ignoring case) **and** its current body
   passes the lint:
   ```bash
   gh issue view <n> --repo <tracker.issues_repo> --json body -q .body > <scratch>/issue-<n>-body.md
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_lint.py" <scratch>/issue-<n>-body.md
   ```
   exits 0 with a last line `label: apply`. Any other result means it is
   specced like any other issue.
4. **One issue at a time.** Each issue goes through this whole skill: *Before
   you write*, the question rounds, and Posting steps 0 to 7. Only then does
   the next issue start. Ask about one issue only in each question call, and
   name it in every question (`#<n>: …`).
5. **Research one issue ahead.** When an issue starts, start background
   research of the next one in the list, and only that one (see
   *Claude-specific*). It is read-only: it reads the issue, its comments and
   the code, then returns its findings with `file:line` and the forks it sees.
   It posts nothing, labels nothing, moves no card and asks no question. Its
   result is neither shown nor used until the current issue is posted, left
   open or skipped. When the next issue starts, take its research. Before its
   first question, re-read any file that the just-posted spec lists under
   `## Files` and that the research relied on, and state any order between
   the two issues as the chain rule in *Hard-stop verdict* says.
6. **Leave it open ends that issue only.** Choice 4 of *When the user declines
   a question*, or a declined menu, posts nothing and adds no label on that
   issue. Record the question left open, and go on to the next issue. When the
   question tool errors (no person to ask), stop the whole run and report
   every issue not reached.
7. **Card moves come once, at the end.** Posting step 8 is not run per issue.
   After the last issue, apply step 8's conditions to every issue labelled in
   this run. Read each card's column, then ask **one** question listing every
   card not already in `tracker.queue` with its current column: move them all,
   or none. On yes, move each one and report each result as step 8.3 says. On
   no or a decline, say which column each stays in.
8. **The final report** has one line per issue in the list: *specced and
   labelled*; *posted without the label* (naming Posting step 7's withholding
   case); *left open* (with the question); *skipped* (closed, a pull request,
   or already ready); or *not reached* (with why the run stopped). Then each
   issue filed during the run, with `/gogogo:spec <n>`.

## The issue body IS these sections, in this order

| Section | Contains |
|---|---|
| `## Original report` | **First thing in the issue.** The body as it was before the spec, verbatim, as a blockquote. Omitted only when the issue never had a report (empty body). See Posting. |
| `## Verify by hand` | **First section of the spec**, directly under the report. Numbered steps a non-technical person can follow to confirm the work is done. Required, never omitted. |
| `## Approvals` | Every decision the **user** made. Required, never omitted. |
| `## Context` | What is broken, with `file:line`. Why the ticket's framing misleads. The unlock. The traps. Alternatives rejected, each with its reason. |
| `## Design` | Artefacts numbered 1., 2., 3. at the start of a line. Exact signatures, exact rules in order, exact selectors. Where each piece lands, following `design.placement_rule` when the profile has one. |
| `## Test cases` | Real cases in every applicable lane, numbered 1., 2., 3. at the start of a line straight through the section, across lanes; checks in a lane a test cannot reach stay as bullets. Never "add tests". |
| `## Files` | A `**Create:**` and an `**Edit:**` group with each path in backticks, then `**Explicitly not in scope:**` as a bullet list. |
| `## Verification` | Gate commands and the prove-it-fails step. This is the implementing agent's gate. |
| `## Hard-stop check` | Each item in the profile's `hard_stops.items` answered, then the verdict. |

`/gogogo:dev` checks the change against these items one by one (Design, Test cases, the file groups, and the *Verify by hand* steps and Approvals rows), so `spec_lint.py` refuses a spec whose Design or Test cases are not numbered or whose Files are not grouped this way.

## `## Verify by hand`

Goes directly under `## Original report`, above everything else including
`## Approvals`. The issue's first reader is usually the person who reported it
or whoever closes it out, not the implementing agent. They open the issue to
answer one question: *how do I check this is actually fixed?* Make that the
first thing they reach after their own words.

Write it for someone who has not read the rest of the spec and never will:

- **Open with what happened before**, in one or two plain sentences, in the
  reporter's terms and not the code's. "The Pages section showed no rows, so
  there was no way to create the first page", not "the queryset filtered on a
  flag".
- **Numbered steps, plain English, no `file:line` and no code.**
- **Name where to do it, and when.** The profile's `verify.human` names the
  environment where a person confirms a fix in this repo. Call it by the
  profile's name for it and give full clickable URLs under that environment's
  `url`. The profile's `stages` say how a change gets there; if that is later
  than the merge, say so in the first line ("Check this on production, after
  the next deploy"), so nobody looks for a fix that has not arrived.
- **Use a real record.** The real id or slug of a record that actually
  reproduces the problem. Find one. A placeholder such as `<slug>` in a URL
  hands the recon back to the reporter.
- **Say which login is needed** in step 1, not halfway down, so a permission
  refusal is not mistaken for the bug. If it needs a second browser or a second
  person, say that in step 1 too.
- **Every step says what you should see.** A step with no observable result is
  not a verification step.
- **Say what "still broken" looks like**, not only what "fixed" looks like.
  The failure is often the thing that looked almost right.
- **Cover what a human can catch that a test cannot**: does it look right, read
  right, feel fast enough. Skip anything the automated lanes already prove.
- **Say plainly which parts of the report this does not cover**, if any.
- **Keep it short.** Five to ten steps. If it needs thirty, the scope is too big
  for one issue.

This is not a duplicate of `## Verification`. That section is the agent's gate:
commands, the prove-it-fails step, exit criteria. This one is a person with a
browser. An agent confirming its own fix is not the reporter confirming their
problem is gone, so a browser test lane never substitutes for this block.

## `## Approvals`

Its job is to stop the implementing agent reopening settled decisions, and to
stop it assuming approval nobody gave.

`| Date | Question put to the user | Chosen | Rejected |`

- One row per question asked. Record what they picked it **over**: the rejected
  option is what prevents re-litigation.
- **Any product decision goes to the user, not into your rationale.** Catching
  yourself writing "Rationale for the split" means you approved something on
  their behalf. Ask instead.
- A Hard Stop the user approved is a row, and that row is what licenses
  implementation.
- No approvals needed? Then the row is literally *"None — every Hard Stop item
  is no, implement directly."* An empty section is ambiguous between "nothing
  needed" and "nobody asked"; those have opposite consequences.
- End with a `Not approved:` line for anything you raised and they did not take
  (`Not approved: none` when there is nothing).

## Ask in rounds until no forks remain

The Approvals table is the **output of a loop**, not of a single pass. Keep
asking until pre-post check question 1 answers *"none"*.

- **Never post a spec that lists open questions.** A spec whose own status is
  "blocked on Q1-Q5" is a questionnaire wearing a deliverable's clothes. The
  forks are not findings to report; they are work you have not finished.
- One call asks a limited number of questions (see *Claude-specific* below).
  More forks than that means more rounds. Batch related ones; never drop one.
- **Answers create new forks.** Re-scan the design after every round: picking a
  trigger point can raise a backfill question that did not exist before.
- Ask the highest-leverage fork first; its answer often deletes the rest.
- **"You decide" is an answer.** Record it (`Chosen: delegated — <what you
  picked>`), pick, state it, move on. The loop must never hang on a user who
  does not want to choose. Only an answer the user gives counts; a declined
  question does not (below).
- Only an **external unknown** (something nobody knows yet, awaiting a person
  or a measurement) may ship unresolved, named in Approvals as a block with who
  can answer it and when. A decision the user could make today is never that.

### When the user declines a question

A question the user declines, interrupts or skips is **not an answer**, and
never an instruction to decide. Do not pick for them, do not file or label
anything, and do not carry on to the next fork.

Stop and offer these four choices as a short list, in whatever words suit the
question. All four are always offered:

1. **Explain the question more**: what it is really asking, and why it matters.
2. **The impact on users**: who sees what, and what changes for them, under
   each option.
3. **You decide**: you pick the option you recommend, say why, and record it
   as `Chosen: delegated — <what was picked>`.
4. **Leave it open**: stop, post nothing, apply no label, and say what remains.
   In a run of several issues, this ends that issue only
   (§ *Several issues in one run*, rule 6).

After choice 1 or 2, ask the original question again. After 3, continue the
round. After 4, stop. A declined menu is choice 4: stop, and do not offer it
again.

Only the user delegates. Never offer "you decide" as your own decision, and
never read silence or a refusal as delegation.

A decline is a person's act: the question reached them and they turned it
down. When the question tool is not available, or fails with an error rather
than a refusal, there is no person to ask: do not show the menu; stop without
posting, and report the question as unanswered. When you cannot tell, show the
menu once: if it too comes back refused, that is choice 4, so the run stops
without posting either way.

## Hard-stop verdict

The repo's Hard Stop test is at `hard_stops.source`, and `hard_stops.items`
names its parts: categories when `hard_stops.form` is `categories`, questions
when it is `questions`.

Answer **every** item yes or no against the design, in a table, then state the
verdict **matching your own answers**. Use the item names from the profile
word for word, one row each, and `yes` or `no` alone in the second cell:

```
| Item | Triggered? | Why |
|---|---|---|
| <item from the profile> | no | <one line> |

**Verdict: implement directly.**
```

The verdict line takes one of three forms, and `spec_lint.py` checks it against
the table:

- `**Verdict: implement directly.**` when every item is **no**. The commands in
  `## Verification` are the gate; the implementing agent does not ask.
- `**Verdict: approved — <item> by Approvals row N.**` when an item is **yes**
  and an Approvals row approves that specific change. Name every yes item and
  its row.
- `**Verdict: proposal — <item> awaits approval.**` when an item is **yes** and
  no row approves it. The spec stops at that gate. Put the proposal elements
  the repo's rules ask for (what changes, what it touches, impact, rollout,
  alternatives) in `## Context`.

A spec that answers "yes" to an item and then writes "all no" is the exact
contradiction this section exists to catch.

### Some changes ask two questions, not one

Approving a change's **design** and approving **applying it to a shared
environment** (one of the profile's `environments`) are separate permissions, and an unattended run can only act on
what the body says. The profile's `hard_stops.two_licence` lists the changes
this applies to here, and what "apply" means for each.

When the design includes one, put both to the user in the same round and
record both as rows:

1. **The design**: exactly what changes.
2. **Applying it**: the profile's `apply` for that change, during the
   unattended run. The row states whether it only adds or also rewrites or
   destroys, and the rollback. If anything is destroyed, the row names **what
   is lost**; an unnamed loss is not approved.

Never write a stop into `## Verification` for something the apply row already
approved. That re-gates what the user just approved and strands the run. Write
instead that the step is licensed by Approvals row N, and point at the
profile's procedure for it. If the user declines the apply row, say so in the
row and keep the stop in Verification: that is a real answer, not a gap.

A chain across issues (one issue's change depends on another's) states the
order in each issue's Context and names the issue it waits for.

## Test cases

The profile's `lanes` are the lanes that exist here. Name real cases in every
applicable lane, and give a reason for any lane you skip. Do not invent a lane
the profile does not list.

Four rules hold in all of them:

1. **"No evidence" must fail, not pass.**
2. **Include a step that proves the test fails**: pin a value, name which tests
   go red, revert.
3. **What a second reader sees needs a test from a second reader.** A test that
   only re-reads what the actor itself just wrote passes against the broken
   code.
4. **A lane you call impossible costs the same proof as a lane you write.**

**REQUIRED REFERENCE:** read `references/test-rules.md` for what each rule
means in practice, and the profile's `## Lane constraints` for what each lane
must specify in this codebase.

## Before you write

0. **Check where any existing spec lives.** If the issue already carries a spec
   in a comment, move it into the body before doing anything else. That alone
   is what unblocks it. Do this even when the user asked for something else on
   the issue; a spec an agent will not act on is not a spec.
1. **Read the code before believing the ticket.** It describes a symptom.
2. **Hunt for data already on the wire before proposing new state.** Highest
   leverage, most skipped. Grep for the field, not the feature.
3. **Distrust what looks live**, and end recon by listing the traps you found.
4. **Hunt non-atomic transitions.** Two writes for one logical change is a
   visible transient and a flaky test.
5. **Correct the ticket where it is wrong**, in the spec and in your reply to
   the user.

**REQUIRED REFERENCE:** read `references/recon.md` for how to do 2-5, and the
profile's `## Recon traps` for what this codebase specifically hides.

## Red flags in your draft

| Phrase | Meaning |
|---|---|
| "choose between" / "either approach works" | Unresolved fork. Ask the user. |
| "Rationale for the split/choice" | You approved a product decision yourself. |
| "add appropriate tests" | Name the cases and what each guards. |
| "consider whether" / "may need to" | Handing over your uncertainty. |
| "should be straightforward" | You have not read the code. |
| A claim with no `file:line` | Unverified. Verify or delete. |
| No Approvals row | Not ready, even if nothing was approved. |
| A two-licence change with a design row and no apply row | The run will build it and then cannot apply it. Ask the second question. |
| "waits for its own approval" alongside an apply row | Re-gates an approval already given; the unattended run stops for nothing. |
| A destructive change whose apply row does not name what is lost | Not approved. Name it, or ask again. |
| Spec, Approvals or Hard-stop verdict posted as a comment | Invisible where the implementing agent looks. Put it in the issue body. |
| The reporter's words moved into a comment | Buried. Put them back under `## Original report` at the top. |
| The spec itself lists open questions | Go ask them. A spec is not a questionnaire. |
| "Blocked on user answers" as a status | Only valid for an external unknown, never a decision. |
| A lane in the profile with no case and no reason given | Lane silently skipped. |
| "cannot be automated / not testable" | Name the missing capability, or you are excusing a lane you did not investigate. |
| No `## Verify by hand` | The reporter cannot check their own issue. Required in every spec. |
| A placeholder URL in Verify by hand | Find a real record that reproduces it; do not hand the recon back. |
| "verify it works" / "confirm the fix" as a step | Name the clicks and what appears on the page. |
| `## Context` with no traps | Nobody looked. |
| "Done" anywhere in the spec | The spec proposes work; only the implementing agent's report can claim "done". |
| Spec posted, no ready label, no reason given | Either label it or say which condition withheld it. Silence reads as "forgot". |

## Posting

Posting is outward-facing; do it when the user asked for it. When
`tracker.public` is true, everything you post is published: no credentials,
internal hostnames, personal data or infrastructure detail beyond what the
reporter already wrote.

`gh issue edit --body` replaces the whole body; there is no append. So compose
the full body locally and never let the report exist only in memory. In this
order, checking each step before starting the next:

0. **No issue yet?** When the user gave an idea rather than an issue, file one
   first in `tracker.issues_repo`, with a short title and the user's own words
   as the body: `gh issue create --repo <tracker.issues_repo> --title "<title>"
   --body-file <scratch>/idea.md`. Its number is `<N>` below, and those words
   become the original report.
1. **Save the current body to the scratchpad before anything else**:
   `gh issue view <N> --json body -q .body > <scratch>/issue-<N>-original.md`.
   Confirm the file is non-empty (unless the issue body is empty).
2. **Write the spec to the scratchpad**, so a failed call is re-postable.
   Inline `--body` mangles markdown; always use a file.
3. **Compose the body file**: the report section, a `---` rule, then the spec.
   ```
   ## Original report

   > <every line of the original body, each prefixed with "> ">

   ---

   ## Verify by hand
   ...
   ```
   `sed 's/^/> /'` over the saved file does the blockquote. It keeps the
   reporter's own `#` headings from splitting the spec's section structure.
   Do not edit, summarise, or correct the report; corrections go in
   `## Context`.
4. **Lint it before it leaves the machine**:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_lint.py" <composed file>
   ```
   Fix every error it reports. A lint error is a rewrite, not a judgement call.
5. `gh issue edit <N> --body-file <composed file>`.
6. **Re-read the description** and confirm both the report and the spec are
   there.
7. **Apply the ready label**, the profile's `tracker.ready_marker`:
   `gh issue edit <N> --add-label "<ready_marker>"`. It is how a person scanning
   the tracker sees which issues an agent can pick up, so it means exactly one
   thing: *the spec is in this issue's body and needs nothing further from
   anyone*. It goes on only after step 6.

   **Not every posted spec earns it.** Withhold it, and say why in your reply,
   when:

   - the Hard-stop verdict has a **yes** that no Approvals row approves. The
     spec is a proposal waiting at a gate; label it once the user approves and
     you have added the row;
   - `## Approvals` carries an unresolved **external unknown**;
   - any pre-post check answered "no".

   A spec that stops at a gate is still worth posting; it just is not ready
   until the gate is cleared.
8. **Offer to move the card to the queue.** In a run of several issues, this
   step runs once, after the last issue (§ *Several issues in one run*,
   rule 7). Only when step 7 applied the label,
   the profile has both `tracker.tool` and `tracker.queue`, and
   `tracker.queue` is one of the board's columns (`<tracker.tool> fields
   --check` lists them); otherwise skip this
   step without a word.
   1. Read the card's column: `<tracker.tool> show <N>` (for `shared`,
      `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" show <N>`, and the
      same command for `move` below). When it is already in `tracker.queue`,
      skip. When the issue has no card on the board, say so and skip.
   2. Otherwise ask the user whether to move the card from its current column
      to `tracker.queue`, naming both columns.
   3. On yes: `<tracker.tool> move <N> --to "<tracker.queue>"`, and report the
      result. Only its zero exit counts as moved; on any other exit, say it
      failed and leave the card where it is.
   4. On no, a decline, or when no one can answer: do not move it, and say
      which column the card stays in. The four-choice menu for a declined
      question is not used here.

Which report to keep:

- **Body is a plain report** → it is the report.
- **Body is already a spec with `## Original report` at the top** → carry that
  section over unchanged; replace only the spec below the `---`.
- **Body is a spec with no report section** (an older layout) → if the report
  sits above a `---` rule, that part is the report. Otherwise find it in an
  earlier comment or in the issue's edit history (`gh api graphql` →
  `userContentEdits`) and put it back at the top. If no copy can be found, say
  so in your reply; do not invent one.
- **Body is empty** → no report section; the spec starts at `## Verify by hand`.

**Correcting a spec you already posted:** edit the scratchpad file and re-run
`gh issue edit --body-file`, so the issue carries one accurate spec rather than
a spec plus errata.

**Never leave a second copy** of the spec or of the report. If an earlier
version is sitting in a comment (including a spec you just rescued into the
body under *Before you write* §0), delete it once the description is confirmed
correct: `gh api -X DELETE /repos/{owner}/{repo}/issues/comments/{id}`. Get the
id from the comment's URL (the digits after `issuecomment-`).

Comments are for **conversation about** the spec: a question, a correction
someone raised, a follow-up cross-link. Never for the spec itself.

## Pre-post check

Read it as the implementing agent: no memory, no access to you.

1. Any point where I must choose and have no basis?
2. Every claim checkable at a `file:line`?
3. Do I know whether to stop for approval, including whether I may **apply** a
   two-licence change and not just write it?
4. Can I tell when I am done?
5. Is there a test that fails if I build the wrong thing?
6. Do I know what not to touch?

Then read `## Verify by hand` as the reporter, who has no technical context:

7. Could I follow every step without asking what a word means, opening real
   URLs?
8. Does each step tell me what I should see, and what a failure looks like?

Then as the tracker:

9. Is the spec in the issue **body**?
10. Does the issue carry the ready label, and was the move to the queue
    offered or skipped for a reason Posting step 8 names? Or did I say which
    withholding case applies?

Any "no" is a rewrite.

## Claude-specific

Listed in one place so an adapter for another agent knows what to replace.

- **Asking the user** uses `AskUserQuestion`, which takes at most 4 questions
  per call. Five forks means at least two rounds. When a fork is about layout
  or wording, its option previews settle it faster than prose.
- **A declined question**: when the user declines or interrupts it,
  `AskUserQuestion` comes back as a refusal with no answer. In an interactive
  session that is the decline *When the user declines a question* describes.
  A run with no person (`claude -p`) gets the same refusal, which is why that
  subsection shows the menu once and stops when the menu is refused too.
- **Research one issue ahead** (*Several issues in one run*, rule 5) is an
  `Agent` call with `subagent_type: "fork"`, run in the background. Its prompt
  names the one issue, says it is research only for the spec run above, and
  forbids `AskUserQuestion`, any `gh issue edit`, `comment` or `create`, any
  label and any card move. Start a new one only when the issue it researched
  has started.

## Working alongside superpowers

Design exploration may use `superpowers:brainstorming`. Its output goes into
the tracker through this skill, not into a separate design file. See the
profile's `## superpowers boundary`.
