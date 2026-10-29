---
tags: [status]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo status process here. The profile's `tracker.issues_repo` is `example-org/backend`, and both cards below are in it. It has one `related_repos` entry: `repo = "example-org/client-repo"`, `board = "example-org#7"`. The board read (`list --json`) has two open issue cards. #11 is in `Human!Help!` with `blocked_by` `[{"number": 5, "repo": "example-org/client-repo", "state": "OPEN", "column": null, "related": {"board": "example-org#7", "column": "Backlog"}, "blocker_state": "open"}]`. #12 is in `In progress` with `blocking` `[{"number": 9, "repo": "example-org/client-repo", "state": "OPEN"}]`. Give the exact lines the report prints about the related repo, and change nothing.
