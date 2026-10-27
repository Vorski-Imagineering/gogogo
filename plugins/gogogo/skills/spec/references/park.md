# /gogogo:spec: Park it before any design question

Part of `/gogogo:spec`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

*Before you write* § 6, item 4: the issue hits today, but cannot be acted on
yet. In order:

1. **The two triggers**, each named with its evidence:
   - its own text says it waits for something (another issue's result,
     evidence, a measurement), and recon finds it has not arrived: a link or
     `file:line` for what was checked;
   - every design that would work needs a part the issue's text did not name
     and the repo does not have (a client built from undocumented lower-level
     parts, a hand-written wire format, a dependency that does not cover the
     path): the part that is missing, and where recon found it missing. A
     hard design the issue did foresee is not a trigger.
2. **The question**, one `AskUserQuestion` before any design question: **park
   it until <the precondition, in one line>** (first, marked recommended) or
   **spec it anyway**. It opens with the real case in one plain sentence and
   names the evidence.
3. **Finding the column:** the single column from `<tracker.tool> fields`
   whose name contains `backlog`, ignoring case and emoji. With none, several,
   or no `tracker.tool`, the first choice is **close it as not planned**
   instead, with the same comment (rule 5).
4. **On park:** read the card with `<tracker.tool> show <N>`, then
   `<tracker.tool> move <N> --from "<the column read>" --to "<the backlog column>"`.
   For `shared` the tool is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py"`.
   A card in `tracker.columns.in_progress` or `tracker.columns.needs_human`
   is not moved: say so. Then write three lines to `<scratch>/park-<N>.md`:
   ```
   Parked before speccing: <the trigger and its evidence>.
   Unpark when: <what would make it actionable>.
   Cheapest fallback if the need comes first: <one line, or "none found">.
   ```
   and post them with
   `gh issue comment <N> --repo <tracker.issues_repo> --body-file <scratch>/park-<N>.md`.
   No label and no spec. End this issue.
5. **On close as not planned:** § 6's close command, with the same three
   lines as its `--comment`. End this issue.
6. **On spec it anyway:** carry on to *Before you write* § 7. The trigger and
   its evidence go into `## Context` as a trap.
7. **A decline, or no person to ask:** post nothing, move nothing, comment
   nothing, and end this issue, saying what recon found. In a run of several,
   no person to ask stops the run, as *Several issues in one run* rule 6
   says. The four-choice menu for a declined question is not used here.
8. **When `tracker.public` is true**, the comment names no path, repo, host or
   person from outside this repo.
