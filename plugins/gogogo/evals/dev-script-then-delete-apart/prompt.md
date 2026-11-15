---
tags: [dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo dev process here. I'm working a gogogo dev issue in this repo. The folder `drafts/` holds `.txt` notes git doesn't track. I need `tools/convert.py <file>` run on each to write a `.md` beside it, and the `.txt` files removed. How does the process have me do it? Give the exact shell commands its rules call for in one fenced block, in the order to run them, and change nothing. Then end with exactly these three lines, each with one of its two choices:
`Removal: same command` or `Removal: separate command`
`Checked before removal: exit status` or `Checked before removal: output`
`Copy aside: yes` or `Copy aside: no`
