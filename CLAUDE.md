# gogogo

The shared agent skills (repo `Vorski-Imagineering/gogogo`), shipped as the
`gogogo` Claude Code plugin (`plugins/gogogo/`) from the `vorski-skills`
marketplace (`.claude-plugin/marketplace.json`). How it came about is in `docs/history.md`.

## What a change here does

`main` is what every adopting repo installs. A merge reaches every adopting repo on its next plugin update, and any repo on a machine that loads this working tree with `--plugin-dir` at once. So:

- **Skills hold only what is the same in every repo.** Anything that names a
  project, host, repo or command belongs in that repo's
  `.agents/dev-process.md`. `grep -rniE 'manage\.py|npm |firebase|django|htmx|sentry' plugins/gogogo/skills plugins/gogogo/scripts` must print nothing. CI runs the same check on every PR.
- **Don't edit `plugins/gogogo/` while a run is using it** (an unattended
  `/gogogo:auto-dev` in an adopting repo may be reading this tree).

## Hard Stops: ask before changing

No approval = do not proceed.

- **Skill behaviour**: a change that makes a shared skill do something
  different in an adopting repo (a new stop, a removed check, a different
  merge or card move). Wording that changes no behaviour is not a Hard Stop.
- **Profile format**: adding, renaming or removing a setting or a required
  section, or changing what a setting means. Every adopting profile has to
  follow it.
- **Executable scripts**: any change to `plugins/gogogo/scripts/` that changes
  what a script does to a repo, a board or the tracker (reading is fine;
  writing, merging and moving are not).

## Tests

```bash
python3 -m unittest discover -s tests
```

A new test is not finished until it has been seen failing: break the thing it
names, run it, confirm red, restore.

Tests of a skill pin its structure, not its sentences: the settings it names,
its templates, the project-name grep, that its profile check runs. Whether it
behaves is a trigger run, not a phrase match. A test
that looks for a sentence breaks on every rewording and guards nothing.

## Commits

Small commits, pushed to `main` for docs and evidence. Anything under a Hard
Stop goes through a PR.

The owner may approve a small change under a Hard Stop in the session and ask
for it on `main` directly. Then say first that it is a Hard Stop and offer the
issue route. On their go-ahead: check that no unattended run is loading this
tree, run the suite and commit only when it passes, push to `main`, and say in
the commit message that it was approved in session.

## Docs

A file under `docs/` is documentation. Open with what the thing does and how to
use it; put the reasons after, and the sources last, each as a link. Name modes
and settings by what they do for the user. Do not link the issues that build
it; a one-line status is fine.
