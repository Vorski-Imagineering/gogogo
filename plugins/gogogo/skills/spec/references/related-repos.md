# /gogogo:spec: The part of the work in a related repo

Part of `/gogogo:spec`. Read it in full. Section names and § numbers here are `SKILL.md`'s.

1. **When.** The profile has `related_repos` and the Design needs a change in
   one of its repos. A repo the list does not name is handled as before:
   described in `## Context`, not filed.
2. **Write it as that repo's part.** In `## Design`, a numbered item starting
   with the entry's `half` as a bold label (`**Client's half.**`), saying what
   that repo must do in its own terms, with no `file:line` from this repo.
3. **File it**, once the last question round is answered and before Posting
   begins, one issue per part. Write the body to `<scratch>/half-<N>-<k>.md`:
   the part's text, then
   `Filed by the spec of <tracker.issues_repo>#<N>; this repo owns it from here.`
   Then run
   `gh issue create --repo <repo> --title "<title>" --body-file <scratch>/half-<N>-<k>.md`,
   with no label, project, milestone or assignee. When
   `gh repo view <repo> --json isPrivate -q .isPrivate` does not print `true`,
   re-read the body first as Posting step 2 says for a public tracker. Then
   read it back with `gh issue view <M> --repo <repo> --json number,url`.
4. **Never touch it again.** No edit, comment, label, close or card move on
   that issue, in this run or a later one: that repo's own process owns it.
5. **Cite it.** The part's item ends `Filed as <repo>#<M>.` When this side
   cannot work or merge before it is done, add `<repo>#<M>` to the
   `**Blocked by:**` line in `## Context` (Posting step 7 sets the link);
   otherwise the citation alone.
6. **Already filed.** On a re-spec, a part whose item already cites an issue in
   that repo keeps that citation and files nothing. A part whose text changed
   is not filed again, and the reply says the other repo's issue may be out of
   date.
7. **Filing fails.** On a non-zero exit from `gh issue create` or the read-back,
   write the part without a citation and go on to Posting. The check withholds
   the label for it. Say in the reply which part was not filed, with the error.
8. **The reply** names each issue filed, with its link, and says it stays in
   that repo even when this spec is not posted.
