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
findings as a comment on #<n>**, or **file a new issue**. The answer sets the
*target* for steps 2 to 5: a comment on #<n>, or a new issue. No likely
match: the target is a new issue. A declined question: write the draft as for
a new issue (steps 2 and 3), post nothing, say where it is and what step 3
removed, and stop.

Never edit another issue's body; it may be a spec.

## 2. Draft

Write the draft to a file in the scratchpad. The title, for a new issue, is
`<area>: <what>`, in the style of the titles step 1's search returned, if it
returned any; a comment has none. The body has these headings and no others,
in this order:

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

When `tracker.public` is true, the title and body keep only what is known to be
safe to publish. When unsure, remove it. Do this before the person sees the
draft, and again after every change to it. Remove:

- any path outside this checkout: absolute (`/Users/`, `/home/`, `/tmp/`,
  `/private/`, `C:\`), home-relative (`~/`), or into another checkout. A path
  inside this checkout is written relative to its root, and is kept;
- every repo, project, client, product or folder name from outside this
  checkout, in any form (`owner/repo`, a bare name, a folder), except
  `tracker.issues_repo`, `tracker.code_repo`, and tools and products anyone
  would know as public;
- hostnames and IP addresses, except inside a link the next rule keeps;
- links, except into `tracker.issues_repo` or `tracker.code_repo`, or to a
  public product's documentation. A share, preview, signed or secret link (a
  shared document, a gist, a preview deploy, a URL with a token) is removed
  wherever it points. The rule on names above applies inside a kept link too;
- anything that looks like a token or key, and email addresses;
- people's names (use their role);
- anything else not known to be safe, such as customer or business data in
  command output. The kinds above are the usual ones, not the only ones.

Keep a list of what you removed, in your own reply and never in the draft
file: each item's kind, where it was, and the removed text, except that a
token, key, email address or anything the last rule removed is named by kind
and place only (*a token, in the second finding*). Step 4 shows it with the draft. Something the person, having
seen that list, tells you to keep is theirs to publish: put it back and do not
remove it again.

## 4. Show and ask

Show the target, the title (for a new issue), the whole body and step 3's
list of removals. Then ask with `AskUserQuestion`: **post it** (naming the
target: *file it as a new issue* or *post it as a comment on #<n>*), **change
something**, or **don't post**.

- Change something: edit the draft, or change the target (a new issue then
  needs step 2's title; a comment goes only on an issue in
  `tracker.issues_repo`, so a target the person names in another repo is
  refused and the question asked again), run step 3 on it again, and ask
  again.
- Don't post, or the question is declined: post nothing, say where the draft
  file is, and stop.

## 5. Post

A new issue:

```bash
gh issue create --repo <tracker.issues_repo> --title "<title>" --body-file <file>
```

A comment on #<n>, however the target was chosen. First:

```bash
gh issue view <n> --repo <tracker.issues_repo> --json state,url -q '.state + " " + .url'
```

Post only when it exits 0 and prints `OPEN` and a URL ending `/issues/<n>` in
`tracker.issues_repo` (compared ignoring case). Anything else (closed, a pull
request, not found, an error): post nothing, tell the person why, set the
target to a new issue, write step 2's title, run step 3 on it, and go back to
step 4. Then:

```bash
gh issue comment <n> --repo <tracker.issues_repo> --body-file <file>
```

No label of any kind. Above all never `tracker.ready_marker`: it means
"specced", and the loop would take the issue. After a comment, skip step 6.

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
- still `not on project …`: add it once, then read it back the same way, and
  report what that read-back prints (or the add's error), without adding
  again;
- a non-zero exit with any other message: report that line and add nothing.

```bash
gh project item-add <tracker.project_number> --owner <tracker.project_owner> --url <issue url>
```

Never move the card. Otherwise (another tracker kind or tool): say the board
step was skipped, and why.

## 7. Report

- the issue's or the comment's link;
- the card's column as read back, or why there is none;
- what step 3 removed;
- for a new issue, next: `/gogogo:spec <n>` when someone is ready to design
  it.

## Claude-specific

- `AskUserQuestion` for steps 1 and 4.
