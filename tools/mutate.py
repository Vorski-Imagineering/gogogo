#!/usr/bin/env python3
"""Mutate the lines a change made to this repo's scripts, and report what the tests miss.

    tools/mutate.py <base> [--keep]

This repo's `mutate` command for its `unit` lane (`.agents/dev-process.md`),
meeting the contract in the plugin's `references/profile-schema.md` § Lanes.
It is not part of the plugin, so the plugin names no tool.

It mutates only the `.py` files directly in plugins/gogogo/scripts that changed
since the change left <base> (`git merge-base <base> HEAD`), uncommitted and
new files included, and runs each script's own `tests/test_<name>.py` against
each mutant. Any other changed file there is printed as `not covered:`.

The mutation tool (mutmut 2.5.1, pinned: later versions cannot import this
repo's tests) writes each mutant over the source file, so it runs only in a
throwaway copy of the tracked and unignored files, never in this tree: this
tree may be the plugin another repo's run is loading. The copy is removed on
every exit, unless `--keep`. The tool is installed on first use into
${XDG_CACHE_HOME:-~/.cache}/gogogo/mutmut-2.5.1, or taken from GOGOGO_MUTMUT.

Output: each survivor as `SURVIVED <path>:<line>` and its `-` and `+` lines,
then exactly `mutants: <n> killed: <n> survived: <n> timeout: <n>`.

Exit codes: 0 no survivors; 1 survivors; 2 it could not finish (no `mutants:`
line is printed then). There is no time limit.

Standard library only.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = "plugins/gogogo/scripts"
VERSION = "2.5.1"
PINS = (f"mutmut=={VERSION}", "whatthepatch==1.0.7")
HUNK = re.compile(r"^@@ -(\d+)")
# Fixed whatever the user's git config says: the tool reads paths after a/ and b/.
PLAIN_DIFF = ["--src-prefix=a/", "--dst-prefix=b/", "--no-color", "--no-ext-diff"]


class Stop(Exception):
    """The run cannot finish; the message goes to stderr and the exit is 2."""


def _run(args: list[str], cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _git(*args: str) -> str:
    out = _run(["git", *args])
    if out.returncode != 0:
        raise Stop((out.stderr.strip().splitlines() or [f"git exited {out.returncode}"])[-1])
    return out.stdout


def merge_base(base: str) -> str:
    out = _run(["git", "merge-base", base, "HEAD"])
    if out.returncode != 0:
        raise Stop(f"cannot find where this change left {base}")
    return out.stdout.strip()


def changed_scripts(fork: str) -> list[str]:
    """The scripts to mutate; prints every other changed file under the scripts folder as not covered."""
    changed = _git("diff", "--name-only", "--diff-filter=d", fork, "--", SCRIPTS).splitlines()
    changed += _git("ls-files", "--others", "--exclude-standard", "--", SCRIPTS).splitlines()
    scripts = []
    for path in dict.fromkeys(p for p in changed if p):
        if path.endswith(".py") and os.path.dirname(path) == SCRIPTS:
            scripts.append(path)
        else:
            print(f"not covered: {path}")
    return scripts


def make_patch(fork: str, scripts: list[str]) -> str:
    tracked = set(_git("ls-files", "--", *scripts).splitlines())
    patch = _git("diff", *PLAIN_DIFF, fork, "--", *[s for s in scripts if s in tracked]) if tracked else ""
    for path in scripts:
        if path not in tracked:
            out = _run(["git", "diff", *PLAIN_DIFF, "--no-index", "--", "/dev/null", path])
            if out.returncode not in (0, 1):
                raise Stop(f"cannot diff the new file {path}")
            patch += out.stdout
    return patch


def copy_tree(dest: Path) -> None:
    """Every tracked or unignored file that exists, at the same path under `dest`."""
    for path in _git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0"):
        if path and os.path.isfile(path):
            (dest / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest / path)


def tool() -> str:
    if os.environ.get("GOGOGO_MUTMUT"):
        return os.environ["GOGOGO_MUTMUT"]
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "gogogo" / f"mutmut-{VERSION}"
    exe = cache / "bin" / "mutmut"
    if not exe.is_file():
        for step in (["python3", "-m", "venv", str(cache)], [str(cache / "bin" / "pip"), "install", "-q", *PINS]):
            out = _run(step)
            if out.returncode != 0:
                raise Stop((out.stderr.strip().splitlines() or [f"{step[0]} exited {out.returncode}"])[-1])
    return str(exe)


def runner(scripts: list[str], root: Path) -> str:
    modules = [f"tests.test_{Path(s).stem}" for s in scripts]
    if all((root / "tests" / f"test_{Path(s).stem}.py").is_file() for s in scripts):
        return "python3 -m unittest " + " ".join(modules)
    return "python3 -m unittest discover -s tests"


def survivor(show: str) -> list[str]:
    """`SURVIVED <path>:<line>` and the hunk's `-` and `+` lines, from the tool's `show` output."""
    path, line, body, first = "?", None, [], None
    for text in show.splitlines():
        if text.startswith("--- "):
            path = text[4:].strip()
        elif text.startswith("+++ "):
            continue
        elif HUNK.match(text):
            line = int(HUNK.match(text).group(1))
        elif line is not None:
            if text.startswith("-") or text.startswith("+"):
                if first is None and text.startswith("-"):
                    first = line
                body.append(text)
            if not text.startswith("+"):
                line += 1
    return [f"SURVIVED {path}:{first if first is not None else '?'}", *body]


def mutate(base: str, keep: bool) -> int:
    fork = merge_base(base)
    scripts = changed_scripts(fork)
    if not scripts:
        print("mutants: 0 killed: 0 survived: 0 timeout: 0")
        return 0
    patch = make_patch(fork, scripts)
    exe = tool()
    copy = Path(tempfile.mkdtemp(prefix="gogogo-mutate-"))
    try:
        copy_tree(copy)
        (copy / ".gogogo-mutate.patch").write_text(patch)
        run = _run([exe, "run", "--paths-to-mutate", ",".join(scripts), "--use-patch-file", ".gogogo-mutate.patch",
                    "--runner", runner(scripts, copy), "--no-progress"], cwd=str(copy))
        if run.returncode % 2 == 1:
            raise Stop("\n".join((run.stdout + run.stderr).strip().splitlines()[-20:])
                       or f"the mutation tool exited {run.returncode}")

        def ids(status):
            out = _run([exe, "result-ids", status], cwd=str(copy))
            if out.returncode != 0:
                raise Stop(f"could not read the {status} mutants: "
                           + ((out.stderr or out.stdout).strip().splitlines() or ["no output"])[-1])
            return out.stdout.split()

        # "suspicious" is the tool's word for a mutant the tests killed, slowly.
        killed, timeout = ids("killed") + ids("suspicious"), ids("timeout")
        survived = ids("survived")
        missing = ids("untested") + ids("skipped")
        if missing:
            raise Stop(f"incomplete: {len(missing)} mutants were not run")
        for mutant in survived:
            print("\n".join(survivor(_run([exe, "show", mutant], cwd=str(copy)).stdout)))
        total = len(killed) + len(survived) + len(timeout)
        print(f"mutants: {total} killed: {len(killed)} survived: {len(survived)} timeout: {len(timeout)}")
        return 1 if survived else 0
    finally:
        if keep:
            print(f"kept the copy at {copy}", file=sys.stderr)
        else:
            shutil.rmtree(copy, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", help="the branch the change merges into")
    parser.add_argument("--keep", action="store_true", help="leave the copy and print its path")
    args = parser.parse_args(argv)
    try:
        return mutate(args.base, args.keep)
    except Stop as exc:
        print(exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"could not start a command: {exc}; if the tool's cache is broken, delete "
              f"{Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'gogogo'} and run again",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
