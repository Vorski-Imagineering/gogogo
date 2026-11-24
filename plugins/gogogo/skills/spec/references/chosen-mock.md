# /gogogo:spec: a design chosen from mock-ups

Part of `/gogogo:spec`. Read it in full. Section names and § numbers here are `SKILL.md`'s.

A person who picked a mock expects the page in it. A difference the spec
decides quietly is found only when the page is built, and then the issue is
specced again.

1. **When.** The person chose a design from mock-ups on record: an Approvals
   row whose Chosen names a mock, or the person's own words picking one, in
   the report, a comment or this session. A mock is a picture of the screen:
   an image, a canvas or design file, or frames a session drew. A mock that is
   only linked, with nobody picking it, is not chosen. When the person picked
   parts of several mocks, the chosen design is those parts together.
2. **List every difference.** Once the Design is drafted, compare it with the
   chosen mock screen by screen. Each part placed elsewhere, left out, added,
   or drawn differently (a control, a label, an order, a navigation) is a
   difference, however small, including one forced by the code. Whether it
   matters is the person's call.
3. **None.** Write "Builds the chosen mock as drawn: no visible difference."
   in `## Context`. No round is asked.
4. **The round.** Draw one "as built" frame for each screen that differs,
   beside the chosen mock's frame, with each difference marked and numbered.
   Ask one question, opening with the real case and the three lines of
   `references/decision-questions.md` in this plugin, with two choices:
   **build as drawn here**, or **build these as the mock** (the person names
   which). It is asked at every level, after the level's one round and not
   counted in it.
5. **The record.** One Approvals row: the question cell lists each difference
   by number (`1. <difference>; 2. …`); Chosen says which are built as drawn
   and which as the mock; Rejected names the other. Every difference sent
   back to the mock is built as the mock in the Design. When building it as
   the mock raises a fork (a Hard Stop, a new product choice), that fork is
   asked under `SKILL.md`'s rules. A decline follows *When the user declines a
   question*.
6. **Never decided.** No difference from the chosen mock goes under
   *Decided without asking*, at any level.
7. **No picture.** When the session cannot draw, the question lists one plain
   line per difference and opens "No picture could be drawn: <why>." When the
   mock itself cannot be opened, the differences are listed against what the
   person said they picked, and the question says so.
8. **Verify by hand** has a step for each screen that differs or that the
   mock shows: open the chosen mock (or the approved "as built" frames) beside
   the built page, name the parts to find in their place, and say that a part
   missing or moved is "still broken".
9. **A public tracker.** A link to the mock or the frames goes in the issue
   only when Posting step 2 keeps it. Otherwise the row says "frames shown in
   the session; link not published".
