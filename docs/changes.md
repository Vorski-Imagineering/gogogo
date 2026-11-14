# What changed in gogogo

What changed in the plugin each month, newest first, grouped by what it means for a repo that uses it: new skills, settings to look at, changes to what the skills do, script fixes, and everything else. Read it when you update the plugin, to see what your next run will do differently. Each line links the issue it came from.

Each month's section is drafted by `python3 tools/changes.py <YYYY-MM>` from `main`'s commits, then edited by hand, with a one-line summary above each group, and added at the top through a pull request.

## October 2026

### New skills

The first public release, and six skills added after it: roadmap, auto-test, status, idea, human-help and sentry-debug.

- gogogo: first public release
- roadmap: shared /gogogo:roadmap and roadmap_status.py (#5), [#7](https://github.com/Vorski-Imagineering/gogogo/pull/7)
- auto-test: shared /gogogo:auto-test and record_outcome.py (#3), [#8](https://github.com/Vorski-Imagineering/gogogo/pull/8)
- status: one read-only screen of where things stand (#6), [#37](https://github.com/Vorski-Imagineering/gogogo/pull/37)
- idea: save a session's findings as an un-specced issue (#31), [#38](https://github.com/Vorski-Imagineering/gogogo/pull/38)
- human-help: work the Human!Help! column (Refs #159, partial), [#183](https://github.com/Vorski-Imagineering/gogogo/pull/183)
- sentry-debug: a shared, read-only Sentry debugging and weekly-report skill, [#204](https://github.com/Vorski-Imagineering/gogogo/issues/204)

### Settings

Settings a profile can now set or must look at: notifications, the Human!Help! column, the board queue, independence, where each issue's work goes, related repos and ship waits.

- stage_sync.py: cards follow deploy tags; dev and auto-dev write the Ships-issue trailer (#4), [#9](https://github.com/Vorski-Imagineering/gogogo/pull/9)
- release: one way to number, tag and describe a production release (#15), [#27](https://github.com/Vorski-Imagineering/gogogo/pull/27)
- dev, auto-dev: a Human!Help! column for issues stopped and waiting for a person (#26), [#32](https://github.com/Vorski-Imagineering/gogogo/pull/32)
- The queue is a board column: drop label queues and the github-label tracker kind, [#35](https://github.com/Vorski-Imagineering/gogogo/pull/35)
- notify: send auto-dev's messages by Telegram, and name the run's session (#30), [#39](https://github.com/Vorski-Imagineering/gogogo/pull/39)
- dev, auto-dev: judge review findings by evidence; review_stats.py, [#33](https://github.com/Vorski-Imagineering/gogogo/issues/33)
- dev, auto-dev: compare the tests a change touched before it merges, [#58](https://github.com/Vorski-Imagineering/gogogo/issues/58)
- dev, auto-dev: mutation-test the changed lines before merge, [#45](https://github.com/Vorski-Imagineering/gogogo/issues/45)
- profile_check: defaults and warnings for settings added after adoption, [#87](https://github.com/Vorski-Imagineering/gogogo/issues/87)
- notify: on by default with credentials; a repo's own git-ignored file, [#109](https://github.com/Vorski-Imagineering/gogogo/issues/109)
- setup, dev, auto-dev: ask where each issue's work goes; integration.workspace, [#94](https://github.com/Vorski-Imagineering/gogogo/issues/94)
- spec, dev, auto-dev, setup: an independence setting for which decisions the agent takes, [#90](https://github.com/Vorski-Imagineering/gogogo/issues/90)
- dev, auto-dev: one merge procedure, with an outcome for every kind of refusal, [#88](https://github.com/Vorski-Imagineering/gogogo/issues/88)
- idea, name_check: file a suspected gogogo fault on gogogo's tracker, gated by a name check, [#163](https://github.com/Vorski-Imagineering/gogogo/issues/163)
- Mutation testing leaves the plugin; gogogo keeps it for its own scripts, [#199](https://github.com/Vorski-Imagineering/gogogo/issues/199)
- profile: an optional related_repos list, checked offline, [#235](https://github.com/Vorski-Imagineering/gogogo/issues/235)
- tracker: a blocker in a related repo is read from that repo's board, [#233](https://github.com/Vorski-Imagineering/gogogo/issues/233)
- spec: the part of the work in a related repo is filed there and cited; the lint withholds an uncited one, [#234](https://github.com/Vorski-Imagineering/gogogo/issues/234)
- status: a RELATED block lists what each related repo waits on; auto-dev's close report ends with it, [#239](https://github.com/Vorski-Imagineering/gogogo/issues/239)
- ship-wait: "must not merge before X ships" is a blocked-by link marked (shipped), [#238](https://github.com/Vorski-Imagineering/gogogo/issues/238)

### Skill changes

What the existing skills do differently: how setup, spec, dev and auto-dev read issues, review, merge and hand cards back.

- setup: two kanban views, and start and finish on a clean main, [#1](https://github.com/Vorski-Imagineering/gogogo/pull/1)
- setup: a repo with no Hard Stops gets an interim list and an issue, [#2](https://github.com/Vorski-Imagineering/gogogo/pull/2)
- setup: one standard colour for the ready label, and offer to fix a different one (#18), [#20](https://github.com/Vorski-Imagineering/gogogo/pull/20)
- setup: start by printing the repo's setup and configuration (#12), [#23](https://github.com/Vorski-Imagineering/gogogo/pull/23)
- tracker.py: views --hide-closed and tidy, ported from the stranded board-automation branch (#21), [#28](https://github.com/Vorski-Imagineering/gogogo/pull/28)
- spec: a declined question offers explain, user impact, you decide or leave open; offer to move a ready card (#13), [#24](https://github.com/Vorski-Imagineering/gogogo/pull/24)
- dev, auto-dev: two review rounds for prose only, code until clean; record rounds on the issue (#17), [#25](https://github.com/Vorski-Imagineering/gogogo/pull/25)
- auto-dev: in a straight-to-production repo, merge each issue that clears every gate (#29), [#36](https://github.com/Vorski-Imagineering/gogogo/pull/36)
- spec: file the issue first when the user brings an idea, not an issue
- verify_merged --open; dev and auto-dev name the issue with Refs #n, [#34](https://github.com/Vorski-Imagineering/gogogo/issues/34)
- stranded_work: an open PR claims its branch; name the PR's fate, [#22](https://github.com/Vorski-Imagineering/gogogo/issues/22)
- dev §4: put the work on fix/<issue-number>-<short-slug> before the first edit, [#49](https://github.com/Vorski-Imagineering/gogogo/pull/49)
- setup_check: FAIL when the code repo keeps a PR's branch after it merges, [#50](https://github.com/Vorski-Imagineering/gogogo/pull/50)
- dev, auto-dev: check each change against its spec before the review, [#44](https://github.com/Vorski-Imagineering/gogogo/issues/44)
- auto-dev: take a label-less queue card only when its spec lints clean, and label it, [#60](https://github.com/Vorski-Imagineering/gogogo/issues/60)
- spec: work a list of issues or a column one at a time, [#70](https://github.com/Vorski-Imagineering/gogogo/issues/70)
- roadmap: open the refresh PR, return the checkout, stop on an open refresh, [#72](https://github.com/Vorski-Imagineering/gogogo/issues/72)
- dev, auto-dev, review_stats: session id, phase times and a stop marker, [#62](https://github.com/Vorski-Imagineering/gogogo/issues/62)
- roadmap: released is a green ball, not orange
- roadmap: link every issue the document names, not only in the Issue column
- dev: tell the spec-check reader the evidence rules verify enforces, [#81](https://github.com/Vorski-Imagineering/gogogo/issues/81)
- spec: move the card to the queue without asking, [#83](https://github.com/Vorski-Imagineering/gogogo/issues/83)
- setup, status: auto-add issues only; report pull-request cards, [#85](https://github.com/Vorski-Imagineering/gogogo/issues/85)
- tracker: refuse a move to needs_human whose newest comment gives no reason, [#84](https://github.com/Vorski-Imagineering/gogogo/issues/84)
- auto-dev: hand a triage skip back on its issue; review_stats counts skips and sessions, [#63](https://github.com/Vorski-Imagineering/gogogo/issues/63)
- auto-dev: the loop never waits on chat or a turn's end; mutate: a wrapper and a stall check, [#96](https://github.com/Vorski-Imagineering/gogogo/issues/96)
- spec: before posting, check the open specs that read this issue, [#93](https://github.com/Vorski-Imagineering/gogogo/issues/93)
- spec: post nothing over an issue that changed since the run started it, [#91](https://github.com/Vorski-Imagineering/gogogo/issues/91)
- spec: check for a build in flight, ask whether a follow-up hits anything today, look for prior work, [#97](https://github.com/Vorski-Imagineering/gogogo/issues/97)
- dev, auto-dev: judge a lane or gate by its exit status, never filtered output, [#105](https://github.com/Vorski-Imagineering/gogogo/issues/105)
- dev, auto-dev: read the whole issue; a write-access comment counts like the description, [#108](https://github.com/Vorski-Imagineering/gogogo/issues/108)
- dev, auto-dev: find an issue's earlier work before branching; stranded_work reports an open issue's branch, [#86](https://github.com/Vorski-Imagineering/gogogo/issues/86)
- tracker: move --from refuses a card that has left the column, [#101](https://github.com/Vorski-Imagineering/gogogo/issues/101)
- skills: 500 lines per SKILL.md, steps in references; one more round for a prose fix, [#130](https://github.com/Vorski-Imagineering/gogogo/issues/130)
- dev, auto-dev: remove an issue's worktree once its work has merged, [#92](https://github.com/Vorski-Imagineering/gogogo/issues/92)
- setup: the notification check message names this machine, [#135](https://github.com/Vorski-Imagineering/gogogo/pull/135)
- spec: with no argument, offer to spec everything in New, [#136](https://github.com/Vorski-Imagineering/gogogo/issues/136)
- issue_work.py: a PR that only mentions #N is not offered as earlier work, [#145](https://github.com/Vorski-Imagineering/gogogo/issues/145)
- spec: 'being built?' counts a PR that claims the issue, not one that mentions it, [#143](https://github.com/Vorski-Imagineering/gogogo/issues/143)
- spec_check.py: brace paths in Files, and Class.method evidence, [#144](https://github.com/Vorski-Imagineering/gogogo/issues/144)
- setup: leave out retired-skill recipes for steps the plugin runs itself, [#142](https://github.com/Vorski-Imagineering/gogogo/issues/142)
- setup: say when Telegram credentials already exist, and only the repo's own, [#141](https://github.com/Vorski-Imagineering/gogogo/issues/141)
- session start, status: show the independence level, bold in a terminal, [#138](https://github.com/Vorski-Imagineering/gogogo/issues/138)
- auto-dev: start under /goal, wait on the reader and the review without a stopped-looking turn, [#129](https://github.com/Vorski-Imagineering/gogogo/issues/129)
- spec: a design that reverses a tested behaviour must license the test rewrite, [#118](https://github.com/Vorski-Imagineering/gogogo/issues/118)
- roadmap: cut the refresh branch in a worktree, so a shared checkout is not switched, [#128](https://github.com/Vorski-Imagineering/gogogo/issues/128)
- auto-dev: move a run's cards when its run-branch PR lands, [#59](https://github.com/Vorski-Imagineering/gogogo/issues/59)
- wrap-up: review saved memories and suggest which to promote into the shared process, [#114](https://github.com/Vorski-Imagineering/gogogo/issues/114)
- dev, auto-dev, wrap-up: record suspected gogogo faults, [#140](https://github.com/Vorski-Imagineering/gogogo/issues/140)
- setup: check that the default branch requires CI and refuses force pushes, [#57](https://github.com/Vorski-Imagineering/gogogo/issues/57)
- stages: released work waits unconfirmed, merged is taken for deployed, and there is no way back, [#89](https://github.com/Vorski-Imagineering/gogogo/issues/89)
- dev, worktree_sweep: delete a merged local branch after a verified merge, [#169](https://github.com/Vorski-Imagineering/gogogo/issues/169)
- notify: format run messages from JSON events, [#157](https://github.com/Vorski-Imagineering/gogogo/issues/157)
- auto-dev, dev: focused tests per round, silent-review restart, survivors split by kind, [#178](https://github.com/Vorski-Imagineering/gogogo/issues/178)
- roadmap: keep milestone-linked sections in step with GitHub, after approval, [#184](https://github.com/Vorski-Imagineering/gogogo/issues/184)
- blocked by: a card waiting on another issue goes back to the queue, not Human!Help!, [#185](https://github.com/Vorski-Imagineering/gogogo/issues/185)
- human-help: dev and auto-dev obey the authorisation human-help records, [#159](https://github.com/Vorski-Imagineering/gogogo/issues/159)
- notify: review and mutation testing for the #157 merge, [#157](https://github.com/Vorski-Imagineering/gogogo/issues/157)
- auto-dev: preflight 11 says <profile> is the path profile_check.py printed, [#192](https://github.com/Vorski-Imagineering/gogogo/issues/192)
- spec, human-help: an approval question lists its edge cases, [#195](https://github.com/Vorski-Imagineering/gogogo/issues/195)
- README, setup: the plugin install is recorded per folder, [#207](https://github.com/Vorski-Imagineering/gogogo/issues/207)
- spec: re-read a draft for a public tracker before posting, [#206](https://github.com/Vorski-Imagineering/gogogo/issues/206)
- spec: offer to park an issue that cannot be acted on yet, [#203](https://github.com/Vorski-Imagineering/gogogo/issues/203)
- dev: take the card into In progress once the work has its place, [#228](https://github.com/Vorski-Imagineering/gogogo/issues/228)
- review: a correction is the smallest fix, cut what grew, the reviewer names excess, record v=3, [#231](https://github.com/Vorski-Imagineering/gogogo/issues/231)
- notify: a refused event names every wrong field and the fields it takes; auto-dev resends once, [#237](https://github.com/Vorski-Imagineering/gogogo/issues/237)
- test_guard: a licence naming a folder with a trailing slash covers every test beneath it, [#236](https://github.com/Vorski-Imagineering/gogogo/issues/236)
- spec: mark a blocker (shipped) only when the work needs it live in production, [#250](https://github.com/Vorski-Imagineering/gogogo/issues/250)
- auto-dev: with no goal, a run waits on the forked review's state file, [#253](https://github.com/Vorski-Imagineering/gogogo/issues/253)
- dev: a bug finding says how production reaches it before anything changes, [#248](https://github.com/Vorski-Imagineering/gogogo/issues/248)

### Scripts

Fixes and additions to the scripts the skills run, mostly spec_check, test_guard, stranded_work and worktree_sweep.

- setup_check: warn on cards from another repo and closed cards in the queue (#11), [#19](https://github.com/Vorski-Imagineering/gogogo/pull/19)
- stranded_work: the issue number in a branch name by status's rule, [#40](https://github.com/Vorski-Imagineering/gogogo/issues/40)
- require_unattended: find the transcript by session id, from any folder, [#52](https://github.com/Vorski-Imagineering/gogogo/issues/52)
- spec_check, spec_lint: bold-numbered items, and settings under Edit are not files, [#77](https://github.com/Vorski-Imagineering/gogogo/issues/77)
- review_stats: read only own-line stop markers; medians in whole minutes, [#82](https://github.com/Vorski-Imagineering/gogogo/issues/82)
- session_status: a one-line board status when a session opens, shipped as the plugin's SessionStart hook, [#107](https://github.com/Vorski-Imagineering/gogogo/issues/107)
- test_guard: a path::name licence finds a test method by its enclosing lines, [#76](https://github.com/Vorski-Imagineering/gogogo/issues/76)
- spec_check: a dotfile or extensionless name under Files is an item, [#124](https://github.com/Vorski-Imagineering/gogogo/issues/124)
- worktree_sweep: --only says why when it removes nothing, [#166](https://github.com/Vorski-Imagineering/gogogo/issues/166)
- setup_check: unpack untidy's three values, test the real shape, [#179](https://github.com/Vorski-Imagineering/gogogo/issues/179)
- spec_check: keep a comma inside a ::name test reference, [#198](https://github.com/Vorski-Imagineering/gogogo/issues/198)
- test_guard: a licence naming a renamed file's old path covers it, [#216](https://github.com/Vorski-Imagineering/gogogo/issues/216)
- spec_check: a listed file renamed away counts as touched, [#215](https://github.com/Vorski-Imagineering/gogogo/issues/215)
- stranded_work, worktree_sweep: tell a fork's PR by isCrossRepository; hold the first sweep's merged-PR removals, [#214](https://github.com/Vorski-Imagineering/gogogo/issues/214)
- tracker.py: find a card on a board in another organisation from the board's side, [#227](https://github.com/Vorski-Imagineering/gogogo/issues/227)
- test_guard: a licence is a whole word in a line's own prose, [#252](https://github.com/Vorski-Imagineering/gogogo/issues/252)

### Other

The README, the docs, and gogogo's own tools and profile; nothing here changes what an adopting repo runs.

- README: using gogogo (installed plugin) vs working on it (a clone)
- README: each machine installs the plugin once before update works
- README: one-page overview of why gogogo exists, who it is for, and what already overlaps it
- profile: how a Released card is confirmed here (scenario runs, then close and tidy)
- README: lead with letting Claude work alone for hours, and a Start here path
- README: /gogogo:spec takes an idea or an existing issue
- gitignore: .env, which holds the notify.py test bot's credentials
- gitignore: /evals/, so private trial-run write-ups can't be committed from any clone
- docs: when is enough enough? Ending the review loop
- docs: when is enough enough: what we decided
- docs: how gogogo uses branches, pull requests and merges
- docs: process review against current practice, the flow traced, and what to measure, [#47](https://github.com/Vorski-Imagineering/gogogo/issues/47)
- docs: process review notes what #50 and #51 changed after it was read, [#47](https://github.com/Vorski-Imagineering/gogogo/issues/47)
- README: how the process measures up: what follows current practice, and what is original
- docs: README banner image
- docs: workflow image in README's process section; the 'Human Ideas move faster than Coding Agents' essay
- docs: README and git-process.md match the skills; test_docs_in_step pins the names they spell, [#61](https://github.com/Vorski-Imagineering/gogogo/issues/61)
- profile: run tools/mutate.py without heavy load alongside, [#45](https://github.com/Vorski-Imagineering/gogogo/issues/45)
- mutate: count the tool's suspicious mutants as killed, [#75](https://github.com/Vorski-Imagineering/gogogo/issues/75)
- README: when to run auto-dev under /goal, and when not, [#84](https://github.com/Vorski-Imagineering/gogogo/issues/84)
- docs: independence modes proposal, junior-dev, senior-dev, architect, [#90](https://github.com/Vorski-Imagineering/gogogo/issues/90)
- docs: independence modes written as documentation; model recommendation for senior-dev and architect, [#90](https://github.com/Vorski-Imagineering/gogogo/issues/90)
- CLAUDE.md: the in-session approval path for a small Hard Stop change, and how docs/ are written, [#106](https://github.com/Vorski-Imagineering/gogogo/issues/106)
- evals: nine eval cases for dev, auto-dev and spec, run as the evals lane, [#131](https://github.com/Vorski-Imagineering/gogogo/issues/131)
- profile: recon trap for a new eval case missing from the suite's CASES list
- profile: set independence to product-owner, the highest level, [#171](https://github.com/Vorski-Imagineering/gogogo/pull/171)
- mutate: count a mutant that makes the test run exit while loading as killed, [#167](https://github.com/Vorski-Imagineering/gogogo/issues/167)
- evals: a guide to writing a case, per-case scores, a failed run when a case did not run, [#168](https://github.com/Vorski-Imagineering/gogogo/issues/168)
- mutate: run the changed lines in parts at once, each against its own script's tests, [#175](https://github.com/Vorski-Imagineering/gogogo/issues/175)
- Revise Claude's work description in README, [#189](https://github.com/Vorski-Imagineering/gogogo/pull/189)
- docs: grade a fixed last line when right and wrong differ by a negation; quote a grader's ' safely, [#196](https://github.com/Vorski-Imagineering/gogogo/pull/196)
- Merge pull request #197 from Vorski-Imagineering/docs/changed-files-lint-gate
- eval_changed: a repeated --skill adds up instead of replacing, [#194](https://github.com/Vorski-Imagineering/gogogo/issues/194)
- evals: neutral questions for the setup and roadmap cases, [#193](https://github.com/Vorski-Imagineering/gogogo/issues/193)
- CLAUDE.md: a Hard Stop for anything that adds run time in adopting repos, [#200](https://github.com/Vorski-Imagineering/gogogo/issues/200)
- mutate: each part's tests get their own temp folder, [#217](https://github.com/Vorski-Imagineering/gogogo/issues/217)
- docs: how to see a failing eval case's answers, [#249](https://github.com/Vorski-Imagineering/gogogo/pull/249)
