# When is enough enough? Ending the review loop

Every change an agent makes here is reviewed by another model before it
merges, and every fix the review asks for is reviewed again. That loop is what
lets the queue run unattended. It also has a failure that decides how well the
whole system works: it does not always stop. This page records what we saw, what
the research said in October 2026, and what we decided to do about it
([#33](https://github.com/Vorski-Imagineering/gogogo/issues/33)).

The state of the art here is moving fast. The sources below carry the date we
read them; check them again before relying on this page.

## What the skills do today

Since [#33](https://github.com/Vorski-Imagineering/gogogo/issues/33),
`/gogogo:dev` §5 judges each finding by evidence. Round 1 reviews the whole
change against the issue's spec, at the profile's `review.coverage`. Every
later round reviews only the corrections, at `precise`. A finding is applied
when it shows one of these:
- the change fails the spec or a `CLAUDE.md` rule;
- it breaks something that worked;
- a bug, with a concrete case;
- a security, data-loss or unapproved-Hard-Stop risk.

A small addition the spec does not have may be applied, with a test.
Everything else is declined with a reason word. Each finding gets three
attempts, a correction is never undone and redone, and prose files get two
rounds each, even inside a code change.

A review ends `clean` when a round applies nothing. It ends with a person on:
- a third attempt that is still wrong;
- a reversal the spec doesn't settle;
- an unfixable finding;
- a prose fix in the second round;
- the breaker, at round 13.

Every report ends with a record of the review (`v=2`). `review_stats.py`
prints them as a table, with each issue's outcome and any later bug traced
back to the review that let it through. To read the numbers:
- **Rounds** and **ended** say whether reviews converge.
- **Refix rate** is the share of applied findings that fixed an earlier fix: a
  high one means the attempts rule is doing work.
- **Declined by reason** shows what the reviewer raises that does not matter.
- **Escaped bugs**, declined against missed, say whether the judgement is too
  strict (declined) or the coverage too narrow (missed).

The attempt limit, the breaker and the default coverage change only in an
issue that cites `review_stats.py` output.

### What the skills did before

From [#17](https://github.com/Vorski-Imagineering/gogogo/issues/17) until #33,
`/gogogo:dev` §5 reviewed a code change with `/code-review high`, then
reviewed each round's corrections, round after round, **until a round applied
nothing**. There was no round limit. A finding the reviewer called a
correctness defect could not be declined: it was fixed, or the issue stopped
for a person. A prose-only change got two rounds at most.

The aim was right: nothing merges unreviewed, and corrections, where defects
enter, are reviewed too. In practice the loop often did not converge.

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

## What we decided

Decided on 2026-10-02 and specified in
[#33](https://github.com/Vorski-Imagineering/gogogo/issues/33).

1. **Evidence decides what is applied.** A round applies a finding only when
   the change fails the spec or a rule in the repo's `CLAUDE.md`, breaks
   something that worked, or has a bug shown by a concrete case: for code, a
   test that fails; for prose, a named, real situation. Everything else is
   declined with a recorded reason, even when the reviewer calls it a
   correctness defect. The exception is harm that costs most: where the
   consequence would be a security hole, lost data or an unapproved Hard Stop
   change, a plausible finding is fixed or goes to a person.
2. **A small addition beyond the spec may be applied.** Small means: it touches
   no Hard Stop, adds no new user-visible behaviour, setting or message, stays
   inside the files the spec lists, and has a test. It is named in the report.
   If a later round finds a defect in the addition, it is removed and becomes a
   follow-up; it is not patched again. Anything larger is a follow-up for a
   person.
3. **Prose is judged per file.** Markdown and text files get the prose rule
   (two rounds at most) even inside a change that also has code. Most of the
   churn above was skill text reviewed under the code rule.
4. **Three attempts per finding, and no flip-flops.** After the first round a
   review looks only at the corrections, so a real defect there means a fix was
   wrong. The second attempt must say what the first got wrong and take a
   different approach. A real defect in the third attempt sends the issue to a
   person, with the three attempts. A finding that would undo an earlier
   correction is never applied a second time: the spec's reading stands, and
   where the spec is silent a person decides. This replaces #17's "no round
   limit" with a rule about what a round means; in practice a review ends in
   about four rounds.
5. **A circuit breaker at 13 rounds.** Not a rule to steer by: if a review ever
   gets that far, the loop itself has misbehaved, and the issue stops for a
   person. We hope it is only bad luck that hits it.
6. **Coverage is set per repo.** A repo's profile may set `review.coverage` to
   `precise` (only findings the reviewer is confident in), `broad` (a wider
   net, some less certain; the default) or `exhaustive`. The first round runs
   at that coverage; every correction round runs at `precise`. What a repo
   treats as serious is written as rules in its `CLAUDE.md`, which the
   reviewer reads.
7. **The loop keeps its own numbers.** Each issue's review record carries why
   findings were applied or declined, how many fixes were fixes of fixes, how
   the review ended, and which models wrote and reviewed the change. A
   read-only script, `review_stats.py`, prints the table above from those
   records, with each issue's outcome and any later bug traced back to it. The
   attempt limit, the breaker and the default coverage change only on those
   numbers.

Not taken: a fixed round limit as the rule, depth presets, a setting for the
reviewer's model (the record notes the models instead), and a second agent to
judge findings.

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
- Anthropic, Claude Code documentation: *Code Review* (`/code-review` effort
  levels; `REVIEW.md` guidance on re-review convergence and a verification
  bar), *Skills* and *Subagents* (how a subagent's model is chosen).
  <https://code.claude.com/docs/en/code-review>,
  <https://code.claude.com/docs/en/skills>,
  <https://code.claude.com/docs/en/sub-agents>. Read.
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
