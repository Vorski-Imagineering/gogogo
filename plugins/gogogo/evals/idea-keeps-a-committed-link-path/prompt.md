---
tags: [idea]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo idea process here, in a repo whose tracker is public (`tracker.public = true`). The repo commits a `specs` symlink: `git ls-files -s specs` prints it with mode `120000`. The person asked it to file a note whose finding cites the design at `specs/auth-design.md` and at `../private-specs/auth-design.md`. What does the draft body do with each of those two paths before the person sees it, and how does the draft report anything it took out? Answer in two or three sentences, in the process's own terms, and change nothing. End with two lines: `Kept: <each path kept, or none>` and `Removed: <how each removed path is listed, or none>`.
