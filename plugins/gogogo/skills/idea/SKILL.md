---
name: idea
description: Use when the user wants to keep what this session has found as a new tracker issue without speccing it ("make it an issue", "file this before I close", "an un-specced issue"), or when research is unfinished and the session is about to end. Not for writing a spec; that is spec.
---

# idea: save what this session found, as an un-specced issue

Turns what the session has already worked out into a new issue, so the work is
not lost when the session closes. A later `/gogogo:spec` on the issue starts
from these findings instead of from scratch. This skill files; it does not
design.

## First: read this repo's profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for idea --show
```

Exit 0 prints the settings; use them wherever this skill says *the profile*.
Any other exit: **stop and report the line it printed**. Every `gh issue` call
below passes `--repo <tracker.issues_repo>`.

## Only what the session already has

No further work is the whole point. You will want to "just check" one more file
so the issue is complete: don't. Open no file, run no search and fetch no page
for content. Each gap becomes an item under *Things the spec will need to
settle*. Reading the tracker for an existing issue (next step) is the one
lookup this skill makes.

## 1. Look for an issue that already covers it

```bash
gh issue list --repo <tracker.issues_repo> --state open --search "<two to four key terms>" --json number,title,url --limit 10
```

When one is a likely match, show it and ask with `AskUserQuestion`: **add these
findings as a comment on #<n>**, or **file a new issue**.

- Comment: write the body (step 2's layout, step 3's removals) to a file and
  show and ask as step 4 does. On **post it**, run
  `gh issue comment <n> --repo <tracker.issues_repo> --body-file <file>`, then
  report the comment's link and what step 3 removed, and stop. On **don't
  post** or a declined question, post nothing, say where the file is, and
  stop. Never edit another issue's body; it may be a spec.
- File new, or the question declined: go on.

## 2. Draft

Write the draft to a file in the scratchpad. The title is `<area>: <what>`,
in the style of the titles step 1's search returned, if it returned any. The body has these headings and no
others, in this order:

```markdown
## Request

<what the user asked for, in their words where they said it>

## What is there today

- <each finding, with its file:line, doc link, or the command run and what it printed>

## Ruled out

- <what was considered and dropped, and why>

## Things the spec will need to settle

- <each open question or option>
```

Leave out `## Ruled out` when nothing was. Never add a spec section: a heading
such as *Verify by hand*, *Approvals* or *Hard-stop check* makes the body read
as a spec, to `spec_lint.py` and to any agent. `/gogogo:spec` later carries
this body over as the issue's original report, unchanged.

## 3. Public trackers

When `tracker.public` is true, remove from the title and the body, before the
person sees the draft, and again after every change to it:

- any path outside this repo: absolute (`/Users/`, `/home/`, `/tmp/`,
  `/private/`, `C:\`), home-relative (`~/`), or into another checkout. Paths
  inside this repo are written relative to its root;
- other repos and projects, by any name: an `owner/repo` other than
  `tracker.issues_repo` and `tracker.code_repo`, or a bare repo, project or
  folder name the session met outside this repo;
- hostnames and IP addresses of machines and services. Links to public
  documentation stay;
- anything that looks like a token or key, and email addresses;
- people's names (use their role).

Keep a list of what you removed. It goes in your reply, never in the issue.

## 4. Show and ask

Show the title and the whole body, then ask with `AskUserQuestion`: **file
it**, **change something**, or **don't file**.

- Change something: edit the draft, run step 3 on it again, and ask again.
- Don't file, or the question is declined: file nothing, say where the draft
  file is, and stop.

## 5. File

```bash
gh issue create --repo <tracker.issues_repo> --title "<title>" --body-file <file>
```

No label of any kind. Above all never `tracker.ready_marker`: it means
"specced", and the loop would take the issue.

## 6. The card

Only when `tracker.kind` is `github-project` and `tracker.tool` is `shared`.
The board's own workflows add a new issue and place it, a few seconds after it
is filed, so read the card back before concluding anything:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py" show <n>
```

Run it up to six times, five seconds apart, until it prints a `column:` line
that is not `on board, no status`. Then, by what the last run printed:

- a column: report it;
- still `on board, no status`: report that the board has not placed it yet;
- still `not on project …`: add it, then read it back the same way;
- a non-zero exit with any other message: report that line and add nothing.

```bash
gh project item-add <tracker.project_number> --owner <tracker.project_owner> --url <issue url>
```

Never move the card. Otherwise (another tracker kind or tool): say the board
step was skipped, and why.

## 7. Report

- the issue link;
- the card's column as read back, or why there is none;
- what step 3 removed;
- next: `/gogogo:spec <n>` when someone is ready to design it.

## Claude-specific

- `AskUserQuestion` for steps 1 and 4.
