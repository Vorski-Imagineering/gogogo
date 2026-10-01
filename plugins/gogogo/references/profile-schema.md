# The process profile: `.agents/dev-process.md`

Every repo that uses `gogogo` has one profile. The shared skills hold
the rules that are the same everywhere; the profile holds what differs in this
repo. A skill checks the profile before it does anything else and stops,
naming the field, if something it needs is missing.

## Shape

The file starts with a settings block: TOML between two `+++` lines. After it
come `## ` sections of project knowledge that the skills point to.

```
+++
profile = 1

[tracker]
kind = "github-project"
issues_repo = "owner/repo"
...
+++

## Recon traps
...

## Lane constraints
...

## superpowers boundary
...
```

Settings are values: names, commands, URLs. Keep rules and explanations out of
them. Rules that apply to every task stay in `CLAUDE.md`, and the profile
points at them (`hard_stops.source`) without copying them.

## Check it

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py"                        # everything
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for spec    # one skill
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --show                 # settings as JSON
```

Exit 0 is ok, 2 means there is no profile, 3 means it is unreadable or
incomplete. Each problem is one line on stderr that starts with the field.
With no `--for` it checks every skill, and `auto-test` only when the profile
has an `[auto_test]` table, so a repo that never adopted it still passes.

## Settings

"Required by" lists the skills that stop without the field. "optional" means
no skill requires it; a skill that finds it uses it.

| Setting | Type | Required by | Meaning |
|---|---|---|---|
| `profile` | int | all | Profile format version. |
| `tracker.kind` | str | all | github-project / github-label / todo-file. |
| `tracker.issues_repo` | str | all | owner/repo that holds the issues. |
| `tracker.code_repo` | str | all | owner/repo that holds the code. |
| `tracker.public` | bool | all | True if the tracker is readable by the public. |
| `tracker.ready_marker` | str | `spec`, `auto-dev` | Label that marks an issue as specced and pickable. |
| `tracker.tool` | str | `dev`, `auto-dev`, `auto-test`, `roadmap` | 'shared' for the plugin's tracker.py, or a command for the repo's own tool meeting references/tracker-contract.md. |
| `tracker.project_owner` | str | optional | Owner of the GitHub project board. |
| `tracker.project_number` | int | optional | Number of the GitHub project board. |
| `tracker.queue` | str | `auto-dev` | Column or label the loop works. |
| `tracker.columns` | dict | `dev`, `auto-dev` | Columns before any code moves: in_progress, back_to_queue. |
| `environments` | list | all | Where code runs: name, roles, and url/serves/reached_by/data/writes. |
| `stages` | list | `dev`, `auto-dev`, `auto-test` | The path a change takes after it merges: code_is, column, environment. |
| `hard_stops.source` | str | all | Where the repo's Hard Stop rules live (file#anchor). |
| `hard_stops.form` | str | `spec`, `dev`, `auto-dev` | categories / questions. |
| `hard_stops.items` | list | `spec`, `dev`, `auto-dev` | Names of the categories or questions, in order. |
| `hard_stops.two_licence` | list | optional | Changes that need a design approval and an apply approval. |
| `design.placement_rule` | str | optional | Where the repo says which layer or folder new code belongs in. |
| `technology.register` | str | optional | Path of the technology decisions register, from the repo root. |
| `roadmap.file` | str | optional | Path of the roadmap document, from the folder holding `.agents/`; it may sit in another git repo checked out inside this one. |
| `lanes` | list | `spec`, `dev`, `auto-dev` | Test lanes: name, plus run/focused/env/ci. |
| `verify.agent` | list | `dev`, `auto-dev` | Environments where the implementing agent checks its work. |
| `verify.human` | str | `spec`, `auto-test` | Environment where a person confirms a fix. |
| `verify.rungs` | list | `dev`, `auto-dev` | Ordered verification steps. |
| `state.read` | str | optional | How to read a safe copy of real state. |
| `state.forbidden` | list | `dev`, `auto-dev` | What must never be written or run. |
| `report.staleness_source` | str | optional | How to tell which build a report came from. |
| `observability` | str | optional | Error tracker to consult before reading code. |
| `gates.always` | list | `auto-dev` | Checks run before every merge. |
| `gates.when` | dict | optional | Path pattern -> extra checks. |
| `integration.strategy` | str | `auto-dev` | merge-script / run-branch-pr / pr-squash. |
| `integration.base` | str | `auto-dev` | Branch issue branches are cut from. |
| `integration.command` | str | optional | Merge command, for merge-script. |
| `integration.final_target` | str | optional | Branch the run's PR targets, for run-branch-pr. |
| `integration.mode_check` | str | optional | Command that proves unattended mode is on. |
| `integration.ci_before_merge` | bool | `auto-dev` | True if CI must pass on each issue before it merges. |
| `handback.reporter` | str | `dev`, `auto-dev` | trailer / assign / none. trailer: each merge writes a Ships-issue trailer naming the reporter, and stage sync assigns them when the card enters a stage with a tag. |
| `preflight.extra` | list | optional | Extra checks before a run. |
| `stop.extra` | list | optional | Extra conditions that stop a whole run. |
| `notify` | str | optional | none / telegram. |
| `auto_test.pass_column` | str | `auto-test` | Column a card moves to on PASS. |
| `auto_test.fail_column` | str | `auto-test` | Column a card moves to on FAIL. |
| `auto_test.fail_label` | str | `auto-test` | Label added on FAIL. |
| `auto_test.human_label` | str | `auto-test` | Label added on NEEDS HUMAN. |
| `auto_test.pass_closes` | bool | `auto-test` | True if PASS closes the issue. |

### Lanes

`lanes` is a list of tables. Each needs a `name`, and either `run` (a command)
or `env` (where the lane is checked). Optional: `focused` (the command for one
test or module, used for the seen-failing step) and `ci` (true if CI runs it).

```toml
[[lanes]]
name = "automated"
run = "make test"
focused = "make test TEST=<module>"
ci = false

[[lanes]]
name = "browser"
env = "https://dev.example.org"
```

### Environments

`environments` lists where this repo's code runs. The shared skills never say
"dev" or "staging". They say one of three **roles**, and the profile says what
each is called here.

| Role | Meaning |
|---|---|
| `pre-merge` | Where a change is exercised before it merges. |
| `pre-production` | Where merged work is live for the team, not for users. A repo may have none. |
| `production` | What users use. |

Each environment needs a `name` (this repo's word for it) and `roles`. One
environment may fill two roles. Optional: `url`, `serves` (what code it runs),
`reached_by` (how code gets there), `data`, and `writes` (what may be written
there, and by whom). A skill takes its safety rules for an environment from
`writes`; it does not assume them.

```toml
[[environments]]
name = "dev"
roles = ["pre-merge", "pre-production"]
url = "https://dev.example.org"
serves = "the checked-out branch; main between runs"
data = "restore of production"
writes = "allowed, except restores"

[[environments]]
name = "production"
roles = ["production"]
url = "https://app.example.org"
reached_by = "a person runs the deploy script"
writes = "only through the app's own UI"
```

`verify.agent` lists the environments where the implementing agent checks its
work. `verify.human` names the one where a person confirms a fix; a spec's
"Verify by hand" points there.

### Straight to production

A repo where a merge to the main branch is the release has no
`pre-production` environment. The rule `/gogogo:setup` and `setup_check.py`
use: **no environment has the role `pre-production` ⇒ straight to production.**
It then has one stage, and the agent verifies before the merge only.

```toml
[[environments]]
name = "local"
roles = ["pre-merge"]

[[environments]]
name = "production"
roles = ["production"]

[[stages]]
code_is = "merged to main"
environment = "production"
column = "Released"

[verify]
agent = ["local"]
human = "production"
```

### Stages

`stages` is the path a change takes after it merges, in order. Each stage says
where the code is (`code_is`), the board `column` that says so, and optionally
the `environment` that now serves it and who moves the card (`moved_by`). A
stage with no `environment` is one where no site serves the code yet.

```toml
[[stages]]
code_is = "merged into the run branch"
column = "Merged to run"
moved_by = "the loop, after the merge is verified"

[[stages]]
code_is = "merged into staging"
environment = "staging"
column = "In Staging"
moved_by = "the loop, once the run PR shows MERGED"
```

A card moves only as far as the code has. A skill checks the code is at a stage
before it moves the card there, and names the column, never a stored id.

A stage may also have a `tag`: a glob such as `deploy-*`. A card enters that
stage when every commit linked to its issue (by a `Ships-issue` trailer) is in
a pushed tag matching the glob, and it comes from the stage before it. The
repo's CI runs `stage_sync.py` on each such tag; see
`references/stage-sync.md`. A `tag` is optional, never on the first stage (a
merge puts a card there, not a tag), needs an `environment` (the comment says
where the fix is now live), must not contain `/`, and is used by one stage
only.

```toml
[[stages]]
code_is = "merged to main"
environment = "dev"
column = "In Dev"
moved_by = "the loop, after the merge is verified"

[[stages]]
code_is = "every linked commit is in a deploy tag"
environment = "production"
column = "In Production"
moved_by = "stage_sync.py, run by CI on each deploy tag"
tag = "deploy-*"
```

`profile_check.py` warns on any other key in a stage (a typo there would
otherwise be silent), and when `handback.reporter` is `trailer` but no stage
has a `tag`.

### Two-licence changes

`hard_stops.two_licence` lists changes where approving the design and approving
its application to a shared environment are separate questions. Each entry has
`change`, `apply`, and optionally `procedure` (a section of this profile).

```toml
[[hard_stops.two_licence]]
change = "migration"
apply = "migrate on the dev DB"
procedure = "Applying a migration to dev"
```

### Auto-test

`/gogogo:auto-test` tests the cards in one column: the `column` of the one
stage whose `environment` is `verify.human`. That environment needs a `url`
(where the tests run) and `writes` (the whole of what a test may write there).
The `[auto_test]` table says what each outcome does:

```toml
[auto_test]
pass_column = "Done"
fail_column = "Backlog"
fail_label = "test fail"
human_label = "test needs human"
pass_closes = true
```

The table is the opt-in. A profile without it is not checked for `auto-test`
when `profile_check.py` runs with no `--for`, and `/gogogo:setup` reports it
as not set up rather than as a failure. A profile with it also needs a
`## Test data` section (below).

### Roadmap

`roadmap.file` is read only by `/gogogo:roadmap`, which keeps a roadmap
document's state marks in step with the board. That skill also needs
`tracker.kind = "github-project"` and `tracker.tool = "shared"`: it reads
columns through the plugin's own `tracker.py`, in-process. It needs
`tracker.ready_marker` when the document's legend uses `ready label`. What each
mark means lives in the document's own legend (its `Covers` column), not in the
profile. Unset, the repo has no roadmap document and the skill stops.

```toml
[roadmap]
file = "docs/roadmap.md"
```

## Sections

| Section | Read by |
|---|---|
| `## Recon traps` | `spec`, `dev` |
| `## Lane constraints` | `spec`, `dev` |
| `## superpowers boundary` | all |
| `## Technology evaluation` | `tech-eval` (optional) |
| `## Wrap-up checks` | `wrap-up` (optional) |
| `## Test data` | `auto-test` |

- **Recon traps**: what this codebase hides. The table of traps and the worked
  examples.
- **Lane constraints**: what each test lane can and cannot reach here, and what
  a spec must therefore specify.
- **superpowers boundary**: the three rules that keep tracker work in the
  tracker.
- **Technology evaluation**: this repo's stack facts for `/gogogo:tech-eval`:
  paths to leave out of counts, how to read installed versions, rules about new
  infrastructure, what runs only in production, and worked examples.
- **Wrap-up checks** (optional): what `/gogogo:wrap-up` checks here on top of
  its own list, as a `| Check | How |` table (other repos this one depends on,
  a database a session may have changed, a docs site a push deploys), which of
  them block closing, and where this repo's learnings go.
- **Test data**: what the repo's live environment holds that
  `/gogogo:auto-test` may touch, and what it must never touch. It has six
  `### ` headings, each of which may say "None":
  - **Running build**: how to read the build the environment runs, and the
    git ref it names.
  - **Finding the change**: how this repo links a commit to an issue, before
    the shared fallbacks.
  - **Sandbox and fixtures**: where test data may be created, the fixtures and
    their baseline, and where planned fixtures are listed.
  - **Optional lanes**: lanes beyond the browser, and how preflight decides
    each is READY.
  - **Extra step rules**: exceptions to the default step classes.
  - **Never call**: routes and actions never used, on any lane.

A profile may add more sections (for example a procedure that
`two_licence.procedure` names). Unknown sections are fine; unknown settings
produce a warning, because a typo in a setting name would otherwise be silent.
