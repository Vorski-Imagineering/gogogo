# Where gogogo came from

## Where it came from

Since early 2026 we have been building several products of our own: a Django
web app, a React and Firebase app, a WebGL game and a Cloudflare Workers app.
Claude Code agents do most of the development. They write specs into issues,
build from those specs, and work the queue unattended while we sleep.

That only works if the process around the agent is tight. A vague issue gives a
confident wrong change. A green test suite is not the same as a fix that works
on real data. An unattended loop that guesses at a rule it should have asked
about does damage nobody sees until morning.

## What went wrong

Each product grew its own copy of the spec skill and of the auto-dev loop, and
each copy was forked by hand from another. Fixes landed in one copy and never
reached the others. A bug that silently truncated the queue, for example, was
fixed twice, in two repos, in two different ways.

What differed between the copies was always the same short list: the tracker,
the Hard Stop rules, the test commands, where a fix is checked, and how code
merges. Everything else had been copied and was drifting.

## What we did

In September 2026 we pulled the part that was the same everywhere into one
plugin, `gogogo`, and moved what differs into one profile file per repo,
`.agents/dev-process.md`. Steps that must not depend on a model's mood, such as
moving cards, checking that a merge landed, and checking a spec, became small
scripts. We piloted it on two of the products, and this repo now runs its own
queue with it.

## What we kept from the forks

The rules that earned their place, each in a sentence:

- The spec lives in the issue body, and a comment never counts as sign-off.
- An Approvals table records every decision a person made, and it is what
  licenses a risky change.
- Hard Stops: a short list of changes an agent must ask about, never decide.
- A new test is seen failing before it is trusted.
- "Done" means run on real data, not a green suite.
- The loop gives up properly: it reports and moves on rather than retrying
  blind.
- A human moves the card to Done.

## Why it is public

We want to share the process easily, and a plugin anyone can install is the
easiest way. The profile is what makes it fit someone else's stack: you write
down your tracker, your Hard Stops, your test commands and how you ship, and
the same skills do the rest.
