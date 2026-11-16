#!/bin/sh
# Is this Claude Code session in bypassPermissions mode?
#
# An unattended run that merges must not reach the merge and then stall on a
# permission prompt, with finished work stranded on a branch. Nothing in the
# environment exposes the mode, so this reads the last `permissionMode` from
# the session's own transcript, found by the session id under any folder of
# ~/.claude/projects (the session may have started in another folder than the
# one this runs from, such as a worktree). That is an undocumented format, so
# it FAILS CLOSED: a missing transcript, a second transcript with the same id,
# a missing field, or any other value is a stop, with two exceptions that read
# how this Claude process was started instead:
# - no transcript at all: a headless run (claude -p) started with a bypass
#   flag passes;
# - a transcript with no permissionMode: any Claude process started with a
#   bypass flag passes, interactive or background, since the transcript
#   records the mode only when it changes. A recorded mode always wins.
#
# Exit 0 prints "bypassPermissions: on". Anything else prints ERROR and exits 1.
set -u

started_in_bypass() {
  # $1 is `headless` or `any`. Fall back to how this Claude process was
  # started: walk up the process tree and accept only an explicit bypass flag.
  # `headless` also needs -p/--print: a headless run cannot change mode
  # mid-session, so its start flag is its mode. `any` is for a transcript with
  # no recorded mode: the mode is recorded only when it changes, so with no
  # record it has not changed since launch.
  need=$1
  pid=$$
  i=0
  while [ "$pid" -gt 1 ] && [ $i -lt 8 ]; do
    comm=$(ps -o comm= -p "$pid" 2>/dev/null) || return 1
    args=""
    # Only a process that is Claude Code itself counts; a shell whose command
    # text merely mentions the flag must not.
    case "${comm##*/}" in claude) args=$(ps -o args= -p "$pid" 2>/dev/null) ;; esac
    case "$args" in
      *claude*--dangerously-skip-permissions*|*claude*--permission-mode\ bypassPermissions*|*claude*--permission-mode=bypassPermissions*)
        [ "$need" = any ] && return 0
        case "$args" in *" -p "*|*" --print "*|*" -p") return 0 ;; esac ;;
    esac
    pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ') || return 1
    i=$((i + 1))
  done
  return 1
}


fail() {
  echo "ERROR: $1" >&2
  echo "An unattended run needs bypassPermissions mode to merge." >&2
  echo "In a running session, switch the mode once with Shift+Tab (out of bypass and back) so it is recorded, then run again." >&2
  echo "A background job that cannot switch modes is restarted with --permission-mode bypassPermissions." >&2
  echo "A repo can replace this check with integration.mode_check in its profile." >&2
  exit 1
}

[ -n "${CLAUDE_CODE_SESSION_ID:-}" ] || fail "CLAUDE_CODE_SESSION_ID is not set; cannot find the session transcript."
projects="$HOME/.claude/projects"
transcript=""
count=0
for f in "$projects"/*/"$CLAUDE_CODE_SESSION_ID".jsonl; do
  [ -r "$f" ] || continue
  transcript=$f
  count=$((count + 1))
done
if [ "$count" -eq 0 ] && started_in_bypass headless; then
  echo "bypassPermissions: on (headless run started with a bypass flag)"; exit 0
fi
[ "$count" -gt 0 ] || fail "no session transcript named $CLAUDE_CODE_SESSION_ID.jsonl under $projects."
[ "$count" -eq 1 ] || fail "$count session transcripts named $CLAUDE_CODE_SESSION_ID.jsonl under $projects; cannot tell which is this session's."
mode=$(grep -o '"permissionMode":"[^"]*"' "$transcript" | tail -1 | cut -d'"' -f4)
if [ -z "$mode" ]; then
  started_in_bypass any && { echo "bypassPermissions: on (started with a bypass flag; no mode change recorded)"; exit 0; }
  fail "no permissionMode recorded in the session transcript, and this Claude process was not started with a bypass flag; cannot tell the mode."
fi
[ "$mode" = "bypassPermissions" ] || fail "permission mode is '$mode', not 'bypassPermissions'."
echo "bypassPermissions: on"
