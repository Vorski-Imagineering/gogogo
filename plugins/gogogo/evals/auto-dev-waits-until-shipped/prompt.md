---
tags: [auto-dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo auto-dev process here, in triage-only mode. Issue 11 is in the queue with the ready label and no open decision. Its body's Context has the line `**Blocked by:** example-org/client-repo#5 (shipped)`. Its only `blocked_by` entry in the board read is `{"number": 5, "repo": "example-org/client-repo", "state": "OPEN", "column": null, "related": {"board": "example-org#7", "column": "In Dev"}, "blocker_state": "merged", "shipped": false}`. What does triage say about issue 11? Answer in two or three sentences, in the process's own terms, change nothing, and end with the exact line the run's triage prints for it.
