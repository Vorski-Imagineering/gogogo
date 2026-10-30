# /gogogo:auto-dev: 4. Waiting for a review with no goal active

Part of `/gogogo:auto-dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

1. **When.** No goal is active, and the review command returned saying it runs
   in the background. A review that returns its findings in the same turn needs
   none of this. These are Claude Code's own files, read here because it gives
   a forked skill no other handle.
2. **Before each review round and each restart**, `touch <scratch>/review-start`, then start the
   review, then print
   `Waiting on the review (started <HH:MM>); the run resumes when it reports.`
   and go on in the same turn.
3. **Find the review**, repeated every 15 seconds for at most 2 minutes:

```bash
d="$(ls -d "$HOME"/.claude/projects/*/"$CLAUDE_CODE_SESSION_ID"/subagents 2>/dev/null | head -1)"
f="$(find "$d" -name 'agent-*.forked-skill.json' -newer <scratch>/review-start 2>/dev/null | head -1)"
echo "${f%.forked-skill.json}"
```

   The printed `<agent>` is the review. `<agent>.meta.json` is its state and
   `<agent>.jsonl` its transcript.
4. **Nothing found after 2 minutes, no `<agent>.meta.json` by then**, or
   `$CLAUDE_CODE_SESSION_ID` unset: the issue stops for a person
   (`/gogogo:dev` §8) with reason `review`, and its
   `**Needs you:**` line says the review's state file was not found, so the
   plugin may need updating for this Claude Code version. The run goes on with
   the next issue.
5. **Wait**, one foreground command at a time, under the shell tool's limit:

```bash
sh -c 'n=0; while [ $n -lt 36 ] && ! grep -Eq "\"finished\": *true" "<agent>.meta.json"; do sleep 15; n=$((n+1)); done'; grep -Eq '"finished": *true' "<agent>.meta.json" && echo finished || echo waiting
```

   Repeat until it says `finished`. After each `waiting`, apply `/gogogo:dev`
   §5 rule 9, the silent-review check, to `<agent>.jsonl`'s last write time.
6. **Read the result**, the last assistant text in the transcript:

```bash
python3 - "<agent>.jsonl" <<'EOF'
import json, sys
for line in reversed(open(sys.argv[1], encoding="utf-8").read().splitlines()):
    message = json.loads(line).get("message") or {}
    if message.get("role") != "assistant":
        continue
    text = [c["text"] for c in message.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"]
    if text:
        print("\n".join(text))
        break
EOF
```

   Empty output is not a clean review: the issue stops as rule 4 says, and its
   `**Needs you:**` line says the review finished with no result.
7. **The notice.** A task notification for a review already read is ignored.
   Findings are applied once.
