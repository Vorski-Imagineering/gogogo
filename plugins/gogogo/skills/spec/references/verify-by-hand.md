# /gogogo:spec: `## Verify by hand`

Part of `/gogogo:spec`. Read it in full. Section names and § numbers here are `SKILL.md`'s.

Goes directly under `## Original report`, above everything else including
`## Approvals`. The issue's first reader is usually the person who reported it
or whoever closes it out, not the implementing agent. They open the issue to
answer one question: *how do I check this is actually fixed?* Make that the
first thing they reach after their own words.

Write it for someone who has not read the rest of the spec and never will:

- **Open with what happened before**, in one or two plain sentences, in the
  reporter's terms and not the code's. "The Pages section showed no rows, so
  there was no way to create the first page", not "the queryset filtered on a
  flag".
- **Numbered steps, plain English, no `file:line` and no code.**
- **Name where to do it, and when.** The profile's `verify.human` names the
  environment where a person confirms a fix in this repo. Call it by the
  profile's name for it and give full clickable URLs under that environment's
  `url`. The profile's `stages` say how a change gets there; if that is later
  than the merge, say so in the first line ("Check this on production, after
  the next deploy"), so nobody looks for a fix that has not arrived.
- **Use a real record.** The real id or slug of a record that actually
  reproduces the problem. Find one. A placeholder such as `<slug>` in a URL
  hands the recon back to the reporter.
- **Say which login is needed** in step 1, not halfway down, so a permission
  refusal is not mistaken for the bug. If it needs a second browser or a second
  person, say that in step 1 too.
- **Every step says what you should see.** A step with no observable result is
  not a verification step.
- **Say what "still broken" looks like**, not only what "fixed" looks like.
  The failure is often the thing that looked almost right.
- **Cover what a human can catch that a test cannot**: does it look right, read
  right, feel fast enough. Skip anything the automated lanes already prove.
- **Say plainly which parts of the report this does not cover**, if any.
- **Keep it short.** Five to ten steps. If it needs thirty, the scope is too big
  for one issue.

This is not a duplicate of `## Verification`. That section is the agent's gate:
commands, the prove-it-fails step, exit criteria. This one is a person with a
browser. An agent confirming its own fix is not the reporter confirming their
problem is gone, so a browser test lane never substitutes for this block.
