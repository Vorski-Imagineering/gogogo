---
tags: [dev]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

We use the gogogo dev process here. Issue 42's spec lists `shared/ranking.py` under Create. Our lint forbids anything in `shared/` from importing product code, which the module needs, so the change put it at `app/ranking.py` instead. Now the spec check is being answered, and its item list shows `F:shared/ranking.py` with nothing at that path and `outside: app/ranking.py`. What line, if any, goes into the answers file for that planned file? Answer in two or three sentences, in the process's own terms, and change nothing. End with one line, exactly `Line: none` or `Line: <the answers-file line>`.
