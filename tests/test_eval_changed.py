#!/usr/bin/env python3
"""Tests for tools/eval_changed.py, this repo's `evals` lane command (gogogo#131).

Git runs for real in a temporary repository; `claude` never runs:
`eval_changed._run_eval` is patched to write a given result document and
return a given exit code, and records the arguments it was called with.

    python3 -m unittest tests.test_eval_changed
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import eval_changed  # noqa: E402


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def write(root, rel, text="x\n"):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def case(root, name, skill):
    write(root, f"plugins/gogogo/evals/{name}/prompt.md", f"---\ntags: [{skill}]\n---\n\nQuestion?\n")


def doc(total=3, passed=3, cost=1.234, partial=False, deltas=None):
    d = {"partial": partial, "costUsd": cost,
         "aggregates": {"casesTotal": total, "casesPassed": passed}, "cases": []}
    for name, delta in (deltas or {}).items():
        d["cases"].append({"name": name, "aggregates": {"delta": delta}})
    return d


class Lane(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        for s in ("dev", "auto-dev", "spec", "idea"):
            write(self.root, f"plugins/gogogo/skills/{s}/SKILL.md")
        case(self.root, "dev-reversal", "dev")
        case(self.root, "auto-dev-list-fails", "auto-dev")
        case(self.root, "spec-being-built", "spec")
        write(self.root, "README.md")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")
        git(self.root, "switch", "-q", "-c", "work")
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_lane(self, argv=(), result=None, code=0):
        def fake(args, cwd):
            self.calls.append(args)
            if result is not None:
                Path(args[args.index("--json") + 1]).write_text(json.dumps(result), encoding="utf-8")
            return code
        out = io.StringIO()
        with mock.patch.object(eval_changed, "_run_eval", fake), contextlib.redirect_stdout(out):
            rc = eval_changed.main(["--base", "main", *argv], root=self.root)
        return rc, out.getvalue()

    def test_a_changed_skill_runs_its_cases_with_the_approved_gate(self):
        write(self.root, "plugins/gogogo/skills/dev/SKILL.md", "changed\n")
        rc, _ = self.run_lane(result=doc())
        self.assertEqual(len(self.calls), 1)
        args = self.calls[0]
        self.assertEqual(args[:4], ["claude", "plugin", "eval", "plugins/gogogo"])
        self.assertLess(args.index("plugins/gogogo"), args.index("--tag"))
        self.assertEqual(args[args.index("--tag"):], ["--tag", "dev"])
        for flag, value in (("--runs", "3"), ("--threshold", "0.66"), ("--ablation", "none")):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertIn("--trust-plugin", args)
        self.assertIn("--no-publish", args)
        self.assertEqual(rc, 0)

    def test_a_changed_reference_selects_its_skill(self):
        write(self.root, "plugins/gogogo/skills/dev/references/review.md")
        self.run_lane(result=doc())
        self.assertEqual(self.calls[0][-2:], ["--tag", "dev"])

    def test_a_changed_case_selects_the_skill_it_is_tagged_for(self):
        write(self.root, "plugins/gogogo/evals/dev-reversal/prompt.md", "---\ntags: [dev]\n---\n\nChanged?\n")
        self.run_lane(result=doc())
        self.assertEqual(self.calls[0][-2:], ["--tag", "dev"])

    def test_no_skill_changed_runs_nothing(self):
        write(self.root, "README.md", "changed\n")
        rc, out = self.run_lane()
        self.assertEqual((rc, out.strip(), self.calls), (0, "evals: no skill changed", []))

    def test_a_skill_with_no_case_fails_and_runs_nothing(self):
        write(self.root, "plugins/gogogo/skills/idea/SKILL.md", "changed\n")
        rc, out = self.run_lane()
        self.assertEqual(rc, 1)
        self.assertIn("evals: no case for idea; add one (CLAUDE.md § Tests)", out)
        self.assertEqual(self.calls, [])

    def test_no_result_is_a_failure(self):
        write(self.root, "plugins/gogogo/skills/dev/SKILL.md", "changed\n")
        rc, out = self.run_lane(result=None, code=0)
        self.assertEqual(rc, 1)
        self.assertIn("evals: no result (", out)

    def test_a_result_with_no_case_is_a_failure(self):
        write(self.root, "plugins/gogogo/skills/dev/SKILL.md", "changed\n")
        rc, out = self.run_lane(result=doc(total=0, passed=0), code=0)
        self.assertEqual(rc, 1)
        self.assertIn("evals: no result (", out)

    def test_a_partial_run_is_a_failure(self):
        write(self.root, "plugins/gogogo/skills/dev/SKILL.md", "changed\n")
        rc, out = self.run_lane(result=doc(partial=True), code=2)
        self.assertEqual(rc, 1)
        self.assertIn("evals: no result (partial", out)

    def test_a_failing_case_fails_the_lane(self):
        write(self.root, "plugins/gogogo/skills/dev/SKILL.md", "changed\n")
        rc, out = self.run_lane(result=doc(total=3, passed=2, cost=1.5), code=1)
        self.assertEqual(rc, 1)
        self.assertIn("evals: cases=3 passed=2 cost=$1.50", out)

    def test_every_case_passing_passes_the_lane(self):
        write(self.root, "plugins/gogogo/skills/dev/SKILL.md", "changed\n")
        rc, out = self.run_lane(result=doc(cost=1.234), code=0)
        self.assertEqual(rc, 0)
        self.assertIn("evals: cases=3 passed=3 cost=$1.23", out)

    def test_skill_runs_those_cases_with_no_change(self):
        rc, _ = self.run_lane(["--skill", "spec"], result=doc())
        self.assertEqual(self.calls[0][-2:], ["--tag", "spec"])
        self.assertEqual(rc, 0)

    def test_baseline_fails_a_case_that_does_as_well_without_the_plugin(self):
        rc, out = self.run_lane(["--skill", "dev", "--baseline"],
                                result=doc(total=2, passed=2, deltas={"dev-a": 1.0, "dev-b": 0.0}))
        args = self.calls[0]
        self.assertEqual(args[args.index("--ablation") + 1], "with-without")
        self.assertEqual(rc, 1)
        self.assertIn("evals: dev-b does as well without the plugin", out)
        self.assertNotIn("dev-a does", out)

    def test_baseline_passes_when_every_case_does_better_with_the_plugin(self):
        rc, _ = self.run_lane(["--skill", "dev", "--baseline"],
                              result=doc(total=2, passed=2, deltas={"dev-a": 1.0, "dev-b": 0.5}))
        self.assertEqual(rc, 0)

    def test_two_skills_are_one_run_tagged_in_order(self):
        write(self.root, "plugins/gogogo/skills/dev/SKILL.md", "changed\n")
        write(self.root, "plugins/gogogo/skills/auto-dev/SKILL.md", "changed\n")
        self.run_lane(result=doc())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][-3:], ["--tag", "auto-dev", "dev"])

    def test_committed_changes_count_too(self):
        write(self.root, "plugins/gogogo/skills/spec/SKILL.md", "changed\n")
        git(self.root, "commit", "-q", "-am", "change")
        self.run_lane(result=doc())
        self.assertEqual(self.calls[0][-2:], ["--tag", "spec"])


if __name__ == "__main__":
    unittest.main()
