---
tags: [dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo dev process here. Issue 42's review ended clean at round 3, whose range ended at commit a1b2c3d. Then the test comparison found an assertion the change had loosened; the run put it back and fixed the code so it passes, committed as e4f5a6b. The full suite and the comparison now pass. What does the process do before recording the verified commit and merging? Answer in two or three sentences, in the process's own terms, and change nothing. End with one line, exactly `Next: merge` or `Next: review`.
