#!/usr/bin/env python3
"""Run the eval cases of each skill a change touched, and pass on the result.

    tools/eval_changed.py [--base <ref>] [--skill <name> ...] [--baseline]

This repo's `run` command for its `evals` lane (`.agents/dev-process.md`).
It is not part of the plugin, so the plugin names no tool (gogogo#131).

The skills are the names given with --skill, or else those the change touched
since it left <base> (`git merge-base <base> HEAD`, default origin/main),
uncommitted and untracked files included: a file under
plugins/gogogo/skills/<s>/ adds <s>, and a file under plugins/gogogo/evals/<case>/
adds the skill that case's prompt.md names in its `tags`. A case belongs to a
skill when its `tags` holds the skill's name.

No skill: prints `evals: no skill changed` and exits 0, running nothing. A
skill with no case: prints `evals: no case for <s>; ...` and exits 1, running
nothing. Otherwise it runs `claude plugin eval` on those skills' cases, three
runs each, with the plugin only (`--ablation none`), and a case passes at 2 of
3 runs. It prints `evals: cases=<n> passed=<n> cost=$<x>` and exits 0 only when
every case passed. A result it cannot read, with no case in it, or cut short
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
FIXED = ["--runs", "3", "--threshold", "0.66"]


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _run_eval(args: list[str], cwd: Path) -> int:
    """Run `claude plugin eval` with its own output on this process's streams; return its exit code."""
    return subprocess.run(args, cwd=cwd).returncode


def case_tags(root: Path) -> dict[str, list[str]]:
    """Each case folder's name, and the tags its prompt.md names."""
    cases = {}
    for prompt in sorted((root / EVALS).glob("*/prompt.md")):
        m = TAGS.search(prompt.read_text(encoding="utf-8"))
        cases[prompt.parent.name] = [t.strip().strip("'\"") for t in m.group(1).split(",")] if m else []
    return cases


def changed_files(root: Path, base: str) -> list[str]:
    fork = _git(["merge-base", base, "HEAD"], root).strip()
    files = _git(["diff", "--name-only", fork], root).splitlines()
    files += _git(["ls-files", "--others", "--exclude-standard"], root).splitlines()
    return files


def skills_touched(files: list[str], cases: dict[str, list[str]]) -> set[str]:
    skills = set()
    for f in files:
        if f.startswith(SKILLS):
            skills.add(f[len(SKILLS):].split("/")[0])
        elif f.startswith(EVALS):
            skills.update(cases.get(f[len(EVALS):].split("/")[0], []))
    return skills


def main(argv=None, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--skill", nargs="+", default=None)
    ap.add_argument("--baseline", action="store_true")
    a = ap.parse_args(argv)

    cases = case_tags(root)
    skills = set(a.skill) if a.skill else skills_touched(changed_files(root, a.base), cases)
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
    print(f"evals: cases={agg['casesTotal']} passed={agg.get('casesPassed', 0)} "
          f"cost=${float(doc.get('costUsd') or 0):.2f}")
    flat = []
    if a.baseline:
        for c in doc.get("cases") or []:
            delta = (c.get("aggregates") or {}).get("delta")
            if delta is None or delta <= 0:
                flat.append(c.get("name"))
                print(f"evals: {c.get('name')} does as well without the plugin")
    return 0 if code == 0 and not flat else 1


if __name__ == "__main__":
    sys.exit(main())
