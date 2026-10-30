# /gogogo:spec: how an approval question is asked

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
7. **A sign-off or a go/no-go.** The question is a sign-off only when the
   person has decided the feature, in their own words on record: in this
   session, or in the issue's report as their own request to build it. An
   agent-filed follow-up is not, and neither is a report saying a person
   agreed to file it. A change that adds run time is never a sign-off: the
   time is the decision. Nor is a two-licence change: what it does to a shared
   environment is. Anything else is a go/no-go, with "don't approve"
   as a choice, and rules 8 to 10 do not apply.
8. **The sign-off's opening and choices.** It opens: "Formal sign-off this
   repo's rules require, not whether to build <the feature>." Then the
   decided design, then the edge cases as above. The first choice approves.
   The second is "Post the spec first, I'll approve after reading". A third
   may offer a real alternative in the design. None offers not building;
   a person can still type that.
9. **Post first.** Its row's Chosen says "Post first, not approved yet". The
   verdict is the proposal form, the item's Why cell does not use the word
   "row", and `Not approved:` names the item. Posting then withholds the
   label and leaves the card. When the card is already in the queue, a run
   hands it back to a person, since no row approves it, and the reply says so.
   The reply says to run `/gogogo:spec <N>` after
   reading.
10. **The return.** `/gogogo:spec <N>` on an issue whose verdict is a
    proposal from rule 9 asks only the sign-off of rule 8, with "Not yet, keep
    it as a proposal" as its second choice, and this is not another question
    round. Read the body again first, and show the person anything changed
    since it was posted. On approval: add a row, make the verdict `approved`
    citing it, take the item off `Not approved:` (`none` when it was the only
    one), correct the spec as Posting says, then run Posting steps 8 and 9. A
    change the person asks for is made, and rule 7 decides the next question
    afresh. A typed "don't build" is recorded as a row, the proposal stands,
    and a later return is a go/no-go. On anything else the proposal stands and
    nothing moves.
