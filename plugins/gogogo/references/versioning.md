# Versioning and release notes

One way to number, tag and describe a production release, in every repo that
adopts it. A repo adopts it by having a `[release]` table in its profile
(`references/profile-schema.md` § Release). `scripts/release.py` does the
work; `/gogogo:setup` reports whether a repo follows it. gogogo follows it
itself: its `main` is production, and a workflow after its tests tags every
push to `main` `deploy-<build>`, version `1.0.<build>`.

Nothing here is bumped by hand except a deliberate major. Every number people
remember to bump goes wrong; the two that stay right are mechanical: a tag cut
by the deploy, and the commit count.

## 1. The build

The build number is `git rev-list --count` on the deployed commit:

- **on the base branch only.** A commit on a staging or feature branch can
  share a count with a different commit on the base, so `release.py tag`
  refuses a commit that is not on `origin/<integration.base>`;
- **with full history.** A shallow clone counts only what it has and gives a
  wrong number with no error, so `release.py` refuses a shallow clone. CI
  checks out with `fetch-depth: 0`.

`release.py build` prints it.

## 2. The tag

Each production deploy gets one annotated tag, `deploy-<build>`:

- cut by `release.py tag --push origin`, **after** the deploy has succeeded
  (migrations, checks and static files all passed). The tag announces the
  release; a deploy that fails after tagging has already announced itself;
- a re-run on the same commit creates nothing: the name is taken by that
  commit, so it prints `already tagged`. With `--push` it pushes that tag
  again, so a re-run after a failed push still reaches the remote; a remote
  that already has the tag on that commit is left as it is, and it exits 0.
  The name taken by a *different* commit means history was rewritten, and is
  refused;
- a push that fails exits 4 with the local tag kept; the caller decides
  whether that fails its deploy;
- a staging or dev deploy is not tagged;
- older date-named `deploy-*` tags stay where they are. The first
  `deploy-<build>` release finds the newest of them as its previous tag, so its
  notes cover everything since the last old-style deploy.

## 3. The version

`<major>.<minor>.<build>`:

- `major` is `release.major`, raised by a person, never automatically;
- `minor` is `0` until Vorski-Imagineering/gogogo#14 decides how it is worked
  out;
- the build never resets, so every release sorts above the last.

`release.py version` prints it. It is generated into built artefacts at build
time (a package version, an extension manifest, the release name reported to
an error tracker as `<project>@<version>+<sha7>`) and never committed.

A store that only accepts a version higher than its last one: while the build
is at or below the store's current version, start `major` above it. Every part
stays far below the 65535 such stores allow.

## 4. What an app shows

`<build> · <sha7>`. The build is the number people say. A repo may add its own
extras next to it, such as a per-release name or colour, but never instead of
it.

## 5. Release notes

- **The tag's message.** `release.py tag` writes it with `git` alone (a deploy
  box may have no `gh`): `Release <version> · <sha7>`, when and where it was
  deployed, then the issues the release ships since the previous `deploy-*`
  tag, read from the `Ships-issue` trailers (`stage_sync.py`), and a count of
  commits with no linked issue.
- **A GitHub Release** with issue titles, created in the deploy job by
  `release.py announce --tag <tag>` from `release.py notes --tag <tag> --titles`
  (below).
- Issue comments and card moves stay with `stage_sync.py sync` on a stage with
  `tag = "deploy-*"` (`references/stage-sync.md`).

## 6. Artefacts named after a release

A backup, an archive, or anything else named after a release keeps a timestamp
of its own. A re-run of the same commit reuses the tag name: a database dump
named `deploy-<build>` alone would be overwritten by the dump of a
half-migrated database after a failed migrate.

## 7. The announcement, in the deploy job

After the deploy succeeds and `release.py tag --push origin` has pushed the
tag, the same job runs `release.py announce` for it. That one command does the
three things a deploy announces, in order, each once per tag:

1. **release**: the GitHub Release, created with issue titles when it is
   missing;
2. **sync**: the cards the tag ships, moved as `stage_sync.py sync` moves them,
   when a stage's `tag` glob takes the tag (otherwise it says so and goes on);
3. **notify**: one `deployed` message through `notify.py`. When it went, the
   Release's notes are marked with a hidden line, so a re-run does not send it
   again.

Each job prints one line. A failed job prints the command that retries it
alone (`--only <job>`), and the next job still runs: the announcement never
fails the deploy.

```yaml
tag-name:
  runs-on: ubuntu-latest
  outputs:
    tag: ${{ steps.name.outputs.tag }}
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    - id: name
      run: echo "tag=deploy-$(python3 <vendored scripts>/release.py build)" >> "$GITHUB_OUTPUT"
deploy:
  needs: tag-name
  runs-on: ubuntu-latest
  concurrency:
    group: announce-${{ needs.tag-name.outputs.tag }}
  permissions:
    contents: write
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    # ... the deploy itself ...
    - name: Tag and announce
      env:
        GH_TOKEN: ${{ secrets.STAGE_SYNC_TOKEN }}
        TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
        TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      run: |
        python3 <vendored scripts>/release.py tag --push origin
        TAG=$(git describe --tags --exact-match --match 'deploy-*' HEAD)
        python3 <vendored scripts>/release.py announce --tag "$TAG"
```

`STAGE_SYNC_TOKEN` is the token stage sync already uses (it can read and
move the board and create a Release). The `concurrency` group, keyed by the
tag, keeps two runs for one tag from both sending: reading the mark and
sending are two steps. The tag is only cut inside the deploy job, so the
`tag-name` job works out its name first, with `release.py build`, and the
group reads it from that job's output. The tag reaches the command through
the shell, never interpolated into the workflow. `release.py` imports its
neighbours from its own folder: vendor all five, `release.py`,
`profile_check.py`, `stage_sync.py`, `tracker.py` and `notify.py`, from **one**
gogogo commit, as `references/stage-sync.md` § Vendoring describes.

**Why in the deploy job.** A tag pushed with CI's default `GITHUB_TOKEN`
starts no other workflow, so a separate workflow that waits for the tag never
runs when the deploy job cuts it. Running the announcement in the job that
pushed the tag needs no other trigger.

## 8. Straight to production

The CI job that deploys checks out with `fetch-depth: 0` and runs
`release.py tag --push origin` as its last step, after the deploy has
succeeded.

An annotated tag needs a tagger: a CI runner or a fresh deploy box with no git
identity fails at `git tag`. Set one first (`git config user.name` and
`user.email`, or `GIT_COMMITTER_NAME` and `GIT_COMMITTER_EMAIL`).
