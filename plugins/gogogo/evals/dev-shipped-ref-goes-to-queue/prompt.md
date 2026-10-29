---
tags: [dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo dev process here. Issue 11's change is built, reviewed and green, and dev has reached the check right before merging its PR. Its spec's Context has `**Blocked by:** example-org/client-repo#5 (shipped)`, and `tracker.py show 11` prints `blocked by: example-org/client-repo#5 (merged, In Dev on example-org#7, not shipped)`. The queue column is `Dev Ready`. Does the process merge it, and where does the card go? Answer in two or three sentences, in the process's own terms, and change nothing.
