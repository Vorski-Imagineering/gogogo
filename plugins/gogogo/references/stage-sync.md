# Stage sync: moving a card when a tag ships its fix

The shared skills move a card to the first of the profile's `stages` after a
verified merge. A later stage, such as "in production", is reached by a
release, not a merge. When that stage has a `tag` (a glob such as `deploy-*`,
`references/profile-schema.md` § Stages), the repo's CI runs
`scripts/stage_sync.py` on every pushed tag that matches it, and the script
moves each card whose fix the tag contains.

## The link: a `Ships-issue` trailer

Which issue a merge fixes is a git trailer on the squash commit:

```
Fix the empty state on the dashboard (#57)

* show a message when there is nothing yet
* test it

Ships-issue: owner/issues-repo#450 reporter=jdoe
Co-Authored-By: Someone <someone@example.org>
```

- `Ships-issue: <owner>/<repo>#<n>`, with ` reporter=<login>` when someone
  should be asked to confirm the fix. One line per issue; a merge may name
  several.
- **Git reads trailers only from the final paragraph, and only when every line
  of it is a trailer.** A prose line after it, or a blank line between
  `Ships-issue` and `Co-Authored-By`, and the link is silently gone. Build the
  whole final paragraph with `stage_sync.py trailer --co-authors-from`, never
  by hand.
- The legacy short form, `Ships-issue: <repo name>#<n>`, is still read when
  `<repo name>` is the repo part of `tracker.issues_repo` or
  `tracker.code_repo`. History cannot be rewritten, so readers keep accepting
  it; writers emit the full form only.
- Not `Fixes:` or `Closes:`: those are GitHub closing keywords, and would close
  the issue at merge, before anyone has seen the fix live.
- Why a trailer: git already stores and parses it, a CI runner or a release box
  with no `gh` can read it, and there is no second store (a comment marker, a
  board field) to disagree with the history.

## Who writes it

- **A repo's own merge script** (`integration.strategy = "merge-script"`)
  calls `stage_sync.py trailer` and puts its output at the end of the squash
  body.
- **`/gogogo:dev` and `/gogogo:auto-dev`**, when they merge with `gh`
  (`pr-squash`, `run-branch-pr`) and the profile uses the link
  (`handback.reporter = "trailer"`, or any stage has a `tag`). The recipe is in
  `/gogogo:dev` §8; `verify_merged.py --ships` then reads the link back from
  the merge commit.
- Under `run-branch-pr`, the run's final PR must be merged with a **merge
  commit**, not squashed: a squash leaves the issue commits out of the
  target's history, and no tag cut from it carries their links.

## The commands

```
stage_sync.py [--profile FILE] trailer (--issue ISSUE ... | --branch NAME) [--verify] [--co-authors-from RANGE]
stage_sync.py [--profile FILE] sync --tag TAG [--main-ref REF] [--dry-run]
stage_sync.py [--profile FILE] shipped --tag TAG [--titles]
```

`--profile` defaults to the nearest `.agents/dev-process.md`. Pass it
explicitly in CI.

- **`trailer`** prints the `Ships-issue` lines. `--issue` takes `<n>`,
  `<n>=<login>`, `<owner/repo>#<n>[=<login>]` or the short `<name>#<n>`; a bare
  number is `tracker.issues_repo`. `--branch fix/<n>-<slug>` names issue `<n>`
  (ignored when `--issue` is given). `--verify` checks on GitHub that each
  issue exists and each reporter can be assigned. `--co-authors-from <range>`
  appends the range's `Co-Authored-By` lines, de-duplicated, so the output is
  the whole final paragraph.
- **`sync --tag T`** finds the stages whose `tag` matches `T`. For each, it
  reads the cards in the column of the stage before it, and moves each card
  whose linked commits are **all** in `T`: it checks the card is still there,
  comments "Now live on `<environment url>`", assigns the reporter (when
  `handback.reporter` is `trailer`), and moves the card through `tracker.py`.
  A card with a commit not yet in `T` stays. `--dry-run` prints the plan and
  writes nothing. `--main-ref` is the branch the tags are cut from (default
  `origin/main`).
- **`shipped --tag T`** lists the issues linked from the commits between the
  previous tag matching the same glob and `T`, for a release notification.
  `--titles` looks the titles up with `gh`.

| Exit | Meaning |
|---|---|
| 0 | ok |
| 1 | `sync`: every possible move was made, and something needs a look (a card with no linked commit, or a reporter that could not be assigned) |
| 2 | nothing trustworthy to act on (no such tag, no stage matches it, an unreadable board or profile), or a comment or move failed |
| 3 | `trailer --verify`: every issue exists, but a reporter cannot be assigned. Retry without the login |

A crash exits 2, never 1. The comment carries a marker,
`<!-- stage-sync tag=<tag> shas=<sha8>,… -->`, keyed on the commits: a sync
that commented and then failed to move moves the card on the next tag without
commenting again.

## Running it in CI

### Vendoring

The workflow runs a pinned copy, not the plugin: CI must not follow gogogo's
`main` unpinned, and the board token should not cross repos.

1. Copy `tracker.py`, `profile_check.py` and `stage_sync.py` from **one**
   gogogo commit into one folder of the repo (they import each other from
   their own folder).
2. Record that commit and each file's sha256 in a pin file next to them.
3. Keep a test in the repo that fails when a copy no longer matches its pin.
4. To refresh, copy all three again from one newer commit and rewrite the pin.

CI needs Python 3.11 or later (`tomllib`).

### Workflow example

```yaml
name: Stage sync

on:
  push:
    tags: ['deploy-*']          # the stage's tag glob
  workflow_dispatch:
    inputs:
      tag:
        description: 'Tag to sync against'
        required: true
      dry_run:
        description: 'Print the plan without commenting, assigning or moving'
        type: boolean
        default: true

# Two live syncs at once could both pass the "still in the source column?"
# check and both comment: one at a time. GitHub keeps only the newest pending
# run per group, so dry runs queue in a group of their own and never replace a
# queued live run.
concurrency:
  group: stage-sync-${{ github.event.inputs.dry_run == 'true' && 'dry' || 'live' }}
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          # The trailer scan and the ancestry check need the whole history.
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Move the cards this tag ships
        env:
          # Values go through the environment, never into the script body:
          # GitHub substitutes ${{ }} before the shell parses it.
          TAG: ${{ github.event.inputs.tag || github.ref_name }}
          DRY_RUN: ${{ github.event.inputs.dry_run || 'false' }}
          # The default GITHUB_TOKEN cannot reach an organisation project: use
          # a token that can write the board and comment on the issues repo.
          GH_TOKEN: ${{ secrets.STAGE_SYNC_TOKEN }}
        run: |
          test -n "$GH_TOKEN" || { echo "::error::STAGE_SYNC_TOKEN is not set"; exit 1; }
          # --main-ref is the branch the tags are cut from.
          ARGS=(--profile .agents/dev-process.md sync --tag "$TAG" --main-ref origin/main)
          if [ "$DRY_RUN" = "true" ]; then ARGS+=(--dry-run); fi
          python3 <vendored folder>/stage_sync.py "${ARGS[@]}"
```

Replace `<vendored folder>` with the folder from *Vendoring*.

### Notification

`shipped` writes plain text (titles are user-written; send it without markup):

```bash
python3 <vendored folder>/stage_sync.py --profile .agents/dev-process.md \
  shipped --tag "$TAG" --titles > message.txt \
  || printf 'Tag %s pushed (issue list unavailable)\n' "$TAG" > message.txt
```

Then send `message.txt` with the repo's own transport. A listing that fails
must never cost the notification itself, hence the fallback.
