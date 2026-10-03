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

Every test run goes through a wrapper, `.gogogo-run.py`, written into the copy.
It runs the test command, hands its output on decoded as UTF-8 with anything
unreadable replaced (the tool reads that output as text and hangs on bytes it
cannot decode), keeps the command's exit code, and records the start and end
of each run in `.gogogo-heartbeat` in the copy.

The stall check reads that heartbeat. Once the first test run (the baseline)
has finished, a tool that starts or finishes no test run for 10 times that
run's duration, and at least 10 minutes, has stopped: the tool's own per-mutant
timeout ends a slow test run long before then. It and everything it started
are ended, and the run exits 2 as `stalled:`. A slow run has no time limit:
only a run that has stopped starting tests is ended.

Output: each survivor as `SURVIVED <path>:<line>` and its `-` and `+` lines,
then exactly `mutants: <n> killed: <n> survived: <n> timeout: <n>`. The tool's
`suspicious` (the tests failed, but ran slowly) counts as killed.

Exit codes: 0 no survivors; 1 survivors; 2 it could not finish, or stalled (no
`mutants:` line is printed then).

Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = "plugins/gogogo/scripts"
VERSION = "2.5.1"
PINS = (f"mutmut=={VERSION}", "whatthepatch==1.0.7")
HUNK = re.compile(r"^@@ -(\d+)")
# Fixed whatever the user's git config says: the tool reads paths after a/ and b/.
PLAIN_DIFF = ["--src-prefix=a/", "--dst-prefix=b/", "--no-color", "--no-ext-diff"]
WRAPPER = ".gogogo-run.py"
HEARTBEAT = ".gogogo-heartbeat"
# The stall window is max(STALL_MIN, STALL_TIMES x the first test run's seconds),
# checked every STALL_POLL seconds; an ended tool gets KILL_AFTER seconds before SIGKILL.
STALL_MIN = 600
STALL_TIMES = 10
STALL_POLL = 15
KILL_AFTER = 10

WRAPPER_SOURCE = f'''"""Runs one test command for tools/mutate.py; written into its throwaway copy.

It becomes the test command (exec), so the tool's own timeout kills the test run itself, and
the exit status is the command's. A forked child waits for it to end, then passes its output
on as UTF-8 and marks the end.
"""
import os
import sys
import time
from pathlib import Path

beat = Path(__file__).resolve().parent / {HEARTBEAT!r}


def mark(line):
    with open(beat, "a") as f:
        f.write(line + "\\n")


start = time.time()
mark(f"start {{start:.3f}}")
test_pid = os.getpid()
out = beat.parent / f".gogogo-out-{{test_pid}}"
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
if os.fork() == 0:
    # Waits for the test run itself to end, then passes on all it wrote. Not a pipe read to its
    # end: a process the test started may hold a pipe open, and write to it, long after the tool
    # has killed the test, and the tool waits on this output.
    os.close(fd)
    while os.getppid() == test_pid:
        time.sleep(0.1)
    data = out.read_bytes()
    out.unlink()
    sys.stdout.buffer.write(data.decode("utf-8", errors="replace").encode("utf-8"))
    sys.stdout.flush()
    end = time.time()
    mark(f"end {{end:.3f}} {{end - start:.3f}}")
    os._exit(0)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.close(fd)
os.execvp(sys.argv[1], sys.argv[1:])
'''


class Stop(Exception):
    """The run cannot finish; the message goes to stderr and the exit is 2."""


def _run(args: list[str], cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _end_group(proc: subprocess.Popen, grace: float) -> None:
    """Ends `proc` and everything it started: SIGTERM, then SIGKILL after `grace` seconds."""
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, None)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            # Gone, or (macOS) only exited members left: nothing to end.
            pass
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            continue


def _progress(copy: Path) -> tuple:
    """(tested, total) mutants from the tool's cache, or ("?", "?") when it cannot be read."""
    try:
        with contextlib.closing(sqlite3.connect(f"file:{copy / '.mutmut-cache'}?mode=ro", uri=True)) as db:
            statuses = [row[0] for row in db.execute("SELECT status FROM Mutant")]
    except sqlite3.Error:
        return "?", "?"
    return sum(1 for s in statuses if s != "untested"), len(statuses)


def _run_mutmut(args: list[str], cwd=None) -> subprocess.CompletedProcess:
    """The tool's run in its own process group, ended as `stalled:` when it stops starting test runs."""
    copy = Path(cwd)
    beat = copy / HEARTBEAT
    with open(copy / ".gogogo-mutmut.out", "wb") as out, open(copy / ".gogogo-mutmut.err", "wb") as err:
        proc = subprocess.Popen(args, cwd=cwd, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                start_new_session=True)
        seen, last, window = None, time.monotonic(), None
        try:
            while True:
                try:
                    proc.wait(timeout=STALL_POLL)
                    break
                except subprocess.TimeoutExpired:
                    pass
                try:
                    stat = beat.stat()
                    now_seen = (stat.st_size, stat.st_mtime_ns)
                except FileNotFoundError:
                    now_seen = None
                if now_seen != seen:
                    seen, last = now_seen, time.monotonic()
                if window is None and seen is not None:
                    ends = [ln.split() for ln in beat.read_text().splitlines() if ln.startswith("end ")]
                    if ends:
                        window = max(STALL_MIN, STALL_TIMES * float(ends[0][2]))
                if window is not None and time.monotonic() - last > window:
                    _end_group(proc, KILL_AFTER)
                    tested, total = _progress(copy)
                    raise Stop(f"stalled: no test run for {round(window / 60, 1):g} minutes "
                               f"after {tested} of {total} mutants")
        finally:
            # Also ends what a timed-out test run left behind: the tool kills only the wrapper.
            _end_group(proc, 0)
    read = lambda name: (copy / name).read_bytes().decode("utf-8", errors="replace")  # noqa: E731
    return subprocess.CompletedProcess(args, proc.returncode, read(".gogogo-mutmut.out"),
                                       read(".gogogo-mutmut.err"))


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


def write_wrapper(copy: Path) -> None:
    (copy / WRAPPER).write_text(WRAPPER_SOURCE)


def runner(scripts: list[str], root: Path) -> str:
    """The test command, through the wrapper."""
    modules = [f"tests.test_{Path(s).stem}" for s in scripts]
    if all((root / "tests" / f"test_{Path(s).stem}.py").is_file() for s in scripts):
        return f"python3 {WRAPPER} python3 -m unittest " + " ".join(modules)
    return f"python3 {WRAPPER} python3 -m unittest discover -s tests"


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
        write_wrapper(copy)
        run = _run_mutmut([exe, "run", "--paths-to-mutate", ",".join(scripts), "--use-patch-file", ".gogogo-mutate.patch",
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

        killed = ids("killed") + ids("suspicious")
        survived, timeout = ids("survived"), ids("timeout")
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
        cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "gogogo"
        advice = (f"; the tool's install looks broken: delete {cache} and run again"
                  if exc.filename and "mutmut" in str(exc.filename) else "")
        print(f"could not finish: {exc}{advice}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
