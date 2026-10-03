# Process measures

What to measure about the gogogo process, so it can be judged on quality,
speed and token cost instead of on impressions. Each measure says what
question it answers, exactly how it is computed, where the data is, whether
the history a repo already has can answer it, and whether the number may be
published. Part 1 of the process review
([#47](https://github.com/Vorski-Imagineering/gogogo/issues/47),
[process-review-2026-10.md](process-review-2026-10.md)) defines them; part 2
computes them from one adopting repo's history (in that repo's own tracker).

Written 2026-10-02. The data sources were checked against the skills on `main`
at `6dd73fc` and against a Claude Code 2.1.287 transcript.

## Sources

| Key | Source | What it holds | Kept for |
|---|---|---|---|
| **G** | git history of `integration.base` | merge commits and their times; `Ships-issue` trailers (`references/stage-sync.md`); `Revert "…"` commits | forever |
| **T** | `deploy-*` tags | which commits each production release carried, and when (`references/versioning.md`) | forever |
| **I** | issue events (GitHub REST `issues/{n}/events`, `timeline`) | created, `labeled` / `unlabeled` (the ready label, auto-test labels), closed, reopened, each with a time | forever |
| **C** | issue comments | the per-issue review record `<!-- gogogo:review … -->` (`skills/dev/SKILL.md:199`); the `**Needs you:**` first line of a hand-back (`skills/dev/SKILL.md:220-230`); auto-test outcome comments (`skills/auto-test/SKILL.md:14-23`); stage sync's `<!-- stage-sync … -->` marker | forever |
| **P** | pull requests | created and merged times, checks, for `pr-squash` and `run-branch-pr` | forever |
| **B** | board item history | when a card entered and left each column | not confirmed: the shared `tracker.py` reads current columns only; whether GitHub exposes column-change history for a Project item has to be checked before relying on it |
| **X** | Claude Code session transcripts, `~/.claude/projects/<folder>/<session>.jsonl` on the machine that ran the session | per line: `sessionId`, `timestamp`, `gitBranch`, `isSidechain`; per model reply: `usage` (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`); `cost-state` lines with `totalCostUSD` | **30 days by default**: Claude Code deletes session data older than `cleanupPeriodDays` at startup ([costs](https://code.claude.com/docs/en/costs), read 2026-10-02) |
| **O** | Claude Code OpenTelemetry, when enabled | `claude_code.token.usage`, `claude_code.cost.usage`, `claude_code.active_time.total`, `claude_code.commit.count`, `claude_code.pull_request.count`, each with `session.id`; custom labels through `OTEL_RESOURCE_ATTRIBUTES` ([monitoring](https://code.claude.com/docs/en/monitoring-usage), read 2026-10-02) | as long as the collector keeps it |
| **R** | the run report and between-issues log of `/gogogo:auto-dev` (`skills/auto-dev/SKILL.md:313-356`), and notify messages | issues taken, skipped and why, stops, merges per run | the narrative **only in the session**; since #63 each triage skip is a `gogogo:skip` marker on its issue, and a run is the set of markers sharing a session id (C) |

## Who may see what

- **Quality and speed numbers may be public.** They are about issues and
  commits that are already public wherever the tracker is.
- **Token counts and cost stay on the owner's machine**, or in the adopting
  repo when it is private. They are never written to a public tracker or to
  this repository.
- **Transcripts are never quoted.** A measure reads counts, times, session ids,
  session names and branch names from them, and nothing of what was said.

## Linking a session to its issue

Speed per phase and tokens per issue need to know which issue a stretch of a
session was about. In order of preference:

1. **The branch.** Every transcript line carries `gitBranch`, and issue work
   happens on `fix/<n>-<slug>` (`skills/auto-dev/SKILL.md:117-122`,
   `skills/dev/SKILL.md:98-109`). Lines on that branch belong to issue `n`.
   Lines on the base branch between two issues (triage, selecting the queue,
   preflight) belong to the run, not an issue. Works on past transcripts, for
   as long as they are kept.
2. **The session name** given with `-n` at launch
   (`skills/auto-dev/SKILL.md:387-392`) ties a session to a run.
3. **A session id in the per-issue record** (since #62): the review record's
   `session=` names the session that produced the change, so a transcript can
   be found from the issue without guessing.

`OTEL_RESOURCE_ATTRIBUTES` is set once per process, so it can label a run but
not the issues inside one; the branch is the per-issue key.

## The measures

"History" says whether a repo's existing history can answer it: **yes**,
**partly** (some of the period, or with a stated gap), or **no**.

### Quality: does it ship working changes?

| Measure | Question | Definition | Unit | Source | History | Public or local | Recording that would close the gap |
|---|---|---|---|---|---|---|---|
| **Q1 Escaped defects** | How often does a shipped issue cause a later bug? | shipped issues later named as the cause of a new issue ÷ shipped issues, per period | ratio, with n | I, C | **partly**: since #51, the fixing issue's review record names the issue that introduced the bug; older bugs only by a person tagging them | public | `escaped_from=` and `escaped_as=` in the fixing issue's review record (`/gogogo:dev` §7, #51), reported by `scripts/review_stats.py` |
| **Q2 First-pass confirmation** | Does the fix work when a person (or auto-test) checks it? | issues whose first auto-test verdict is PASS ÷ issues with at least one verdict | ratio, with n | C (auto-test comments), I (labels) | **yes** where auto-test ran; **no** elsewhere | public | none where auto-test runs; elsewhere, the person's confirmation (closing as completed) is the only signal |
| **Q3 Reverts and reopens** | How often is shipped work taken back? | (`Revert` commits of a `Ships-issue` commit + issues reopened after a close) ÷ shipped issues | ratio, with n | G, I | **yes** | public | none |
| **Q4 Needs-you rate, by reason** | How often does the loop stop for a person, and why? | issues handed to `needs_human` ÷ issues taken, split by reason: Hard Stop or decision, review stop, verification abandoned, gate or CI failure, other | ratio per reason, with n | C (`**Needs you:**` lines), I | **partly**: the line's wording dates from the shared plugin; earlier local skills wrote other forms | public | the `<!-- gogogo:stop v=1 reason=… -->` marker under the Needs-you line (`/gogogo:dev` §8, since #62), counted by `scripts/review_stats.py` |

### Quality: are the specs good enough?

| Measure | Question | Definition | Unit | Source | History | Public or local | Recording that would close the gap |
|---|---|---|---|---|---|---|---|
| **Q5 Triage skips** | How often does a queued issue turn out not to be workable? | issues skipped at triage ÷ issues read from the queue, per run | ratio, with n | C | **no** before #63: the run report was not kept | public | the `gogogo:skip` marker on the skipped issue, read by `review_stats.py` |
| **Q6 Spec edits after ready** | How often does a spec change after it was called ready? | specced issues whose body was edited after the ready label was added ÷ specced issues | ratio, with n | I (`labeled` time), issue edit history | **partly**: edit history is readable through GitHub's GraphQL `userContentEdits`, not REST | public | none |

### Quality: is the review worth it?

| Measure | Question | Definition | Unit | Source | History | Public or local | Recording that would close the gap |
|---|---|---|---|---|---|---|---|
| **Q7 Review rounds and yield** | How long does review take to settle, and how much does it change? | per issue: `rounds`; sum of `applied`; `applied` in rounds after the first (fixes of fixes); `stopped`. Median and spread per period | rounds, findings | C (review record) | **partly**: since the record format (#17); earlier issues have none | public | since #51, the record says why each finding was applied or declined, and `scripts/review_stats.py` reads it back |
| **Q8 Review precision** | How many applied findings were real defects? | applied findings later judged real ÷ applied findings | ratio, with n | C | **no**: needs a person's judgement per finding, as was done once for #26 | public | `scripts/review_stats.py` (#51) tracing a later bug to the review that passed it, from `escaped_from` (Q1) |

### Speed

| Measure | Question | Definition | Unit | Source | History | Public or local | Recording that would close the gap |
|---|---|---|---|---|---|---|---|
| **D1 Deployment frequency** | How often does work reach users? | production releases per week: `deploy-*` tags, or merges to the base where a merge is the release | per week | T, or G | **yes** | public | none |
| **D2 Lead time** | How long from "ready" to "live"? | per shipped issue: ready label added → merge commit (`Ships-issue`) → first `deploy-*` tag containing it; median of each leg | hours | I, G, T | **yes** where trailers and tags exist; issues merged without a trailer are counted as unlinked, not guessed | public | none |
| **D3 Change failure rate** | How often does a release need fixing? | releases followed, before the next release, by a revert, an auto-test FAIL, or a reopen of an issue it shipped ÷ releases | ratio, with n | T, G, C, I | **partly**: auto-test only where it ran | public | none |
| **D4 Time to restore** | How long is a failed release left failed? | FAIL verdict or reopen → first release containing a fix linked to the same issue; median | hours | C, I, G, T | **partly** | public | none |

### Speed: where the time goes

| Measure | Question | Definition | Unit | Source | History | Public or local | Recording that would close the gap |
|---|---|---|---|---|---|---|---|
| **P1 Time per phase** | Where does an issue's time go? | per issue, wall time between: branch created, first commit, review start, review end, verification end, merge verified | minutes | X (first and last line on the issue's branch; skill and tool calls in between), G | **partly**: start and end from X for the last 30 days; the phases inside need markers | public (times only) | `t_branch=` and `t_verified=` in the review record (since #62); the review end is the report's posted time, and the merge comes from G and P |
| **P2 Run size and length** | How much does one unattended run get through? | per run: issues taken, merged, sent to a person, skipped; wall time | count, hours | C, X | **partly**: X for the last 30 days, by session | public | the `sessions:` section of `review_stats.py`, from markers sharing a session id |
| **P3 Owner wait** | How long does work wait for the owner? | (a) time a card spends in `needs_human`; (b) time from entering the `verify.human` stage's column to closed as completed | hours | B, I | **partly**: (b) from the close event if the stage entry is known; (a) needs board history | public | a hand-back comment already marks entry to `needs_human`; a comment or event when the owner moves it on would close (a) |

### Token efficiency

| Measure | Question | Definition | Unit | Source | History | Public or local | Recording that would close the gap |
|---|---|---|---|---|---|---|---|
| **K1 Tokens per merged issue** | What does a shipped issue cost? | per merged issue: sum of `usage` over transcript lines on its `fix/<n>-…` branch, main session and side chains; median per period. Report input, output, cache read, cache write separately | tokens | X | **partly**: only sessions still on disk (30 days by default) | **local** | `session=` in the review record (since #62; see *Linking*); OpenTelemetry for a durable copy |
| **K2 Cost per merged issue** | The same, in money | `totalCostUSD` growth across the issue's lines, or K1 at list price | USD | X | **partly**, as K1 | **local** | as K1 |
| **K3 Tokens spent on work that did not ship** | What do stops and skips cost? | K1 summed over issues sent to `needs_human` or abandoned, plus run lines on the base branch, ÷ all tokens in the run | ratio | X, C | **partly**, as K1 | **local** | as K1 |
| **K4 Review's share** | How much of an issue's cost is review? | tokens in `/code-review` side chains and their correction turns ÷ K1, per issue | ratio | X (`isSidechain`, the skill call) | **partly**, as K1 | **local** | phase markers (P1) |

## For part 2

Compute in this order. Each line says what it needs from the adopting repo.

1. **D1 Deployment frequency**: `deploy-*` tags, ordered by tag date, not name.
2. **D2 Lead time**: `Ships-issue` trailers, tags, and the ready label's `labeled` events on the issues repo.
3. **Q3 Reverts and reopens**: `Revert` commits on the base; reopen events.
4. **Q2 First-pass confirmation**: auto-test comments and labels.
5. **D3 Change failure rate** and **D4 Time to restore**: 1-4 together.
6. **Q4 Needs-you rate**: hand-back comments; count the ones in another format as unparsed, per period.
7. **Q7 Review rounds and yield**: review records.
8. **Q6 Spec edits after ready**: edit history, through GraphQL.
9. **K1-K4**: transcripts on the owner's machine, for the days they cover; say which days.
10. **P1 Time per phase** (start and end only) and **P2 Run size**: transcripts.

Report as *no data*, with the reason, never as zero: Q1, Q5 (before #63), Q8, the inside of
P1, and P3 (a) unless board history turns out to be readable.

Every number is given per period with its sample size. A period with a few
issues gives a number, not a trend.
