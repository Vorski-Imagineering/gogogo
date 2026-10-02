# When is enough enough? Ending the review loop

Every change an agent makes here is reviewed by another model before it
merges, and every fix the review asks for is reviewed again. That loop is what
lets the queue run unattended. It also has a failure that decides how well the
whole system works: it does not always stop. This page records what we saw, what
the research said in October 2026, and what we propose to do about it
([#33](https://github.com/Vorski-Imagineering/gogogo/issues/33)).

The state of the art here is moving fast. The sources below carry the date we
read them; check them again before relying on this page.

## What the skills do today

Since [#17](https://github.com/Vorski-Imagineering/gogogo/issues/17),
`/gogogo:dev` §5 reviews a code change with `/code-review high`, then reviews
each round's corrections, round after round, **until a round applies nothing**.
There is no round limit. A finding the reviewer calls a correctness defect may
not be declined: it is fixed, or the issue stops for a person. A prose-only
change gets two rounds at most.

The aim was right: nothing merges unreviewed, and corrections, where defects
enter, are reviewed too. In practice the loop often does not converge.

## What we saw

The review record each issue carries (`<!-- gogogo:review … -->`) gives the
numbers. The last four code reviews:

| Issue | Rounds | Findings applied | Declined | Applied as correctness |
|---|---|---|---|---|
| [#26](https://github.com/Vorski-Imagineering/gogogo/issues/26) | 8 | 38 | 38 | 4 |
| [#6](https://github.com/Vorski-Imagineering/gogogo/issues/6) | 11 | 46 | 16 | 9 |
| [#31](https://github.com/Vorski-Imagineering/gogogo/issues/31) | 17 | 93 | 11 | 28 |
| [#30](https://github.com/Vorski-Imagineering/gogogo/issues/30) | 20 | 111 | 11 | 34 |

The "correctness" column is the implementing agent's own label, applied under
a rule that made declining a correctness finding expensive; it overstates the
real defects. On #26, a later count found 4 real bugs among the 38 applied
findings.

Three things kept the loop going:

1. **Nothing fixed to measure against.** Each round reviewed the previous
   round's corrections against "anything that could go wrong", not against the
   spec. Every patch gave the next round new surface. #31 spent thirteen rounds
   reshaping its rules for removing private details from a public issue; each
   rewrite drew findings from the opposite direction.
2. **Corrections that added behaviour.** On #30 a finding asked for a message
   the spec did not have; the fix opened new cases, and about eight rounds went
   into that one addition before it was removed and the text put back to the
   spec's wording.
3. **Declining was harder than applying.** A hypothetical setup framed as a
   correctness defect could not be declined, and declined findings came back
   in the next round unless the implementer listed them in the review prompt by
   hand.

## What the research says

1. **Most of the value comes in the first two or three rounds; after that,
   more rounds can make things worse.** Studies of iterative self-refinement
   find the largest gains in rounds one and two and a plateau around three.
   Several models get worse with more correction rounds, because each
   correction can introduce an error. One 2026 paper treats this as a stability
   condition: iterating only helps while the rate of newly introduced errors is
   near zero, and a single instruction ("only change your answer if you find a
   concrete, specific error") brought that rate to zero
   ([Self-correction as feedback control](#sources)).
2. **Non-convergence is a known failure, and the fixes are severity gates and
   escalation, not more rounds.** One open-source agent saw 11 consecutive
   rounds, each with one to three new, mostly low-severity findings; their fix
   suppresses new low-severity findings after round 4 and reports only medium
   or higher ([fullsend-ai #1294](#sources)). Contrast Security saw findings grow
   from 1 to 37 across three rounds, because several reviewers phrased the same
   fix differently; they recommend escalating to a person whenever blocking
   findings do not strictly fall from one round to the next
   ([When AI reviewers cannot agree](#sources)). Published guidance puts the
   ceiling at two to three rounds for self-review and three to five for
   interactive review, always with escalation
   ([Agent self-review loop](#sources), [Multi-model convergence loops](#sources)).
3. **A review converges against a fixed reference.** A 2026 case study made an
   agent converge on a 189-file change with no human code review by auditing
   the code, pass after pass, against a frozen written spec until two passes in
   a row found nothing. It cites the finding that a model revising its own
   output with nothing external to compare against does not improve and can
   get worse ([Specification-first convergence](#sources)).
4. **The reference tools filter hard.** Anthropic's own code-review plugin
   scores every finding from 0 to 100 and reports only those at 80 or above
   ("real and important"); it drops pre-existing issues, pedantic nitpicks,
   anything a linter catches, and general quality unless the repo's
   `CLAUDE.md` asks for it ([code-review plugin](#sources)). Google's review
   standard approves a change once it improves the code's health, not when it
   is perfect; optional polish is marked "Nit" and never blocks
   ([Google: the standard of code review](#sources)).

## What we propose

For [#33](https://github.com/Vorski-Imagineering/gogogo/issues/33). These are
proposals until the issue's Approvals table records the owner's decisions; the
skills still follow the rules above.

1. **The spec is the yardstick.** A round applies a finding only when the
   change does not do what the spec says, breaks something that already works,
   or has a bug a real repo or a real run would hit. Everything else is
   declined with a one-line reason: hypothetical setups, style, settled
   decisions, reversals of an earlier fix.
2. **Beyond the spec is a follow-up, never a fix.** A correction may not add
   behaviour the spec does not have. A finding that asks for new behaviour goes
   into the issue's report for a person to decide.
3. **Verify before changing.** Before applying a finding, confirm it with a
   concrete case: reproduce it, or trace it to a line and a real input. This is
   the instruction the feedback-control paper found decisive.
4. **Carry decisions forward.** Each round reviews only the previous round's
   corrections, and is given the findings already declined and the decisions
   the spec settled, so they are not raised again.
5. **Watch the trend, and escalate instead of grinding.** Rounds one to three
   follow the rules above. From round four, only a real correctness defect is
   applied; everything else becomes a follow-up. If round six still finds a real
   correctness defect, the issue stops for a person: a loop that will not
   settle usually means a gap in the spec or the design, which is a person's
   decision.

Point 5 replaces #17's "there is no round limit". It keeps #17's goal, that
nothing merges unreviewed, by stopping for a person rather than merging.

## Sources

All retrieved 2026-10-02. "Read" means the page itself was read for this
write-up; "summary" means only a search result's summary was seen.

- Abenhaïm, J. *Specification-first convergence with an AI coding agent: a case
  study of dismantling a core architectural invariant across 189 files in a
  717k-line codebase with no test oracle and no human code review*, 31 July
  2026. <https://arxiv.org/pdf/2608.12440>. Read (pages 1–4).
- *Self-Correction as Feedback Control: Error Dynamics, Stability Thresholds,
  and Prompt Interventions in LLMs*. <https://arxiv.org/html/2604.22273v2>.
  Read.
- fullsend-ai/agents issue #1294, *Review agent should detect non-converging
  review loops and suppress low-severity new findings*.
  <https://github.com/fullsend-ai/agents/issues/1294>. Read.
- Contrast Security, *When AI Reviewers Cannot Agree*.
  <https://www.contrastsecurity.com/security-influencers/when-ai-reviewers-cannot-agree>.
  Read.
- AgentPatterns.ai, *Agent Self-Review Loop for Iterative Self-Improvement*.
  <https://agentpatterns.ai/code-review/agent-self-review-loop/>. Read.
- Zylos Research, *Multi-Model AI Code Review: Convergence Loops and Automated
  Quality Assurance*, 1 March 2026.
  <https://zylos.ai/research/2026-03-01-multi-model-ai-code-review-convergence/>.
  Read.
- Anthropic, Claude Code `code-review` plugin README.
  <https://github.com/anthropics/claude-code/blob/main/plugins/code-review/README.md>.
  Read.
- Madaan et al., *Self-Refine: Iterative Refinement with Self-Feedback*, 2023.
  <https://arxiv.org/pdf/2303.17651>. Summary.
- Emergent Mind, *Iterative Self-Refinement* (topic overview).
  <https://www.emergentmind.com/topics/iterative-self-refinement>. Summary.
- Google Engineering Practices, *The Standard of Code Review* (mirror).
  <https://xcd0.github.io/eng-practices-ja-mdbook/review/reviewer/standard.html>;
  original at <https://google.github.io/eng-practices/review/reviewer/standard.html>.
  Summary.
- Augment Code, *CodeRabbit vs Greptile vs Augment Cosmos: AI Code Review
  Compared* (precision against recall of review tools).
  <https://www.augmentcode.com/tools/coderabbit-vs-greptile-vs-augment-cosmos>.
  Summary.
