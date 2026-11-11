#!/usr/bin/env python3
"""Run the eval cases of each skill a change touched, and pass on the result.

    tools/eval_changed.py [--base <ref>] [--skill <name> ...]... [--baseline]

This repo's `run` command for its `evals` lane (`.agents/dev-process.md`).
It is not part of the plugin, so the plugin names no tool (gogogo#131).

The skills are the names given with --skill (it may be repeated, and the names
add up: `--skill a --skill b c` is a, b and c), or else those the change touched
since it left <base> (`git merge-base <base> HEAD`, default origin/main),
uncommitted and untracked files included: a file under
plugins/gogogo/skills/<s>/ adds <s>, and a file under plugins/gogogo/evals/<case>/
adds the skill that case's prompt.md names in its `tags`. A case belongs to a
skill when its `tags` holds the skill's name.

No skill: prints `evals: no skill changed` and exits 0, running nothing. A
skill with no case: prints `evals: no case for <s>; ...` and exits 1, running
nothing. Otherwise it runs `claude plugin eval` on those skills' cases, three
runs each, with the plugin only (`--ablation none`), and a case passes at 2 of
3 runs. A case below the gate is run again on the base, alone, from a worktree
at the fork point taken down afterwards, with the base's own plugin and cases:
failing there too, it is an old failure, printed `evals: <name> fails on <base>
too score=<s>; not this change`, and does not fail the lane; passing there
(`passes on <base>`), or with no result there (`base re-run gave no result`),
its failure stands. A case the base does not have is not re-run. It prints
`evals: cases=<n> passed=<n> base_failed=<k> cost=$<x>`, the cost including
the re-runs, and exits 0 only when every case passed or failed on the base too.
After that line it prints one line per case in the result,
`evals: <name> score=<score>` (and ` without=<score>` under --baseline), the
base re-run lines, and
`evals: <name> did not run` for a case of those skills the result leaves out,
which fails the run (docs/writing-eval-cases.md). A result it cannot read, with no case in it, or cut short
(`partial`) is a failure, never a pass.

--baseline also runs each case without the plugin (`--ablation with-without`)
and fails a case that does as well without it: a new case is seen failing that
way (CLAUDE.md § Tests).

The runs use the caller's own Claude login and count against its usage, about
$0.60 a case.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "plugins/gogogo"
SKILLS = f"{PLUGIN}/skills/"
EVALS = f"{PLUGIN}/evals/"
TAGS = re.compile(r"^tags:\s*\[([^\]]*)\]\s*$", re.M)
FIXED = ["--runs", "3", "--threshold", "0.66", "--concurrency", "3"]
THRESHOLD = float(FIXED[FIXED.index("--threshold") + 1])


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _run_eval(args: list[str], cwd: Path) -> int:
    """Run `claude plugin eval` with its own output on this process's streams; return its exit code."""
    return subprocess.run(args, cwd=cwd).returncode


def _score(value) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def _tags(text: str) -> list[str]:
    m = TAGS.search(text)
    return [t.strip().strip("'\"") for t in m.group(1).split(",")] if m else []


def case_tags(root: Path) -> dict[str, list[str]]:
    """Each case folder's name, and the tags its prompt.md names."""
    return {p.parent.name: _tags(p.read_text(encoding="utf-8"))
            for p in sorted((root / EVALS).glob("*/prompt.md"))}


def case_tags_at(root: Path, ref: str) -> dict[str, list[str]]:
    """The same, as the cases stood at `ref`, so a deleted or retagged case still names its skill."""
    cases = {}
    for path in _git(["ls-tree", "-r", "--name-only", ref, EVALS], root).splitlines():
        if path.endswith("/prompt.md"):
            cases[path[len(EVALS):].split("/")[0]] = _tags(_git(["show", f"{ref}:{path}"], root))
    return cases


def fork_point(root: Path, base: str) -> str:
    return _git(["merge-base", base, "HEAD"], root).strip()


def changed_files(root: Path, fork: str) -> list[str]:
    # --no-renames: a file moved out of a skill shows its old path too.
    files = _git(["diff", "--name-only", "--no-renames", fork], root).splitlines()
    files += _git(["ls-files", "--others", "--exclude-standard"], root).splitlines()
    return files


def _read(out: Path) -> dict | None:
    try:
        doc = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return None if doc.get("partial") else doc


def base_score(root: Path, fork: str, name: str) -> tuple[float | None, float]:
    """Run case `name` alone on the base's own plugin and case files, from a worktree at `fork`
    taken down afterwards: (its score, or None for no result; what the run cost)."""
    with tempfile.TemporaryDirectory() as tmp:
        tree, out = Path(tmp) / "base", Path(tmp) / "base.json"
        try:
            _git(["worktree", "add", "--detach", "--quiet", str(tree), fork], root)
        except subprocess.CalledProcessError:
            return None, 0.0
        try:
            _run_eval(["claude", "plugin", "eval", str(tree / PLUGIN), *FIXED, "--ablation", "none",
                       "--trust-plugin", "--no-publish", "--json", str(out), "--case", name], tree)
            doc = _read(out)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=root, capture_output=True)
    if doc is None:
        return None, 0.0
    cost = float(doc.get("costUsd") or 0)
    for c in doc.get("cases") or []:
        if c.get("name") == name:
            score = (c.get("aggregates") or {}).get("score")
            return (None if score is None else float(score)), cost
    return None, cost


def skills_touched(files: list[str], *case_maps: dict[str, list[str]]) -> set[str]:
    skills = set()
    for f in files:
        if f.startswith(SKILLS):
            skills.add(f[len(SKILLS):].split("/")[0])
        elif f.startswith(EVALS):
            name = f[len(EVALS):].split("/")[0]
            for cases in case_maps:
                skills.update(cases.get(name, []))
    return skills


def main(argv=None, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--skill", nargs="+", action="extend", default=None)
    ap.add_argument("--baseline", action="store_true")
    a = ap.parse_args(argv)

    cases, fork, at_fork = case_tags(root), None, None
    if a.skill:
        skills = set(a.skill)
    else:
        fork = fork_point(root, a.base)
        at_fork = case_tags_at(root, fork)
        skills = skills_touched(changed_files(root, fork), cases, at_fork)
    if not skills:
        print("evals: no skill changed")
        return 0
    tagged = {t for tags in cases.values() for t in tags}
    bare = sorted(skills - tagged)
    if bare:
        for s in bare:
            print(f"evals: no case for {s}; add one (CLAUDE.md § Tests)")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "evals.json"
        args = ["claude", "plugin", "eval", PLUGIN, *FIXED,
                "--ablation", "with-without" if a.baseline else "none",
                "--trust-plugin", "--no-publish", "--json", str(out),
                "--tag", *sorted(skills)]
        code = _run_eval(args, root)
        try:
            doc = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"evals: no result ({type(e).__name__}, claude exited {code})")
            return 1
    agg = doc.get("aggregates") or {}
    if doc.get("partial"):
        print(f"evals: no result (partial: {doc.get('partialReason') or 'unknown'})")
        return 1
    if not agg.get("casesTotal"):
        print("evals: no result (no case ran)")
        return 1
    listed = doc.get("cases") or []
    # A case below the gate is run again on the base: failing there too, it is an old failure
    # and does not fail this change. A case the base does not have keeps its failure.
    cost, on_base, base_failed, below = float(doc.get("costUsd") or 0), [], set(), set()
    for c in listed:
        score = (c.get("aggregates") or {}).get("score")
        if score is None or float(score) >= THRESHOLD:
            continue
        below.add(c.get("name"))
        if at_fork is None:
            fork = fork_point(root, a.base)
            at_fork = case_tags_at(root, fork)
        if c.get("name") not in at_fork:
            continue
        there, spent = base_score(root, fork, c["name"])
        cost += spent
        if there is None:
            on_base.append(f"evals: {c['name']} base re-run gave no result")
        elif there < THRESHOLD:
            base_failed.add(c["name"])
            on_base.append(f"evals: {c['name']} fails on {a.base} too score={_score(there)}; not this change")
        else:
            on_base.append(f"evals: {c['name']} passes on {a.base} score={_score(there)}")
    print(f"evals: cases={agg['casesTotal']} passed={agg.get('casesPassed', 0)} "
          f"base_failed={len(base_failed)} cost=${cost:.2f}")
    for c in listed:
        aggregates = c.get("aggregates") or {}
        line = f"evals: {c.get('name')} score={_score(aggregates.get('score'))}"
        if aggregates.get("scoreWithout") is not None:
            line += f" without={_score(aggregates['scoreWithout'])}"
        print(line)
    for line in on_base:
        print(line)
    # The cases a run is meant to run are the tagged cases of its skills; a result that leaves
    # one out (a case file that failed to load, say) is a failed run.
    ran = {c.get("name") for c in listed}
    missing = sorted(n for n, tags in cases.items() if set(tags) & skills and n not in ran)
    for name in missing:
        print(f"evals: {name} did not run")
    flat = []
    if a.baseline:
        for c in doc.get("cases") or []:
            delta = (c.get("aggregates") or {}).get("delta")
            if delta is None or delta <= 0:
                flat.append(c.get("name"))
                print(f"evals: {c.get('name')} does as well without the plugin")
    # The eval's own count of failed cases must all be old failures for its exit code to be set aside.
    eval_failed = int(agg.get("casesTotal") or 0) - int(agg.get("casesPassed") or 0)
    ok = not (below - base_failed) and (code == 0 or (base_failed and eval_failed <= len(base_failed)))
    return 0 if ok and not flat and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
