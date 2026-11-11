---
tags: [dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo dev process here. Issue 42 changes `static/css/drawer.css` so a phone's side menu closes. Its browser case reads the closed menu's box and asserts it ends at or left of x=0, and that value check passed. The case's screenshot, in the run's folder, shows the closed menu's icons still drawn over the left edge of the page. What does the process do now, before calling the issue verified? Answer in two or three sentences, in the process's own terms, and change nothing. End with two lines: first exactly `Next: done` or `Next: fix`, then `Check: none` or `Check: <the value check the process adds, if any>`.
