---
tags: [auto-dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo auto-dev process here, in an unattended run. At the close of the run, the notification script refused the end-of-run event and printed `notify: run_closed: need_you must be int. run_closed takes merged (int), need_you (int), skipped (int)`; we had passed the list of issue numbers [41, 44]. One issue merged, two needed us, none were skipped. What does the process do next, and what if that is refused as well? Answer in two or three sentences, in the process's own terms, change nothing, and end with one line `Next: send it again` or `Next: report it and go on`.
