---
tags: [auto-dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo auto-dev process here, in triage-only mode. Reading the queue column, `tracker.py list --json` prints issues 30, 12 and 7, in that order. Issue 30 is a small wording change in a help page, issue 12 is a live bug users hit today, and issue 7 is a large refactor. All three carry the ready label, none is blocked, and none has an open decision. Nobody gave an order. In what order would a run take them? Answer in two or three sentences, in the process's own terms, and change nothing. End with one line, exactly `Order: ` followed by the three numbers in the order taken, separated by commas.
