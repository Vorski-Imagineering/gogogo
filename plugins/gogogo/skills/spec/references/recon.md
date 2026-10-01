# Recon: finding the blocker, and what to distrust

Reference for `## Context`. Recon ends by listing the traps you found. A spec
whose Context contains no traps usually means nobody looked.

This file holds the method. What this particular codebase hides is in the
profile's `## Recon traps`; read both.

## Hunt for data already on the wire before proposing new state

Highest-leverage step, most skipped, because the ticket's framing points
elsewhere. Grep for the **field**, not the feature. Ask: what does the system
already store, send or render that is *implied* by the thing I want to show?

A feature that looks like it needs new shared state often collapses to one
derived predicate over values that are already written and already read
everywhere. When it does, a change that would have been a Hard Stop becomes one
that needs no approval at all.

Check the repo's placement rule (`design.placement_rule` in the profile) before
proposing where new state lives. Proposing it in the wrong layer or folder is
itself a trap: it either duplicates something the right place already has, or
it breaks the direction dependencies are allowed to point.

The reverse is also worth stating: if you *cannot* find it, say so explicitly.
"Every Hard Stop item is no" is a real finding, and it is what tells the
implementing agent not to stop and ask.

## Distrust what looks live

General shapes. The profile's table has this codebase's own instances and the
check for each.

| Trap | How it bites |
|---|---|
| **Dead code that looks like the path** | You spec against a file or view that nothing routes to or imports. |
| **Validation that exists on one side only** | The spec claims "the server rejects X" when only the client does. Read the enforcing layer before any "enforced" claim. |
| **A value that looks like code but is data** | The label the reporter quotes is user-editable content, and no string in the tree matches it. |
| **A write that silently overwrites** | A blind write to a shared record destroys someone else's. Find who else writes the same place. |
| **A reader with no writer, or a writer with no reader** | Removing one half orphans the other. |

## Hunt non-atomic transitions

Any place two writes represent one logical change is a visible transient and a
flaky test. Found ones need a **decided mitigation that is an input to the
logic under test**, so a test covers it. A comment saying "watch out" is not a
mitigation.

Two common shapes:

- **Two writes for one edit.** A reader between them sees a half-applied
  change. Mitigation: make it one write, or one transaction, or give the
  decision an explicit "in between" input.
- **"Write the record, then render the list."** If the list renders before the
  write lands, the user acts on stale emptiness and creates a duplicate.
  Mitigation: render from the same operation that did the write, or carry an
  in-flight flag that suppresses the empty state.

## Correct the ticket where it is wrong

Tickets state wrong details confidently. Reporters describe what they *saw*, in
their own words; the words in the title are rarely the string in the codebase.
Implemented literally, a wrong sentence puts the change on the wrong element.

State the correction in the spec, design the correct behaviour, and say so in
your reply to the user. Do not spec a sentence you know to be wrong, and do not
silently drop it either.
