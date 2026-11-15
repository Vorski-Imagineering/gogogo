# Decision questions

A decision question asks a person to decide about a change or an issue:
approve it, build it, close it, file it, requeue it, remove it. It is not
a question that only picks something (an issue number, a column). Before
its options, after the real case in one plain sentence, it says three
things, one plain line each:

1. **What it is.** The thing being decided, in words a person who was not
   in the session follows: what it does, not its file or flag.
2. **Where its risk reaches.** How far the change has got, or would get:
   not built yet; on a branch not yet merged; the pre-merge environment;
   production. Use the profile's names for its `environments`, and its
   `reached_by` words for production, so the reach is the repo's own.
   Where the profile does not say, use the plain words above.
3. **Its run time.** What it adds to a run: a figure already measured (a
   test run, a run report, a review record), with where it came from;
   `adds no time`; or `not measured`. Never run anything to get a figure
   for the question.

Then the options, each saying what changes for people, as the skill says.
No file names, flags or exit codes in any of it.
