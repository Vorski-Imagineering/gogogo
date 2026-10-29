---
tags: [dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo dev process here. Issue 11's change is built, reviewed and green, and dev has reached the check right before merging its PR. Its spec's Context has `**Blocked by:** example-org/client-repo#5 (shipped)`, but nobody has linked the two issues yet, so `tracker.py show 11` prints no `blocked by:` line. example-org/client-repo#5 is still open; its card on that repo's board is in `Live`, a column its `related_repos` entry lists under `shipped_columns`. What does dev do before deciding, and does it merge? Answer in two or three sentences, in the process's own terms, and change nothing. End with one line, exactly `Next: merge` or `Next: back to the queue`.
