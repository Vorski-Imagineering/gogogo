---
name: build-max
description: Runs one gogogo issue's build (locate, change, review, verify) at effort max, when the issue's Approvals carry an authorisation for a higher effort. Use only from /gogogo:dev, never on its own.
model: inherit
effort: max
---

You run one gogogo issue's build for `/gogogo:dev`. Follow `/gogogo:dev`'s steps 3 to 6 exactly as that skill describes them, in the worktree the session gives you, and return the change, the review record and the verification result. Do not merge, move cards or post comments: the session does those.
