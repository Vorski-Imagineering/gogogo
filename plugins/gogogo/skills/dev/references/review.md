# /gogogo:dev: 5. Review

Part of `/gogogo:dev`. Read it in full. Section names and § numbers here are `SKILL.md`'s. `${CLAUDE_PLUGIN_ROOT}` below is not filled in for you: it is the plugin's folder, the one whose `scripts/` `SKILL.md` names in full.

## Contents

- First, the change against its spec
- A round
- Which findings are applied
- Three attempts per finding
- No flip-flops
- Late findings
- A small addition that goes wrong is removed
- Prose, per file
- How a review ends

Review the change before reporting anything, with the review command named in
`## Claude-specific`. Apply findings deliberately, one at a time, never with
the review command's own fix option, and render them as markdown, never raw
JSON. Nothing merges unreviewed. Configuration inside a Markdown file (a
profile's settings block) is code, not prose.

**First, the change against its spec.** Before round 1, every numbered item of
the issue's spec is answered against the change, so a piece never built, or
built another way than the spec says, is found before the review reads the
change for bugs. In order:

- **List the items.** Save the issue body to a file and run
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_check.py" items <body file> --base origin/<base>
  ```
  from the change's working tree, where `<base>` is the branch the change
  merges into (`integration.base`, or the repo's default branch when the
  profile has none); `git fetch origin` first, so files other changes already
  merged are not counted as this change's. Exit 1 means the body has no spec:
  skip the rest of this step, and say so in §7. An `unlisted:` line names a
  section the check could not list item by item; say so in §7.
- **A reader answers them.** Give a reader that has not seen how the change
  was made three things and nothing else: where the spec is (the issue
  number), the item list, and the change (the working tree and its difference
  from `<base>`). It writes one line per `V`, `A`, `D`, `T` and `N` item to an
  answers file, as `<id> | <status> | <evidence> | <note>`, and edits nothing.
  It is told:
  - `met`: the change does what the item says. Evidence is where: a file
    (`path`), a file and one line (`path:line`, a single line number, never
    a range), or a file and the test's name (`path::name`, or for a test inside a class
    `path::Class.name` or `path::Class::name`); several are
    separated by `, `. Paths are relative to the working tree.
  - `missing`: nothing in the change does it. `differs`: the change does it
    another way than the item says; the note gives the spec's words and what
    the change has.
  - `na`: only for what cannot be seen in the change (a run in a lane no test
    reaches, another repo), with the reason.
  - `met` and `differs` on a `D`, `T` or `A` item always have evidence. An
    `A` row whose Chosen is carried out on the tracker, not in the change
    (a comment on another issue, an issue body left alone), is `na`, with
    that as its reason.
  - An item holding several exact rules takes the worst status among them,
    and the note names each part that is not met.
  - A `V` step is `met` when the change makes what the step says you will see
    true. A `T` case is `met` only when a test exists and asserts what the
    case says. An `A` row is `met` when the change does what was Chosen and
    nothing that was Rejected. An `N` item is `met` when the change leaves it
    alone.
  - It does not judge quality, look for bugs or propose changes.

  When no such reader can be started, answer the list yourself and record
  `reader=self`.
- **Check the answers.** Run `spec_check.py verify <body file> <answers file>
  --base origin/<base>`. On exit 2, give the reader the `error:` lines and have it
  answer again.
- **Handle what is not `met`**, each by the first case that fits:
  - two parts of the spec disagree, so that meeting one item breaks another →
    the issue stops for a person (§8);
  - `missing` → build it. An `F:` item that is `missing` → make the change the
    spec lists for that file;
  - `differs` → change it to match the spec;
  - `differs`, and matching the spec is not possible or would be wrong, and
    the difference is small (it touches no Hard Stop item, adds no
    user-visible behaviour, setting or message the spec does not have, and
    stays inside the files the spec lists) → keep it and declare it in §7;
  - any other `differs`, and a `missing` item that cannot be built → the
    issue stops for a person (§8);
  - an `outside` file → take it out of the change, or keep it when a spec
    item cannot be met without it and declare it in §7 with that item;
  - `na` → listed in §7.
- **A misreading.** An answer you believe is a misreading: give the reader the
  file and line for that item and ask once more. Its second answer stands.
- **Again, at most three times.** After changing anything, have the reader
  answer the items that were not `met` again, replacing their lines in the
  answers file and keeping the rest, and run `verify` again. At most
  three reader runs. An item still `missing`, or `differs` and not declared,
  after the third → the issue stops for a person (§8).
- **Then round 1 starts.** What this step changed is part of the change the
  review reads. The spec check is not run again after the review.

Then the review, by these rules:

1. **A round.** Round 1 reviews the whole change against the issue's spec, at
   the profile's `review.coverage` (`broad` when unset); a change whose files
   are all prose is reviewed at `precise`. Every later round reviews only what
   the previous round's corrections changed, at `precise`: in a run that
   commits, the correction commits' range; otherwise name the changed files
   and what each correction changed. A correction round's own check is the
   lane's `focused` command for each test module that covers a file the
   correction changed (the lane's `tests` pattern); the lane's full `run` is
   not run per round (§6 runs it once, after the last round). Every round, tell the review where the
   spec is (the issue number) and to report only where the change fails the
   spec or a rule in `CLAUDE.md`, breaks something that worked, or has a bug
   with a concrete triggering case. From round 2, also give it the findings
   already declined, one line each, and tell it not to raise them again.
2. **Which findings are applied.** Take the first test a finding meets. A
   reviewer's own label ("correctness", a severity) does not change which
   test that is.

   | # | The finding shows | What happens | Recorded as |
   |---|---|---|---|
   | 1 | the change fails the spec or a rule in `CLAUDE.md` | applied | `spec` |
   | 2 | the change breaks something that worked before it | applied, with the case | `regression` |
   | 3 | a bug, with a concrete case | applied. Code: write the test that fails first, see it fail, then fix. What no test reaches (prose, configuration, a script's output): the exact situation or input and the wrong result, reproduced or traced to a `file:line` | `bug` |
   | 4 | a consequence that would be a security hole, lost or corrupted data, or a change the repo's Hard Stop rules require approval for that no Approvals row covers | no concrete case needed: fixed, or the issue stops for a person; an unapproved Hard Stop always stops (§4) | `risk` |
   | 5 | behaviour the spec does not have | applied only when small: touches no Hard Stop item, adds no new user-visible behaviour, setting or message, stays inside the files the spec lists, and has a test. Named in the report under *Added beyond the spec*. Otherwise declined and listed as a follow-up | `added`, or declined as `beyond` |
   | 6 | anything else | declined, with one line saying why | `hypothetical` (a setup or input no real repo or run has), `style` (wording, naming, tidiness, speed with no wrong result), `settled` (the spec, an Approvals row or an earlier round decided it), `reversal`, `late` |

   Test 4 is read by consequence, not by file: a finding on a file a Hard
   Stop covers is not test 4 unless its consequence is. A finding that meets
   tests 1 to 4 and cannot be fixed stops the issue for a person (§8), except
   under `review=until-clean` (rule 8).
3. **Three attempts per finding.** From round 2, a finding that meets tests 1
   to 4 means a correction was wrong; it belongs to the finding that
   correction was for. The second attempt says what the first got wrong and
   takes a different approach, not a patch on the patch. A third attempt does
   the same. When a round finds such a defect in the third attempt, the issue
   stops for a person, with the three attempts and what each got wrong in the
   report. Under `review=until-clean` (`/gogogo:dev` §1) there is no attempt
   limit: each attempt still says what the last got wrong and takes a
   different approach.
4. **No flip-flops.** A finding that would undo a correction made in an
   earlier round: when it meets no test from 1 to 4, it is declined as
   `reversal`. When it does, and the spec or `CLAUDE.md` says which way is
   right, that way is applied once and stands, and later findings against it
   are `settled`. When it does and the spec is silent, nothing is changed and
   the issue stops for a person, who decides.
5. **Late findings.** From round 2, a finding about something no correction
   touched is declined as `late` and listed as a follow-up, unless it meets
   test 2, 3 or 4, in which case it is a new finding with its own three
   attempts.
6. **A small addition that goes wrong is removed.** When a later round finds a
   defect in something applied as `added`, the addition is taken out and
   listed as a follow-up.
7. **Prose, per file.** A file is prose when it is Markdown or plain text and
   no configuration in it changed. A prose file gets two rounds, in any
   change: the round that reviews it and the round that reviews its
   corrections. After its second round it changes only to fix a finding that
   meets tests 1 to 4. Such a fix gets one more round, of that fix alone. When
   that round finds nothing in the fix that meets tests 1 to 4, the file's
   review has ended. When it does, the defect is fixed, and that fix sends the
   issue to a person, marked unreviewed, once the code files' review has
   ended. No prose file gets a fourth round. Its other findings from the
   second round on are declined and listed as follow-ups. Code files follow
   rules 3 to 6. Under `review=until-clean`, a prose file gets as many rounds
   as it takes, and its fixes are reviewed as code's are (rules 3 to 6).
8. **How a review ends.** `clean`: a round applies nothing. For a person
   (§8): `third-attempt` (rule 3), `reversal` (rule 4), `unfixable` (a
   finding that meets tests 1 to 4 and cannot be fixed), `prose` (rule 7).
   And `breaker`: when round 13 ends and the review has not, the issue stops
   for a person and the report says the loop itself misbehaved. There is no
   other limit on rounds. Under `review=until-clean`, `third-attempt`,
   `unfixable`, `prose` and `breaker` are not ends: the review ends `clean`,
   `reversal`, or `silent` (rule 9), and a finding that cannot be fixed is
   attempted again with a different approach.
9. **A silent review.** A review whose transcript has not been written for 20
   minutes is stopped and started again once, on the same range; the issue's
   review section names the restart. A restart does not count toward round 13
   of rule 8. A second silence ends the review with `silent`, which stops the
   issue for a person. The transcript is the review fork's file under the
   session's `subagents` folder; its last write time is the check.

When the spec moves content unchanged, findings about that content are not
part of the move: list them in the report as follow-ups. A finding there that
meets tests 1 to 4 still means fix or stop.
