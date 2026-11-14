# /gogogo:guided-review: Walk, Record, Resume

Part of `/gogogo:guided-review`. Read it in full before step 1. Section names
here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you:
it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- Each step
- Marks
- A fail
- The ledger line
- Each issue's verdict
- Recording
- Clean up
- Pause
- Resume
- The report

## Each step

1. **Set it up**: the data, the page, the state the step starts from, within
   the step classes.
2. **Send the step message**, exactly as `SKILL.md` *Walk* gives it, and end
   the turn.
3. **Take the answer.** The person's words go in the ledger **verbatim**,
   never summarised or tidied. A screenshot is saved in the walk folder.
4. **Check the system side**, Read class only:
   - `GET` and `HEAD` requests, and browser reads of the walk environment;
   - `state.read`, only when the walk environment is in `verify.agent`;
   - the lanes `## Test data` → *Optional lanes* marks `READY`.

   With no system-side check possible, say so and why:
   "no system-side check: <why>".
5. **Say whether the two sides agree**, in one or two sentences: what you
   read, and whether it matches what they saw.

## Marks

| The person | The system side | Mark |
|---|---|---|
| pass | agrees, or no check possible | ✅ |
| fail, reproduced once | any | ❌ |
| pass | shows the step wrong | asked once to look again; still apart: ⚠ *disagree* |
| free text or a screenshot | shows the step wrong, reproduced once | ❌ |
| skip | not run | ⏭ |

A disagreement is never resolved in your favour, nor in theirs: ⚠ is recorded
with both sides, and is never ✅.

## A fail

Diagnose it **read-only**, for a few minutes at most: its system-side check
again, `git show <build>:<path>` for the code that should have done it. A
suspected cause goes into that issue's *Reproduce*, then the walk goes on. The
walk changes no code and files no issue.

## The ledger line

One line per answered step in `ledger.jsonl`:

```json
{"walk": "<walk id>", "step": <k>, "issues": ["<repo>#<n>"], "build": {"<repo>": "<ref>"}, "answer": "<their words>", "system": "<what you read>", "mark": "<mark>"}
```

A step walked again (*Resume*) gets a new line; the old one stays.

## Each issue's verdict

- **PASS**: every step of the issue is ✅.
- **FAIL**: any step is ❌.
- **NEEDS_HUMAN** otherwise, naming each ⚠, ⏭, held, not reached and not on
  this environment step.

An issue whose every step is held gets no comment, only its row in the report.

## Recording

When every step of an issue has a mark, or at `finish` (its unanswered steps
become *not reached*):

1. Write `<walk folder>/<owner>__<name>/spec-<n>.json` with auto-test's spec
   keys (`n`, `verdict`, `kind`, `summary`, `role`, `commits`, `checks`, and
   `repro` for a FAIL, `human` for a NEEDS_HUMAN), and always `signals` (what
   the system side read), `data` (this issue's ledger objects, kept or
   deleted, or "None created.") and `not_tested` (its held, not reached and
   not on this environment steps, or "Nothing."). One `checks` row per step:
   `[criterion, source, steps, expected, observed, mark]`, where *source* is
   `<repo>#<n> step <k>` and *observed* holds the person's words and the
   system side, both.
2. Render it:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/record_outcome.py" render <walk folder>/<owner>__<name> <n> --walk <walk id> --env <env> --repo <owner/name> --build <build> --model <model id> < <walk folder>/<owner>__<name>/spec-<n>.json
   ```
3. **Read the rendered file.**
4. Apply it:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/record_outcome.py" apply <walk folder>/<owner>__<name> <n> <PASS|FAIL|NEEDS_HUMAN> --walk --repo <owner/name>
   ```
   On `verify.human`, for an issue of this repo whose card is in the column
   under test and which is open, it does what auto-test's outcome does
   (labels, close, card). Anywhere else it posts the comment alone and prints
   `comment only: <reason>`, and the card stays where it is. A PASS or
   NEEDS_HUMAN commented only because the walk was `not the confirming
   environment` still waits for someone to confirm it on `verify.human`.
5. A non-zero exit from either **stops the walk** (`SKILL.md` *Stop the
   walk*): the comment may or may not be on the issue, and the person decides.

`render` refuses, as auto-test's does, a PASS with any step not ✅, and, when
the tracker is public or the issue is in another repo, a value holding the
walk environment's host or `verify.human`'s, a URL with a query string or a
password, or an IP address. Keep hosts, real names and records out of every
value, as `skills/auto-test/SKILL.md` § What a published comment may contain
says.

## Clean up

At the end of each issue, as `skills/auto-test/SKILL.md` § Clean up says:
fixtures restored to their baseline; for PASS or NEEDS_HUMAN, each `created`
ledger object for the issue deleted after reopening it and confirming it
carries this walk's name; for FAIL, kept as the reproduction and listed in
the comment. Anything that looks like old test data and is not in this
walk's ledger is never touched, and listed in the report.

## Pause

`pause` posts nothing and records nothing. Write the walk's position to
`walk.md`, and print the walk id and the command to resume it:
`/gogogo:guided-review --resume <walk id>`. Issues whose steps are all marked
and were already recorded stay recorded.

## Resume

1. Re-run Preflight (a new stamp and model id are recorded beside the old) and
   Prepare's build reads.
2. Steps with a mark, on a build that has not changed, are kept.
3. Steps whose repo's build changed are walked again; the report keeps both
   answers.
4. Carry on from the first step with no mark.
5. An issue already recorded is not recorded again, unless one of its steps
   was walked again.

## The report

`report.md`, printed at the end:

- one row per step: number, issues, mark, the person's words, the system side;
- each issue's verdict and what was written: the full outcome, or a comment
  only and the reason the script printed;
- **not reached**: the steps unanswered at `finish`;
- **held**: steps whose fix is not in the build, with the commit and the build;
- **not on this environment**: the production-only steps;
- ledger leftovers, and old test data seen and not touched;
- **what the release still waits on**: held steps, production-only steps,
  each ⚠, each FAIL, and each other issue commented only because the walk was
  `not the confirming environment`, which someone still confirms on
  `verify.human`.
