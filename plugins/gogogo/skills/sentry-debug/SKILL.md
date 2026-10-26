---
name: sentry-debug
description: Use when asked to debug, triage or report on a repo's Sentry errors — a Sentry issue URL, "what broke this week", a symptom a user reported that may have thrown, or the weekly Sentry report. Read-only, through the Sentry MCP, with the repo's org, projects and release format from its profile.
---

# sentry-debug: what threw, and what it means

Ask Sentry what happened before reading code, and say only what the data
shows. The method is the same in every repo; the values are each repo's own,
in its profile's `[sentry]` table and `## Sentry` section.

## Read-only

Never call a Sentry MCP tool that changes state: `update_issue` (resolve,
assign, ignore), creating or editing alerts, or starting a Seer autofix.
Only when the person asks for that specific change in this session.

## Needs the Sentry MCP

```bash
claude mcp add --transport http sentry https://mcp.sentry.dev/mcp
```

then `/mcp` to authenticate. When no Sentry MCP tool is available, say so with
that command and stop.

## First: read the profile

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_check.py" --for sentry-debug --show
```

Exit 0 prints the settings. Any other exit: **stop**, report the line it
printed, and ask the person for the missing values (`sentry.org`,
`sentry.region_url`, `sentry.projects`, `sentry.release_format`). Never pick an
organisation or project yourself with `find_organizations` or `find_projects`:
ask, don't guess. Any `warning:` line the check printed goes, verbatim, at the
top of your report.

Then read the profile's `## Sentry` section: which events are failures, which
are measurements, and where each is captured. Use `sentry.org`,
`sentry.region_url` and `sentry.projects` in every MCP call.

## Method

1. **Ask Sentry what threw before reading code.** `search_issues` for the
   symptom, then `get_sentry_resource` on the issue for its stack, tags and
   context. A report with no event behind it usually points at a UX or data
   problem, not a throw, which narrows the search.
2. **Resolve each release to a commit.** Read the release string as
   `sentry.release_format` says, then, after `git fetch origin`,
   `git merge-base --is-ancestor <commit> origin/<base>; echo $?`, where
   `<base>` is `integration.base`, else `main`: 0 is shipped, 1 is not, and
   anything else (a commit this clone does not have) is unknown, never "not
   shipped". When the fetch failed, a 1 is unknown too: the base may be stale. A report can come from a tab still running a bundle older than
   the fix.
3. **Level is not severity.** Before calling an `info` or `warning` event
   noise, read its capture site. A high-volume issue with a fixed fingerprint
   is often a measurement, such as a session outcome that serves as a
   denominator. Count as failures only the failure-tagged events the
   `## Sentry` section names, and quote them as "N of M", never as a bare
   event count.
4. **A zero is a result only once delivery is proven.** Run
   `find_dropped_events` for the window before reading silence as health.
   Then say whether low volume may only mean low traffic.
5. **Deduplicate before counting.** One user hitting one failure can raise
   several events and several issues, and a user can retry. Group by trace or
   correlation id, and say "one user, one failure".
6. **Locate the code, then stop at the evidence.** Find the frames with the
   repo's search tool. When the cause is still ambiguous, say what
   instrumentation would settle it, rather than guess.

## Weekly report

When `sentry.evidence_command` is set, run it first and use its output in
place of deriving releases by hand. Then pull the window, the unresolved
issues by frequency, and the dropped-events check. The report has:

- **Window and volume**, with the dropped-events result stated.
- **Releases seen**, each resolved to a commit and marked on or not on the
  base branch.
- **Incidents**, deduplicated: what failed, for how many of how many, and
  what the data cannot say.
- **Carried items.** Every item of the previous report gets exactly one
  verdict: **Fixed** (the commit, and a release in the window that carries
  it), **Still open** (the search that shows it), or **Unverifiable** (the
  signal that is missing).
- **Stale unresolved issues** (no events in the window), listed, not resolved.

Every sentence about the state of the code names a commit. Before recommending
that a signal be removed, search for what reads it and name the consumers.

Write it to `sentry.report_dir` when set; otherwise ask where. The `## Sentry`
section may add this repo's own layout on top.

## Do not

- Mutate issues or set up alerts unasked.
- Read an `info` event as noise before reading its capture site.
- Call a window healthy before the dropped-events check.
- Put user identifiers, locations or other personal data into anything
  committed, or filed where `tracker.public` is true.
