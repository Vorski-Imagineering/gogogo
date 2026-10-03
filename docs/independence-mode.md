# Independence: which decisions the agent asks about, and which it takes

A proposal for [#90](https://github.com/Vorski-Imagineering/gogogo/issues/90).
It is not built yet. It sets out the problem, what others have written about
it, the modes it could offer, and who each mode suits, so the owner can pick
before the spec is written.

Written 2026-10-03.

## The problem

Today `/gogogo:spec` sends every product decision to the person, and keeps
asking in rounds until no open choice is left
(`plugins/gogogo/skills/spec/SKILL.md`, § *Approvals* and § *Ask in rounds
until no forks remain*). The only line between "ask" and "decide" is the
repo's list of things to ask before changing (its Hard Stops, `CLAUDE.md`).
In this repo almost every change to a skill or a script is on that list, so
almost every choice in a spec becomes a question.

On 2026-10-03 that cost the owner these questions:

| Issue | Questions |
|---|---|
| #57 | 4 |
| #63 | 1 |
| #83 | 3 |
| #84 | 4 |
| #85 | 4 |
| #86 | 10, in three rounds; the third was declined |

Most were about how something is built, not what it does. The owner took the
recommended option on almost every one, and said so: "I feel you are asking me
a long list of questions which I don't understand, and don't understand if are
important enough for me to want to understand."

Unattended runs (`/gogogo:dev`, `/gogogo:auto-dev`) have the same problem in
another form. They stop an issue and hand it to a person when they meet "a
decision that belongs to a person and is not in the body"
(`plugins/gogogo/skills/dev/SKILL.md` §4, `auto-dev/SKILL.md` §2). Nothing says
which decisions those are.

## What others have found

- **Autonomy is a design choice, set in levels by the human's role.** The
  Knight First Amendment Institute's
  [*Levels of Autonomy for AI Agents*](https://arxiv.org/abs/2506.12469v1)
  (2025;
  [summary](https://knightcolumbia.org/content/levels-of-autonomy-for-ai-agents-1))
  describes five levels: the user as **operator** (decides everything),
  **collaborator** (plans together), **consultant** (the agent leads but asks
  for input), **approver** (the agent asks only "in risky or pre-specified
  scenarios") and **observer** (full autonomy, with the human watching and
  able to step in). The paper treats the level as something you choose,
  separate from how capable the agent is.
- **The rule for what to ask lives in the workflow, not in the agent's
  judgement.** "If the AI gets to decide whether its own action needs
  approval, a sufficiently persuasive prompt can talk it out of asking"; the
  gate should fire "based on what the action is"
  ([Arthur, *Human-in-the-Loop Governance for AI Agents*](https://www.arthur.ai/column/human-in-the-loop-governance-for-ai-agents)).
  So a setting should name **kinds** of decision, not "ask when unsure".
- **Grade by how easy a mistake is to undo.** One practical scheme has four
  grades. Trivial decisions are made and logged. Low-stakes ones are made, then
  you are told, with an easy undo. High-stakes ones are previewed and approved
  first. Irreversible ones are prevented by design or need a second person.
  Asking about trivial things "just train[s] rubber-stamping"
  ([*When should an AI agent ask for human approval?*](https://dev.to/brennhill/when-should-an-ai-agent-ask-for-human-approval-5a16)).
  [*Act or Escalate?*](https://arxiv.org/pdf/2604.08588) models the same three
  things: how unsure the agent is, what a mistake costs, and whether it can be
  undone. Cheap, reversible decisions should be made even at moderate
  confidence.
- **Constant approval creates friction without much safety.** Anthropic's
  [*Measuring AI agent autonomy in practice*](https://www.anthropic.com/research/measuring-agent-autonomy)
  (February 2026) found that on complex tasks Claude Code stops to ask more
  than twice as often as people choose to interrupt it, and that experienced
  users grant it more autonomy over time. It warns that rules "requiring
  humans to approve every action, will create friction". What matters is that
  people are "in a position to effectively monitor and intervene".
- **Teams solved this long ago by agreeing the level per kind of decision.**
  Management 3.0's
  [seven levels of delegation](https://management30.com/empower-teams/delegation-empowerment/)
  run from *tell* (the leader decides) through *consult* and *advise* to
  *delegate*. A *delegation board* records, for each kind of decision, which
  level applies, so nobody has to ask each time.

## Three kinds of decision

Every choice a spec or a run meets falls into one of three kinds. The kind is
decided by what the choice changes, never by how confident the agent feels.

| Kind | What it is | Examples from 2026-10-03 |
|---|---|---|
| **Approval** | Anything on the repo's ask-before-changing list (its Hard Stops), and applying a change to a shared environment | Adding a new profile setting; a script that starts refusing a board move; turning on branch rules for `main` |
| **Product** | Changes what a person sees, gets, or has to do: on the board, in the tracker, in a report, in the product itself | Pull requests stop appearing as cards (#85); auto-dev takes over an existing PR's branch (#86); a skipped card moves to Human!Help! (#63) |
| **Engineering** | How it is built, where a later pull request could undo it without anyone noticing a difference | Which pattern finds an issue number in a branch name; which exit code a refusal uses; whether a check reads a comment or takes a flag; the order of two issues that touch the same file |

When a choice could be read as two kinds, it counts as the one that asks more.
Approval is never decided by the agent, whatever the mode.

## The modes

One setting per repo picks which kinds are asked. Each mode is named after the
colleague the agent then behaves like, the way the Knight paper names its
levels by role. Whatever is not asked, the agent decides. It writes the decision into the issue as **Decided without
asking**, with its reason and the evidence. It also lists those decisions in
two or three lines at the end of its reply, so you can overturn any of them.
This is the "do it, then tell you, with an easy undo" grade from the research.

| Mode | Approvals | Product | Engineering | In the Knight levels |
|---|---|---|---|---|
| `junior-dev` | asked | asked | asked | consultant |
| `senior-dev` | asked | asked | decided and listed | between consultant and approver |
| `architect` | asked | decided and listed | decided and listed | approver |

- A **junior dev** checks every choice with you before making it.
- A **senior dev** decides how things are built, and checks with you on
  anything people will see.
- An **architect** decides how things are built and what they do, and comes
  to you only for approvals.

In every mode:

- the repo's ask-before-changing list is always asked, and so is applying a
  change to a shared environment;
- at most one round of questions per issue, except as a `junior-dev`;
- each question opens with the real case in one plain sentence, and each
  option says what changes for people. Questions do not name files, flags or
  exit codes;
- when the person answers against the agent's recommendation, the agent works
  out what follows from that answer itself, rather than opening a new round;
- the same test decides when an unattended run stops an issue: it stops only
  for a kind its mode asks about, and writes every decision it took in its
  report on the issue.

There is no fully hands-off mode. Approvals stay with a person in every mode,
because the research is clear that irreversible and high-stakes actions need a
gate a prompt cannot argue away.

## Who each mode suits

- **`junior-dev`**: a repo that is new to gogogo, or new to the person running
  it, while they learn what the agent decides well. It also suits a product
  where nearly every choice is visible to customers, or a team that wants
  every choice reviewed. It is today's behaviour.
- **`senior-dev`**: most repos, once the owner trusts how the agent builds
  things. It suits an owner who cares what the product does but not how. The
  owner is asked about what people will see, and engineering choices arrive
  as a short list to skim. This matches what this repo's owner asked for in
  #90.
- **`architect`**: a repo whose product choices are already settled in its
  issues and specs, or a stream of small, well-understood changes, or an owner
  who mostly wants to approve risky changes and review results afterwards. It
  gives the fewest interruptions and puts the most weight on the
  end-of-spec list.

## Open choices

The owner has decided that each repo picks its own mode (a setting, not one
rule for all), and that unattended runs follow the same test as speccing.
Still to pick:

1. **What a repo gets when it has not set the mode.** `senior-dev` would make
   every adopting repo quieter on its next plugin update. `junior-dev` would keep
   today's behaviour until each repo opts in, and `/gogogo:setup` would offer
   to set it.
2. **Levels or a list.** The three modes above are fixed levels. The other
   shape is a list of kinds the agent may decide (`["engineering"]`), which is
   more flexible but harder to explain, and adding a new kind would change the
   profile format.
3. **The setting's name.** `independence` is the working name; its values are
   the three role names above.

Adding the setting is a change to the profile format, and it changes what the
spec, dev and auto-dev skills do in every adopting repo. Both are on this
repo's ask-before-changing list, so the pick above is also the approval to
build it.
