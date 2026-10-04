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

**The one exception: gogogo's own tracker.** A suspected fault in a gogogo
skill or script (`references/gogogo-faults.md`) may go to
`Vorski-Imagineering/gogogo`, as a new issue or a comment on an open issue
there, and only when all of these hold: the person names gogogo's tracker in
words; a person is present (never in an unattended run); and step 3a's name
check has passed on the exact title and body posted. This skill never offers
it on its own. In the gogogo repo itself, `tracker.issues_repo` already is that
tracker: it is the first target, and step 3a is not run.

## 1. Look for an issue that already covers it

```bash
gh issue list --repo <tracker.issues_repo> --state open --search "<two to four key terms>" --json number,title,url --limit 10
```

When one is a likely match, show it and ask with `AskUserQuestion`: **add these
findings as a comment on <tracker.issues_repo>#<n>**, or **file a new issue in
<tracker.issues_repo>**. The answer, or another issue in `tracker.issues_repo`
the person chooses instead, sets the target for steps 2 to 5 (§ *The target*).
An answer that chooses no target counts as declined. No likely
match: the target is a new issue. A declined question: write the draft as for
a new issue (steps 2 and 3), post nothing, say where it is and what step 3
removed, and stop.

Never edit another issue's body; it may be a spec.

For gogogo's tracker, the search runs on `Vorski-Imagineering/gogogo`
(`--repo Vorski-Imagineering/gogogo`), and its answer sets the target the
same way, within that repo.

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

When `tracker.public` is true, or the target is gogogo's tracker (§ *The
target*), the title and body keep only what is known to be safe to publish. When unsure, remove it. Do this before the person sees the
draft, and again on the whole draft after every change. Remove:

- any path outside this checkout: absolute (`/Users/`, `/home/`, `/tmp/`,
  `/private/`, `C:\`), home-relative (`~/`), or into another checkout. A path
  inside this checkout is written relative to its root, and is kept;
- every repo, project, client, product or folder name from outside this
  checkout, in any form (`owner/repo`, a bare name, a folder), except
  `tracker.issues_repo`, `tracker.code_repo`, and tools and products anyone
  would know as public (for gogogo's tracker: `Vorski-Imagineering/gogogo` and
  nothing else of this repo's);
- hostnames and IP addresses, except inside a link the next rule keeps;
- links, except into `tracker.issues_repo` or `tracker.code_repo` (for gogogo's
  tracker: into `Vorski-Imagineering/gogogo`), or to a public product's
  documentation. A share, preview, signed or secret link (a
  shared document, a gist, a preview deploy, a URL with a token) is removed
  wherever it points. The rule on names above applies inside a kept link too;
- anything that looks like a token or key, and email addresses;
- people's names (use their role);
- anything else not known to be safe, such as customer or business data in
  command output, wherever it is, a kept link included. The kinds above are
  the usual ones, not the only ones.

Keep a list of what you removed, in your own reply and never in the draft
file: each item by its kind and where it was (*a hostname, in the second
finding*), never the removed text. Step 4 shows it with the draft, and every
later mention of what was removed (step 1, step 7) uses the same form. Nothing
removed is put back. A person who wants it published posts it themselves.

## 3a. The name check, for gogogo's tracker only

Skip this step for every other target. The text is going to a public tracker
that is not this repo's, so the names of this repo must not be in it, and a
person reading it twice is not a check. A script does it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/name_check.py" --title "<scratch>/idea-title.txt" "<draft>"
```

Write the title to `<scratch>/idea-title.txt`, the title and nothing else, one
line (for a comment, write a one-line summary so the script can read the file;
it is not posted), and write it again whenever the target or the title changes. The draft
is the file step 2 wrote. By the exit:

- **0**: it printed `name-check: clean (…)`. Go on to step 4.
- **1**: it printed each hit as `<file>:<line>: <matched text>`. Show them,
  remove each from the draft or the title file, and run it again.
- **2**: stop, post nothing, and give the reason it printed. The profile or the
  files are wrong; never post around it.

Run it at most three times: after the third run that does not exit 0, stop,
post nothing, and say where the draft is. Every later change to the title or
the draft (step 4's *change something*) runs it again and counts. The check
cannot see a name nobody listed (a product name, a host quoted in output,
another repo this session touched): `publish.private_names` in the profile
lists the ones to add.

## 4. Show and ask

Show the target, the title (for a new issue), the whole body and step 3's
list of removals. Then ask with `AskUserQuestion`: **post it** (naming the
target: *file it as a new issue in <tracker.issues_repo>* or *post it as a
comment on <tracker.issues_repo>#<n>*), **change something**, or **don't post**.
For gogogo's tracker the target is named as *file it as a new issue in
Vorski-Imagineering/gogogo* or *post it as a comment on
Vorski-Imagineering/gogogo#<n>*, and you also show step 3a's last `name-check: clean` line, and say
that the check cannot see every private name: read the title and body once more
yourself before choosing.

- Change something: edit the draft, or change the target within § *The
  target* (a new issue then needs step 2's title), run step 3 again (for
  gogogo's tracker, then step 3a again, which counts toward its three runs),
  and ask again.
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
target to a new issue, write step 2's title, run step 3 again (for gogogo's
tracker, then step 3a on the new title file and the draft), and go back to
step 4. Then:

```bash
gh issue comment <n> --repo <tracker.issues_repo> --body-file <file>
```

For gogogo's tracker, post only right after an exit-0 run of step 3a on the
files posted, and post exactly those files, with nothing edited since:

```bash
gh issue create --repo Vorski-Imagineering/gogogo --title "$(cat "<scratch>/idea-title.txt")" --body-file "<draft>"
gh issue comment <n> --repo Vorski-Imagineering/gogogo --body-file "<draft>"
```

The comment needs the open-issue check above first, with `Vorski-Imagineering/gogogo`
in place of `tracker.issues_repo`. No label there either.

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
step was skipped, and why. For gogogo's tracker the step is skipped: it is not
this repo's board.

## 7. Report

- the issue's or the comment's link;
- the card's column as read back, or why there is none;
- what step 3 removed;
- for a new issue, next: `/gogogo:spec <n>` when someone is ready to design
  it.

## Claude-specific

- `AskUserQuestion` for steps 1 and 4.
