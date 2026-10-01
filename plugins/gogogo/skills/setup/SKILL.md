---
name: setup
description: Use when onboarding a repo onto the gogogo skills, or checking that a repo's setup is still right — the plugin settings, the process profile, the Hard Stop source, the tracker board and its columns, the ready label, and local skills the shared ones replace. Also when a gogogo skill stopped on a missing setting and the user wants it fixed.
---

# setup: onboard a repo onto the gogogo skills, or check it still is

## 1. Check

From anywhere in the repo:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup_check.py"
```

It only reads. Each line is `PASS`, `FAIL` (with the fix after `->`), `WARN`
or `INFO`. Show the user the whole list, grouped: what is fine, what is broken,
what to look at. Exit 0 means nothing failed.

## 2. Fix, one thing at a time, with approval

Work down the `FAIL` lines, then the `WARN` lines the user wants handled.
**Each fix that writes outside this session (a commit, a label, a board change)
is asked first**: say exactly what will be created or changed, then do it. Then
re-run the check.

What each fix involves:

- **Plugin settings.** `claude plugin marketplace add Vorski-Imagineering/gogogo --scope project`,
  then `claude plugin install gogogo@vorski-skills --scope project`, then set
  `"autoUpdate": true` on the marketplace entry. Commit `.claude/settings.json`
  (with `git add -f` if the repo ignores `.claude/`).
- **No profile.** Draft `.agents/dev-process.md` from
  `references/profile-schema.md`, reading the repo rather than guessing:
  - **Release shape: ask first.** Before reading any deploy script, ask with
    `AskUserQuestion` one question: after a change merges to the main branch, is
    it live for users straight away, or does it reach a dev/staging site first
    and a person promotes it later? Two options: `Straight to production` and
    `Dev or staging first`. The answer decides the shape of `environments`,
    `stages`, `verify.agent` and `verify.human` below. Then read the deploy
    scripts and CI to fill in names, URLs and `reached_by`; if what is read
    contradicts the answer, say so and ask again, do not pick.
  - `hard_stops`: the repo's own Hard Stop rules, usually a `CLAUDE.md`
    section. Name its items word for word. If the repo has none, **stop and
    ask**: Hard Stops are the owner's decision, never the skill's.
  - `lanes`: the test commands the repo actually uses (`package.json`
    scripts, `Makefile`, the CI workflow, `CLAUDE.md`).
  - `environments` and `stages`: where code runs before and after a merge, and
    what a merge deploys, in the shape the answer above gave:
    - *Straight to production:* two environments: one with roles
      `["pre-merge"]` where the change runs before merging (the repo's own word
      for it, such as a local server or preview build), one with roles
      `["production"]`; **no** `pre-production` role anywhere. Exactly one
      `[[stages]]` entry: `code_is = "merged to main"`, `environment` = the
      production environment, `column = "Released"`. `verify.agent` names the
      pre-merge environment only, never production; `verify.human` names
      production. The loop then stops each issue at a PR (`auto-dev` §4), and
      the draft says so.
    - *Staged:* an environment with the role `pre-production`, and one stage per
      step in the order code travels, as `references/profile-schema.md` shows.
  - `tracker`: the issues repo, the ready label, and the board.
  - The sections `## Recon traps`, `## Lane constraints` and
    `## superpowers boundary`. When the repo already has local skills being
    replaced, **move** their project-specific text into these sections word
    for word; do not rewrite it.

  Show the draft to the user before writing it. It describes how their project
  works; they approve it.
- **No board, or missing columns.** Every board uses the same Status
  columns, in this order:

  | Column | Holds |
  |---|---|
  | `Future` | Kept for later; not in the working backlog. |
  | `⚡️ New` | Just arrived; a human triages it into Backlog or Future. |
  | `Backlog` | Filed; not yet specced or not yet chosen. |
  | `Dev Ready` | Specced and chosen: the queue (`tracker.queue`, and `columns.back_to_queue`). |
  | `In progress` | Being worked (`columns.in_progress`). |
  | one per stage | The profile's `stages`, in order, named in the repo's words. |
  | `Done` | Confirmed by a human. The skills never move a card here. |

  A straight-to-production repo has one stage, so one stage column
  (`Released`); do not create stage columns it will never use.

  Offer to create the board (`gh project create --owner <owner> --title <repo>`),
  set these Status options, link it to the repo, and add the open issues.
  On an existing board, rename a column in place rather than deleting it and
  adding a new one: send every option back with its `id` in one
  `updateProjectV2Field` call, change only the name, and compare
  `<tracker.tool> list` before and after. An option sent without its `id` is
  recreated, and every card in it loses its column.

  Two things only the board's web page can set. Do them yourself with the
  Claude in Chrome tools (load the `claude-in-chrome` skill and its tools in
  one `ToolSearch` call), signed in as the user; say what you are about to
  change first, as for any other write, and read the page back afterwards.
  If the browser tools are missing, the user is not signed in, or an action is
  refused, stop and give the user these steps instead; never retry a refused
  click another way.
  - **Workflows** (`https://github.com/orgs/<owner>/projects/<n>/workflows`).
    Open **Auto-add to project** → Edit: choose this repo, set the filter to
    `is:issue,pr is:open` (the default `label:bug` adds almost nothing), Save
    and turn on. Open **Item added to project** → Edit: set the value to
    Status = the new-issue column (`⚡️ New`), Save and turn on. The check
    reads both back.
  - **Labels in each view.** In every view, **View → Fields** and tick
    **Labels**, then **Save view** and confirm; with it off, a card carrying
    the ready label looks unlabelled. The check cannot see this: read the
    column header (or a card's label chip) back in each view.
  Then set `tracker.tool = "shared"`.
- **No ready label.** The check prints the `gh label create` command.
- **Local skills the shared ones replace.** Move each to
  `.claude/skills-retired/` in the same change that moves its project
  specifics into the profile, and update anything that names it.
- **`CLAUDE.md` does not point at the profile.** Add a short section saying
  the process skills come from the `gogogo` plugin and this repo's specifics
  are in `.agents/dev-process.md`.

## Reviewing a repo that is already set up

Run the same check and treat its `WARN` lines as the review: they are what has
drifted since the repo was onboarded. Do not stop at an exit 0. Group them,
propose one fix for each (what will change, and where), and apply only the
ones the user approves:

- `marketplace source` names an old repo name → set `source.repo` to the
  current one in `.claude/settings.json`.
- `board workflows`, `issues missing from the board`, `cards without a column`
  → the web steps above (done in the browser), then `<tracker.tool> move` for stray cards; add
  missing issues with `gh project item-add`.
- `unused column` → move its cards to the column that now holds that stage,
  then ask the user to remove the column in the board's Status settings. Never
  delete a column that still holds cards.
- `release shape` → correct the profile's `environments`, `stages` or
  `verify.agent` to the shape the repo really has.
- `local skills` → retire them as above.

Name the `INFO` lines too (release shape, tool): they are what the check
understood the repo to be, and the user should confirm it.

## 3. Prove it works

When the check passes:

1. In a fresh session, the `/` menu lists `gogogo:spec`, `gogogo:dev` and
   `gogogo:auto-dev`, and none of the retired local skills.
2. `/gogogo:auto-dev --triage-only` reads the queue and changes nothing.

Report what was set up, what was left as a warning and why, and anything the
user still has to do on their own machine (for example `gh auth setup-git`, so
a private marketplace can be fetched without a prompt).

## Changes go through the repo's own path

Commit the setup changes on a branch and merge them the way the profile's
`integration` says, like any other change. Do not push to a protected main
branch directly.
