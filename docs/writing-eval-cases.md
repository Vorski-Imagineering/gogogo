# Writing an eval case

An eval case checks that a skill does what it should, and does it **because of
the plugin**. A change to what a skill does adds or changes a case for it, and
the case must do worse without the plugin (`CLAUDE.md` § Tests). This page is
how to write one that does, and how to show it.

## The folder

A case is a folder under `plugins/gogogo/evals/`:

```
plugins/gogogo/evals/<skill>-<what-it-checks>/
  prompt.md
  graders/
    skill-fired.md
    <one or more checks>.md
```

- `prompt.md` starts with a header holding `tags: [<skill>]` (one skill, named
  as in `plugins/gogogo/skills/`), `max_turns`, and `allowed_tools`, then the
  question. Copy a neighbouring case's header.
- `graders/skill-fired.md` is the grader `type: tool_used` for the `Skill`
  tool; copy it from a neighbouring case and change the skill's name.
- Every case has at least one more grader, a `type: regex` on the answer.
- Add the folder's name to `CASES` in `tests/test_eval_suite.py`, which pins
  the list.

## The prompt

- Ask a neutral question about a situation, not for a particular word. A
  prompt that contains the words a grader looks for passes without the plugin.
- Name the skill's process as the one in use ("We use the gogogo dev
  process here"). Without that the `Skill` tool is often never called, and
  the case measures nothing.
- Give the facts the answer depends on, and ask for two or three sentences
  with nothing changed.

## The graders

- A grader's `pattern:` is a JavaScript regular expression. Inline flags such
  as `(?i)` do not load; put the flag on its own line, `flags: i`.
  `tests/test_eval_suite.py` fails on an inline flag group. `(?:…)` and
  lookbehind `(?<!…)` are fine.
- A grader that must not match is `match: not_contains`; see
  `plugins/gogogo/evals/auto-dev-review-wait/graders/no-question.md`. It must
  not match the correct answer's own wording: "the second is kept; the first
  is deleted" and "never deletes the second" are the sentences a careless
  pattern catches.
- Check every pattern in node against one correct and one wrong sample
  answer before running the lane:
  ```bash
  node -e 'const re = /branch -D/i; console.log(re.test("run git branch -D x"), re.test("keep it"))'
  ```
  The first should print `true`, the second `false`.
- At least one grader must check something only the plugin knows: a name, a
  step or an order that is in the skill's text and nowhere in the prompt.
- No `llm` or `baseline` graders; the suite test rejects them.

## Showing it does worse without the plugin

```bash
python3 tools/eval_changed.py --skill <skill> --baseline
```

runs each of the skill's cases three times with the plugin and three without,
and fails a case that does as well or better without it. It exits 0 when every
case does better with the plugin.

To see the new case fail on the old skill text, restore the skills from
`origin/main` in a throwaway worktree and run the lane there:

```bash
git worktree add --detach ../<repo>-old origin/main
cp -R plugins/gogogo/evals/<the case> ../<repo>-old/plugins/gogogo/evals/
(cd ../<repo>-old && python3 tools/eval_changed.py --skill <skill>)
git worktree remove --force ../<repo>-old
```

The case should fail there and pass in your working tree.

## Reading the result

`tools/eval_changed.py` prints `evals: cases=<n> passed=<n> cost=$<x>`, then one
line per case, `evals: <name> score=<score>`, with ` without=<score>` added
under `--baseline`. A case that was meant to run and is not in the result
(a grader file that failed to load, for example) is printed as
`evals: <name> did not run` and fails the lane.

Each run's own scores are in `aggregate-result.json` in the run's report folder
under `plugins/gogogo/evals/results/` (not committed).

## Why it is written this way

- **0.66.** The lane passes a case at a score of 0.66 or more over its graders
  in two of three runs, so a case that loses one of three graders can still
  count as passed. The per-case score line exists so a lowered score is
  visible without opening the report.
- **`--baseline` is a floor, not a margin.** It fails only a case that does as
  well without the plugin, not one that is only a little worse. A prompt that
  gives the answer away therefore passes without the plugin; the neutral
  prompt and the plugin-only grader are what make the comparison mean
  something. Requiring a margin is a separate decision.
- **Why a missing case fails.** A run in which some case files failed to load
  used to pass on the cases that did load. A case that never ran proves
  nothing, so the lane says so.
- **Why a grader never calls a model.** A judge costs money on every run and
  can change its mind; a regex over the answer does neither.

## Sources

- [Test plugins with evals, Claude Code documentation](https://code.claude.com/docs/en/plugin-evals)
- [Regular expressions, MDN](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Regular_expressions)
