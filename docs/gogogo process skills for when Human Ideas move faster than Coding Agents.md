# gogogo: process skills for when Human Ideas Move Faster Than Coding Agents
Victor Vorski 1 Oct 2026

For the last eight months I have been building software with coding agents across several products. At this point, the interesting problem is no longer whether an agent can write competent code. Given a coherent task, enough repository context and decent tooling, it usually can.

The problem is that I think faster than it can implement.

That sounds like a luxurious problem until you try to work this way for more than an afternoon.

I will be thinking about one feature and see three adjacent ideas, an architectural implication, a simplification somewhere else in the system and a completely different feature that becomes possible if the first one works. Ten minutes later I have six threads in my head.

The obvious thing to do is tell the agent all six.

This is a mistake.

Give a coding agent six partially related ideas and its context starts to blur. It tries to reconcile things that were never meant to be reconciled. A speculative architectural thought gets treated as an implementation requirement. An idea for a future feature leaks into the current one. Scope expands without anybody explicitly deciding that it should.

The agent has not become less intelligent. I have given it a bad cognitive environment.

Humans suffer from the opposite version of the same problem. If I am thinking about the shape of a system and the agent interrupts to ask whether a database field should be nullable, whether a test fixture needs updating or which branch it should be working on, I lose the thread I was following.

Ask the agent to think about six things at once and it gets stupid.

Ask me to think about implementation trivia while I am designing and I get stupid too.

That observation sits at the center of **gogogo**, an open-source development process I have extracted from the way I now work with coding agents.

The project began as a collection of increasingly elaborate repository instructions. Then those instructions spread across projects. Then they diverged. Then I found myself fixing the same process problem in several places, which is the software equivalent of discovering that your copy-paste habit has quietly become an architecture.

Eventually I pulled the process out into its own project.

The result is less interesting as a Claude Code plugin than as an attempt to solve a broader problem: **how do you preserve human and machine attention when ideas and implementation move at different speeds?**

## The conversation is the wrong unit of work

Most coding-agent workflows still look like extended pair programming.

You explain what you want. The agent starts coding. You remember something and add it. It asks a question. You answer it. Another idea occurs to you. You add that too. The agent finishes a first pass, you inspect it, discover a missing case, send it back, then continue the conversation until the thing works.

For one task, this is excellent.

For five tasks, it starts to hurt.

For several products, it becomes a coordination system held together by your short-term memory.

The problem is not merely interruption. A single conversational thread accumulates several different kinds of information: speculative ideas, settled product decisions, architecture, implementation detail, failed approaches, testing results and future work. Once those categories collapse into the same stream, both human and agent have to keep reconstructing which statements are still authoritative.

A simple example: suppose I am exploring a feature for collaborative notes. While thinking through it, I mention that live cursors could be interesting, that offline mode would be useful, that the data model may eventually need version history and that perhaps comments should become first-class objects.

Those are four ideas. They are not four requirements.

If I send that entire conversation into an implementation agent, I have made the agent responsible for deciding which parts of my thinking were exploratory and which were instructions. That is exactly the kind of decision I do not want it making.

The answer is not “better prompting”. The answer is to stop treating the conversation as the unit of work.

Ideas need an idea space.

Implementation needs an implementation space.

Something explicit has to sit between them.

In gogogo, that something is the spec.

## A spec is a context boundary

I used to think of specifications mainly as communication artefacts. Someone thinks about a feature, writes down what should happen, and another person implements it.

With agents, the role becomes more precise. A good spec is a **context compression mechanism**.

The upstream thinking can be messy. It should be messy. That is where possibilities are compared, contradicted, combined and discarded. Forcing early-stage thinking into implementation-ready form too soon destroys useful ambiguity.

But the implementation agent does not need the entire history of that thinking. It needs the result.

A good spec answers questions such as: what are we actually building, what is outside scope, which decisions are settled, which alternatives were rejected, what existing behaviour must remain unchanged, and how will we know that the implementation works?

That last part matters. “Make collaborative notes better” is not executable. “When two authenticated users edit the same note, changes should synchronize within X conditions while preserving Y existing behaviour” starts to become executable.

The spec is therefore not documentation pasted on top of development. It is the membrane between two cognitive modes.

On one side, ideas are allowed to branch.

On the other, implementation is allowed to narrow.

This is also why rejected options belong in the spec when they matter. If we considered storing state in Redis and rejected it because the feature must work offline, the next agent should not spend twenty minutes rediscovering Redis as an attractive idea. The decision has already been made.

Without that record, an agentic system develops a peculiar form of amnesia: the code remembers the result, but nobody remembers why the result looks that way.

Humans do this too, of course. We just gave the forgetting mechanism a terminal.

## The useful form of autonomy is uninterrupted execution

A lot of discussion around coding-agent autonomy focuses on permissions. Can the agent edit files? Run commands? Open pull requests? Deploy?

Those questions matter, but they are not what changed my workflow.

The useful form of autonomy is **the ability to complete a coherent piece of work without dragging me back into its implementation context**.

Once I have made the important decisions, I want the agent to take the task, understand the repository, create the right branch, implement the feature, run the appropriate tests, inspect failures, fix them, verify the result and hand it back in a state I can assess.

I do not want to know that test number 47 failed because an old fixture used a stale object shape unless that fact changes a product or architectural decision.

That belongs to the agent's attention context, not mine.

Likewise, the agent should not have my entire stream of product thinking poured into its context while it is trying to debug test number 47.

This separation changes the working rhythm.

Instead of:

think → tell agent → wait → answer question → wait → inspect → resume thinking

the workflow becomes closer to:

think → resolve decisions → prepare work → hand off

and later:

inspect evidence → handle exceptions → continue thinking

The difference is not cosmetic. It determines whether several streams of work can happen at once without the human becoming the mutex.

That, for me, is the real promise of coding agents.

Not “code appears faster”.

**Human attention stops being serialized behind implementation.**

## Process should live in the system, not in my head

Once I started separating idea work from execution, a second source of cognitive waste became obvious.

Software engineering contains an absurd amount of procedure.

Create a branch. Use the correct naming convention. Check that the working tree is clean. Link the issue. Run one group of tests before another. Commit. Push. Check CI. Inspect the deployed version. Update the issue. Move it to the correct state. Leave enough information that the next person, or agent, can understand what happened.

None of this is intellectually difficult.

That is precisely why I do not want to spend attention on it.

Git deserves special mention here. It is an extraordinarily powerful tool with the user experience of a device recovered from a Soviet submarine. Developers eventually internalize its rituals, but there is no reason to confuse memorizing those rituals with software engineering ability.

gogogo encodes these processes as skills.

A skill knows the sequence.

Instead of me remembering every procedural step involved in taking a task from specification to completed work, the agent executes the workflow.

That sounds like a minor convenience until you maintain the process across several repositories.

Without a shared skill, every repo accumulates its own instructions. One project says to run tests before pushing. Another adds a deployment check. A third contains the fix for a CI edge case you discovered six weeks ago. Now you have three versions of your development process, and improving one does nothing for the others.

Encoding the process once changes the maintenance model.

If the branch workflow changes, change the skill.

If verification gains a new stage, change the skill.

If you discover that a particular class of deployment failure needs an extra check, add it once.

The knowledge stops living in prompts scattered across projects and becomes executable infrastructure.

I think this is one of the more interesting uses of agent systems. We spend a great deal of time talking about what models know. I care just as much about what processes they can carry.

The difference matters because procedural knowledge consumes human working memory in a particularly irritating way. It is too trivial to deserve attention and too important to skip.

That is exactly the sort of thing machines should inherit from us.

## Give execution to the agent, keep decisions with the human

Separating contexts does not mean handing the entire development process to the machine and going for lunch.

There is still a boundary between execution and judgment.

My rule is simple: **the agent gets autonomy over execution, not autonomy over decisions.**

If a task requires changing authentication behaviour, altering an external contract, migrating production data or making a choice with a significant blast radius, I want the agent to stop.

Not because I expect it to make a catastrophically stupid choice. That has not been the dominant failure mode in my experience.

I want it to stop because those decisions belong to a different context.

They affect product design, system architecture or risk. I want to make them while thinking about those things, not have them quietly emerge as side effects of implementation.

gogogo calls these boundaries Hard Stops.

The agent can discover the need for the change. It can gather the relevant information. It can explain why the current implementation path runs into the boundary. What it cannot do is turn an implementation obstacle into a product decision without making the transition explicit.

This is less about restraining the agent than about protecting the architecture of attention.

The machine should stay deep in execution until execution reaches a decision.

Then the decision comes back to the human.

Once resolved, execution continues.

A clean handoff is more important than constant supervision.

## More context is not better context

A strange assumption has crept into AI tooling: if a model can consume more context, giving it more context must improve the result.

That is false in practice.

The issue is not only context-window size. It is context quality.

A 100,000-token conversation containing five abandoned directions, three future ideas, old requirements, debugging logs and current implementation instructions is not a rich context. It is a landfill.

An agent still has to infer which parts matter now.

Human reasoning has the same constraint. I can sit in front of fifty open browser tabs, four terminals, three half-written documents and a Slack thread containing the answer I need somewhere around message 216. Nothing has technically been lost. Cognitively, the room is on fire.

gogogo's approach is deliberately subtractive.

The implementation agent should get what it needs to solve the current problem, plus enough repository knowledge to avoid breaking the surrounding system.

Not every thought that led to the task.

Not every idea that might follow it.

Not the entire archaeological record of how we arrived here.

This requires discipline upstream because separating thinking from execution means resisting the temptation to send every new idea straight into the coding session.

I am still bad at this.

Agents make implementation cheap enough that the impulse is to build the thought immediately. Sometimes that is exactly right. Sometimes fifteen more minutes of thinking would have deleted the feature entirely.

Cheap execution makes premature implementation more seductive, not less.

## Verification becomes the return channel

Once the agent works without continuous supervision, another question becomes important: what exactly comes back?

Reading the entire implementation history defeats the point.

“The tests passed” is also not enough.

I want evidence that lets me regain context quickly.

What changed? What did the agent verify? Which assumptions did it rely on? Did the code pass CI? Did the deployed feature behave correctly in the actual environment? Is anything unresolved?

This is where verification becomes part of the attention model rather than simply part of testing.

The agent expands a compact spec into a potentially large implementation. The return path needs to compress that work again into evidence.

I do not need to know every command it ran.

I do need to know whether the thing works.

This distinction becomes more important as tasks become longer. If an agent spends three hours implementing something, the quality of the hand-back determines whether those three hours saved me time or merely produced three hours of material I now need to reconstruct.

The goal is not autonomous coding.

The goal is **cheap re-entry into completed work**.

That requires better summaries, stronger verification and clearer evidence than most coding tools currently produce.

## Where gogogo is still incomplete

The current implementation reflects the system I needed while building it. It is not a finished theory of agentic development.

The first area I want to improve is measurement.

If this process actually preserves attention, I should be able to measure that.

How many tasks complete without human interruption? Where do agents stop? How long does it take me to re-enter a task after execution? How many implementations pass real-environment verification on the first attempt? How much model time and money does each type of task consume?

Those numbers matter more to me than lines of code or tickets closed.

A coding agent that produces twice as much code but interrupts me every twelve minutes is not obviously better than one that works more slowly and returns a coherent result two hours later.

The unit worth optimizing is human attention per useful outcome.

The second area is enforcement.

Some boundaries in gogogo are instructions to the agent. That is appropriate for parts of the workflow, but important safety constraints should migrate into infrastructure where possible.

A branch rule enforced by GitHub is stronger than a prompt telling the agent not to push to main.

A deployment permission enforced by the environment is stronger than a sentence saying “do not deploy without approval”.

As the process matures, I want fewer critical guarantees to depend on the model remembering that it was told something.

The third area is proportionality.

A schema migration and a four-pixel spacing change should not travel through identical machinery.

Heavy process on trivial work is not rigor. It is latency wearing a tie.

The workflow needs better task classes so that the amount of specification, verification and approval scales with complexity and blast radius.

And the current implementation is Claude-specific because that is the environment in which I built it. I do not think the underlying process should stay that way.

The durable layer is not Claude.

It is the protocol connecting human thought to machine execution:

ideas become decisions; decisions become bounded work; agents execute; verification produces evidence; unresolved decisions return to the human.

That architecture should survive model changes.

## Why I am sharing it now

gogogo is the distillation of eight months of working this way, not a framework invented on a whiteboard.

Most of its ideas came from irritation.

I got tired of repeating instructions.

I got tired of losing architectural thoughts because an implementation needed attention.

I got tired of feeding half-formed ideas into an agent and watching the boundaries between them dissolve.

I got tired of improving the development process in one repository and realizing that four others still contained the old version.

So the process became a project.

The repo is public because I doubt this is a problem unique to me. Once coding agents become a serious part of software production, the limiting factor shifts. The hard problem stops being “how do I get an AI to produce code?” and becomes “how do I organize thought and execution so that both the human and the machine stay good at what they are doing?”

I expect different people to arrive at different answers.

That is exactly why I want gogogo in the open.

If you are already running coding agents for substantial pieces of development, working across several repositories, experimenting with autonomous issue queues or trying to separate product thinking from implementation, I would like to compare systems.

Try it. Break it. Remove parts you think are unnecessary. Add process where I have missed something. Port it to another agent. Challenge the assumptions. Most importantly, bring evidence.

We are still early enough that many of the conventions for agentic software development have not hardened yet.

That is a rare engineering moment.

We get to decide which habits deserve to become infrastructure.

**gogogo**  
https://github.com/Vorski-Imagineering/gogogo

This version has a much cleaner argument: **the bottleneck is not agent competence, it is preserving context across two cognitive systems operating at different speeds.** Everything else in gogogo follows from that.