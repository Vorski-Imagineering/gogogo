---
name: spec
description: Use when turning a tracker issue, or an idea not yet filed as one, into a specification another agent will implement (also a list of issues or a board column, such as "spec these five" or "spec everything in New", specced one at a time; with no argument, it offers to spec everything in New), when triaging whether an issue is ready to hand off, or when an agent came back blocked on an issue that looked fully specified.
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

Any `warning:` line the check printed goes, verbatim, at the top of your report to the person; if it printed none, the report says so.

Then read the profile's `## Recon traps` and `## Lane constraints` sections, and
the Hard Stop rules at `hard_stops.source`. They are required reading before
you write anything, and nothing here repeats them.

Every tracker command targets `tracker.issues_repo`. When it differs from
`tracker.code_repo`, pass `--repo <issues_repo>` on every `gh issue` call.

## Who decides

Every choice you meet while speccing is one of three kinds. The kind is fixed
by what the choice changes, never by how sure you are:

| Kind | What it changes | Example |
|---|---|---|
| **Approval** | Anything the Hard Stop rules list, or applying a two-licence change | A script that starts refusing an action it used to allow |
| **Product** | What a person sees, gets or has to do: on the board, in the tracker, in a report, or in the product | A skipped card moves to the needs-a-person column |
| **Engineering** | How it is built, where a later change could undo it without anyone noticing a difference | Which pattern finds an issue number in a branch name |

A choice that could be two kinds counts as the one that asks more: approval
over product, product over engineering.

The profile's `independence` sets which kinds you ask about. Absent means
`junior-dev`.

| Level | You ask about | You decide |
|---|---|---|
| `junior-dev` | approvals, product, engineering | nothing |
| `tech-lead` | approvals, product | engineering |
| `product-owner` | approvals | product, engineering |

Approvals are asked at every level. A kind the level does not ask about is
yours to decide: pick, and record it under *Decided without asking* in
`## Approvals` with its reason (§ *`## Approvals`*), and build the spec's
`## Design` on it.

At `tech-lead` or `product-owner`, when your model is not Opus-class or above,
say in one line that this level is recommended for an Opus-class model at
medium effort or higher, then carry on.

## Given nothing to spec

When the user gives no issue, no idea and no column (`/gogogo:spec` with no
argument, or words that name none of them):

1. Without `tracker.tool`, ask for an issue number or an idea; the rest of
   this section does not apply.
2. Find the column with the word `New`, the way `references/several-issues.md`
   rule 2 matches words: the column `/gogogo:setup` creates as `⚡️ New`. A
   non-zero exit from `fields` is said as such, and this section stops. None
   matches: say the board has no New column and ask for an issue number.
   Several: rule 2's question names them.
3. Read it with rule 2's `list` command and apply rule 3's skips to each
   issue. A non-zero exit is said as such, and this section stops: a failed
   read is not an empty column.
4. None left (empty, or every issue skipped): say so, naming each skipped
   issue and why, and stop.
5. Otherwise ask one `AskUserQuestion` naming the column, the count and the
   numbers in the list's order: **spec everything in `<column>` (<k>: #a,
   #b, …)** or **name an issue instead**. A typed answer naming an issue, idea
   or column is that request.
6. *Spec everything*: a board-column run of that column. Read
   `references/several-issues.md` and start at rule 2 with the column chosen;
   its list is read again there. *Name an issue* with none given: ask for it
   in plain text and wait for the reply.
7. A decline, or no person to ask (the question tool errors, or
   `claude -p`): stop, post nothing, and say nothing was
   specced. The four-choice menu of *When the user declines a question* is
   not used: no spec fork was asked.

## Several issues in one run

Only when the user gives more than one issue, or a board column, or accepted the offer in *Given nothing to spec*. **REQUIRED REFERENCE:** then read `references/several-issues.md` (in this skill's folder) in full before starting the first issue. With one issue, skip it.

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

**REQUIRED REFERENCE:** read `references/verify-by-hand.md` (in this skill's folder) in full before anything else in this step. It holds the whole of this step.

## `## Approvals`

Its job is to stop the implementing agent reopening settled decisions, and to
stop it assuming approval nobody gave.

`| Date | Question put to the user | Chosen | Rejected |`

- One row per question asked. Record what they picked it **over**: the rejected
  option is what prevents re-litigation.
- **Any decision of a kind the level asks about goes to the user
  (§ *Who decides*)**, not into your rationale. Catching yourself writing
  "Rationale for the split" about such a decision means you approved something
  on their behalf. Ask instead.
- A Hard Stop the user approved is a row, and that row is what licenses
  implementation.
- No approvals needed? Then the row is literally *"None — every Hard Stop item
  is no, implement directly."* An empty section is ambiguous between "nothing
  needed" and "nobody asked"; those have opposite consequences.
- End with a `Not approved:` line for anything you raised and they did not take
  (`Not approved: none` when there is nothing).
- Then, when the agent decided anything, a `Decided without asking:` line and
  one bullet per decision with its reason. These are not approvals and no
  verdict may cite them.

## Ask in rounds until no forks remain

The Approvals table is the **output of a loop**, not of a single pass. Keep
asking until pre-post check question 1 answers *"none"*.

- At `tech-lead` and `product-owner`, ask at most one round per issue. When the
  person answers against the recommendation, work out what follows from the
  answer yourself.
- Every question opens with the real case in one plain sentence, and each
  option says what changes for people. Name no files, flags or exit codes in a
  question.
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
round. After 4, stop (in a run of several issues, stop that issue only). A
declined menu is choice 4: stop, and do not offer it again.

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

Five rules hold in all of them:

1. **"No evidence" must fail, not pass.**
2. **Include a step that proves the test fails**: pin a value, name which tests
   go red, revert.
3. **What a second reader sees needs a test from a second reader.** A test that
   only re-reads what the actor itself just wrote passes against the broken
   code.
4. **A lane you call impossible costs the same proof as a lane you write.**
5. **Another issue's body as test data is asserted in its narrowest form**,
   and that issue is named in `## Context` as a dependency.

**REQUIRED REFERENCE:** read `references/test-rules.md` for what each rule
means in practice, and the profile's `## Lane constraints` for what each lane
must specify in this codebase.

## Is someone building it already?

When an issue starts (one issue, or each issue of a run as rule 4 starts it),
check this before *Before you write* § 0. Never for an idea not yet filed: it
has no card and no pull request.

1. Run `<tracker.tool> show <N>` (for `shared`,
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" show <N>`) when the
   profile has `tracker.tool`, and
   `gh pr list --repo <tracker.code_repo> --state open --limit 1000 --json number,title,body,headRefName,url`.
2. It is being built when the card's column is `tracker.columns.in_progress`,
   or an open pull request **claims** `<N>`: any one of
   - its branch name carries `<N>` by `/gogogo:status`'s rule: the first match
     of `/(\d+)(?:-|$)` in the name, else of `^(\d+)-`, is `<N>`;
   - its title has `#<N>` as a whole token;
   - a body line, after optional spaces and a `-` or `*` bullet, starts with
     `refs`, `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`,
     `resolves` or `resolved` (any case, optional `:`), then references split by `,` or `and`, one being `#<N>` or
     `<tracker.issues_repo>#<N>` as a whole token.

   Match the token, not a plain number search (`1<N>`, line numbers). A
   non-zero exit from either command counts as being built, with the reason
   "could not check". A card in `tracker.columns.needs_human` does not count:
   it was handed back for a person, usually for exactly this re-spec.
   An open pull request with `#<N>` as a token in its title or body that claims
   it by none of these is a *mention*: say one line per mention, "PR <link>
   mentions #<N> but does not claim it", whether or not it is being built, and
   ask nothing about it.
3. Not being built: go on to *Before you write*.
4. Being built: say so in one sentence, naming the column or the pull request
   link, and that the build was made against the current spec. Ask: **change
   the spec anyway** or **leave it**. On *change it anyway*, go on; after
   Posting step 6, comment on each pull request that claims it: "The spec in #<N>
   changed after this was built: <one line per changed Design or Test case
   item>". On *leave it*, a decline, or no person to ask: post nothing, add no
   label, and end this issue (in a run of several, no person to ask stops the
   run, as rule 6 says). The four-choice menu for a declined question is
   not used here.

## Before you write

0. **Check where any existing spec lives.** If the issue already carries a spec
   in a comment, move it into the body before doing anything else. That alone
   is what unblocks it. Do this even when the user asked for something else on
   the issue; a spec an agent will not act on is not a spec.

   **Then take the start snapshot**, in every run, one issue or several, when
   the issue actually starts (after this step's own edit, which is this run's
   change):
   `gh issue view <N> --repo <tracker.issues_repo> --json body,labels > <scratch>/issue-<N>-start.json`.
   Posting step 1 compares the issue with it. In a run of several, rule 3's
   read before starting stays as it is; it only decides skipping.
1. **Read the code before believing the ticket.** It describes a symptom.
2. **Hunt for data already on the wire before proposing new state.** Highest
   leverage, most skipped. Grep for the field, not the feature.
3. **Distrust what looks live**, and end recon by listing the traps you found.
4. **Hunt non-atomic transitions.** Two writes for one logical change is a
   visible transient and a flaky test.
5. **Correct the ticket where it is wrong**, in the spec and in your reply to
   the user.
6. **Does anything hit it today?** After steps 1 to 3, name the case that hits
   it today, with a link or `file:line`: a person asked for it, or a record (an
   issue report, a run report, an error) or a real path in a repo shows it. A
   person's request always hits today; this check is for follow-ups an agent
   filed (a review finding, a "what if"). When recon finds none:
   1. For an issue: ask **close it as not planned** or **spec it anyway**. On
      close: `gh issue close <N> --repo <tracker.issues_repo> --reason "not planned" --comment "Not specced: nothing hits this today. Reopen when <the case that would make it real>."`,
      and end this issue.
   2. For an idea not yet filed: ask **don't file it** or **file and spec
      it**. On don't: file nothing, and end.
   3. A decline, or no person to ask: post nothing, file nothing, close
      nothing, and end this issue, saying what recon found (in a run of
      several, no person to ask stops the run, as rule 6 says). The
      four-choice menu for a declined question is not used here.
7. **A new mechanism: look for prior work first.** When the design would add
   something the repo does not have (a setting, a script, a kind of check, a
   state, a process step), search the web before the first question: how
   others solve it, and what went wrong for them. Put a `**Prior work.**`
   paragraph in `## Context` with each source as a link and one line on what
   it adds, or the searches run and "none found". Prior work is evidence, not
   authority: the Design still answers to this repo's code and the person's
   choices. It is not a question to the person.

**REQUIRED REFERENCE:** read `references/recon.md` for how to do 2-5, and the
profile's `## Recon traps` for what this codebase specifically hides.

## Red flags in your draft

| Phrase | Meaning |
|---|---|
| "choose between" / "either approach works" | Unresolved fork. Ask the user. |
| "Rationale for the split/choice" | You decided a kind the level asks about. Ask instead. |
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
| Posting over a body that changed since the issue started | Someone else's work quoted as the report or overwritten. Compare with the start snapshot first. |
| A step that reads another issue's body, asserted broadly ("no line containing …") | The next re-spec of that issue breaks it. Use the narrowest form and name the dependency in Context. |
| "cannot be automated / not testable" | Name the missing capability, or you are excusing a lane you did not investigate. |
| No `## Verify by hand` | The reporter cannot check their own issue. Required in every spec. |
| A placeholder URL in Verify by hand | Find a real record that reproduces it; do not hand the recon back. |
| "verify it works" / "confirm the fix" as a step | Name the clicks and what appears on the page. |
| `## Context` with no traps | Nobody looked. |
| "Done" anywhere in the spec | The spec proposes work; only the implementing agent's report can claim "done". |
| Spec posted, no ready label, no reason given | Either label it or say which condition withheld it. Silence reads as "forgot". |
| A changed spec on an issue whose card is In progress or that has an open PR, not raised | The build was reviewed against the old spec and is now short of the new one. Ask first (§ Is someone building it already?). |
| A follow-up specced with no case that hits it today | A question round spent on something nobody meets. Offer closing first (Before you write § 6). |
| A new mechanism with no Prior work in Context | Options invented without looking at how others solved it (Before you write § 7). |

## Posting

**REQUIRED REFERENCE:** read `references/posting.md` (in this skill's folder) in full before anything else in this step. It holds the whole of this step.

**The reply after posting** lists the *Decided without asking* items in two or
three lines, so the person can overturn any.

## Pre-post check

Read it as the implementing agent: no memory, no access to you.

1. Any point where I must choose and have no basis?
   Is every decision the agent took of a kind the level does not ask about,
   and listed under *Decided without asking*?
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
10. Does the issue carry the ready label, and did Posting step 8 move the
    card or say why it did not? Or did I say which withholding case applies?
11. Were the open specs that read this issue checked (Posting step 4), and
    does each failing step have its narrower form and its outcome decided
    (fixed or commented on after step 6, or reported)?
12. Was the issue checked for work in flight before anything was written (or
    did it start as an idea not yet filed), and
    does `## Context` name the case that hits it today?

Any "no" is a rewrite.

## Claude-specific

Listed in one place so an adapter for another agent knows what to replace.

- **Asking the user** uses `AskUserQuestion`, which takes at most 4 questions
  per call. Five forks means at least two rounds. When a fork is about layout
  or wording, its option previews settle it faster than prose.
- **A declined question**: when the user declines or interrupts it,
  `AskUserQuestion` comes back as a refusal with no answer. In an interactive
  session that is the decline *When the user declines a question* describes,
  except for the offer in *Given nothing to spec*, which stops (its step 7).
  A run with no person (`claude -p`) gets the same refusal, which is why that
  subsection shows the menu once and stops when the menu is refused too.
- **Research one issue ahead** (*Several issues in one run*, rule 5) is an
  `Agent` call with `subagent_type: "fork"`, run in the background. Its prompt
  names the one issue, says it is research only for the spec run above, and
  forbids `AskUserQuestion`, any `gh issue edit`, `comment` or `create`, any
  label and any card move. Start a new one only when the issue it researched
  has started.
- **Prior work** (*Before you write* § 7) uses `WebSearch`, and `WebFetch` to
  read a page it finds. Without them, say so in the `Prior work` paragraph.

## Working alongside superpowers

Design exploration may use `superpowers:brainstorming`. Its output goes into
the tracker through this skill, not into a separate design file. See the
profile's `## superpowers boundary`.
