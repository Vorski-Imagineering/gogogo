# Test rules that hold in every lane

Reference for the `## Test cases` section of a spec. Which lanes exist, what
each must specify, and the constraints that force the design are in the
profile (`lanes` and `## Lane constraints`); read both.

For every lane the profile lists, name real cases or give a reason for skipping
it. For each case: the input, the expected result, **and the regression it
guards**.

When a lane reads a page, it reads back real content: text, an attribute, an
element's presence or absence. A screenshot is never an assertion. Nobody diffs
it and it passes forever.

## "No evidence" must fail, not pass

A check that goes green when nothing was measured stops anyone looking, which is
worse than no check. If a run can produce zero observations, that state is a
FAIL. Carry the floor in the evidence (a count of observations actually taken)
so "we watched 60 times and never saw it" is distinguishable from "we never
looked".

## Include a step that proves the test fails

Pin the value to a constant or revert the fix, re-run, name **which** tests must
go red, then restore. A suite never seen red is not verified. Write the pins
into the spec; do not leave it as "confirm the tests are meaningful".

## What a second reader sees needs a test from a second reader

Say it loudly when it applies. If the bug is that a change never reaches
anyone but the actor (a signal that never leaves one browser, a write that
never lands where a later request reads it), a test that only re-reads what the
actor itself just wrote **passes against the broken code**. The assertion has
to be made from the other side: another participant, a fresh session, a
different user, or the endpoint that renders the data back from scratch.

## A lane you call impossible costs the same proof as a lane you write

An impossibility claim is a claim. Name the *missing capability* and where it
would live (a missing fixture, a missing emulator, infrastructure the project
deliberately does not run), or you are excusing a lane you did not investigate.

Stating it that way turns a dead end into a named gap someone can close. It
also shows when closing the gap is a Hard Stop of its own, to be raised rather
than slipped into the current issue.
