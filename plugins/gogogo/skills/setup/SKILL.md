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
  - **Workspace: ask.** Ask where gogogo does each issue's work, as the
    *Where each issue's work goes* bullet below says: its explanation first,
    then `AskUserQuestion` with two options, `The checkout` and
    `A worktree per issue`, the recommended one first and marked. Record the
    answer as `integration.workspace` (`"checkout"` or `"worktree"`).
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
    for word; do not rewrite it, **except a recipe for a step the plugin runs
    itself**: text telling an agent how to send notifications (`notify`),
    branch or set up a workspace (`integration.workspace`, `integration.base`),
    merge (`integration.strategy`), move cards (`tracker.columns`, `stages`),
    report and hand back (`handback`), or run preflight checks
    (`preflight.extra`). That includes a send function, where its credentials
    live, and a table keyed to the retired skill's own section numbers or
    columns. Decide by what the text does, not by its heading. A project fact
    such a step uses (a command, a host, a quirk of this repo's CI or deploy)
    still moves. A section holding both moves its facts and leaves out its
    recipe. The profile gets no section or line for what is left out.

  Show the draft to the user before writing it. It describes how their project
  works; they approve it. Under **Left out**, name each part left out: the
  retired skill, its heading, and the setting that covers it.
- **A profile missing a setting the skills now require.** Add it with the
  value the board uses, shown to the user first. When the setting names a new
  column, the board needs that column too (below), and when the profile sets
  `roadmap.file`, that document's legend needs a row covering it, as
  `/gogogo:roadmap` shows; offer to add it. When the
  check warns that a setting is unknown (a key retired from the profile
  format, such as a column role no skill reads any more), offer to remove it.
- **A setting the check filled with a default.** A warning
  `<path>: missing; using <value> (default since gogogo#<n>)` means the skills
  already run on `<value>`. Offer to write `<path>` into the profile with that
  value, shown to the user first, and write it only on a yes.
- **Where each issue's work goes** (`WARN workspace: not decided`, or a new
  profile). `integration.workspace` decides where `/gogogo:dev` and
  `/gogogo:auto-dev` put an issue's branch. Ask it outright, every time it is
  not set; never pick for the user.
  1. When the `workspace` row names a `live checkout`, say first, before
     anything else, exactly what runs from this folder: each reason it gives,
     one per line. Explain that until that thing runs from an installed copy,
     an issue's branch checked out here changes what it runs, for every
     session on this machine. Recommend moving it to an installed copy (a
     deploy step that copies it outside the repo, or the installed plugin in
     place of `--plugin-dir`) and keeping the checkout. Offer
     `A worktree per issue` only as the alternative to that recommendation.
     With no live checkout, say nothing about live files.
  2. Show this explanation, word for word, filling in `<repo>` with the main
     worktree's folder name (the folder of the first entry of
     `git worktree list --porcelain`), which is the name dev and auto-dev put
     in `../<repo>-wt-<n>`, not the name part of `tracker.code_repo`. The option labels are not the explanation;
     it is text shown before the question:

     > **Where should gogogo do each issue's work in `<repo>`?**
     >
     > **The checkout** (recommended when one person works this repo in the normal way). Each issue's branch is checked out in the folder you already use. `git status`, your editor and your file browser show the work in progress where you look. When the issue merges, the folder goes back to the main branch, and nothing new is left on disk. The cost: while an agent works an issue, this folder is on that issue's branch. Don't do other work in it at the same time, and anything that runs files straight from this folder runs the branch's version.
     >
     > **A worktree per issue** (only for power users, such as several sessions working this repo at once, or a deploy that runs files from this folder and can't be moved). Each issue gets its own folder beside this one, `../<repo>-wt-<n>`, on its own branch, and this folder stays on the main branch. The cost: work in progress is not in the folder you look at, so you have to know to open `../<repo>-wt-<n>`. Worktrees are complex and tend to leave folders all over the disk. gogogo removes one only after its issue's merge is verified, a stopped issue's folder stays until the issue is finished, and other tools that make worktrees leave their own. Each folder needs its own installs and build state. **gogogo's worktree support is in development and not deeply tested.**

  3. Ask with `AskUserQuestion`: `The checkout` and `A worktree per issue`,
     the recommended one first and marked. `The checkout` is recommended,
     unless the user has turned down moving a live thing to an installed copy
     or has said several sessions work this repo at once.
  4. Show the one-line profile change, `workspace = "checkout"` or
     `workspace = "worktree"` under `[integration]`, and commit it like
     setup's other profile changes. Re-run the check: the row reads
     `INFO workspace: <value>`.
  5. On `The checkout` with a live checkout, offer to file an issue in
     `tracker.issues_repo` describing the move to an installed copy (what
     runs from this folder, and the recommendation above), asking first.
     Setup moves nothing itself.
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
  specifics into the profile, and update anything that names it. Text left
  out of the profile stays only in the retired copy.
- **`CLAUDE.md` does not point at the profile.** Add a short section saying
  the process skills come from the `gogogo` plugin and this repo's specifics
  are in `.agents/dev-process.md`.
- **Independence** (the `independence` row). How much Claude decides on its
  own in this repo, and how much it brings to a person. The row is `INFO`, so
  this question is asked on every setup run, after the `FAIL` and `WARN`
  lines, a repo that is already set up included. Ask once with
  `AskUserQuestion`, in plain words: which level Claude should work at in
  this repo. One option per level, each one line on what it asks and what it
  decides, with the current level marked:
  - `junior-dev`: asks about every choice, and decides nothing itself;
  - `tech-lead`: asks about approvals and anything people will see, and
    decides how things are built;
  - `product-owner`: asks only for approvals, and decides what is built and how.

  Say that `tech-lead` and `product-owner` are best run on an Opus-class model at
  medium effort or higher. On an answer different from the current level,
  write `independence = "<level>"` to the profile (a top-level key, above the
  first `[table]`) and commit it as setup commits any other profile change. On
  a decline, write nothing and say the level stays as it is.
- **Notifications** (the `notify` row). Telegram messages tell a person when
  an unattended run starts, changes state and closes. They are optional. A
  profile with no `notify` line sends whenever this machine has bot
  credentials; `notify = "none"` turns a repo off.
  - `INFO notify: off`: ask once with `AskUserQuestion`:
    - **every repo on this machine** (recommended): steps 1 and 2 below, which
      write the per-user file.
    - **only this repo**: first make sure `.claude/gogogo/` is in the repo's
      `.gitignore`, adding it and committing it like setup's other changes.
      Then steps 1 and 2 with `--repo` on each command:
      `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/notify.py" init --repo`, `chat-id --repo`
      and `chat-id --save <its id> --repo`.
    - **no messages**: write `notify = "none"` to `.agents/dev-process.md` and
      commit it like setup's other profile changes, so messages stay off when
      credentials appear on this machine later. Say that `/gogogo:setup` can
      set them up later.
  - On every repo or only this repo, or on `WARN notify: telegram, but no bot credentials`:
    when the profile says `notify = "none"`, first remove that line and commit
    it like setup's other profile changes, or the row stays `INFO notify: off`.
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
    3. Send the person a message that names this machine, with the hostname from `uname -n`,
       and where it applies: `<scope>` is `every repo on this machine` when the
       credentials went in the per-user file, and `<repo>` (the name part of
       `tracker.code_repo`) when they went in the repo's own file:
       `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/notify.py" send --text "✅ gogogo is connected on $(uname -n) for <scope>. auto-dev runs there will report here: when a run starts and ends, and when each issue starts, is skipped, merges or needs you."`,
       and re-run the check: the row must be `PASS notify: telegram (by default): bot @… -> …`
       (`PASS notify: telegram: …` when the profile names the transport).
  - `WARN notify: telegram: <reason>`: show the reason. The usual causes are a
    wrong token (paste it again) and a chat the bot cannot reach (send the bot
    a message, then `chat-id`, and `chat-id --save <id>` for the chat the
    person confirms). Add `--repo` to each command when this repo keeps its
    own `.claude/gogogo/notify.env`.

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
- `workspace` → ask where each issue's work goes, as the *Where each issue's
  work goes* bullet above says. An `INFO workspace` row with a `live checkout`
  is named to the user too: it is what runs from this folder.

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
