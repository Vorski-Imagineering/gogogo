# /gogogo:roadmap: 6. Milestones

Part of `/gogogo:roadmap`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

A section of the roadmap is a GitHub milestone when its heading links to one:
`## [<heading>](https://github.com/<tracker.issues_repo>/milestone/<number>)`.
A section whose heading links nothing is not one; a history section stays that
way. The document owns which sections are milestones, their titles, and
closing one; which milestone an issue is in goes both ways, and the side that
changed last wins. Nothing in GitHub changes until the person says yes.

1. **Plan.** From `W` (or from `D` when the document is in another repo):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roadmap_milestones.py" plan > <scratch>/milestones-plan.json
   ```
   Add `--link "<heading>"` for each section the person asked, in this request,
   to make a milestone.
   - Exit 0: say the milestones agree, and go to step 6 below.
   - Exit 2: quote its lines (stderr), say no milestone was changed, and go to
     step 6 below: the marks refresh still lands.
   - Exit 1: go on.
2. **Show the plan**, one plain line per item, numbered by its `id`, with its
   `why`, in three groups: *In GitHub* (`side` github or both, not questions,
   and not carrying `publishes`), *In the roadmap (goes into the refresh PR)*
   (`side` doc), and *Questions*. Items carrying `publishes` (a private roadmap
   on a public tracker) go only in a fourth group, *Titles to publish from a
   private roadmap*, each with its title word for word. Then each `skipped` line, each `kept` issue, and the
   `unlinked` headings.
3. **Ask.** First, each item carrying `publishes` in its own question, at
   most four per call: **Publish "<title>"** or **Don't publish**; only that
   answer approves it. A title not published takes with it every item whose
   `milestone.number` is null and `milestone.title` is that title (the issues
   of that section; the script also skips them), and the report names it by
   its item id only, never its text, when `tracker.public` is true. Then ask
   once with `AskUserQuestion`: **Apply all <k>** or **Apply none**, where
   `<k>` counts the items left that are not questions and carry no
   `publishes`; ask nothing when `<k>` is 0. A typed answer lists the ids to
   apply among those. Then ask each question item in its own question, at
   most four per call, its `choices` as the options, in order.
4. **Nobody to answer.** A refused or failed question, or no person (`claude
   -p`): apply nothing, and list every item as not applied. Do not show the
   four-choice decline menu. Nothing is applied without an answer.
5. **Apply** the approved ids and choices:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/roadmap_milestones.py" apply --plan <scratch>/milestones-plan.json --items <ids> [--choose <id>=<choice>]... [--publish <id>]...
   ```
   `<choice>` is the 1-based position of the answer among that question's
   `choices`. For each **Publish** answer, add its id to `--items` and add
   `--publish <id>`; the script writes no such title without it. Report each line it prints. `SKIPPED stale` means someone changed
   it meanwhile; the next refresh plans it again. `FAILED` gives GitHub's
   message. A `WARNING the milestones could not be read` line means the script
   could not tell which titles are on the tracker already, so an item that
   needs a title nobody approved with **Publish** printed `SKIPPED unapproved`
   even when that title may already be there. Say so, and run the same `apply`
   command again once the tracker answers; it asks nothing new. Skip this step
   when nothing was approved.
6. **The document.** Changes to it (a heading linked, a row moved, added or
   removed) stay in the working file, for step 8's commit. When the document
   is still unchanged (step 2 found every mark agrees and nothing here changed
   it), the refresh ends here: report as step 9 says, and in the same repo end
   as *Stopping early* says. Otherwise go on to step 7 of `SKILL.md`.
