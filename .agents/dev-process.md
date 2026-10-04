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
name = "evals"
run = "python3 tools/eval_changed.py"
tests = ["plugins/gogogo/evals/*"]
ci = false

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
rungs = ["seen-failing", "unit", "evals", "live"]

[state]
forbidden = ["editing plugins/gogogo while a run in another repo is using it"]

[gates]
always = ["python3 -m unittest discover -s tests", "the project-name grep in CLAUDE.md"]

[integration]
strategy = "pr-squash"
base = "main"
ci_before_merge = true
workspace = "worktree"

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
| **A new eval case not in the suite's list** | `tests/test_eval_suite.py` lists every case in `CASES` exactly, so a spec that adds a case and does not list that file under Edit has its build read the edit as outside the spec | A spec that adds an eval case adds its name to `CASES` and lists `tests/test_eval_suite.py` under Edit |

## Lane constraints

- **unit**: `python3 -m unittest discover -s tests`. Each test names what it
  guards; each new one is seen failing first (break the code, run, restore).
  Its `mutate` command covers the `.py` files directly in
  `plugins/gogogo/scripts`, each against its own `tests/test_<name>.py`, takes
  minutes, and downloads its tool into the user's cache on first use.
  Under load the tool marks slow kills "suspicious"; `tools/mutate.py` counts
  them as killed (#75), so a busy machine changes how long the run takes, not
  its counts.
- **evals**: `python3 tools/eval_changed.py` runs the eval cases of each skill the
  change touched (`plugins/gogogo/evals/`, with `claude plugin eval` on the
  session's own login, about $0.60 a case), and passes when every case scores 2
  of 3 runs. A case passing on its own does not prove the plugin did it: a new
  case is first run with `--skill <s> --baseline`, which fails when the case does
  as well without the plugin. Its `tests` pattern makes the test guard read a
  weakened or removed case like a weakened test. Not run in CI.
- **live**: a real run of the changed skill in an adopting repo, read-only
  unless the spec says otherwise. Triage-only (`/gogogo:auto-dev
  --triage-only`) and dry runs with posting blocked are the default. Say which
  repo and what was checked.
- **auto-dev on this repo**: the plugin it runs is loaded from this checkout
  (the **live** lane), so never switch branches or pull in that tree during a
  run, and do not edit `plugins/gogogo/` in it while the run is going.
  Switching branches in the loaded tree, or pulling into it, changes the
  skills under the running loop (`CLAUDE.md` § What a change here does). The
  owner chose a worktree per issue here on 2026-10-03
  (`integration.workspace`); the skills make it. The skills remove an issue's
  worktree after its merge is verified (`/gogogo:dev` §8), and each run starts
  by sweeping leftovers whose work merged (auto-dev preflight 11).
- **confirming a Released card**: `/gogogo:auto-test` is browser-based and is
  not set up here. Confirm instead against a worktree of `origin/main`: scripts
  in read-only or dry-run modes, and skill behaviour as scenario runs
  (`claude -p --tools "" --system-prompt "$(cat <SKILL.md> <its references/*.md>)" "<situation>"`,
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
