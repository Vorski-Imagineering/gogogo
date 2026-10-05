# /gogogo:auto-dev: 1. Order, and rows blocked by another issue

Part of `/gogogo:auto-dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

GitHub's issue dependencies ("blocked by", "blocking") say which issue waits
for which. They show on both issues and on the board, and `tracker.py` reads
them in the same board read §1 already makes.

1. **What each row carries.** Every row of §1's `list --json` has a
   `blocked_by` list and a `blocking` list. Each `blocked_by` entry has the
   blocker's `number`, `repo`, `state`, its `column` on this board (null when
   it has no card here) and its `blocker_state`:
   - `open`: it still blocks;
   - `merged`: it is closed as completed, or its card is in one of the
     profile's `stages` columns;
   - `dropped`: it closed as not planned or as a duplicate.
2. **Any `open` blocker: pass the row over.** List it as
   `skip (blocked by <ref> (<column, or "not on this board">))`, one ref per
   open blocker, where a ref is `#B`, or `owner/repo#B` for another repo.
   Post no comment, move no card, write no marker and send no
   `issue_skipped`: the link on the card already says why, and writing it on
   every run would be noise. Show it in triage-only, and in §9's report under
   *blocked*. Keep the ready label.
3. **A `dropped` blocker and no `open` one: a skip** with reason `decision`,
   handed back by §2's *Hand back a skip*. Its Needs-you line names the
   blocker and how it closed (not planned, or a duplicate): whether the
   blocked work still stands is a person's question, and one they can answer
   now.
4. **Every blocker `merged`**, or none: the row is taken as any other.
5. **Order**, when the user gave none:
   - first, rows whose `blocking` list names an open issue, the row blocking
     the most open issues first;
   - then live user-facing bugs, refactors after, anything large last so it
     cannot absorb the run.
6. **Read again each time.** A row passed over as blocked is checked again
   every time §1's list is read in this run, and taken as soon as its
   blockers are out of the way: a blocker merged earlier in the same run
   unblocks it. "Not taken again in the same run" (§4) is about real skips,
   not these.
