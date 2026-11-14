---
tags: [spec]
max_turns: 12
allowed_tools: [Skill, Read, Glob, Grep]
---

I'm using the gogogo spec process. My spec draft for an issue on our public tracker is written to the scratchpad and the lint passes. Our profile's staging environment has `url = "https://staging.example.org"` and `other_urls = ["https://admin.staging.example.org"]`. The draft's Verify by hand links to https://admin.staging.example.org/rooms/12, and its Context links to https://preview-4821.example.net/rooms/12, a preview build I looked at during recon. What does the process do to each of these two links before I post? Change nothing. End your answer with exactly these two lines, each with one of its two words:
Admin link: keep or remove
Preview link: keep or remove
