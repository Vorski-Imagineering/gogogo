# The tracker contract

The shared skills contain no board code. They run the command in the profile's
`tracker.tool` with these four subcommands, and trust nothing else about the
board. A repo's tool may do more; the skills use only this.

| Command | Does | Exit codes |
|---|---|---|
| `list --status "<column>"` | Every card in the column, newest-added first. Reads the whole board and refuses to print a list it cannot reconcile against the board's own total; also prints any card only the issue side can see (GitHub's project index can drop one from both the pages and the count) | 0 ok; 2 the read can't be trusted: **a stop, never an empty column** |
| `show <n> [--expect "<column>"]` | One issue's column, read from the issue side, so it works whatever the board's size | 0 ok; 2 not found or unreadable; 3 in a different column from `--expect` |
| `move <n> --to "<column>"` | Sets the column. Resolves every id live, then reads the card back | 0 **only** when the read-back agrees; 2 the board disagrees or the write failed |
| `fields [--check]` | The board's columns as they are now. `--check` fails if a column the tool's own registry needs is missing | 0 ok; 2 a column is missing |

Column arguments are **column names**, as the profile's `stages` and
`tracker.columns` give them. Never pass a stored option id: ids survive a
column rename, so a stored id can move a card into a column that now means
something else.

## Rules for the skills that call it

- Read the move back: a zero exit from `move` is the confirmation, and nothing
  else is.
- Move a card only as far as the code has actually got, per the profile's
  `stages`. Check the code is there (for example with `verify_merged.py`)
  before the move, never after.
- A non-zero exit from `list` stops the run. It is not an empty queue.

## The shared tool

`${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py` meets this contract for any GitHub
project board. It reads the board (`tracker.project_owner`,
`tracker.project_number`), the issues repo and the columns from the profile, so
a repo's profile sets:

```toml
[tracker]
tool = "shared"
```

`shared` is a keyword, not a path: the plugin's install path changes with every
version, so the skills translate it into
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py"`.

Column arguments may also be the profile's role keys: `queue`, and the keys of
`tracker.columns` such as `in_progress` and `needs_human`. `fields --check`
fails naming any column the profile uses that the live board lacks.

A repo may name its own tool instead, as long as it meets this contract. A repo
whose CI also moves cards (for example on deploy) imports a pinned copy of
`tracker.py` and runs a pinned `stage_sync.py` beside it (see
`references/stage-sync.md`); the skills still use `tracker.py`.

The shared tool also refuses a move to `tracker.columns.needs_human` unless the issue's newest comment carries a stop marker (`gogogo:stop`, `gogogo:skip`, or an `auto-test v1` FAIL or NEEDS_HUMAN verdict), exiting 4 with nothing written; a repo's own tool may do the same.

The shared tool also has `views [--hide-closed]` and `tidy [--apply]`, which
`/gogogo:setup` uses to keep views and cards current. They are not part of the
contract, and a repo's own tool need not provide them.
