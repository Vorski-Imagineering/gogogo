---
tags: [auto-dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use gogogo's auto-dev with one worktree per issue. Issue 12 was stopped and requeued. Its earlier work is one branch on GitHub, and the run's worktree for issue 12 is still on disk, on that branch, with nothing uncommitted, at the same commit as the branch on GitHub. What does the run do with issue 12 at the branch step? Answer in two or three sentences, in the process's own terms, change nothing, and end with one line `Issue 12: continued in its worktree` or `Issue 12: skipped, could not branch`.
