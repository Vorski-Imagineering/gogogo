# /gogogo:spec: Several issues in one run

Part of `/gogogo:spec`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

1. **When it applies.** The user gives more than one issue (numbers, `#n`,
   issue URLs, in any mix) or a board column ("everything in New"). One issue
   works exactly as before, and none of this section applies.
2. **The list is fixed at the start.** Keep issue numbers in the order given.
   For a column, match the user's words against the board's columns from
   `<tracker.tool> fields`: use the single column whose name contains them,
   ignoring case and any emoji. When none or several match, ask which column,
   naming the matches. Then read it once:
   ```bash
   <tracker.tool> list --status "<column>" --issues-only --open-only --json
   ```
   and keep the order it prints. A column needs `tracker.tool`; without it,
   say the tracker has no columns to read, and ask for issue numbers. Say the
   list and its order in one line before starting. An issue filed during the
   run, such as a split-off, is never added; it goes in the final report
   (rule 7).
3. **Skip before starting an issue**, and record why: it is closed (its
   `state` is anything but `OPEN`); it is a pull request (`gh issue view <n>
   --json state,url` answers for one too, and its `url` contains `/pull/`);
   or it is ready already, which means it carries
   `tracker.ready_marker` (compared ignoring case) **and** its current body
   passes the lint:
   ```bash
   gh issue view <n> --repo <tracker.issues_repo> --json body -q .body > <scratch>/issue-<n>-body.md
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_lint.py" <scratch>/issue-<n>-body.md
   ```
   exits 0 with a last line `label: apply`. Any other result means it is
   specced like any other issue.
4. **One issue at a time.** Each issue goes through this whole skill: *Before
   you write*, the question rounds, and Posting steps 0 to 8. Only then does
   the next issue start. Ask about one issue only in each question call, and
   name it in every question (`#<n>: …`).
5. **Research one issue ahead.** When an issue starts, run rule 3 on the
   issues after it until one is not skipped, and start background research
   of that one, and only that one (see
   *Claude-specific*). It is read-only: it reads the issue, its comments and
   the code, then returns its findings with `file:line` and the forks it sees.
   It posts nothing, labels nothing, moves no card and asks no question. Its
   result is neither shown nor used until the current issue is posted, left
   open or skipped. When the next issue starts, take its research. Before its
   first question, re-read any file that the just-posted spec lists under
   `## Files` and that the research relied on, and state any order between
   the two issues as the chain rule in *Hard-stop verdict* says.
6. **Leave it open ends that issue only.** Choice 4 of *When the user declines
   a question*, or a declined menu, posts nothing and adds no label on that
   issue. Record the question left open, and go on to the next issue. When the
   question tool errors (no person to ask), stop the whole run and report
   every issue not reached.
7. **The final report** has one line per issue in the list: *specced and
   labelled*; *posted without the label* (naming Posting step 7's withholding
   case); *left open* (with the question); *skipped* (closed, a pull request,
   or already ready); *skipped: being built* (with the column or pull
   request); *closed: nothing hits it today*; *not filed: nothing hits it
   today*; *stopped: nothing hits it today, no answer*;
   *skipped: changed by someone else meanwhile* (kept, or nobody to ask;
   Posting step 1); *replaced a version posted meanwhile*; or *not reached*
   (with why the run stopped). Each
   *specced and labelled* line ends with its card's result from Posting step
   8: moved, already there, left in `<column>`, moved meanwhile to
   `<column>`, closed, no card, could not be read, the move failed, or step 8
   skipped (and which of its conditions was not met). Every line, whatever its
   outcome, also names any dependent Posting step 4 edited or commented on.
   Then each issue filed during the run, with `/gogogo:spec <n>`.
