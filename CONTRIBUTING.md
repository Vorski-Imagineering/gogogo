# Contributing

Pull requests are welcome.

Before you open one:

- Run `python3 -m unittest discover -s tests`. A new test must have been seen
  failing: break the thing it names, run it, confirm red, restore.
- Skills hold only what is the same in every repo. Anything that names a
  project, host, repo or command belongs in that repo's profile
  (`.agents/dev-process.md`), not in a skill. CI runs the stack-word check from
  [`CLAUDE.md`](CLAUDE.md) on every PR.
- Tests of a skill pin its structure (the settings it names, its templates),
  not its sentences.

A PR that changes a skill's behaviour, the profile format, or what a script
writes to a repo or board is reviewed against the Hard Stops in
[`CLAUDE.md`](CLAUDE.md). Its description says what changes for a repo that
already uses gogogo. Small wording fixes need nothing more than the PR.

Security problems go through [`SECURITY.md`](SECURITY.md), not an issue.
