---
tags: [spec]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo spec process here. An issue's Design deletes the eval case `plugins/gogogo/evals/old-case/` entirely: its prompt and its three graders, all tests in this repo. How does the spec let the build delete them without stopping? Answer in two or three sentences, in the process's own terms, change nothing, and end with the exact line the spec writes in its Test cases.
