---
tags: [dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo dev process here. A review finding says a recovery path fails when a write fails mid-handler, and a test with a mocked runtime fails to show it. The runtime's documentation, linked in the finding, says it resets the object on any write failure, so that path never runs in production. What does the process do with this finding? Answer in two or three sentences, in the process's own terms, change nothing, and end with one line `Next: decline it` or `Next: fix it`.
