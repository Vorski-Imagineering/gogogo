# Suspected gogogo faults

A fault in the plugin itself, noticed during a run, is written down where the
run already reports, so a person can file it on gogogo
without the fault being lost. This file says what counts, what the line looks
like, and what a run never does about one. `${CLAUDE_PLUGIN_ROOT}` below is
not filled in for you: it is the plugin's folder, the one whose `scripts/` the
skill names in full.

## It counts

- A script under the plugin's `scripts/` exits with a traceback, or with an
  exit code its own docstring does not list.
- A script's printed result is contradicted by a direct read. For example, it
  says a change is not merged and `git log` on the base shows the merge.
- A skill step, followed as written under a profile that
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py"` accepts, cannot be
  done or gives a wrong result: it names a setting the checker does not know, a
  command that does not exist, or two steps disagree.

## It does not count

- The repo's own code or tests fail.
- The profile's values are wrong (a stale command, a wrong URL). That is a
  profile fix, reported under *Anything they still own*.
- The tracker or board is in an unexpected state.
- Auth, network or rate limits fail.
- A person decided something.

When unsure whether the profile or the skill is at fault, it is a suspected
gogogo fault only when `profile_check.py` accepts the profile and the step
still fails as written.

## The line

One line per fault, exactly in this form:

```text
**Suspected gogogo fault:** <skill> §<step>, or <script> <its arguments> — <what the step says, or the first line the script printed> — <what actually happened, with the command that showed it and its exit code>
```

It is written under the tracker's own publishing rules, like the rest of the
report it sits in.

## Never

Because of one, a run never stops, moves a card, opens or comments on an issue
anywhere, changes the plugin, or posts to `Vorski-Imagineering/gogogo`. A person
files it from the line with `/gogogo:idea`, naming gogogo's tracker as the
target in words; `name_check.py` checks the exact title and body for the repo's
names before anything posts.
