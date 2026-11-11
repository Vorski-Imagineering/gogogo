---
name: docs
description: Use when asked to audit, check or update a repo's documentation — audit (the default) checks every doc against the code and, on the person's yes, files one tracker issue per doc that is out of date; write <N> updates the docs a shipped issue touched, in a new worktree, and opens a pull request it never merges.
---

# docs: the docs, checked against the code

Docs go wrong quietly: the code changes, and the sentence that described it
stays. This skill finds those sentences. **Audit** reads every doc against the
code and reports what is wrong, then files issues only when the person says
yes. **Write** updates the docs one shipped issue touched, in a pull request a
person merges. Fixes found by an audit go through `/gogogo:spec` and
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
   A pull request whose branch starts `docs/` is this mode's own, never the
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

## What it never does

- Edit the person's checkout, in either mode.
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

## Claude-specific

- The filing question is `AskUserQuestion`, with `multiSelect: true`.
- Write mode's worktree is made with `git worktree add`, never with
  `EnterWorktree`: it must be the branch and path named above.
