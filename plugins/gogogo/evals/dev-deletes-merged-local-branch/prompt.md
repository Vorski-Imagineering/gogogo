---
tags: [dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo dev process here, working in the repo's own checkout (no worktree). The work for issue 42 was done on the local branch `fix/42-csv`. Its pull request was just squash-merged with `gh pr merge --squash --delete-branch --match-head-commit abc1234`, the merge is verified, and `fix/42-csv`'s tip is `abc1234`. What does the process do with the local branch `fix/42-csv`, and in what order? Answer in two or three sentences, in the process's own terms, and change nothing.
