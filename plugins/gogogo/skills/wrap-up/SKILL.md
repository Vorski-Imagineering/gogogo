---
name: wrap-up
description: Use when the user is about to close a session, or asks "are we ok to close", "anything outstanding", "should we store any learnings", or invokes /wrap-up. Finds work left hanging, captures what this session learned in the right place, and gives one verdict on whether it is safe to close.
---

# wrap-up: is it safe to close this session?

The user closes sessions. Anything this session leaves hanging, or learned and
did not write down, is lost when they do. This skill makes the pre-close check
the same every time, instead of depending on the user remembering to ask.

Three parts, in order: **find what's hanging → capture learnings → verdict.**
Do the checks; don't answer from memory of the conversation. "I don't think I
left anything" is the failure this skill exists to replace.

## First: which repos, and what they add

List every repo this session changed, not only the one it started in. For each
one that has a profile, read it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --show
```

From the profile you need `tracker.issues_repo`, `tracker.ready_marker`,
`tracker.tool` and `stages`, and the section `## Wrap-up checks` if there is
one: the repo's own checks, run alongside the ones below, and anything it says
blocks closing. A repo with no profile (exit 2) gets the checks below and nothing else;
say so in the report.

Any `warning:` line the check printed goes, verbatim, at the top of your report to the person; if it printed none, the report says so.

## 1. Find what's hanging

Run every check. Report each one, even when it is clean; a silent check
can't be told apart from one you skipped.

**Separate this session's work from what was already there.** The session
opened with a `gitStatus` snapshot. Compare against it. Pre-existing changes
are named as such and left alone; never commit, stash or discard them as
part of wrapping up.

| Check | How |
|---|---|
| Working trees | In each repo: `git status --short` and `git log @{u}.. --oneline 2>/dev/null` (unpushed commits). Checkouts live in different places on different machines, so never hard-code a path. Name the branch: work left on a feature branch is fine if the user knows it's there. |
| Stashes, and other sessions | `git stash list` in each repo. Another session, or a merge script that switches branches, can move a file you wrote onto another branch mid-session. Confirm this session's files are where you left them (`ls` them) and name the branch they are on now. |
| Worktrees | `git worktree list`, and `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/worktree_sweep.py"` without `--apply` (it leaves out the worktree this session is in, which `git worktree list` still shows). Name each `remove` line and offer to remove it, asking first (`worktree_sweep.py --apply --only <path>`, from the main worktree). A `keep` line for a worktree this session created needs an owner or removal. Check the repo's `CLAUDE.md`: many forbid worktrees unless asked. |
| Stranded work | `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stranded_work.py"` in each repo with a profile. It lists local and `origin` branches, and worktrees, ahead of `origin`'s base that nothing accounts for: no issue number, an issue that is not open, or an open issue with no open pull request and no stop marker naming the branch. It says when a branch shares no history with the base and what became of its pull request. One this session created blocks; older ones are named. |
| Background work | Background shell tasks, `Monitor`s, subagents, workflows and scheduled wakeups this session started. `ListAgents` for agents. Say which are still running and whether it matters: a read-only search dying is harmless; a half-finished write is not. |
| Tracker | Every issue created or edited this session: the substance is in the body, not only in a comment; a specced issue carries `tracker.ready_marker`, or its absence is explained (`/gogogo:spec` § Posting); comments that now contradict a later edit are fixed, not left as two stories; the card sits in the column of the stage its code has actually reached (`<tracker.tool> show <n>`). |
| Promises | Scan your own replies for "I'll", "next", "later", "follow-up", "want me to". Each one is done, handed to an issue, or listed as open. Offers the user didn't take up are not open items; list them only if the user might have missed the question. |
| Files outside the repos | Anything written elsewhere (the scratchpad, `~/Documents`, exported files) that the user still needs the path to. |
| Artifacts and docs | Anything published or pinned this session that the user still needs the link to. |
| The repo's own checks | Each row of the profile's `## Wrap-up checks`. |

## 2. Capture learnings

Go through the session looking for three kinds of thing:
- **corrections** the user gave (including quiet ones: an answer that rejected your framing);
- **approaches they confirmed**;
- **facts** about the project or its people that aren't in the code or git history.

Put each one in exactly one place:

| It is… | Goes to | Rule |
|---|---|---|
| How the user wants *me* to work, or a project fact that isn't in the repo | **Memory**: the memory directory named in the system prompt (its path differs per machine), one file per fact, plus a line in `MEMORY.md` | Check the index for an existing file first and update it rather than duplicating. Wrong or outdated memories get fixed or deleted now. Follow the memory format in the system prompt. |
| A rule everyone working in the repo should follow, a process detail, a doc that was wrong | **The repo**: `CLAUDE.md`, `.agents/dev-process.md`, its docs, or wherever the profile's `## Wrap-up checks` says | **Propose, don't write.** These are shared; show the exact text and where it goes, and let the user say yes. If it is bigger than a few lines, it becomes an issue via `/gogogo:spec`. |
| A gogogo skill that misled you, a `Suspected gogogo fault` line written this session, or a rule that should hold in every repo | **An issue in `Vorski-Imagineering/gogogo`**, filed with `/gogogo:idea` and its upstream target | Propose it: idea shows the scrubbed draft and posts only on yes. A skill change there reaches every repo. |
| A problem with Claude Code itself | **`SendFeedback`** (drafts only; the user approves sending) | Only for a real product or model-behaviour issue seen this session. |
| Only mattered to this session | **Nowhere** | Say so. Not everything is a learning. |

Don't save to memory what the repo already records (code structure, past
fixes, git history, CLAUDE.md), and don't write a memory that restates a rule
already in `CLAUDE.md`.

Save memories without asking; that's what memory is for. Name each one in the
report so the user can object.

## 3. Verdict: resist by default

The user asked for this skill to **push back hard** when things aren't clean.
Closing a session with work hanging is the expensive mistake; one extra
exchange is cheap. So the default answer is **Not yet**, and **Safe to close**
has to be earned by every check in §1 coming back clean.

**Blocks closing** (the verdict is *Not yet*):
- anything this session changed that isn't committed, or is committed but not pushed;
- a branch or worktree this session created that no open issue claims;
- a background task, agent or workflow still running that writes anything (files, a database, GitHub, an outside service);
- an issue this session touched whose body, label, comments and card disagree;
- a promise from §1 that's neither done nor handed to an issue;
- a learning found in §2 and not yet saved (memory), or not yet put to the user (repo);
- anything the profile's `## Wrap-up checks` says blocks.

**Doesn't block, but is named every time:** pre-existing uncommitted changes
and stranded branches from before the session, with their names. Name them in
one line, not as a reason to refuse. They stay the user's call, and the next
wrap-up will name them again until they're resolved, so they can't quietly go
stale.

Write the verdict as:

- **Not yet.** Lead with it, as the first line, in bold. Then a numbered list:
  what is open, what is lost if the session closes now, and the one action
  that closes it. Do the ones you can when the user says so, then **run the
  checks again**; don't carry the old results forward.
- **Safe to close.** Only when nothing blocks. One line per check proving it,
  plus the pre-existing line if there is one.

**If the user wants to close anyway:** don't soften the verdict and don't
suddenly find the problems minor. Say once, plainly, exactly what will be lost
or left dangling, and ask them to confirm that specific list. Their explicit
"yes, close anyway" is the override; your own reassurance never is. Then stop
arguing: it's their session.

Keep the report short: a line per check, the learnings with where each went,
the verdict. Don't bury the answer under a session recap.

## Red flags

| Thought | Reality |
|---|---|
| "I remember what I changed" | Run `git status`. The conversation doesn't show edits made by subagents or hooks. |
| "I only worked in this repo" | Check. Sessions drift into sibling repos; list every repo a command wrote to. |
| "Those uncommitted files aren't mine, so skip them" | Report them as pre-existing, in one line. The user decides; silence looks like a clean tree. |
| "Nothing worth saving" without having looked | Scan for corrections first. A session where the user redirected you and nothing was saved is the usual miss. |
| Writing to `CLAUDE.md`, the profile or a skill during wrap-up | Propose it. Shared files get a yes first. |
| Committing, stashing or pushing to make the tree look clean | Never, as part of wrap-up. Report it and offer; the user decides. |
| "The background task will probably finish" | Say what it is and what happens if the session dies mid-way. |
| "It's basically clean, just one small thing" | One small thing is *Not yet*. Say it that way. |
| The user sounds keen to go, so lead with the good news | Lead with the verdict. Wanting to close is the moment the check matters most. |
| "Safe to close" with a check you didn't run | That's a guess. Run it or report it as unchecked, and unchecked blocks. |
