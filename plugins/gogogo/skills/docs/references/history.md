# /gogogo:docs history: the evidence rules

Part of `/gogogo:docs`. Read it in full before writing any of a history
section. A history is read as fact. These rules decide what may go in; how it
reads (voice, style, who tells it) is the repo's own and is not set here.

A sentence that cannot meet its rule is cut, not softened. A shorter true
section is the right result; a gap in the record is never filled with a guess.

## 1. Every date is linked

Each date comes from git or the tracker and links the commit, issue or pull
request it was read from. A change's date is the day it reached the base
(`git log --first-parent --format='%H %cs' origin/<base>`), not its author
date: a squash merge keeps the author's date. A date that cannot be linked is
left out.

## 2. Every quote is exact

A quote is copied character for character from an issue, pull request or
comment, and links it. Never paraphrase inside quotation marks. To shorten
one, quote less of it; mark a cut inside it with `…`. Words with no record to
link (a conversation, a call) are not quoted.

## 3. Every number was counted in this run

A count, duration or total was counted in this run, and the command that
counted it is given in a footnote under the section, for example
`[^1]: git log --first-parent --oneline <start>..<end> | wc -l`. A number that
was not counted is left out, never estimated: no "about", "roughly" or "a
dozen".

## 4. Mistakes stay in

Each of these in the period is told, with its link:

- a pull request closed without merging;
- a revert;
- an issue closed as not planned;
- a card handed back to a person (a stop marker in an issue comment).

Each is owned by its role ("the agent", "the owner", "a reviewer"), never left
out or turned into a success because it reflects badly.

## And: no invented connecting facts

Between two records, say what happened, not why, unless the record says why
(a commit message, an issue body, a comment), and then link it. "Because", "so
that" and "after realising" each need their link.

## On a public tracker

When `tracker.public` is true, people are named by role, never by name or
handle, and the section is re-read as `/gogogo:spec`'s Posting step 2 does
before the commit.
