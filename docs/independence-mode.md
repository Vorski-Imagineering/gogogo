# Independence: which decisions Claude asks about, and which it takes

`independence` is a repo setting. It says how much Claude decides on its own
while it specs and builds your issues, and how much it brings to you. It has
three levels, each named after the colleague Claude then behaves like:

| Level | Claude asks you about | Claude decides, and tells you |
|---|---|---|
| `junior-dev` | approvals, product, engineering | nothing |
| `senior-dev` | approvals, product | engineering |
| `architect` | approvals | product, engineering |

- A **junior dev** checks every choice with you before making it. This is the
  default, and it is how gogogo has always worked.
- A **senior dev** decides how things are built, and checks with you on
  anything people will see.
- An **architect** decides how things are built and what they do, and comes
  to you only for approvals.

## The three kinds of decision

Every choice Claude meets while speccing or building falls into one of three
kinds. The kind comes from what the choice changes, never from how sure Claude
feels about it.

| Kind | What it is | Examples |
|---|---|---|
| **Approval** | Anything on the repo's list of things to ask before changing (its Hard Stops), and applying a change to a shared environment such as production | Adding a profile setting; a script that starts refusing an action it used to allow; turning on branch rules for `main` |
| **Product** | Changes what a person sees, gets or has to do: on the board, in the tracker, in a report, or in the product itself | Pull requests stop appearing as board cards; an unattended run takes over a branch someone else started; a skipped card moves to the needs-a-person column |
| **Engineering** | How it is built, where a later change could undo it without anyone noticing a difference | Which pattern finds an issue number in a branch name; which exit code a refusal uses; whether a check reads a comment or takes a flag |

When a choice could be read as two kinds, it counts as the kind that asks
more.

## What stays the same at every level

- **Approvals are always asked.** No level lets Claude approve its own change
  to anything on the repo's ask-before-changing list, or apply a change to a
  shared environment.
- **What Claude decides is written down.** In a spec, each decision Claude
  took goes under *Decided without asking* in the issue, with its reason. The
  reply ends with a short list of them, so you can overturn any one. An
  unattended run lists its decisions in its report on the issue.
- **Questions are put in plain words.** Each question opens with the real
  case in one sentence, and each option says what changes for people. A
  question does not name files, flags or exit codes.
- **A `senior-dev` or `architect` asks at most one round of questions per
  issue.** When you answer against Claude's recommendation, Claude works out
  what follows from your answer itself, rather than asking another round.

## Unattended runs

`/gogogo:dev` and `/gogogo:auto-dev` read the same setting. A run stops an
issue and hands it to a person only for a decision its level asks about that
the issue does not already settle:

| Level | A run stops for |
|---|---|
| `junior-dev`, `senior-dev` | an approval, or a product decision, that the issue does not settle |
| `architect` | an approval the issue does not settle |

A run always takes engineering decisions within the spec itself, at every
level, as it does today.

## Setting it

The setting lives in the repo's profile, `.agents/dev-process.md`, which is
committed with the rest of the repo, so everyone working in the repo gets the
same level:

```toml
independence = "senior-dev"
```

`/gogogo:setup` shows the current level and asks the person running it which
level they want, explaining the three in plain words. It writes the answer to
the profile, like any other setup change. A profile without the setting works
as `junior-dev`.

Which level suits whom:

- **`junior-dev`** suits a repo that is new to gogogo, or new to the person
  running it, while they learn what Claude decides well. It also suits a
  product where nearly every choice is visible to customers, or a team that
  wants every choice reviewed.
- **`senior-dev`** suits most repos once the owner trusts how Claude builds
  things. The owner is asked about what people will see, and gets the
  engineering choices as a short list to skim.
- **`architect`** suits a repo whose product direction is already settled in
  its issues, a stream of small, well-understood changes, or an owner who
  mostly wants to approve risky changes and review results afterwards. It
  interrupts least, and puts the most weight on the list of decisions Claude
  took.

## Which model to run

`senior-dev` and `architect` need the judgement to take decisions a person
used to take. They also need to tell a product choice from an engineering one,
and a misjudged kind is the mistake a less capable model makes more often. Run
them on an Opus-class model or better, at medium effort or higher.
`junior-dev` asks about everything, so it carries no such recommendation.

`/gogogo:setup` says this when it asks which level the repo wants. When
`/gogogo:spec`, `/gogogo:dev` or `/gogogo:auto-dev` starts at one of those
levels on a smaller model, it says so in one line and carries on. Effort is
not visible to a skill, so it is a recommendation only.

## Why it works this way

**Autonomy is a design choice, set in levels by the human's role.** The
Knight First Amendment Institute's *Levels of Autonomy for AI Agents* names
five levels by the role the user plays: operator, collaborator, consultant,
approver and observer. It treats the level as a choice made when designing the
system, separate from how capable the agent is. `junior-dev` is close to its
consultant level, and `architect` to its approver level. There is no observer
level here, because approvals always stay with a person.

**The rule for what to ask belongs to the process, not to the agent's
judgement.** "If the AI gets to decide whether its own action needs approval,
a sufficiently persuasive prompt can talk it out of asking"; the gate should
fire "based on what the action is". That is why the levels name kinds of
decision rather than "ask when unsure", and why approvals cannot be
delegated.

**Grade decisions by how easy a mistake is to undo.** A common scheme makes
trivial decisions and logs them. It makes low-stakes ones and then reports
them, with an easy undo. It previews and approves high-stakes ones first, and
prevents irreversible ones or has a second person check them. Asking about
trivial things "just train[s] rubber-stamping". *Act or Escalate?* models the
same factors: how unsure the agent is, what a mistake costs, and whether it
can be undone. Engineering choices that a later change can undo sit in the
"make it and report it" grade. That is what *Decided without asking*
provides.

**Constant approval creates friction without much safety.** Anthropic found
that on complex tasks Claude Code stops to ask more than twice as often as
people choose to interrupt it, and that experienced users give it more
autonomy over time. It warns that rules "requiring humans to approve every
action, will create friction". What matters is that people are "in a position
to effectively monitor and intervene", which the written list of decisions
gives them.

**Teams agree the level per kind of decision in advance.** Management 3.0's
seven levels of delegation run from *tell*, where the leader decides, to
*delegate*. A delegation board records which level applies to each kind of
decision, so nobody has to ask each time. The `independence` setting is a
delegation board with three columns.

## Sources

- Feng, McDonald and Zhang, *Levels of Autonomy for AI Agents*, Knight First
  Amendment Institute, 2025:
  [paper](https://arxiv.org/abs/2506.12469v1),
  [summary](https://knightcolumbia.org/content/levels-of-autonomy-for-ai-agents-1)
- Arthur, [*Human-in-the-Loop Governance for AI Agents*](https://www.arthur.ai/column/human-in-the-loop-governance-for-ai-agents)
- [*When Should an AI Agent Ask for Human Approval?*](https://dev.to/brennhill/when-should-an-ai-agent-ask-for-human-approval-5a16), DEV Community
- [*Act or Escalate? Evaluating Escalation Behavior in Automation with Language Models*](https://arxiv.org/pdf/2604.08588)
- Anthropic, [*Measuring AI agent autonomy in practice*](https://www.anthropic.com/research/measuring-agent-autonomy), February 2026
- Management 3.0, [*Delegation and the seven levels of delegation*](https://management30.com/empower-teams/delegation-empowerment/)

All read on 2026-10-03.
