---
name: human-help
description: Use when asked to work the Human!Help! column, clear the cards that stopped for a person, or requeue issues whose question has been answered. Reads each card's stop reason and the answers written after it, settles what the agent can, asks the person about the rest, and moves each card with a comment saying what was done.
---

# human-help: work the cards that stopped for a person

Part of the gogogo process. A card lands in the Human!Help! column when
`/gogogo:dev` or `/gogogo:auto-dev` stops an issue and hands it back with a
`**Needs you:**` comment. Nothing else moves it, so the column only grows
unless someone works it. This skill works it: for each card, it settles what
the agent can settle, asks the person about the rest, and moves the card with
a comment saying what it did and why.

## First: read this repo's profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for human-help --show
```

- Exit 0 prints the settings. Use them wherever this skill says *the profile*.
- Any other exit: **stop and report the line it printed.** Do not guess a
  tracker, a column or a label.

Any `warning:` line the check printed goes, verbatim, at the top of your report.
If it printed none, the report says so.

Every tracker command targets `tracker.issues_repo`. When it differs from
`tracker.code_repo`, pass `--repo <issues_repo>` on every `gh issue` call.

## Read the column

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/human_help.py" list --json
```

Exit 0 gives each card, oldest first: its number, title, `reason` (the stop
reason, or `skip`, or `none`), its `needs_you` line, the `branch` it names,
its `answers` (comments by someone with write access after the stop), and its
`requeued` count for that same reason. Exit 2 means the board or an issue could
not be read: **stop and report it.** A failed read is never an empty column.

Say the list in one line per card before working any of them: number, reason,
and whether it has an answer.

## Work the cards, one at a time, oldest first

Before acting on a card, read it again:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" show <n>
```

A card no longer in `tracker.columns.needs_human` is left alone and reported
as moved meanwhile.

For each card, in this order:

1. **An answer already given settles the question.** Record it (see *Record
   an answer*) and requeue, without asking.
2. **Otherwise the reason decides**, by `references/reasons.md`. That file holds
   the rule for each reason. Read the one for this card's reason before acting.
3. **A question goes to the person** with `AskUserQuestion`, one card per
   question. Name `#<n>` in it, give the card's Needs-you line in one plain
   sentence, the evidence (the commit, the survivor's line, the missing
   approval), and your recommendation. Each option says what changes for
   people. Name no files, flags or exit codes in the question.
4. **A declined question** leaves the card where it is. Say so in the report and
   go on to the next card.
5. **With no person to ask** (the question tool errors, or `claude -p`), every
   card that needs a question stays in the column, and the run goes on.

A card's `requeued` count is at least 1 for the same reason it stopped on
again: that is a question, never another requeue, so a loop cannot run forever.

## Record an answer

A decision taken or answered goes into the issue **body**, not only a
comment, using `/gogogo:spec`'s rules:

- an Approvals row: date, the Needs-you question, the answer chosen, what it
  was picked over. A folded comment's row cites its link;
- a *Decided without asking* line for a decision the skill took itself, with
  its reason.

Read the body, add the row, and write it back with `gh issue edit <n> --repo
<tracker.issues_repo> --body-file <file>`. Lint the body before any requeue
(below).

## Outcomes

Each outcome posts one comment on the issue saying what was done and why.
Confirm every move by its exit status.

- **Requeue.** Run the lint on the body:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_lint.py" <body file>
  ```
  On `label: apply`: add `tracker.ready_marker`
  (`gh issue edit <n> --repo <issues_repo> --add-label "<ready_marker>"`),
  post a comment whose own line is `<!-- gogogo:requeue v=1 reason=<reason> -->`,
  then `tracker.py move <n> --from needs_human --to "<tracker.queue>"`.
  A lint failure: no label, no move. The card stays, and the report gives the
  lint's first error.
- **Close as not planned.**
  `gh issue close <n> --repo <issues_repo> --reason "not planned" --comment "<why>"`.
  Name the branch in the comment. Do not delete the branch.
- **Back to Backlog.** Remove the ready label, then move the card to
  `Backlog`. Offered only when `tracker.py fields` shows a Backlog column.
- **Re-spec.** Run `/gogogo:spec <n>` in this session, then requeue as above.
- **Leave.** Nothing changes. The report says why.

Do not move any card into `tracker.columns.needs_human` yourself. The tracker
refuses a move there unless the issue's newest comment carries a stop marker,
and this skill never hands a card back.

## Authorised effort

For a card that stopped on `review` (any end but `reversal`), `tests`,
`mutation`, `verify` or `gate`, the question also offers **keep at it until it
succeeds**, followed by a second question for the level: same model, high
effort, Fable, or Fable at high effort. This is always asked, at every
`independence` level. It is never taken from a comment unless that comment
says it in words, and it is never chosen without a person to answer.

The answer is an Approvals row whose Chosen reads
`authorised: review=until-clean[ model=<m>][ effort=<e>]`, then requeue. The
next run reads it with:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/human_help.py" authorised <body file>
```

## Report

One line per card: `#<n> <outcome> → <column>`, and one clause of why. Then
each question left open, then any failed move or read with its message. End
with the column's remaining count.

## Working alongside superpowers

Do not use `superpowers:using-git-worktrees` or
`superpowers:finishing-a-development-branch` here. Requeued cards are resumed
by `/gogogo:auto-dev`, which follows the profile.

## Claude-specific

- `AskUserQuestion` takes at most four questions per call. A round of cards
  that need answers is one question per card, asked in separate calls when
  there are more than four.
