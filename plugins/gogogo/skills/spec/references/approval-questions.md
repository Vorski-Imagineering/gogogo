# /gogogo:spec: an approval question lists its edge cases

Part of `/gogogo:spec`. Read it in full. Section names and § numbers here are `SKILL.md`'s.

A person who approves only the change as described is surprised later by what
it does at its edges, or by what it leaves as it was. The question says both
before they answer.

1. **When.** A question that asks for an approval: a Hard Stop row, or the
   apply row of a two-licence change. Product and engineering questions, and
   the menu after a declined question, carry no list.
2. **The shape.** Under the recommendation, a list headed `Edge cases:`, one
   line per case:

   `<what happens> — <how the design handles it> — stays unfixed: <what is left, or "nothing">`

3. **At most four lines.** Keep the four most able to surprise a person who
   approved only the described change. List the rest in the issue's
   `## Context`.
4. **No real edge case.** One line: `Edge cases: none found (<what was checked>)`.
5. **Plain words.** Like the rest of the question: no file names, flags or exit
   codes. Each line reads as something that could happen to a person using the
   repo.
6. **In the issue too.** The same list goes into that Approvals row's question
   cell, so what stays unfixed is in the issue body and not only in the chat.
   A table row is one line: write it there as `Edge cases: <case>; <case>`,
   with no line break and no `|`.
