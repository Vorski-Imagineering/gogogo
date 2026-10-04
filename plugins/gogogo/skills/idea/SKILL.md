---
name: idea
description: Use when the user wants to keep what this session has found as a new tracker issue without speccing it ("make it an issue", "file this before I close", "an un-specced issue"), or to file a finding on gogogo itself ("file this on gogogo", upstream), or when research is unfinished and the session is about to end. Not for writing a spec; that is spec.
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
below passes `--repo <target repo>` (§ *The target*).

Any `warning:` line the check printed goes, verbatim, at the top of your report to the person; if it printed none, the report says so.

## Only what the session already has

No further work is the whole point. You will want to "just check" one more file
so the issue is complete: don't. Open no file, run no search and fetch no page
for content. Each gap becomes an item under *Things the spec will need to
settle*. Reading the tracker for an existing issue (next step) is the one
lookup this skill makes.

## The target

The text this skill posts goes to one *target*: a new issue in
`tracker.issues_repo`, or a comment on an issue there (step 5 checks it is
open). Nowhere else, and
only one. An answer or a change that chooses a target anywhere else, or more
than one, is refused as a whole: say so, change nothing, and ask again. Merely
mentioning another repo is not choosing it.

One exception, the *upstream target*: when the person asks in words for it to
go to gogogo ("file it on gogogo", "upstream", "against the plugin"), and
`tracker.issues_repo` is not `Vorski-Imagineering/gogogo` (compared ignoring
case), the target is a new issue in `Vorski-Imagineering/gogogo`, or a comment
on an open issue there. Still one target, and any other repo is still refused
as a whole. `<target repo>` below is `tracker.issues_repo`, or
`Vorski-Imagineering/gogogo` for the upstream target.

## 1. Look for an issue that already covers it

```bash
gh issue list --repo <target repo> --state open --search "<two to four key terms>" --json number,title,url --limit 10
```

When one is a likely match, show it and ask with `AskUserQuestion`: **add these
findings as a comment on <target repo>#<n>**, or **file a new issue in
<target repo>**. The answer, or another issue in `<target repo>`
the person chooses instead, sets the target for steps 2 to 5 (§ *The target*).
An answer that chooses no target counts as declined. No likely
match: the target is a new issue. A declined question: write the draft as for
a new issue (steps 2 and 3), post nothing, run step 3's name check when the target is the
upstream target, say where it is and what step 3 removed, and stop.

Never edit another issue's body; it may be a spec.

## 2. Draft

Write the draft to a file in the scratchpad. The title, for a new issue, is
`<area>: <what>` (also written to a second file next to the draft, for step 3's name check), in the style of the titles step 1's search returned, if it
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

When `tracker.public` is true, or the target is the upstream target (whatever
`tracker.public` says), the title and body keep only what is known to be safe
to publish. When unsure, remove it. Do this before the person sees the
draft, and again on the whole draft after every change. Remove:

- any path outside this checkout: absolute (`/Users/`, `/home/`, `/tmp/`,
  `/private/`, `C:\`), home-relative (`~/`), or into another checkout. A path
  inside this checkout is written relative to its root, and is kept. A path
  inside the plugin's folder, wherever it is installed (an installed copy sits
  in a cache folder outside the checkout), is rewritten relative to the
  plugin's root and kept; every other path outside the checkout is removed;
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
  command output, wherever it is, a kept link included. The kinds above are
  the usual ones, not the only ones.

For the upstream target, the draft goes to a tracker that is not this
checkout's, so the exceptions for `tracker.issues_repo` and
`tracker.code_repo` above do not apply, and these are removed too: the name and
owner parts of `tracker.issues_repo` and `tracker.code_repo`,
`tracker.project_owner`, this checkout's folder name, the host of each
`environments` entry's `url`, links into this checkout's tracker, and every
path inside this checkout except a path inside the plugin, kept relative to the
plugin's root (`skills/dev/SKILL.md`, `scripts/verify_merged.py`). Any of these
values equal to `Vorski-Imagineering` or `gogogo` (ignoring case) is left out
of the removal and of the check below.

Then, wherever step 3 ends with an upstream draft on disk (before step 4 shows
it, and on step 1's declined path), check the draft file and the title file for
those values, one `-e` per value. Leave out an empty value, and a value that is
only a word inside a kept plugin path (`dev`, `scripts`, `skills`): it would
match the kept text, so step 3's removal alone covers it.

```bash
grep -n -i -F -e <value> -e <value> <draft file> <title file>
```

Exit 1 (nothing found): go on. Exit 0: remove what it printed, add each item to
the removal list by kind, and run it again; after three runs that still exit 0,
post nothing and say so. Any other exit: post nothing and say the check could
not run. Run it again after every change at step 4.

Keep a list of what you removed, in your own reply and never in the draft
file: each item by its kind and where it was (*a hostname, in the second
finding*), never the removed text. Step 4 shows it with the draft, and every
later mention of what was removed (step 1, step 7) uses the same form. Nothing
removed is put back. A person who wants it published posts it themselves.

## 4. Show and ask

Show the target, the title (for a new issue), the whole body and step 3's
list of removals. Then ask with `AskUserQuestion`: **post it** (naming the
target: *file it as a new issue in <target repo>* or *post it as a
comment on <target repo>#<n>*), **change something**, or **don't post**.

- Change something: edit the draft, or change the target within § *The
  target* (a new issue then needs step 2's title), run step 3 again (the name
  check included), and ask again. When the target repo changed, run step 1's
  search again for the new `<target repo>` first.
- Don't post, or the question is declined: post nothing, say where the draft
  file is, and stop.

## 5. Post

A new issue:

```bash
gh issue create --repo <target repo> --title "<title>" --body-file <file>
```

A comment on #<n>, however the target was chosen. First:

```bash
gh issue view <n> --repo <target repo> --json state,url -q '.state + " " + .url'
```

Post only when it exits 0 and prints `OPEN` and a URL ending `/issues/<n>` in
`<target repo>` (compared ignoring case). Anything else (closed, a pull
request, not found, an error): post nothing, tell the person why, set the
target to a new issue, write step 2's title, run step 3 again, and go back to
step 4. Then:

```bash
gh issue comment <n> --repo <target repo> --body-file <file>
```

No label of any kind. Above all never `tracker.ready_marker`: it means
"specced", and the loop would take the issue. After a comment, skip step 6.

## 6. The card

Skipped for the upstream target, and say so: the issue is in gogogo's tracker,
whose board places it. Otherwise, only when `tracker.kind` is `github-project`
and `tracker.tool` is `shared`.
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

- the issue's or the comment's link, naming `<target repo>`;
- the card's column as read back, or why there is none;
- what step 3 removed;
- for a new issue, next: `/gogogo:spec <n>` when someone is ready to design
  it.

## Claude-specific

- `AskUserQuestion` for steps 1 and 4.
