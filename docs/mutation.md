# Mutation testing gogogo's own scripts

A change to a `.py` file directly in `plugins/gogogo/scripts` is mutation-tested
before it merges: `tools/mutate.py` changes the lines the change made, one small
edit at a time, and runs that script's own tests against each edit. An edit the
tests still pass on (a survivor) is a line the tests do not check. This applies
to this repo only; the plugin does not run it in adopting repos.

## How to run it

Run it last, once every lane's `run` command is green and the real run has
been made:

```bash
git fetch origin
python3 tools/mutate.py origin/main
```

It takes minutes and has no time limit: let it finish, in the background if
your shell has a foreground limit, and poll it. Its last line is
`mutants: <n> killed: <n> survived: <n> timeout: <n>`. A spec whose change
touches such a file names this run as the last step of its `## Verification`.

## What to do with the result

1. A run whose output has no `mutants:` line is a failed run, never a pass. Run
   it once more. A second failed run stops the issue for a person (stop reason
   `mutation`).
2. `mutants: 0` means nothing on the changed lines can be mutated. It is
   reported and is not a failure.
3. Each survivor is handled by the first of these that applies, and nothing
   else is a reason (not "unlikely", "hard to test" or "the review covered
   it"):
   - **Kill it.** Add a test, or tighten an assertion, so the tests fail with
     the mutant in place. Such a change only adds or tightens: it never
     deletes, skips or loosens a test.
   - **Decline it** as `equivalent`: no input makes the mutated code behave
     differently from the original.
   - **Decline it** as `text`: the mutant changes only wording a person reads
     (a message, help text, a label, how much of an id is shown) and the spec
     does not fix that wording.
   - **Decline it** as `outside`: the difference shows only outside what the
     tests can observe (what is handed to an external program or service the
     tests replace with a stand-in, a wait or retry interval), **and** the real
     run executed that line. When the real run did not execute it, kill it:
     assert what is handed over.
4. When the test written to kill a survivor also fails on the unmutated code,
   the survivor found a bug. Fix the code. That fix is a correction: it goes
   back through review as a new round on the fix, then through verification
   again.
5. After killing, run the command again. A survivor counts as killed only when
   a run reports it killed. At most three runs that give counts. After the
   third run, survivors whose only change is wording a person reads (a
   message, a label, help text, how much of an id is shown, with no condition
   or value that code tests) are declined as `text` together, each listed by
   file and line in the report. The issue stops for a person (stop reason
   `mutation`) only on the survivors that change logic, listed under the
   Needs-you line.
6. Tests added or tightened here are not reviewed again: their evidence is the
   run that reports the mutant killed. After the last such change, run every
   lane's `run` command once more and see it green.

## Where the result goes

One line in the pull request's description and in the issue's report:
`mutants: <n> killed: <n> survived: <n> timeout: <n>` from the first run, how
many survivors were then killed by added or tightened tests, and each declined
survivor by file, line, the change in a few words and its reason word.

## Why it is only here

Mutation testing used to be a step every adopting repo ran when its profile
had a `mutate` command. Across about 2,700 mutants it found one real bug,
and each run took many minutes on every issue, in every repo that had it. The
owner took it out of the plugin and kept it for gogogo's own scripts, where
the scripts other repos run are written.
