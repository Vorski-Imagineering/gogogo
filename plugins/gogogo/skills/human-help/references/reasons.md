# /gogogo:human-help: the rule for each stop reason

Part of `/gogogo:human-help`. Read it in full before a card's reason decides
anything. Section names here are `SKILL.md`'s.

Every reason in `tracker.py`'s `STOP_REASONS`, plus `skip` (an auto-dev triage
skip) and `none` (no marker at all), has a rule below. A new stop reason with no
rule here is a failing test, not a silent gap.

## Before any reason's rule

- A card with an answer already given is settled by that answer (*Work the
  cards*, step 1). The rules below apply only to a card without one.
- A card whose `requeued` count is at least 1 for its same reason is asked,
  whatever the rule below says.

## `review`

The review ended for a person: the Needs-you names a commit that has had no
review round after it, or a defect the review could not fix.

1. Run one review round on the commit the Needs-you names, by `/gogogo:dev`
   §5's rules (`plugins/gogogo/skills/dev/references/review.md`), in a worktree
   of the branch.
2. **No defect:** requeue. The requeue comment names the round's result.
3. **A defect:** a question. Offer to fix it on the next run, or to leave the
   card.

## `ci`

The pull request's checks failed and the Needs-you says so.

1. Re-run the failed jobs once: `gh run rerun <run> --failed`, for the PR's
   failed run.
2. Wait for the run. **Green:** requeue. **Still red, or unreadable:** a
   question.

## `gate`

A gate gave up. Requeue once. The requeue comment says the card was requeued
for a second attempt. A second stop for the same reason is a question (*Before
any reason's rule*).

## `verify`

Verification gave up. Requeue once, with the same comment and the same rule for
a second stop as `gate`.

## `mutation`

An engineering decision: decline or keep a mutation survivor. Decided as `tests`
below is.

## `tests`

An engineering decision: accept or refuse a weakened test.

- When `independence` lets the skill decide engineering (`tech-lead` or
  `product-owner`), decide it, and record it under *Decided without asking* in
  the issue body with its reason.
- Otherwise, a question.

## `decision`

A product or engineering decision the body did not settle. Decide it or ask,
by the kind named in the Needs-you text and the profile's `independence`. A kind
the skill cannot tell apart is asked.

## `spec`

The spec check stopped: the spec and the change disagree, or items were left
after the third reading. A question offering a re-spec with `/gogogo:spec <n>`
in this session, then a requeue.

## `hard-stop`

A Hard Stop approval is needed. **Always a question**, at every `independence`
level. The question names the approval and recommends an answer.

## `skip`

An auto-dev triage skip: the issue was not workable at triage (a missing
decision, a lint failure, or a Hard Stop with no approval row). Always a
question.

## `none`

The card has no stop marker, so nothing says why it stopped. Always a question,
naming the card.

## `merge`

A merge was refused, conflicted, or did not land, and the Needs-you says so.
Always a question: the skill does not retry a merge on its own.

## `reverted`

A fix that had shipped was reverted, and the card was handed back for it.
Always a question, naming the reverting commit.
