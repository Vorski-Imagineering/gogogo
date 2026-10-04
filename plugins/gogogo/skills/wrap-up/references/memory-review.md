# /gogogo:wrap-up: memories saved before this session

Part of `/gogogo:wrap-up`. Read it in full when §2 reaches the memories. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- 1. Expiry
- 2. Promotion
- 3. Proposals
- 4. Marker
- 5. Report

Memories saved by earlier sessions are read again at every wrap-up, so a note
that has done its job goes and a rule that has outgrown one person's memory is
offered to the repo. Use the memory directory the system prompt names, never a
path of your own. Read it fresh, and when you delete a memory edit only its one
line in `MEMORY.md`: another session may be editing the index, so never rewrite
it from a copy you read earlier.

## 1. Expiry

The memory directory also holds `MEMORY.md` (the index) and the
`.gogogo-memory-review` marker. Neither is a memory: skip both in this scan, so
an index hook line such as "once #<n> ships" never makes the index a deletion
candidate. An index line is edited only as the deletion of the memory it points
at.

For each memory file whose text holds `until #<n>`, `until #<n> ships` or
`once #<n> ships` (any capitalisation), read that issue: `<tracker.tool> show <n>`
when the profile has `tracker.tool`, else
`gh issue view <n> --repo <tracker.issues_repo> --json state,stateReason`.

- Shipped (its card is in a `stages` column or `Done`, or it is closed as completed): delete the file and its `MEMORY.md` line. When the file holds more than that one note, remove only the note.
- Still open: keep it.
- Closed as not planned: keep it and name it in the report ("its issue was dropped; the note may now be the only record").
- The read failed (offline, no auth, not found, no tracker tool), or the memory names an issue in another repo: keep it and name it in the report ("could not tell whether #<n> shipped"). Never delete on a failed read.

Delete only when the memory says it holds **until** the issue ships. A memory
that cites an issue as an example or as evidence is never deleted because that
issue is closed; only §2 can shorten or delete it.

## 2. Promotion

Check each memory file newer than `.gogogo-memory-review` in the memory
directory (every file when the marker is missing). `MEMORY.md` and the marker
itself are not memories: exclude both, since the index is always newer than the
marker. Skip the rest: only what changed is read. Put each one in exactly one outcome:

- `covered`: a skill, the profile or `CLAUDE.md` already states it. Delete or shorten the memory.
- `every-repo`: a rule that holds in every repo (nothing in it names a project, host, repo or command). Propose an issue for `Vorski-Imagineering/gogogo`.
- `this-repo`: a rule for the repo wrap-up runs in. Propose a `CLAUDE.md` or profile line. In an adopting repo a rule that names that repo is never a gogogo issue.
- `stays`: it is a memory and nothing else.

## 3. Proposals

Show each `every-repo` or `this-repo` item with its exact text. An
`every-repo` item is always shown with every project name, host, path and
person removed, because its target, the gogogo tracker, is public. A
`this-repo` item, whether it is a line for a file or an issue in this repo's
tracker, has every project name, host, path and person removed whenever
`tracker.public` is true, because a tracked file of a public repo is public too.
It is shown as it is only when `tracker.public` is false. A yes files an `every-repo` item
through `/gogogo:idea`, or writes the `this-repo` line. A no is done. Nothing is
filed or written without a yes.

## 4. Marker

After the answers to step 3, `touch` the file `.gogogo-memory-review` in the
memory directory, only when every proposal got a yes or a no and every expiry
read succeeded. If the session ends with a proposal unanswered, or a read
failed, do not touch it, so the next wrap-up looks again.

## 5. Report

Under **Memories**, one line per memory deleted or shortened with its reason
(name each one so the user can object), one per proposal with its outcome, and
"nothing new since <marker date>" when step 2 found no files. The memory review
never changes the verdict.
