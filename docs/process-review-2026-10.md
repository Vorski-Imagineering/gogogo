# Process review, October 2026

A check of the whole gogogo process, done once, on 2026-10-02
([#47](https://github.com/Vorski-Imagineering/gogogo/issues/47)). It asks
three things:

1. **Against current practice:** where does the process match, deliberately
   depart from, or fall short of what DORA, GitHub, OpenSSF, OWASP and
   Anthropic recommend?
2. **The flow:** can one issue be followed from report to Done, in every merge
   shape, without confusion or a card left stranded?
3. **What to measure:** defined in its own file,
   [process-measures.md](process-measures.md), so the process can be judged on
   quality, speed and token cost. Part 2 computes them from one adopting repo's
   history, in that repo's tracker.

Everything here was read at `main` `6dd73fc`. Nothing in `plugins/gogogo/` was
changed. The findings at the end are written down, not filed: the owner picks
which become issues. Line references are to that commit.

**Since this was read.** Later the same day #50 and #51 landed on `main`.
#51 put #33's rule into the skills: a review finding is applied only on
evidence, with three attempts per finding and a person after 13 rounds, and
`scripts/review_stats.py` reads the review records back. That narrows A13
(findings are now judged against the spec; the diff is still not checked
against it, #44) and gives Q7 and Q8 in [process-measures.md](process-measures.md)
a reader. No finding below is resolved by them. Line references stay at
`6dd73fc`.

**Settled before this review, not re-argued here:** the comparison of the git
and PR process made the same day (branch per issue, squash merge, gates and CI,
the `Ships-issue` link, annotated release tags); the owner's position that
nobody hand-reviews code except the core data model; no second or stronger
reviewer and no random audits; and the issues already filed (#33, #34, #40,
#41, #42, #44, #45).

## A. Against current practice

### Sources

Retrieved 2026-10-02. **Read** means the page itself was read; **summary** means
only a search result's summary was seen, because the page was blocked by this
session's network policy (`dora.dev`, `docs.github.com`, `genai.owasp.org`).
GitHub's documentation was read from its source repository instead.

| Key | Source | Read or summary |
|---|---|---|
| DORA-TBD | DORA, *Trunk-based development* capability. <https://dora.dev/capabilities/trunk-based-development/> | summary |
| DORA-CA | DORA, *Streamlining change approval* (2019 State of DevOps findings). <https://dora.dev/capabilities/streamlining-change-approval/> | summary |
| DORA-CD | DORA, *Continuous delivery*, *Test automation*, *Monitoring and observability* capabilities. <https://dora.dev/capabilities/monitoring-and-observability/> | summary |
| GH-FLOW | GitHub Docs, *GitHub flow*. <https://github.com/github/docs/blob/main/content/get-started/using-github/github-flow.md> | read |
| GH-PROT | GitHub Docs, *About protected branches*. <https://github.com/github/docs/blob/main/content/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches.md> | read |
| GH-MERGE | GitHub Docs, *About pull request merges*. <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/about-pull-request-merges> | summary |
| GH-LINK | GitHub Docs, *Linking a pull request to an issue*. <https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue> | summary |
| SCORECARD | OpenSSF Scorecard, *Checks* (Branch-Protection, Code-Review, CI-Tests, Signed-Releases). <https://github.com/ossf/scorecard/blob/main/docs/checks.md> | read |
| OWASP-06 | OWASP Top 10 for LLM Applications 2025, *LLM06 Excessive Agency*. <https://github.com/OWASP/www-project-top-10-for-large-language-model-applications/blob/main/2_0_vulns/LLM06_ExcessiveAgency.md> | read |
| CC-BP | Anthropic, *Best practices for Claude Code*. <https://code.claude.com/docs/en/best-practices> | read |
| CC-OTEL | Anthropic, *Monitoring usage* and *Manage costs* (Claude Code). <https://code.claude.com/docs/en/monitoring-usage>, <https://code.claude.com/docs/en/costs> | read |
| PR-SIZE | Pull request size studies, via Graphite's guide (review quality falls past 200 to 400 lines). <https://graphite.dev/guides/best-practices-managing-pr-size> | summary |

### Scorecard

Verdicts: **matches**; **deliberate departure, reason written** (where the reason is
written is cited); **deliberate departure, no reason written**; **gap**.

| # | Practice | Source | What gogogo does | Verdict | Note |
|---|---|---|---|---|---|
| A1 | Short-lived branches, few at a time, merged to trunk at least daily | DORA-TBD | One issue at a time, each cut from a freshly pulled base, merged within the run (`skills/auto-dev/SKILL.md:117-132`, `:8-13`) | matches | Branches of stopped issues are kept on purpose and can age (`skills/auto-dev/SKILL.md:145-171`); `stranded_work.py` reports them but nothing ages them out |
| A2 | One branch per set of unrelated changes; delete it after the merge | GH-FLOW | `fix/<n>-<slug>` per issue, `--delete-branch` on merge (`skills/dev/SKILL.md:98-109`, `:323`) | matches | |
| A3 | Small batches: a review falls off past a few hundred lines | PR-SIZE, DORA-CD | One issue per PR; a spec whose hand check needs thirty steps is "too big for one issue" (`skills/spec/SKILL.md:98-99`). No limit on the size of the change itself | gap | Already named on 2026-10-02 |
| A4 | Tests run automatically before every merge | SCORECARD (CI-Tests), DORA-CD | New test seen failing, every lane run (`skills/dev/SKILL.md:156-184`); PR checks waited for and judged per check (`skills/auto-dev/SKILL.md:191-213`); "zero checks is a failure" under `run-branch-pr` (`:239`) | matches | Under `merge-script` the repo's script decides; when it runs no suite, the loop's own run is the only test (`skills/auto-dev/SKILL.md:232-234`) |
| A5 | Protect the default branch: no force push or deletion, required status checks | SCORECARD (Branch-Protection), GH-PROT | `/gogogo:setup` checks the profile, board and label, not branch protection (`skills/setup/SKILL.md:3`). This repo's `main` is unprotected (GitHub API, 2026-10-02) | gap | |
| A6 | Every change reviewed before merge; bot reviews do not count | SCORECARD (Code-Review), DORA-CA | `/code-review` in a fresh subagent, round after round (`skills/dev/SKILL.md:122-152`); no person reads the code, except the core data model | deliberate departure, no reason written | The owner's position is written only in #47's body, not in the README or a doc |
| A7 | Change approval by lightweight peer review and automation, not an external board | DORA-CA | Decisions approved once, up front, in the spec's Approvals table (`skills/spec/SKILL.md:106-125`); Hard Stops need a row (`skills/dev/SKILL.md:66-79`); no approval step per change | matches | See *The owner's stance* below |
| A8 | A person approves high-impact actions before they are taken | OWASP-06 | Hard Stops and two-licence apply rows need the owner's row first (`skills/spec/SKILL.md:211-235`); a release merge is made by the agent when every gate passed (`skills/auto-dev/SKILL.md:48-56`) | deliberate departure, reason written | Reason: `README.md:150-153` (*A release only after every gate*) and #29 |
| A9 | Enforce authorisation in the system that acts, not by the model's judgement | OWASP-06, CC-BP (hooks are deterministic, instructions advisory) | Every gate, the unattended check, the merge conditions and "never to Done" are skill text the agent follows; GitHub enforces none of them | gap | The highest-value gap: see finding F1 |
| A10 | Least privilege for the agent | OWASP-06, CC-BP (allowlists, sandboxing, auto mode) | The loop requires `bypassPermissions` and refuses any other mode (`scripts/require_unattended.sh:1-10`, `skills/auto-dev/SKILL.md:57-66`) | deliberate departure, reason written | Reason: an unattended run must not stall on a prompt (`scripts/require_unattended.sh:4-6`). Auto mode now also runs without prompts, with a classifier that blocks risky actions, and is the default since Claude Code 2.1.283 (CC-BP); the reason does not consider it |
| A11 | Give the agent a check it can run, and evidence instead of assertions | CC-BP | The seen-failing test and the run on real data (`skills/dev/SKILL.md:156-184`); the hand-back reports rungs, red tests and what the real run showed (`skills/dev/SKILL.md:186-213`) | matches | |
| A12 | Explore, plan, then build from a self-contained spec with out-of-scope and an end-to-end check | CC-BP | `/gogogo:spec` writes Files with *explicitly not in scope*, Verification, and Verify by hand (`skills/spec/SKILL.md:50-62`) | matches | |
| A13 | A fresh-context review that checks the diff against the plan and flags only what affects correctness or the requirements | CC-BP | `/code-review` reviews the diff for bugs, not against the spec (`skills/dev/SKILL.md:122-152`); findings are not filtered to the spec yet | gap | Filed: #44 (check against the spec); #33 (findings judged against it) shipped in #51 after this was read |
| A14 | Link the change to the issue without closing it before it is confirmed | GH-LINK | `Refs #<n>` and a `Ships-issue` trailer; closing references checked before merge, reopened after (`skills/dev/SKILL.md:265-298`, `references/stage-sync.md:36-37`) | deliberate departure, reason written | Reason: closing keywords close the issue at merge, before anyone saw the fix (`references/stage-sync.md:36-37`) |
| A15 | Squash for one logical change; keep history where commits matter | GH-MERGE | `pr-squash` per issue; the `run-branch-pr` final PR by merge commit (`skills/auto-dev/SKILL.md:240-249`) | matches | |
| A16 | Signed releases | SCORECARD (Signed-Releases) | Annotated `deploy-<build>` tags, unsigned (`references/versioning.md:25-27`) | gap | Low value for a private app; listed for completeness |
| A17 | Watch the system after a release | DORA-CD (monitoring) | `observability` is read before code when an issue comes in (`skills/dev/SKILL.md:52-55`); nothing looks at a release after it ships | gap | |
| A18 | Measure delivery: deploy frequency, lead time, failure rate, time to restore | DORA-CD | Nothing is measured; the review record is the only per-issue data (`skills/dev/SKILL.md:194-203`) | gap | [process-measures.md](process-measures.md) defines them |

### The owner's stance against DORA's findings on change approval

The stance: decide up front (the spec and its Approvals), verify behaviour on
a real environment, and read no code except the core data model.

**Where it agrees with the research.** DORA found that external change
approval boards slow delivery (lead time, deploy frequency, time to restore)
and show no link to a lower change failure rate; boards approved over 90% of
what they saw (DORA-CA, summary). It recommends approval during development,
by peer review, backed by automation that catches bad changes early. gogogo
has no board and no per-change approval. Its one approval step records
*decisions*, not changes, before any code exists, and the rest is automation:
tests seen failing, gates, CI, a run on real data. On the evidence DORA has,
that is the right shape.

**Where it relies on something the research does not support.** DORA's
alternative to a board is *peer* review. gogogo replaces the peer with a model
reviewing in a fresh context. DORA's data predates coding agents and says
nothing about model review as a substitute; OpenSSF's Code-Review check
explicitly does not count a bot's review (SCORECARD). So the stance is not
contradicted, but it is unsupported: whether model review plus automation
catches what peer review would have is an open question, and the only way to
answer it for this process is to measure what escapes (Q1, Q3 and D3 in
[process-measures.md](process-measures.md)). DORA's own emphasis on automation
also means the stance is only as strong as the tests: hence #45 (mutation
testing) and finding F7 (tests guarded by nobody).

## B. The flow

### The four shapes

Columns are the board's standard ones (`README.md:258-262`). The first rows are
the same in every shape:

| Event | From | To | Moved by | Rule |
|---|---|---|---|---|
| Issue filed | (none) | ⚡️ New | the board's own workflow | `README.md:261` |
| Spec posted and linted | ⚡️ New / Backlog | (label `dev ready` added) | `/gogogo:spec` | `skills/spec/SKILL.md:345-361` |
| Owner agrees to queue it | any | Dev Ready | `/gogogo:spec`, on a yes | `skills/spec/SKILL.md:362-378` |
| Loop takes it | Dev Ready | In progress | `/gogogo:auto-dev` | `skills/auto-dev/SKILL.md:128-129` |
| Hard Stop or missing decision mid-change; review stop; verification abandoned after three attempts; gate failure | In progress | Human!Help! (ready label removed) | the loop | `skills/auto-dev/SKILL.md:145-171`, `:179-184`; `skills/dev/SKILL.md:220-242` |
| Owner has done what the Needs-you line asked | Human!Help! | wherever the owner puts it | a person | `skills/dev/SKILL.md:237-239` |

**1. Straight to production, `pr-squash`** (this repo):

| Event | From | To | Moved by | Rule |
|---|---|---|---|---|
| PR checks fail, or none ran where CI is required | In progress | Human!Help! (PR left open) | the loop | `skills/auto-dev/SKILL.md:204-217` |
| PR squash-merged; `verify_merged.py` says MERGED | In progress | Released (the first and only stage) | the loop | `skills/auto-dev/SKILL.md:260-294`; `skills/dev/SKILL.md:234-235` |
| Owner confirms on production | Released | Done, issue closed | a person; or `/gogogo:auto-test` on PASS when configured | `README.md:143`; `skills/auto-test/SKILL.md:14-17` |

**2. A pre-production site first, then a tagged release** (for example "In
Dev", then "In Production" on `deploy-*`):

| Event | From | To | Moved by | Rule |
|---|---|---|---|---|
| Merge verified | In progress | In Dev (first stage) | the loop | `skills/auto-dev/SKILL.md:293-294` |
| Merge verified but `Ships-issue` missing (exit 3) | In progress | In Dev, flagged | the loop | `skills/auto-dev/SKILL.md:278-281` |
| A `deploy-*` tag contains every linked commit | In Dev | In Production, with a "now live" comment | `stage_sync.py`, run by the repo's CI | `references/stage-sync.md:75-80` |
| Tag pushed, card has no link | In Dev | stays: moved by hand | a person | `skills/auto-dev/SKILL.md:278-281`; `references/stage-sync.md:90` |
| Auto-test PASS on the `verify.human` stage's column | that column | `auto_test.pass_column` (for example Done), closed when `pass_closes` | `/gogogo:auto-test` | `skills/auto-test/SKILL.md:14-17`; `references/profile-schema.md:265-270` |
| Auto-test FAIL | that column | `auto_test.fail_column`, label added | `/gogogo:auto-test` | `skills/auto-test/SKILL.md:17` |
| Auto-test NEEDS HUMAN, NOT DEPLOYED or HELD | that column | stays | none | `skills/auto-test/SKILL.md:18-20` |

**3. `run-branch-pr`:**

| Event | From | To | Moved by | Rule |
|---|---|---|---|---|
| Issue PR into the run branch squash-merged and verified | In progress | the run-branch stage's column | the loop | `skills/auto-dev/SKILL.md:235-239`, `:293` |
| Issue PR with failing checks, or zero checks | In progress | Human!Help! | the loop | `skills/auto-dev/SKILL.md:208-217`, `:239` |
| Final PR is a release and its checks pass | run-branch stage | next stage, after a merge commit and the `--open` check | the loop | `skills/auto-dev/SKILL.md:240-245`, `:300-311` |
| Final PR is a release and its checks fail | run-branch stage | stays; the whole run stops | the loop | `skills/auto-dev/SKILL.md:242-245`, `:361-362` |
| Final PR is not a release; a person merges it after the run | run-branch stage | **stays: nothing named moves it** | none | `skills/auto-dev/SKILL.md:245`, `:300-311`; finding F2 |

**4. `merge-script`** (for example a script that pushes, opens a PR and
squash-merges):

| Event | From | To | Moved by | Rule |
|---|---|---|---|---|
| `integration.command` merges; `verify_merged.py <pr>` says MERGED | In progress | first stage | the loop | `skills/auto-dev/SKILL.md:232-234`, `:260-270` |
| The script fails | In progress | stays; never hand-rolled around | the loop | `skills/auto-dev/SKILL.md:253-254` |
| Later stages | as shape 2 | as shape 2 | as shape 2 | as shape 2 |

The shared skill verifies every merge by its PR, so a `merge-script` must
produce one; the profile format does not say so (`references/profile-schema.md:89-91`;
finding F12).

### Scenarios

| Scenario | Shape | Ends in column | Anything stranded? | Evidence |
|---|---|---|---|---|
| Happy path | 1 | Released, then Done by a person | no | `skills/auto-dev/SKILL.md:288-294` |
| Happy path | 2 | In Dev, In Production on the tag, Done by auto-test PASS or a person | no | `references/stage-sync.md:75-80`; `skills/auto-test/SKILL.md:14-17` |
| Happy path | 3 | run-branch stage; next stage only if the loop merges the final PR | see the last row | `skills/auto-dev/SKILL.md:300-311` |
| Hard Stop found mid-change | all | Human!Help!, branch pushed and unmerged, ready label removed | no: the branch is named in the Needs-you line | `skills/auto-dev/SKILL.md:156-161` |
| Review stops the issue | all | Human!Help!, commit marked *unreviewed* or *known defect* | no | `skills/auto-dev/SKILL.md:145-155` |
| Verification abandoned after three attempts | all | Human!Help!, commit marked *abandoned*; not retaken in the same run | no; but the README says it "goes back to the queue" (finding F5) | `skills/auto-dev/SKILL.md:162-171`; `README.md:156-157` |
| Red CI on a release merge | 1 | Human!Help!, PR open | no | `skills/auto-dev/SKILL.md:215-217` |
| Red CI on a release merge | 3 | run-branch stage; whole run stops | no; the owner is asked | `skills/auto-dev/SKILL.md:242-245` |
| Merged, `Ships-issue` missing | 2 | In Dev; must be moved by hand when its tag ships | yes, until a person moves it; the run report says so | `skills/auto-dev/SKILL.md:278-281` |
| A person merges the run's final PR the next morning | 3 | **stays in the run-branch stage**; no skill or script moves it | **yes**: confirmed by three scenario runs (below) | `skills/auto-dev/SKILL.md:245`, `:300-311` |
| A card in Dev Ready without the ready label | all | taken like any other | no, but an unlinted spec gets built (finding F3) | `skills/auto-dev/SKILL.md:92-115`; three scenario runs |

### Where the documents disagree

| # | What | One place | The other |
|---|---|---|---|
| C1 | Who moves a card to Done. The README and `git-process.md` say no skill does; `/gogogo:auto-test` does on PASS when `pass_column` is Done (METIS's profile sets exactly that) | `README.md:107`, `:143`; `docs/git-process.md:222` | `skills/auto-test/SKILL.md:14-17` |
| C2 | What happens after three failed attempts: "back to the queue" versus Human!Help! | `README.md:156-157` | `skills/auto-dev/SKILL.md:162-171` |
| C3 | What makes an issue pickable: the label is described as marking an issue "specced and pickable" and is gated by `spec_lint.py`; the loop selects by column and never reads the label | `references/profile-schema.md:62`; `skills/spec/SKILL.md:345-361` | `skills/auto-dev/SKILL.md:92-115` |
| C4 | Whether `ci_before_merge = true` holds a merge that is not a release until CI passes. The checks step is entered only "when a merge is a release", and the `pr-squash` rule says "when a merge is a release, wait for its checks; then squash-merge it", so read literally a non-release merge goes through with CI pending or red. Yet the Judge step inside that same release-only step names `ci_before_merge`, the profile format says the setting means "CI must pass on each issue before it merges", and `docs/git-process.md` says the loop waits. Three scenario runs all answered "wait", by reaching into the Judge step | `skills/auto-dev/SKILL.md:191`, `:250` | `skills/auto-dev/SKILL.md:208-210`; `references/profile-schema.md:94`; `docs/git-process.md:107-108` |
| C5 | `session_url` (per environment) and `verify.session_url` are read by preflight but appear in neither the profile format nor `profile_check.py`; METIS uses the first | `skills/auto-dev/SKILL.md:78-82` | `references/profile-schema.md:69`, `:136-138`; `scripts/profile_check.py:58` |
| C6 | `/gogogo:dev` now branches before the first edit (#49) and names the issue with `Refs #<n>`, checking closing references (#34); `docs/git-process.md`, written the same morning, still says dev "changes the working tree only" and does not mention either | `docs/git-process.md:86` | `skills/dev/SKILL.md:98-109`, `:265-298` |
| C7 | "A person moving it to Done" is listed as one of gogogo's distinguishing features | `README.md:107` | as C1 |

### Cold-reader test

A fresh `claude -p` with no tools was given only `README.md`, `docs/*.md` and
`plugins/gogogo/references/*.md`, and each question on its own. The questions
and the expected answers were written down before any run.

| # | Question | Verdict | What decided it |
|---|---|---|---|
| 1 | Does auto-dev merge on its own where a merge is a release, and when? | right | `skills/auto-dev/SKILL.md:48-56`, `:188-217` |
| 2 | Which column does auto-dev take issues from; is a label needed too? | not stated: the reader saw that the docs never say how the column and the label combine | C3 |
| 3 | After a merge, which column, and who moves it next? | wrong: "the card never goes to Done by any skill" | C1 |
| 4 | Who moves a card to Done? | right, and the reader flagged the contradiction itself | C1 |
| 5 | What happens after three failed verifications? | right, and the reader flagged the README's "back to the queue" | C2 |
| 6 | What is the branch called and where is it cut from? | right | `skills/auto-dev/SKILL.md:117-122` |
| 7 | How does the squash commit name the issue, and why not `Fixes`? | right | `references/stage-sync.md:36-37` |
| 8 | How is a `run-branch-pr` final PR merged, and why? | right | `skills/auto-dev/SKILL.md:240-249` |
| 9 | Does the loop wait for CI on a non-release merge with `ci_before_merge = true`? | contested: the reader answered "yes", from `docs/git-process.md`; the skill's `pr-squash` rule says no; the skill's own scenario runs said yes | C4 |
| 10 | What must be true before auto-dev starts? | partly: it missed the logged-in browser and the stranded-work report | `skills/auto-dev/SKILL.md:78-90` |

Six right, one wrong, one not stated, one contested (the docs and the skill
disagree), one partly right. Every miss but row 10 traces to a disagreement
listed above. Row 10's reader missed the stranded-work report, which
`docs/git-process.md:264` does mention, and the logged-in browser on the
pre-merge environment, which no document outside the skill mentions
(`skills/auto-dev/SKILL.md:78-82`).

### Scenario runs

Each ran three times with `skills/auto-dev/SKILL.md` as the whole system
prompt and no tools. A first call asked for the launch command, which only that
skill states; it was quoted exactly, so the prompt had loaded.

| Situation | Expected (written first) | Three runs | Agree? |
|---|---|---|---|
| S1: a person merges the run's final PR the morning after a `run-branch-pr` run | nothing moves the cards | "no step of this skill moves them" ×3; each says the owner or a deploy must | yes |
| S2: an issue in the queue column with a full spec but no ready label | take | take ×3: the label is never a selection criterion | yes |
| S3: `pr-squash`, `ci_before_merge = true`, merge not a release, checks pending | unclear | wait ×3, each by applying the Judge step, which the text enters only for a release | yes, but against the literal `pr-squash` rule (`skills/auto-dev/SKILL.md:250`): the runs agree with each other and with the profile format, not with the line that governs this case |
| S4: no `session_url` anywhere, `verify.agent = ["local"]` | split between stop and skip | "other" ×3: note in the report that preflight 8 had nothing to check, ask if a rung needs a browser | yes |

Calls used: 2 to check `claude -p` worked, 10 cold-reader, 1 launch-command
check, 12 scenario runs: **25 of the 60 allowed**.

## C. What to measure

In [process-measures.md](process-measures.md): nineteen measures by question
(quality, speed, token efficiency), each with its formula, source, whether past
history can answer it, and whether it may be public, and the order part 2
computes them in. Two facts found here shape it: transcripts carry `gitBranch`
on every line, so tokens can be attributed to an issue by its `fix/<n>-…`
branch; and Claude Code deletes local session data after 30 days by default, so
a token baseline from history covers the last month at most.

## Findings, ranked

Severity is one of: **strands work or misleads an adopter**; **costs time or
tokens**; **minor**.

| Rank | Finding | Strand | Severity | Evidence | Suggested issue title |
|---|---|---|---|---|---|
| F1 | Every safety rule is advisory skill text. GitHub enforces none of them (required checks, no force push to the default branch), and `/gogogo:setup` does not check for it; this repo's `main` is unprotected. OWASP and Anthropic both say rules that must hold every time belong in the system that acts, or in a hook | A | strands work or misleads an adopter | A5, A9; `skills/setup/SKILL.md:3` | setup: check that the default branch requires the CI checks and refuses force pushes |
| F2 | Under `run-branch-pr`, a final PR that a person merges after the run leaves every card in the run-branch stage: no skill or script moves them | B | strands work or misleads an adopter | `skills/auto-dev/SKILL.md:245`, `:300-311`; S1 ×3 | auto-dev: move a run's cards when its final PR is merged after the run |
| F3 | The loop selects by column and never reads the ready label, so a card dragged into Dev Ready is built whether or not `spec_lint.py` ever passed its spec | B | strands work or misleads an adopter | C3; S2 ×3 | auto-dev: take only issues carrying the ready label, and report the ones in the queue without it |
| F4 | The README and `docs/git-process.md` say no skill moves a card to Done; `/gogogo:auto-test` does on PASS, and closes the issue | B | strands work or misleads an adopter | C1, C7; cold-reader 3 | docs: say that auto-test can close an issue and move it to Done when the profile asks |
| F5 | The README says an abandoned issue "goes back to the queue"; it goes to Human!Help! | B | strands work or misleads an adopter | C2; cold-reader 5 | README: an abandoned issue goes to Human!Help!, not back to the queue |
| F6 | `ci_before_merge = true` may not hold a non-release merge: the `pr-squash` rule waits for checks only when the merge is a release, while the profile format and `docs/git-process.md` say CI must pass first. Three runs read it as "wait"; a literal reader merges with CI red. What the loop does depends on who reads it | B | strands work or misleads an adopter | C4; S3 ×3; `skills/auto-dev/SKILL.md:250` | auto-dev §6: when `ci_before_merge` is true, wait for and judge the checks on every merge, not only a release |
| F7 | Nothing guards the tests themselves: a change that deletes, skips or loosens a test passes every gate. With no person reading code, the tests are the only reader | A | strands work or misleads an adopter | A6, A11; `skills/auto-dev/SKILL.md:134-144` | dev, auto-dev: fail a change that removes, skips or loosens tests the spec did not ask to change |
| F8 | `docs/git-process.md` went stale within hours: it predates #48 and #49 (dev branches before the first edit; `Refs #<n>`; closing references checked; exit 4). No test ties a doc to the skills, and none should look for sentences, so docs drift silently | B | costs time or tokens | C6 | docs: bring git-process.md up to date with dev §4 and §8 |
| F9 | The owner's position (no human code review except the core data model) is written only in an issue body. An adopter reading the README expects some review by a person | A | costs time or tokens | A6; *The owner's stance* | README: say plainly who reviews what |
| F10 | The loop refuses every mode but `bypassPermissions`. Auto mode now runs without prompts and blocks risky actions with a classifier, and is Claude Code's default; the reason for requiring bypass was written before that and does not consider it | A | costs time or tokens | A10; `scripts/require_unattended.sh:4-6` | auto-dev: decide whether auto mode is an acceptable unattended mode |
| F11 | `session_url` and `verify.session_url` are read by preflight but are in neither the profile format nor `profile_check.py`; a typo there is silent, and the format does not tell an adopter they exist | B | minor | C5; S4 ×3 | profile format: document session_url, or stop reading it |
| F12 | The skill verifies every merge by its PR, so a `merge-script` must open one; the profile format does not say so | B | minor | `skills/auto-dev/SKILL.md:260-270`; `references/profile-schema.md:89-91` | profile format: say that a merge script must merge through a pull request |
| F13 | Nothing measures the process: no lead time, failure rate or cost per issue is recorded, and the run report, the richest record of a run, lives only in the session | A | costs time or tokens | A18; [process-measures.md](process-measures.md) *Sources*, R | auto-dev: keep the run report; record phase times and the session id in the review record |
| F14 | Nothing watches a release after it ships | A | minor | A17 | (none suggested: per repo, through `observability`) |
| F15 | Release tags are unsigned | A | minor | A16 | (none suggested) |
