---
name: tech-eval
description: Use when deciding whether to adopt, replace, or move to a library, framework, language, service or tool: "should we use X", "move to Y", a research write-up recommending a technology, an upgrade across a major version, or reopening a decision recorded in the repo's technology decisions register.
---

# Deciding whether to adopt a technology

The pitch is always for the tool in general. The question is only ever whether **this
codebase** needs the one thing it does that we cannot already do — and how many times.

In one evaluation the evidence reversed a confident research recommendation to adopt: the
write-up cited 71 card roots, and a recount found the shared component hand-written in one
template. That is the whole method in a sentence: count before you trust.

**This skill reads. It never writes to any environment's data, never runs a command that
changes data, and never installs anything. The profile's `state.forbidden`, when it has
one, lists what is forbidden here. Its one write is the register rows this decision changes, in step 10.** It
reads code, git history, the tracker and public package APIs. The verdict goes to the
user; adopting is a code change, reviewed like any other.

## First: read this repo's profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for tech-eval --show
```

- Exit 0 prints the settings. Use them wherever this skill says *the profile*.
- Any other exit: **stop and report the line it printed.** It names the missing
  field.

Then read the profile's `## Technology evaluation` section **if it has one** (it is
optional). It holds this repo's stack facts, commands and worked examples, and the steps
below say where they apply.

## 0. Read the register first

The register is at the profile's `technology.register`. If the setting is unset, carry on
and do step 10's no-register branch at the end. If it is set and the file does not exist,
carry on; step 10 starts it.

List the candidates: the technologies the question names as something to adopt or move to
("X or Y?" names two; "move from X to Y" names Y, and X is background). Look up each
candidate's row under the name the evaluation will use, version included. A row for another
version of the same tool, and the row for the tool moved from, are background.

- **`Not now`**: **test its `Reopen when` condition** against today's code, or against
  whatever it names (a release, a measurement), and say whether it holds. If it does not
  hold, or you cannot tell, say so and stop — do not re-argue a settled decision because
  someone asked again. If it holds, carry on, and step 10 writes over this row.
- **`Rejected`**: if the user explicitly asked to reopen it, carry on, and step 10 writes
  over this row. Otherwise say so and stop.
- **`Adopted`** or **`Superseded`**: background, not a decision to re-test. Read its
  **Why** first, and carry on. If the verdict changes it, step 10 writes over this row; it
  never adds a second one.
- **No row**: carry on; step 10 says where its row goes.

**Several candidates.** A comparison is one evaluation per candidate: steps 1–10 run for
each, each ending in its own verdict and its own row, and the report sets them side by
side. The candidate not chosen is `Rejected` or `Not now`, and its **Why** names the one
chosen. A candidate stopped at this step is named in the report with the reason from its
row, and the others carry on. The run stops only when every candidate is stopped; then it
writes no row.

## 1. Name the one thing only this tool gives you

One sentence. Everything else it bundles is not a reason to adopt it — it is a reason the
tool exists. If you cannot write this sentence, there is nothing to evaluate.

## 2. Count where the code needs that thing

```bash
rg -n '<the pattern>'
```

plus any paths the profile's `## Technology evaluation` says to exclude.

- Report `file:line` for each hit.
- **Recount every number a pitch or research document gives you**, and report both when
  they differ. This is the step that gets skipped.
- Split the hits: which genuinely need the distinctive feature, and which an existing
  mechanism already serves?

## 3. Search past bugs for ones it would have prevented

```bash
git log --since='6 months ago' --pretty='%h %s' | rg -i '<symptom words>'
gh search issues --repo <tracker.issues_repo> '<terms>'
```

For each bug found: would this tool actually have prevented it, and is a cheaper fix
already open or merged? Name it. **"None found" is a finding** — write it down rather than
leaving the step silent.

## 4. Check the stack we already run

What does the *installed* version provide?

Verify in the installed code, never from memory. The profile's `## Technology evaluation`
names how to read installed versions here.

A hand-written replacement is also a dependency; its only maintainers are this team. If
that is the native path, say so in those terms rather than calling it "zero dependencies".

## 5. Check the package's health (packages only)

- **Existence and name.** Open the registry page and the repo it links to. Hallucinated
  and slopsquatted names are the reason this is a step and not an assumption.
- ```bash
  # <registry>: ecosyste.ms's name for it, e.g. pypi.org or npmjs.org (listed at
  # https://packages.ecosyste.ms/api/v1/registries?per_page=200) — a bare `pypi` returns
  # {"error":"not found"}, which reads exactly like "this package does not
  # exist": the wrong conclusion, from the step meant to prevent it
  curl -s https://packages.ecosyste.ms/api/v1/registries/<registry>/packages/<name>
  ```
  Read `latest_release_published_at`, `downloads`, `repo_metadata.archived`,
  `repo_metadata.pushed_at`, `advisories`.
- **Read all of these as leads, never as verdicts.** Checked live on 2026-09-26 for one
  package: `dependent_packages_count` was `0` against 246,089 downloads that month;
  `advisories` was `0` although 2.7.1 shipped a security fix (a quote breakout in dynamic
  attributes); `maintainers_count` was `null`. **`null` means unknown, not
  zero**, and `0 advisories` is not evidence of safety. Read the changelog for security
  fixes.
- The licence, and the language and framework versions this repo runs **as tested in
  upstream CI** — not merely as the metadata permits.
- Runtime dependencies of the release this repo would actually install: the newest one
  that matches the version asked about (if any) and supports the stack above. Read them
  from the package's own registry, never a same-named package in another one. The
  release list is at `https://pypi.org/pypi/<name>/json` or
  `https://registry.npmjs.org/<name>`; one release's dependencies are `requires_dist` at
  `https://pypi.org/pypi/<name>/<exact version>/json`, or `dependencies` and
  `peerDependencies` at `https://registry.npmjs.org/<name>/<exact version>`. If the release
  this repo would install is not the latest, say so and why, and check the changelog's
  security fixes against it. **If no release fits, that is a finding**: the verdict is
  Not now (reopen when one does) or Reject.

## 6. Verify the vendor's load-bearing claims in its source

Fetch the file and cite a line for each behaviour the recommendation depends on.

## 7. Cost both paths

- **Setup**, in days.
- **Ongoing**: a second syntax to know, patch cadence, a second test stack, and a
  per-feature choice between two ways of doing the same thing.
- **Deploy artefacts** and **transitive dependencies**.
- **Exit cost**: what backing this out in a year would touch.
- Any rule this repo has about new infrastructure (the profile's `## Technology
  evaluation` points at it) is checked here.

## 8. Look for traps on the deploy path

List what runs only on the way to, or in, the environment with the `production` role (the
profile's `environments` and `stages`, and its `## Technology evaluation`), and say whether
the tool survives each. Anything the pre-merge environment never exercises needs a test
that does.

## 9. Check the timing

What is about to be built that would have to be built twice if this is decided later? That
is usually the real deadline, not the tool's roadmap.

## 10. Verdict

Exactly one of:

- **Adopt** — with the narrowest scope that works, and the rule that keeps it narrow.
- **Not now** — with a **countable** reopen condition: "the third component that needs
  two caller-supplied regions", "a measured p95 over 400ms", "the next LTS release".
  Never "when it matures".
- **Reject** — with a one-line reason.

Then the register. Its rules:

- Columns exactly `Technology | Status | Why | Reopen when | Decided in`.
- Status one of `Adopted`, `Not now`, `Rejected`, `Superseded`.
- No `|` inside a cell.
- A `Not now` row needs a countable **Reopen when**.
- One row per technology. The **Technology** cell is the key and appears once. A version
  being decided is part of the name, as the project writes it (`Python 3.14`). A
  major-version upgrade of an `Adopted` tool is a decision about that version: it gets its
  own row, and the `Adopted` row for the earlier version is left alone unless the upgrade
  is adopted.
- A reopened decision is written over its own row. **Status** and **Why** take the new
  verdict; **Why** says in one clause what it replaced; **Reopen when** takes the new
  condition, or `—`; **Decided in** becomes the earlier reference or references followed
  by the new one, comma-separated. The earlier reasoning lives in what they name.
- Adopting supersedes. When the verdict is Adopt, the same run changes the row of the tool
  moved from, and every row for an earlier version of the same tool, whatever its status,
  to `Superseded`: **Why** `superseded by <Technology>` naming a different row and never
  itself, **Reopen when** `—`, **Decided in** extended as above.
- Rows are never deleted. A superseded row keeps its place, takes status `Superseded`, and
  names its replacement in **Why** as `superseded by <Technology>`.
- **Decided in** is an issue number or a `.md` path; never a date or anything else. If
  the evaluation has neither, ask the user which to name. If there is none, write no row
  of this run and start no file: show every row it would have written or changed, and say
  they are not recorded until they name one.

Where the row goes depends on `technology.register`:

- **Set, and the file exists**: add the row, or write over its existing row as above, and
  change the rows it supersedes.
- **Set, and the file is missing**: create it from this template, then add the row:

  ```
  # Technology decisions

  One row per technology: a library, framework, language, service or tool. A version being
  decided is part of the name.
  `/gogogo:tech-eval` reads this file first and writes its rows last. Rules: see that skill's step 10.

  ## Register

  | Technology | Status | Why | Reopen when | Decided in |
  |---|---|---|---|---|
  ```
- **Unset**: write no file. Give the verdict, show the row as it would be written, and
  say: "This repo has no register. Set `technology.register` in `.agents/dev-process.md`
  to a path (for example `docs/technology-decisions.md`) and the next run will start it;
  `/gogogo:setup` can help."

Then:

- Follow-up work goes through `/gogogo:spec`.
- Give the verdict to the user, with the file you wrote or started, if any. Leave it
  uncommitted in the working tree: the user commits it, or changes the verdict first.
  **Never adopt on your own.**

## Red flags

| Phrase or shape | What it means |
|---|---|
| a number quoted from a pitch without a recount | step 2 was skipped |
| "zero dependencies" for a hand-written replacement | the dependency just changed its author |
| a weighted scoring matrix | invented weights look rigorous and are not; use counts and costs |
| "reopen when it's more mature" | not countable, so it will never be reopened |
| a verdict that never mentions the native option | step 4 was skipped |
| "0 advisories" offered as evidence of safety | see step 5 |
| a recommendation written before the register was read | step 0 was skipped |
| two rows with one Technology cell | step 10's one-row rule was skipped |
| one verdict for a question that names two candidates | step 0's several-candidates rule was skipped |

## Worked examples

This repo's own examples, if any, are in the profile's `## Technology evaluation`.

## Provenance

Three published skills were read while writing this one (when this method was first
written). None was installed; each
contributed one idea:

- **`andrew/managing-dependencies`** (CC0; write-up at nesbitt.io, 2026-01-21) — the
  package-existence check against hallucinated names, and reading health data from the
  ecosyste.ms API (step 5).
- **ADR recorder skills** (for example `affaan-m/everything-claude-code`
  `skills/architecture-decision-records`) — the status lifecycle with "superseded by"
  links (step 10). They record whatever was decided; they have no evidence step.
- **`rampstackco/claude-skills` `dependency-management`** — exit cost and transitive
  dependencies as named cost lines (step 7).

What none of them do, and this does: measure the need **in this codebase**, search **our**
bug history, test the native path in the **installed** version, and end with a countable
reopen condition stored where the next evaluation looks first.
