---
name: setup
description: Use when onboarding a repo onto the gogogo skills, or checking that a repo's setup is still right — the plugin settings, the process profile, the Hard Stop source, the tracker board, its columns and kanban views, the ready label, and local skills the shared ones replace. Also when a gogogo skill stopped on a missing setting and the user wants it fixed.
---

# setup: onboard a repo onto the gogogo skills, or check it still is

## 1. Check

From anywhere in the repo:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup_check.py"
```

It only reads. It opens with a `config:` block: the board's address and the
repo's settings as the profile and `.claude/settings.json` give them, `missing`
where there are none. Show that block to the user first, as printed. Then come
the checks: each line is `PASS`, `FAIL` (with the fix after `->`), `WARN` or
`INFO`. Show the user the whole list, grouped: what is fine, what is broken,
what to look at. Exit 0 means nothing failed. The `notify` row is always
"what to look at", never a blocker: a repo runs the same with messages off.

Among the checks after the block, the one that decides whether setup can go on
is `git: clean main`. Setup commits to the repo, so it starts
on the default branch with nothing uncommitted and level with origin. If that
line fails, stop and tell the user what it found. Do not stash, reset, switch
or pull over their work for them; it may be someone's work in progress. Go on
once they have cleared it and the line passes.

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
    section. Name its items word for word. Hard Stops are the owner's
    decision, never the skill's, so if the repo has none, do not write any.
    Look instead for the nearest list it already has of what an agent must
    ask about first (a section on what stays with the person, what to ask
    before, what never to do). Then put two things to the user together:
    - use that list as an interim `hard_stops.source`, with its items word
      for word;
    - file an issue in the repo recommending it define its own
      `## Hard Stops` section, naming the kinds of change that cost most
      there (what reaches every user, security, identity, data).

    With a yes to both, file the issue, use the interim list, and name the
    issue in the draft and the commit. If the repo has no such list either,
    **stop and ask**.
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
      production. `auto-dev` then merges each issue that clears every gate,
      and every merge is a release; the draft says so, and that a run needs
      bypass permissions to merge.
    - *Staged:* an environment with the role `pre-production`, and one stage per
      step in the order code travels, as `references/profile-schema.md` shows.
  - `[release]`: ask whether production deploys should be numbered and tagged
    by the standard (`references/versioning.md`). On a yes, write `major = 1`,
    or one above a version a store already holds, and say in the draft where
    the deploy should call `release.py tag`. On a no, leave the table out; the
    check then reports it as not adopted.
  - `tracker`: the issues repo, the ready label, and the board.
  - The sections `## Recon traps`, `## Lane constraints` and
    `## superpowers boundary`. When the repo already has local skills being
    replaced, **move** their project-specific text into these sections word
    for word; do not rewrite it.

  Show the draft to the user before writing it. It describes how their project
  works; they approve it.
- **A profile missing a setting the skills now require.** Add it with the
  value the board uses, shown to the user first. `tracker.columns.needs_human`
  is `"Human!Help!"`, and the board needs that column too (below). When the
  profile sets `roadmap.file`, that document's legend needs a row covering the
  new column, as `/gogogo:roadmap` shows; offer to add it. When the
  check warns that a setting is unknown (a key retired from the profile
  format, such as a column role no skill reads any more), offer to remove it.
- **No board, or missing columns.** Every board uses the same Status
  columns, in this order:

  | Column | Holds |
  |---|---|
  | `Future` | Kept for later; not in the working backlog. |
  | `⚡️ New` | Just arrived; a human triages it into Backlog or Future. |
  | `Backlog` | Filed; not yet specced or not yet chosen. |
  | `Dev Ready` | Specced and chosen: the queue (`tracker.queue`). |
  | `In progress` | Being worked (`columns.in_progress`). |
  | `Human!Help!` | Stopped and waiting for a person: an unreviewed fix, a decision, or verification that gave up (`columns.needs_human`). A person moves it on; no skill does. |
  | one per stage | The profile's `stages`, in order, named in the repo's words. |
  | `Done` | Closed. `/gogogo:auto-test` moves a card here on a pass, and `tracker.py tidy --apply`, run by a person, moves closed issues here. No other skill moves a card here. |

  A straight-to-production repo has one stage, so one stage column
  (`Released`); do not create stage columns it will never use.

  Offer to create the board (`gh project create --owner <owner> --title <repo>`),
  set these Status options, link it to the repo, and add the open issues.
  On an existing board, rename a column in place rather than deleting it and
  adding a new one: send every option back with its `id` in one
  `updateProjectV2Field` call, change only the name, and compare
  `<tracker.tool> list` before and after. An option sent without its `id` is
  recreated, and every card in it loses its column. A missing column: the
  check's own fix is for a person to add it in the board's Status field
  settings in the GitHub UI, which has no such risk. Offer that first. If the
  user wants setup to add it, use the same call: every existing option with
  its `id`, plus the new one without, in the table's order.

  Create the two kanban views with the REST API (owner `orgs/<owner>`, or
  `users/<owner>` for a personal board). Read the field ids with
  `gh api orgs/<owner>/projectsV2/<n>/fields -q '.[]|"\(.id) \(.name)"'`,
  then for each view:

  ```bash
  gh api -X POST orgs/<owner>/projectsV2/<n>/views --input - <<<'{"name": "<name>",
    "layout": "board", "filter": "<filter>", "visible_fields": [<ids>]}'
  ```

  | View | Filter |
  |---|---|
  | `Backlog` | `is:open -status:Done,Future` |
  | the queue column's name (`Dev Ready`) | `is:open -status:Done,Future,<each stage column> label:"<tracker.ready_marker>"` (quote a column name that has a space) |

  `visible_fields` holds the ids of Title, Assignees, Status, **Labels**,
  Linked pull requests and Sub-issues progress. Get the filter right the first
  time; `<tracker.tool> views --hide-closed` adds `is:open` to a view that
  lacks it, and a view that is wrong in another way is fixed on the web page. A board layout groups by Status on its own.

  Three things only the board's web page can set. Do them yourself with the
  Claude in Chrome tools (load the `claude-in-chrome` skill and its tools in
  one `ToolSearch` call), signed in as the user; say what you are about to
  change first, as for any other write, and read the page back afterwards.
  If the browser tools are missing, the user is not signed in, or an action is
  refused, stop and give the user these steps instead; never retry a refused
  click another way.
  - **Workflows** (`https://github.com/orgs/<owner>/projects/<n>/workflows`).
    Open **Auto-add to project** → Edit: choose this repo, set the filter to
    `is:issue is:open` (issues only: an issue's PR already shows on its card
    through *Linked pull requests*; the default `label:bug` adds almost
    nothing), Save
    and turn on. Open **Item added to project** → Edit: set the value to
    Status = the new-issue column (`⚡️ New`), Save and turn on. The check
    reads both back.
  - **Backlog newest first.** In the `Backlog` view, **View → Sort by →
    Created**, descending, then **Save view** and confirm.
  - **Labels in each view.** In any view that does not show **Labels** (the
    board's default table, or a view created without it), **View → Fields**
    and tick **Labels**, then **Save view** and confirm; with it off, a card
    carrying the ready label looks unlabelled. The check reads the board views
    back.
  Then set `tracker.tool = "shared"`.
- **No ready label.** The check prints the `gh label create` command, with
  the standard colour.
- **Ready label colour** (`WARN tracker: ready label colour`). Say that the
  label's colour will change from its current value to the standard one and
  nothing else will, ask, then run the `gh label edit` command the row prints
  and re-run the check. If the user declines, leave it.
- **Pull requests on the board**
  (`WARN tracker: pull requests on the board`). Pull requests are cards because Auto-add includes, or included,
  them. Set Auto-add's filter to `is:issue is:open` (the *Workflows* bullet's
  steps). Then list every own-repo pull-request card (`<tracker.tool> list
  --json`, `kind` `PullRequest`) by number and column, and ask whether to
  archive them all. On yes, run
  `gh project item-archive <tracker.project_number> --owner <tracker.project_owner> --id <item_id>`
  for each and report each result; on no or a decline, archive nothing and
  say they stay. Re-run the check afterwards.
- **Delete merged branches** (`FAIL code repo: delete merged branches`).
  Say that GitHub will then delete a pull request's branch on GitHub when
  it merges (local copies stay), and that the row's undo command turns it
  back off. Ask, then run the `gh api -X PATCH` command the row prints and
  re-run the check. If the user declines, leave it and say the line will
  keep failing.
- **Local skills the shared ones replace.** Move each to
  `.claude/skills-retired/` in the same change that moves its project
  specifics into the profile, and update anything that names it.
- **`CLAUDE.md` does not point at the profile.** Add a short section saying
  the process skills come from the `gogogo` plugin and this repo's specifics
  are in `.agents/dev-process.md`.
- **Notifications** (the `notify` row). Telegram messages tell a person when
  an unattended run starts, changes state and closes. They are optional.
  - `INFO notify: off`: ask once with `AskUserQuestion`: set up Telegram
    messages for unattended runs, or no messages. On no, write nothing; say
    messages stay off and that `/gogogo:setup` can set them up later.
  - On yes, or on `WARN notify: telegram, but no bot credentials`:
    1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/notify.py" init`. Tell the
       person to make a bot (in Telegram, **@BotFather**, `/newbot`; a bot
       made for the Telegram channel plugin works too) and to paste its token
       after `TELEGRAM_BOT_TOKEN=` in the file `init` printed, themselves.
       Never ask for the token in the chat, and never print or read that
       file: the transcript is stored on disk.
    2. Ask them to send the bot any message, then run
       `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/notify.py" chat-id`. Show the
       chats it prints; once they say which one is theirs, run
       `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/notify.py" chat-id --save <its id>`.
    3. Only when the profile does not already say `notify = "telegram"`: ask,
       then set it in `.agents/dev-process.md` and commit it like setup's
       other profile changes.
    4. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/notify.py" send --text "<repo>: notifications on"`,
       and re-run the check: the row must be `PASS notify: telegram: bot @… -> …`.
  - `WARN notify: telegram: <reason>`: show the reason. The usual causes are a
    wrong token (paste it again) and a chat the bot cannot reach (send the bot
    a message, then `chat-id`, and `chat-id --save <id>` for the chat the
    person confirms).

## Reviewing a repo that is already set up

Run the same check and treat its `WARN` lines as the review: they are what has
drifted since the repo was onboarded. Do not stop at an exit 0. Group them,
propose one fix for each (what will change, and where), and apply only the
ones the user approves:

- `marketplace source` names an old repo name → set `source.repo` to the
  current one in `.claude/settings.json`.
- `board views`, `labels in board views` → create a missing view with the
  API as above; sort and Labels on the web page.
- `board workflows`, `cards without a column`
  → the web steps above (done in the browser), then `<tracker.tool> move` for stray cards.
- `cards the board's index missed` → nothing to fix unless the row persists:
  `tracker.py` already reads those cards from the issue side.
- `views` → run `<tracker.tool> views --hide-closed` with the user's yes; it
  reads the views back.
- `cards` → run `<tracker.tool> tidy`, show the user the list, and run
  `tidy --apply` only on their yes.
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

## Changes land on the default branch, and the repo is left clean

Commit the setup changes on the default branch and push them. If the push is
refused because the branch is protected, put the same commit on a branch, open
a PR, merge it once the user approves, and delete the branch on origin and
locally.

Either way, finish on the default branch with nothing uncommitted, level with
origin, and no setup branch left behind. Re-run the check to show it:
`git: clean main` passes.
