---
name: log-review
description: Use when asked to review production's logs, find what is going wrong in production, run the periodic log review, or turn production errors into tracker issues. Reads the logs the production environment's `logs` setting names, groups the hits by root cause, files or updates one issue per cause, gives every open log-review issue a verdict, and writes a dated run log.
---

# log-review: production's logs, as tracker issues

A stream of error lines or error emails is something nobody owns. An issue is.
So a finding lives in exactly one place, its issue, and the review's job is to
keep those issues true: one per cause, never a duplicate, and each open one
given a verdict on every run. The method is the same in every repo. Where the
logs are, and how to read them, is each repo's own, in the `logs` setting of
its production environment.

## Read-only

Read logs and nothing else. Never connect to a production database, restart a
service, edit a config, or print a secrets file. That holds even when a log
line points straight at the fix. Production's `writes` setting may forbid more;
it never permits more here.

## First: read the profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for log-review --show
```

Any exit but 0: **stop** and report the line it printed. Without production's
`logs`, ask the person how its logs are read and suggest they add that to the
profile (`/gogogo:setup`); never go looking on the server. Each `warning:` line
goes, verbatim, at the top of your report.

Then read what `logs` names. When it is a doc, read all of it: which logs
belong to this app's production and which do not, how each is read, how far
back each goes, and the review's own notes (where its run log goes, noise
particular to this app).

## The output

- **One issue per root cause** in `tracker.issues_repo`, labelled
  `log-review`; create the label once if it does not exist. Assign it only to
  someone the person names.
- An existing issue for the same cause gets a **comment** with this window's
  numbers, never a second issue.
- Asking for this review is the approval to file and to comment. It is **not**
  approval to close anything (step 6).
- A **run log** (step 7) records the run. It never restates a finding: if the
  log and an issue could disagree, the log is wrong.
- The chat reply: one line per issue created, commented on or judged, with its
  link, and the run log's path.

## When the tracker is public

When `tracker.public` is true, check every issue body and comment before it is
posted. It names no visitor IP address, cookie, session id, email address or
person; no server path, service name, port, database name or user; no
internal host name; no secret and no setting's value. Quote a user agent at
most. Public URLs and paths, status codes, counts, dates, repo file paths with
line numbers, commit hashes, exception types, and messages the app's own code
logs (with any id of a person removed) are fine. What was left out of an issue
goes in the run log, under the issue's number, when the run log is private.

## 1. The window, and what production was running

The window starts where the newest run log's window ended, or 7 days back when
there is none. Take only that date from the old log: each finding's state
comes from its issue.

```bash
gh issue list --repo <tracker.issues_repo> --label log-review --state all --limit 100 \
  --json number,title,state,updatedAt,closedAt
```

A full page means rows were cut off: raise the limit.

Find what was deployed. When the `stages` entry for the production environment
has a `tag`, its tags are the deploy history:

```bash
git fetch --tags origin
git tag -l '<tag>' --sort=-creatordate --format='%(refname:short) %(creatordate:iso) %(objectname:short)'
```

Otherwise use what the `logs` doc says, or record the deploys as unknown. A
problem that starts at a moment starts after some deploy: that commit range is
where its cause is.

## 2. Collect

From each log the `logs` setting names as this app's production, take every
client or server error in the window and every warning, error and traceback
line, not only the lines that match an error response. Also take the same
paths' results from before the window, to tell a new failure from an old one.
When a log does not reach back to the window's start, say so.

## 3. Group into problems

Group by **cause**, not by URL or status. For each group, find the message the
app logged, search the code for that literal message, and read the code that
raises it before deciding what the group is.

- **A deliberate error is still a finding.** Code that refuses on purpose,
  because data or a setting is wrong, is doing its job; the fault is the data.
  File it as a data fix that names the exact change to make. Deliberate is not
  harmless.
- **An alert or an inbox full of error emails is a symptom**, never the finding.
- **Onset matters more than volume.** A path that worked for months and has
  failed since one deploy is a regression, whatever its count. Give its first
  bad hit and the deploy just before it.
- **Noise is counted, never filed**: scanner probes for software this app does
  not run, injection strings, crawlers asking for paths that never existed.
  The exception is a spike of real browsers refused on a path that should
  exist: a broken link or an access regression, and a finding.
- **Who was hit.** Split each finding's hits into bots and real browsers, and
  give the referrers. A link-preview fetcher means the link is being shared,
  so people are arriving.

## 4. Check each problem against the tracker

Search open **and** closed issues, labelled or not, before filing; a user's
report of the same cause counts:

```bash
gh issue list --repo <tracker.issues_repo> --state all --limit 50 \
  --search "<path or message fragment>" --json number,title,state,labels
```

| What exists | Do |
|---|---|
| nothing | File a new issue (step 5) |
| an open issue | Comment: this window's count, still occurring or not, the deployed commit |
| a closed issue, and it **still occurs after its fix was deployed** | A new issue whose first line says it is a regression of #N, naming the fix commit and the deploy it shipped in |
| a closed issue, not occurring | Nothing |

## 5. The issue

The title names the symptom and the cause. The body, in this order:

1. **Summary**: what is broken, for whom, since when (the first bad hit), and
   whether it is still happening.
2. **Cause**: the code path (`file:line`) and the logged message; whether it
   is a fault in the code or in data or configuration; the deploy before the
   onset when that matters.
3. **Impact**: counts over the window, referrers, bots against real browsers.
4. **Fix**: the immediate step, and the follow-up that makes this kind of
   fault loud or impossible.
5. **Acceptance**: checkboxes, including a test that fails without the fix.

## 6. A verdict on every open log-review issue

Each open issue with the label gets one comment with exactly one verdict, even
when it had no hits this window:

| Verdict | Evidence it needs |
|---|---|
| **Still occurring** | This window's count and the newest hit |
| **Stopped, fix deployed** | The fix commit; proof it is deployed (`git merge-base --is-ancestor <fix> <deployed commit>` exits 0); no hits since that deploy. Then suggest closing: closing is a person's call |
| **Stopped, no fix found** | No hits, and no commit explains it. Say so and leave it open |
| **Unverifiable** | Which log is missing, such as one shorter than the window |

"Still an issue" with no numbers is the failure this skill exists to prevent.
"Fixed" because the code on the base branch looks right is not a verdict: only
the deployed commit counts.

## 7. The run log

Write `<run log folder>/<YYYY-MM-DD>.md` (the run's date) in the folder the
`logs` doc names; when it names none, ask where. Four sections and nothing
else:

1. **Run**: the window (start and end, UTC), the deployed commit (hash, date,
   subject), the deploys in the window, and anything that could not be read.
2. **Issues**: one row per issue created, commented on or judged, as
   `#N | created/commented/regression | verdict | hits this window`.
3. **Traffic and noise**: error totals per surface, scanner and bot totals,
   and what was checked and dismissed, with one line on why. This is the only
   home these numbers have, and the next run compares against them.
4. **Private evidence**: only when the folder is in a private repo, under
   `### #N`, what was left out of that public issue (sample log lines, client
   addresses, server paths). Never a secret, a cookie or a session id.

A run that finds nothing still writes its log: the next run needs its end
date. Commit and push it as the `logs` doc says. When it says nothing, leave
the file uncommitted and say so. Never force-push.

## Do not

- File one issue per status code or URL, or file noise.
- Paste an error email or a raw log line into a public issue.
- Close an issue, or call one fixed from the code alone.
- Read last run's states from the old log, or describe a finding in the run
  log.
