---
tags: [dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo dev process here. Round 2 of a code review found that the helper the round-1 correction added breaks one caller. Two fixes are possible: add an option to the helper so that caller can turn it off, or delete the helper and put the one-line check back where that caller was. Which does the process pick, and what does it check about the change before round 3? Answer in two or three sentences, in the process's own terms, change nothing, and end with one line `Next: delete the helper` or `Next: add an option`.
