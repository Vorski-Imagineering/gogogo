# /gogogo:spec: reading a spec's items against each other

Part of `/gogogo:spec`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

The pre-post check, question 1: two items that cannot both hold. In order:

1. **When.** At the pre-post check, on the final draft, before Posting. Save
   the draft spec (the sections from `## Verify by hand` on) to
   `<scratch>/draft-<N>.md` and run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_check.py" items <scratch>/draft-<N>.md`.
2. **Who reads.** A fresh agent with no memory of this session, not a fork.
   It is given three things and nothing else: the draft file, the item list,
   and the paths under `## Files`, which it may open. It edits nothing,
   posts nothing, and asks nothing.
3. **What it looks for**, and nothing else: two `V`, `D`, `T` or `A` items
   that cannot both hold; a `D` item that needs a Hard Stop item the spec
   answers `no`, or one no Approvals row approves; a `T` case that
   contradicts a `D` item.
4. **What it returns.** One line per pair,
   `<idA> | <idB> | <certain|possible> | <why> | <question>`, or the single
   line `none`. *Certain*: it follows from the two items' own words, with no
   assumption about a device, timing, data or environment. *Possible*: it
   needs such an assumption, which `<why>` names. `<question>` is the choice
   to put to a person, in plain words.
5. **What is done with each pair.** It is a fork (§ *Who decides*): decided
   and listed under *Decided without asking* with its reason when the level
   decides its kind, asked when it asks. It may be asked in one question
   beyond the level's one round. The spec is then corrected so the pair
   holds, and the read is not run again.
6. **No reader.** When no fresh agent can be started, say so in the reply
   after posting, and read the pairs yourself by rules 3 and 4.
7. **Claude.** The fresh agent is an `Agent` call with a general-purpose
   agent, never `subagent_type: "fork"`.
