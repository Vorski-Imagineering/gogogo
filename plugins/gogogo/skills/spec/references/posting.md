# /gogogo:spec: Posting

Part of `/gogogo:spec`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- No issue yet?
- Save the current body to the scratchpad before anything else
- Write the spec to the scratchpad
- Compose the body file
- Lint it, then check the open specs that read this issue
- Re-read the description
- Apply the ready label
- Move the card to the queue
- Correcting a spec you already posted
- Never leave a second copy

Posting is outward-facing; do it when the user asked for it. When
`tracker.public` is true, everything you post is published: no credentials,
internal hostnames, personal data or infrastructure detail beyond what the
reporter already wrote.

`gh issue edit --body` replaces the whole body; there is no append. So compose
the full body locally and never let the report exist only in memory. In this
order, checking each step before starting the next:

0. **No issue yet?** When the user gave an idea rather than an issue, file one
   first in `tracker.issues_repo`, with a short title and the user's own words
   as the body: `gh issue create --repo <tracker.issues_repo> --title "<title>"
   --body-file <scratch>/idea.md`. Its number is `<N>` below, and those words
   become the original report. Then take its start snapshot
   (*Before you write* § 0) at once: the issue starts here.
1. **Save the current body to the scratchpad before anything else**, and
   check nobody changed the issue since it started:
   `gh issue view <N> --repo <tracker.issues_repo> --json body,labels > <scratch>/issue-<N>-now.json`,
   then write its body, from that same read, to `<scratch>/issue-<N>-original.md`
   (`python3 -c 'import json,sys; print(json.load(sys.stdin)["body"])' < <scratch>/issue-<N>-now.json > <scratch>/issue-<N>-original.md`).
   Confirm the file is non-empty (unless the issue body is empty). Then
   compare `body` and the set of label names with `issue-<N>-start.json`
   (*Before you write* § 0). Comments and `updatedAt` are not compared.
   - The same: go on to step 2.
   - Different: post nothing and add no label. Show the person what changed
     (a diff of the two bodies, and the labels added or removed), then ask:
     **keep the other version**, or **replace it with this run's answers**.
     - keep: stop this issue, and name the draft's scratchpad path. In a run
       of several, its final-report line is *skipped: changed by someone else
       meanwhile, kept*.
     - replace: the report section follows *Which report to keep* applied to
       the current body (never quote the other spec as the report); the spec
       below the `---` is this run's. Go on to step 2. When step 7 then
       withholds the label and the other version left it on, remove it
       (`gh issue edit <N> --repo <tracker.issues_repo> --remove-label "<ready_marker>"`):
       the label describes the spec now in the body. When the card is in
       `tracker.queue` (where the other version's step 8 put it), leave it
       and say so in the reply: a person moves it, since a run would take
       it from there. The final-report line
       says *replaced a version posted meanwhile*, then the line steps 7 and 8
       would give it.
     - A decline, or no person to ask: as keep, and the line says *skipped:
       changed by someone else meanwhile, nobody to ask*.
2. **Write the spec to the scratchpad**, so a failed call is re-postable.
   Inline `--body` mangles markdown; always use a file.
3. **Compose the body file**: the report section, a `---` rule, then the spec.
   ```
   ## Original report

   > <every line of the original body, each prefixed with "> ">

   ---

   ## Verify by hand
   ...
   ```
   `sed 's/^/> /'` over the saved file does the blockquote. It keeps the
   reporter's own `#` headings from splitting the spec's section structure.
   Do not edit, summarise, or correct the report; corrections go in
   `## Context`.
4. **Lint it, then check the open specs that read this issue**, before it
   leaves the machine:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_lint.py" <composed file>
   ```
   Fix every error it reports. A lint error is a rewrite, not a judgement call.
   Once the lint passes:
   1. List the open issues whose body has a command that reads `<N>`:
      ```bash
      gh issue list --repo <tracker.issues_repo> --state open --limit 1000 --json number,body -q '.[] | select(.body|test("(gh issue view|spec_check\\.py|spec_lint\\.py)[^\\n]*\\b<N>\\b")) | .number'
      ```
      A non-zero exit: post nothing, add no label, and report that the check
      could not run. A failed listing is not "none".
   2. Drop `<N>` itself. For each other number `<D>`, read its body below its
      `---` rule (a quoted report above it holds no steps). `<D>` is a
      *dependent* only when a matched line's command reads issue `<N>`; a
      line number such as `spec_check.py:94` is not an issue. None: say "no
      open spec reads #<N>" in the reply and go to step 5.
   3. For each dependent, re-read every step, test case or verification line
      that reads `<N>`'s body, against the composed new body. Record each as
      *still holds* or *would fail*.
   4. All still hold: go to step 5, and name each dependent and the steps
      re-read in the reply.
   5. A step would fail: find the narrowest form of its assertion that passes
      against the new body and still proves what the step was for (for
      example "no line starting `F:preflight.extra`" in place of "no line
      containing `preflight.extra`").
      - No such form: ask the person, naming the step: **post anyway and
        leave that spec to you**, or **post nothing**. A decline, or no
        person to ask: post nothing on `<N>`, add no label, and report it.
      - The dependent's card is in `tracker.columns.in_progress` (read with
        `<tracker.tool> show <D>`; for `shared`,
        `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" show <D>`), or an
        open pull request references it
        (`gh pr list --repo <tracker.code_repo> --state open --search "<D>"`,
        a PR whose title or body names `#<D>`): say so and ask before editing
        it. A read that fails counts as in flight; a profile with no
        `tracker.tool` or no `tracker.columns.in_progress` has no such column,
        so only the pull request check applies. A no, a
        decline, or no person to ask: do not edit it; after step 6, comment
        on it naming the step, why it now fails, and the narrower form.
      - Otherwise fix it after step 6: save `<D>`'s current body to the
        scratchpad, change only those lines, add one line to its
        `## Context` (`<date>: <step> narrowed because #<N> was re-specced`),
        lint it, `gh issue edit <D> --repo <tracker.issues_repo> --body-file <file>`,
        and re-read it. When the lint fails only on lines you did not change
        (an older spec, linted by newer rules), do not edit it: comment
        instead, as for an in-flight dependent, and say why. Its report, Approvals, label and card stay as they
        were. The fix changes only an assertion's wording, so this check is
        not run again on `<D>`.
   6. The reply names every dependent, each step re-read, and each one
      changed, commented on or left.
5. `gh issue edit <N> --body-file <composed file>`.
6. **Re-read the description** and confirm both the report and the spec are
   there.
7. **Apply the ready label**, the profile's `tracker.ready_marker`:
   `gh issue edit <N> --add-label "<ready_marker>"`. It is how a person scanning
   the tracker sees which issues an agent can pick up, so it means exactly one
   thing: *the spec is in this issue's body and needs nothing further from
   anyone*. It goes on only after step 6.

   **Not every posted spec earns it.** Withhold it, and say why in your reply,
   when:

   - the Hard-stop verdict has a **yes** that no Approvals row approves. The
     spec is a proposal waiting at a gate; label it once the user approves and
     you have added the row;
   - `## Approvals` carries an unresolved **external unknown**;
   - any pre-post check answered "no".

   A spec that stops at a gate is still worth posting; it just is not ready
   until the gate is cleared.

   Then take the start snapshot again (*Before you write* § 0): the body and
   labels are now this run's own, so a later pass through Posting in this
   run does not read them as someone else's change.
8. **Move the card to the queue.** Only when step 7 applied the label, the
   profile has both `tracker.tool` and `tracker.queue`, and `tracker.queue` is
   one of the board's columns (`<tracker.tool> fields --check` lists them);
   otherwise skip this step without a word. In a run of several issues
   (§ *Several issues in one run*) it runs per issue, right after that
   issue's step 7. In order:
   1. Read the card: `<tracker.tool> show <N>` (for `shared`,
      `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" show <N>`, and the
      same for `move` below). Run it as this step's first command,
      immediately before the move, never reusing an earlier read. When it
      exits non-zero, do not move the card: say the card could not be read,
      give its message, and stop this step.
   2. When the issue is closed: do not move it; say so.
   3. When the card is already in `tracker.queue`: nothing to do; say so.
   4. When the card is in `tracker.columns.in_progress`,
      `tracker.columns.needs_human`, or any `stages` entry's `column`: do not
      move it. Say which column it is in and that it was left there, because
      someone may be working on it or it has shipped. A setting the profile
      lacks names no column.
   5. When the issue has no card: for `tracker.tool` `shared`, run
      `move <N> --to "<tracker.queue>" --add-missing`. For any other tool, say
      the issue has no card on the board and leave it.
   6. Otherwise: `move <N> --from "<the column read in 8.1>" --to "<tracker.queue>"`,
      so a card another session moved since that read is not moved back. A
      card 8.1 read with no column has none to name: move it without `--from`.
   7. Report the result. Only a zero exit counts as moved. On exit 3 the card
      moved meanwhile: read it again with `show <N>`, say it moved meanwhile
      and name its column (*already in `<tracker.queue>`* when it is there),
      and leave it. On any other exit, say the move failed, give its message,
      and leave the card. The label stays: it describes the spec, not the card.

   Nothing in this step asks the user anything.

Which report to keep:

- **Body is a plain report** → it is the report.
- **Body is already a spec with `## Original report` at the top** → carry that
  section over unchanged; replace only the spec below the `---`.
- **Body is a spec with no report section** (an older layout) → if the report
  sits above a `---` rule, that part is the report. Otherwise find it in an
  earlier comment or in the issue's edit history (`gh api graphql` →
  `userContentEdits`) and put it back at the top. If no copy can be found, say
  so in your reply; do not invent one.
- **Body is empty** → no report section; the spec starts at `## Verify by hand`.

**Correcting a spec you already posted:** edit the scratchpad file and re-run
Posting steps 4 to 6 (the lint and the check of open specs that read this
issue, `gh issue edit --body-file`, the re-read), so the issue carries one accurate
spec rather than a spec plus errata.

**Never leave a second copy** of the spec or of the report. If an earlier
version is sitting in a comment (including a spec you just rescued into the
body under *Before you write* §0), delete it once the description is confirmed
correct: `gh api -X DELETE /repos/{owner}/{repo}/issues/comments/{id}`. Get the
id from the comment's URL (the digits after `issuecomment-`).

Comments are for **conversation about** the spec: a question, a correction
someone raised, a follow-up cross-link. Never for the spec itself.
