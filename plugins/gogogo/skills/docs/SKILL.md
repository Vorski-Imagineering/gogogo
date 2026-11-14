---
name: docs
description: Use when asked to audit, check or update a repo's documentation — audit (the default) checks every doc against the code and, on the person's yes, files one tracker issue per doc that is out of date; write <N> updates the docs a shipped issue touched, in a new worktree, and opens a pull request it never merges; history adds the period since its last run (or since the history doc last changed), from evidence, in the same kind of pull request.
---

# docs: the docs, checked against the code

Docs go wrong quietly: the code changes, and the sentence that described it
stays. This skill finds those sentences. **Audit** reads every doc against the
code and reports what is wrong, then files issues only when the person says
yes. **Write** updates the docs one shipped issue touched, in a pull request a
person merges. **History** adds what happened since its last run (or since
the history doc last changed), every date, quote and number linked to its record, in the same kind
of pull request. Fixes found by an audit go through `/gogogo:spec` and
`/gogogo:dev` like any other issue.

"The check" below means
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/docs_check.py"`.

## First: read the profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for docs --show
```

Any non-zero exit: **stop**, and report the lines it printed. Any `warning:`
line goes, verbatim, at the top of your report; if it printed none, the report
says so.

The optional `[docs]` table says where the docs are. Each key absent has its
default:

| Setting | Absent means |
|---|---|
| `docs.dir` | `docs`, plus `README.md` at the repo root |
| `docs.index` | no check that an index links every doc |
| `docs.public` | no check for internal detail in public docs |

Docs under `docs.public` are read by outsiders (people using the product,
people adopting the repo). Everything else is read by the developers and
agents working in the repo.

## Audit

`/gogogo:docs`, or `/gogogo:docs audit`.

1. **The check first.** Run the check with `--json`. Exit 2 means it could not
   check (no doc in scope, an unreadable profile, an index or public folder
   that does not exist): report its line and stop. **Zero files read is a
   failure, never "all clear".**
2. **Then the claims.** For each file in scope, every sentence that names a
   script, setting, skill, command, flag or path is a claim. Read the code it
   names. Record it as `stale` only when the code shows it is false, with the
   doc's `file:line` and the code's `file:line` side by side. A claim with no
   evidence either way is not reported: a guess is not a finding.
3. **The report.** The counts first: files read, claims checked. Then one
   block per doc, `stale` findings first (wrong docs are the worst gap), then
   the check's `link`, `index`, `path` and `public` findings. A doc with
   nothing found is not listed.

## Filing

After the report, one `AskUserQuestion` (multiSelect, at most 4 docs per
question, more in later rounds) naming each doc with findings: which to file.
For each doc chosen:

1. Look for its open issue:
   `gh issue list --repo <tracker.issues_repo> --label documentation --state open --search "docs: <path> in:title" --json number,title`,
   keeping the one whose title starts `docs: <path>`.
2. One found: comment the findings on it.
3. None: `gh issue create --repo <tracker.issues_repo> --title "docs: <path> is out of date with the code" --label documentation --body-file <file>`,
   the body the findings.

When `tracker.public` is true, re-read each body as `/gogogo:spec`'s Posting
step 2 does (paths outside the checkout, outside names, hosts, links, tokens
and emails) before posting it. Write each body to a file; never `--body`.

A decline, or no person to ask: file nothing and say so. The report stands on
its own.

## Write

`/gogogo:docs write <N>`, after issue `<N>` has shipped.

1. **The change.** Find the merged pull request that claims `<N>` (by its
   branch, `#<N>` in its title, or a `Refs`/`Fixes`/`Closes`/`Resolves` line
   in its body, as `issue_work.py` claims one):
   `gh pr list --repo <tracker.code_repo> --state merged --search "<N>" --limit 200 --json number,title,headRefName,body`.
   A pull request on a `docs/<N>-` branch is this mode's own, never the
   change. None merged: say so, and stop.
2. **The docs to change.** Read the issue's `## Design` and the pull request's
   changed files (`gh pr view <pr> --json files`). The docs in scope that name
   a changed path, setting, script or skill are the candidates. A new skill,
   script or setting that no doc names is added to the doc that already lists
   things of its kind.
3. **Never in the person's checkout**: another session may be using it. The
   base is `integration.base`, else the repo's default branch
   (`gh repo view <tracker.code_repo> --json defaultBranchRef -q .defaultBranchRef.name`). From
   the main worktree (the first entry of `git worktree list --porcelain`):
   `git fetch origin && git worktree add -b docs/<N>-<slug> <its parent>/<its folder name>-wt-docs-<N> origin/<base>`
   (the slug: two to five lowercase words from the issue's title). Edit there.
4. **Check it.** Add any new doc to `docs.index` when it is set. Run the
   check and each `gates.always` command in the worktree; each passes on its
   own exit status. With no `gates.always`, say that no gate ran.
5. **Open the pull request**: commit, push the branch, and
   `gh pr create --base <base> --body-file <file>`, the body
   saying what changed in each doc and ending `Refs #<N>`. **Never merge it.**
   Report its link.

No doc needs a change: say so, naming the docs read, and open nothing.

## History

`/gogogo:docs history`. **REQUIRED REFERENCE:** read `references/history.md`
in full before writing any of the section: it holds the evidence rules.

1. **Where it starts.** The base is `integration.base`, else the repo's
   default branch, as Write step 3 says. `git fetch origin` first, and read
   the doc from the base (`git show origin/<base>:<docs.dir>/history.md`),
   never from the person's checkout. When the doc's last non-empty line is
   `<!-- history: through <full sha> <YYYY-MM-DD> -->`, the run starts after
   that commit. No such line: start after the last commit that changed the
   doc (`git log -1 --format='%H %cs' origin/<base> -- <doc>`), never from
   the project's first commit, or the run retells what a person already
   wrote. No doc: the whole of the base, first commit included, and the run
   creates it. Say which period the run covers before gathering.
2. **Nothing to tell.** An open pull request on a `docs/history-` branch:
   name it, and open nothing (its section is not on the base yet). The
   marker's sha not on the base
   (`git merge-base --is-ancestor <sha> origin/<base>` fails): stop, say the
   history was rewritten after the marker, and open nothing. Leave out the
   commits that change only the history doc (earlier runs' own pull
   requests); none left after the start: say so, and open nothing.
3. **Gather**, from the start to the tip of `origin/<base>`: the first-parent
   commits with their dates on the base
   (`git log --first-parent --format='%H %cs %s' <start>..origin/<base>`, or
   `origin/<base>` alone when there is no doc), the issues and pull requests
   they reference, pull requests closed without merging, issues closed as not
   planned, and cards handed to a person (stop markers in issue comments) in
   that period.
4. **Write one new section** at the end of the doc,
   `## <start date> to <end date>`, under `references/history.md`'s rules,
   its last line the marker for the tip commit, with its full sha. Earlier
   text is never changed, even where it is wrong: a correction is a sentence
   in the new section, with its link.
5. **Open it as Write does** (steps 3 to 5), with these names: branch
   `docs/history-<end date>`, worktree
   `<its parent>/<its folder name>-wt-docs-history-<end date>`, and a pull
   request body that says which period the section covers, with no `Refs`
   line. The check and each `gates.always` command, commit, push, and a pull
   request it never merges. When `tracker.public` is true, re-read the
   section as `/gogogo:spec`'s Posting step 2 does before the commit; people
   are named by role, never by name or handle.

## What it never does

- Edit the person's checkout, in any mode.
- Change the history doc's earlier text.
- Merge a pull request, close an issue, or move a card.
- File anything the person did not choose.
- Fix a finding from an audit: that is an issue for `/gogogo:spec`.

## Rationalizations that mean you are about to get it wrong

| Thought | Reality |
|---|---|
| "The check found nothing, so the docs are fine" | The check reads links and paths. Only reading the code shows a wrong claim. |
| "No files matched, so nothing is out of date" | No evidence is a failure. Report what could not be read. |
| "This probably changed" | Stale needs the code's `file:line` showing it is false. Otherwise it is not reported. |
| "It's one doc, I'll just fix it here" | Never in the person's checkout. Write mode works in its own worktree. |
| "The PR is tiny, I'll merge it" | A person merges docs. Open it and stop. |
| "They'd want these filed" | Only the docs they chose. |
| "Roughly a dozen features shipped" | A number is counted, with its command given, or left out. |
| "That failed PR spoils the story" | Mistakes stay in, with their links. |
| "The old history is wrong, I'll rewrite it" | Earlier text stays. Correct it in the new section. |

## Claude-specific

- The filing question is `AskUserQuestion`, with `multiSelect: true`.
- The write and history worktrees are made with `git worktree add`, never
  with `EnterWorktree`: each must be the branch and path named above.
