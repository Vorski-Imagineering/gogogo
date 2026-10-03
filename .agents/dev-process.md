+++
profile = 1

[tracker]
kind = "github-project"
issues_repo = "Vorski-Imagineering/gogogo"
code_repo = "Vorski-Imagineering/gogogo"
public = true
ready_marker = "dev ready"
tool = "shared"
project_owner = "Vorski-Imagineering"
project_number = 5
queue = "Dev Ready"
columns = { in_progress = "In progress", needs_human = "Human!Help!" }

[hard_stops]
source = "CLAUDE.md § Hard Stops: ask before changing"
form = "categories"
items = ["Skill behaviour", "Profile format", "Executable scripts"]

[design]
placement_rule = "CLAUDE.md § What a change here does"

[[lanes]]
name = "unit"
run = "python3 -m unittest discover -s tests"
focused = "python3 -m unittest tests.<module>"
mutate = "python3 tools/mutate.py <base>"
tests = ["tests/*"]
ci = true

[[lanes]]
name = "live"
env = "local"

# The plugin's "production" is its main branch: every adopting repo installs it.
[[environments]]
name = "local"
roles = ["pre-merge"]
serves = "this working tree, loaded with --plugin-dir; other repos on the same machine may load it too"

[[environments]]
name = "main"
roles = ["production"]
url = "https://github.com/Vorski-Imagineering/gogogo"
reached_by = "a merge to main; adopting repos pick it up on their next plugin update"
writes = "through a PR for anything under a Hard Stop"

[[stages]]
code_is = "merged to main"
environment = "main"
column = "Released"
moved_by = "the loop or /gogogo:dev, after the merge is verified"

[verify]
agent = ["local"]
human = "main"
rungs = ["seen-failing", "unit", "live"]

[state]
forbidden = ["editing plugins/gogogo while a run in another repo is using it"]

[gates]
always = ["python3 -m unittest discover -s tests", "the project-name grep in CLAUDE.md"]

[integration]
strategy = "pr-squash"
base = "main"
ci_before_merge = true

[handback]
reporter = "none"
+++

# Process profile: gogogo

## Recon traps

| Trap | How it bites | Check |
|---|---|---|
| **A project detail leaking into a shared skill** | The skill then misbehaves in every other repo | The grep in `CLAUDE.md` § What a change here does |
| **The installed copy is not the tree you edited** | A session loads the cached plugin, not this working tree, and tests the old text | Check the session's `init` plugins path, or start it with `--plugin-dir` |
| **`CLAUDE_CODE_PLUGIN_DIRS` does not override** | It stopped taking effect on 2026-09-30 | Use `--plugin-dir` |
| **`--plugin-dir` given the repo root** | It must name `<clone>/plugins/gogogo`. Given the repo root, a repo that installs the plugin silently loads the installed copy instead, and a trigger test measures the old text | The session's `init` lists the plugin's path under the clone, and the new skill's name |
| **A profile setting nobody reads, or a skill reading a setting nobody defines** | The checker and the skills drift | `references/profile-schema.md` is checked against `profile_check.py` by a test; a skill naming a setting must find it there |
| **Headless runs differ from interactive ones** | The transcript can lack `permissionMode`; skills load differently | Test both when a change touches preflight |
| **Mutation tools edit source files in place** | In the loaded tree that hands a broken script to another repo's run | Mutation runs only through `tools/mutate.py`, which works in a copy |

## Lane constraints

- **unit**: `python3 -m unittest discover -s tests`. Each test names what it
  guards; each new one is seen failing first (break the code, run, restore).
  Its `mutate` command covers the `.py` files directly in
  `plugins/gogogo/scripts`, each against its own `tests/test_<name>.py`, takes
  minutes, and downloads its tool into the user's cache on first use.
  Run `tools/mutate.py` with nothing heavy running alongside: under load the
  tool marks killed mutants "suspicious", and the run counts them as survivors
  (#45's first run showed 4 that way).
- **live**: a real run of the changed skill in an adopting repo, read-only
  unless the spec says otherwise. Triage-only (`/gogogo:auto-dev
  --triage-only`) and dry runs with posting blocked are the default. Say which
  repo and what was checked.
- **auto-dev on this repo**: the plugin it runs is loaded from this checkout
  (the **live** lane). Put each issue in its own git worktree or clone, never
  switch branches in the tree the plugin was loaded from, and do not edit
  `plugins/gogogo/` in that tree while the run is going. On this repo, in place
  of auto-dev §3's `git switch` steps, branch the worktree from a freshly
  fetched base: `git fetch origin && git worktree add -b fix/<n>-<slug> <path>
  origin/main`. Switching branches in the loaded tree, or pulling into it,
  changes the skills under the running loop (`CLAUDE.md` § What a change here
  does). The 2026-10-01 runs used a worktree per issue.
- **confirming a Released card**: `/gogogo:auto-test` is browser-based and is
  not set up here. Confirm instead against a worktree of `origin/main`: scripts
  in read-only or dry-run modes, and skill behaviour as scenario runs
  (`claude -p --tools "" --system-prompt "$(cat <SKILL.md>)" "<situation>"`,
  3 runs each, every answer read). Then comment on the issue, remove the ready
  label, close it, and run `tracker.py tidy --apply`: the board's own
  close→Done workflow is off.
- **docs in step**: a change to a skill's behaviour, a script, or a profile
  setting re-reads `README.md` and `docs/git-process.md`, and corrects in the
  same PR any sentence the change makes false. `tests/test_docs_in_step.py`
  catches a script or setting the docs name that no longer exists; only this
  re-read catches a wrong claim about behaviour.

## superpowers boundary

Design exploration may use `superpowers:brainstorming`. Its output goes into
an issue through `/gogogo:spec`, not into `docs/superpowers/`. Decisions and
plans stay in `docs/` and the issues.
