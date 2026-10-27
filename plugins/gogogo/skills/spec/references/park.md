# /gogogo:spec: Park it before any design question

Part of `/gogogo:spec`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

*Before you write* § 6, item 4: the issue hits today, but cannot be acted on
yet. It holds whatever recon found, a person's request included. In order:

1. **The two triggers**, each named with its evidence:
   - its own text says it waits for something (another issue's result,
     evidence, a measurement), and recon finds it has not arrived: a link or
     `file:line` for what was checked;
   - every design that would work needs a part the issue's text did not name
     and the repo does not have (a client built from undocumented lower-level
     parts, a hand-written wire format, a dependency that does not cover the
     path): the part that is missing, and where recon found it missing. A
     hard design the issue did foresee is not a trigger.
2. **An idea not yet filed** has no card to park, so rules 3 to 7 do not
   apply: ask **don't file it** (file nothing; the reply gives the trigger,
   its evidence and what would make it actionable, under rule 10's limits)
   or **file and spec it** (carry on as rule 8; Posting step 0 files it when
   the spec is posted).
3. **Finding the column:** the single column from `<tracker.tool> fields`
   whose name contains `backlog`, ignoring case and emoji. With none,
   several, or no `tracker.tool`, the first choice in rule 4 is **close it as
   not planned** instead. A non-zero exit from `fields` is said as such and is
   not a missing column: rule 4 then offers only **spec it anyway** or
   **stop here** (post nothing, and end this issue).
4. **The question**, one `AskUserQuestion` before any design question: **park
   it until <the precondition, in one line>** (first, marked recommended) or
   **spec it anyway**. It opens with the real case in one plain sentence and
   names the evidence.
5. **The three lines**, written to `<scratch>/park-<N>.md`:
   ```
   Parked before speccing: <the trigger and its evidence>.
   Unpark when: <what would make it actionable>.
   Cheapest fallback if the need comes first: <one line, or "none found">.
   ```
6. **On park:** first read the issue with
   `gh issue view <N> --repo <tracker.issues_repo> --json state,labels`. A
   non-zero exit: say the issue could not be read, move nothing, post nothing,
   and end this issue. A `state` other than `OPEN`: the issue is closed; do
   not move it, say so, post nothing, and end this issue. Then read the card
   with `<tracker.tool> show <N>` (for `shared`,
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py"`, and the same for
   `move` below), immediately before the move.
   - A read that exits non-zero: say the card could not be read, move
     nothing, post nothing, and end this issue.
   - A card in `tracker.columns.in_progress`, `tracker.columns.needs_human`
     or any `stages` entry's column: do not move it. Say which column it is in
     and that it was left there, post nothing, and end this issue.
   - No card: for `shared`,
     `move <N> --to "<the backlog column>" --add-missing`; for any other tool,
     say the issue has no card and post nothing.
   - Otherwise:
     `move <N> --from "<the column read>" --to "<the backlog column>"`. A card
     the read showed with no column is moved without `--from`.
   - A zero exit counts as parked. Exit 2 (the tool could not confirm the
     move): read the card again with `show <N>`; only when that read succeeds
     and shows the backlog column does it count as parked. Exit 3: the card
     moved meanwhile; say to where, and post nothing. Any other case: say the
     move may have failed, with its message, and post nothing.

   Once parked, post the three lines with
   `gh issue comment <N> --repo <tracker.issues_repo> --body-file <scratch>/park-<N>.md`.
   No label and no spec. When the labels the issue read showed include
   `tracker.ready_marker` (compared ignoring case), leave it, and say in the
   reply that the parked issue still carries it, for a person to remove. End
   this issue.
7. **On close as not planned:** first read the issue as rule 6 does; a
   failed read, or a closed issue, closes nothing and posts nothing (say so).
   When the profile has `tracker.tool`, then read the card as rule 6 does; a
   failed read, or a card in one of rule 6's protected columns, closes
   nothing and posts nothing (say so). With no `tracker.tool` there is no
   card to read, and that read is skipped. When nothing above stopped it, run
   § 6's close command with the three lines as its comment, read from the
   file so nothing in them is run by the shell:
   `gh issue close <N> --repo <tracker.issues_repo> --reason "not planned" --comment "$(cat "<scratch>/park-<N>.md")"`.
   End this issue.
8. **On spec it anyway:** carry on to *Before you write* § 7. The trigger and
   its evidence go into `## Context` as a trap.
9. **A decline, or no person to ask:** post nothing, move nothing, comment
   nothing, and end this issue, saying what recon found. In a run of several,
   no person to ask stops the run, as *Several issues in one run* rule 6
   says. The four-choice menu for a declined question is not used here.
10. **When `tracker.public` is true**, the three lines name no path, repo,
    host or person from outside this repo.
