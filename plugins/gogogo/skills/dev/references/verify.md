# /gogogo:dev: 6. Verify: an executed path, not a green suite

Part of `/gogogo:dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- The new test, seen failing
- Never revert with `git checkout -- <file>`
- A lane passes on its command's own exit status
- The tests the change touched, compared
- The real thing, on real data

Work through the profile's `verify.rungs` in order, in the environments
`verify.agent` names. Each rung sees something the one below it cannot. Two are
always required:

**The new test, seen failing.** The regression test must be watched going red.
Stash the change, run the test, confirm red, restore:

```bash
git stash push -- <changed files>
<the lane's `focused` command for the new test>      # expect FAIL
git stash pop
```

**Never revert with `git checkout -- <file>`.** Until the branch has a commit,
`HEAD` is still the base, so `git checkout` on a tracked file you have been
editing silently discards the whole change. Stash and pop, or copy the file
aside first. After any revert experiment, `grep` for something you wrote to
confirm it survived.

Report how many of the new tests went red. Guards that were already true are
fine; name them as guards. Then run every lane's `run` command that applies.

**A lane passes on its command's own exit status** (its `run` command). Save
its output and read the status:

```bash
<the lane's run command> > <scratch>/<lane>.log 2>&1; echo "exit=$?"
```

`exit=0` is green; anything else is red, whatever the log says. Read the
summary from the log afterwards. Never put a filter (`| grep`, `| tail`,
`| head`) between the command and a decision: a pipeline's status is its last
command's, so `| grep -E 'OK|FAILED'` passes a failed run. The `echo` itself always
succeeds, so read the printed `exit=` value before any commit, push or merge;
never chain one onto the `echo`.

**The full run, once.** The lane's full `run` command runs once, after the last
correction round, and is the gate before merge. Correction rounds run the
focused commands of `review.md` rule 1 instead.

**The tests the change touched, compared.** Once every lane is green, check
that the change did not get there by weakening a test. In order:

1. Run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/test_guard.py" list --base origin/<base>`
   from the change's working tree, after `git fetch origin`, where `<base>` is
   the branch the change merges into (`integration.base`, or the repo's
   default branch when the profile has none).
2. Exit 3: say "tests not checked" and why in §7, write the record with
   `checked=no end=unchecked`, and go on. Exit 2: fix the call. `hunks=0`: the
   record is `checked=yes hunks=0 end=clean`.
3. Otherwise give a reader that has not seen how the change was made only the
   `list` output and the issue body. It writes an answers file, one line per
   item, `H<k><TAB><same|stronger|weaker><TAB><reason>`: `same` when the hunk
   guards the same claim, `stronger`, or `weaker` when it guards less (a test or
   case gone, a new skip or expected-failure marker, an assertion removed or
   loosened).
4. Run `test_guard.py verify <body file> <answers file> --base origin/<base>`.
   On exit 2, give the reader the errors and have it answer again.
5. Exit 1: for each `NOT LICENSED` item, restore what the test guarded (put
   back the base version of that hunk, or the deleted file) and make the change
   pass with it. Then run the lanes and steps 1 to 4 again. Up to three
   attempts, each naming a hypothesis different from the last. After the
   third, the issue stops for a person (§8), with the stop marker's reason
   `tests` and each unlicensed item named in §7.
6. Run steps 1 to 4 again after any later step of this section that changed a
   test file.

**The real thing, on real data.** Drive the path the issue describes in the
pre-merge environment and confirm the reported behaviour is gone. Hard-reload
rather than trusting a cached bundle. Read back real content (text, an
attribute, an element's presence), never a screenshot. Close anything you
opened that holds a resource (a room, a camera, a browser left running).

"Done" means an executed path. A green suite alone is "written", not "done".
