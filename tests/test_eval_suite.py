#!/usr/bin/env python3
"""Structure of the skills' eval suite, plugins/gogogo/evals/ (gogogo#131).

Pins the cases, the graders each must carry, that no grader calls a judge
model, that run reports stay out of git, and the lane that runs the suite.
Whether a skill passes its cases is the `evals` lane, not a test here.

    python3 -m unittest tests.test_eval_suite
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "plugins" / "gogogo" / "evals"
SKILLS = ROOT / "plugins" / "gogogo" / "skills"
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import profile_check as pc  # noqa: E402

CASES = {
    "dev-third-attempt", "dev-reversal", "dev-unlicensed-weaker-test",
    "auto-dev-label-less-card", "auto-dev-open-decision", "auto-dev-list-fails",
    "spec-declined-question", "spec-being-built", "spec-nothing-hits-today",
    "spec-no-argument-offers-new", "spec-pr-mentions-only",
    "status-sweep-lists-only", "wrap-up-asks-before-removing",
    "setup-connected-message",
}
TAGS = re.compile(r"^tags:\s*\[([^\]]*)\]\s*$", re.M)
TYPE = re.compile(r"^type:\s*(\S+)\s*$", re.M)


def cases():
    return sorted(p.parent for p in EVALS.glob("*/prompt.md"))


class Suite(unittest.TestCase):
    def test_the_cases_each_name_one_real_skill(self):
        self.assertEqual({c.name for c in cases()}, CASES)
        skills = {p.parent.name for p in SKILLS.glob("*/SKILL.md")}
        for c in cases():
            with self.subTest(case=c.name):
                m = TAGS.search((c / "prompt.md").read_text(encoding="utf-8"))
                self.assertIsNotNone(m)
                tags = [t.strip() for t in m.group(1).split(",")]
                self.assertEqual(len(tags), 1)
                self.assertIn(tags[0], skills)

    def test_every_case_checks_the_skill_fired_and_one_thing_more(self):
        for c in cases():
            with self.subTest(case=c.name):
                fired = c / "graders" / "skill-fired.md"
                self.assertTrue(fired.is_file())
                self.assertEqual(TYPE.search(fired.read_text(encoding="utf-8")).group(1), "tool_used")
                self.assertGreaterEqual(len(list((c / "graders").glob("*.md"))), 2)

    def test_no_grader_calls_a_judge(self):
        judged = [str(g.relative_to(EVALS)) for g in EVALS.glob("*/graders/*.md")
                  if TYPE.search(g.read_text(encoding="utf-8")).group(1) in ("llm", "baseline")]
        self.assertEqual(judged, [])

    def test_run_reports_are_ignored(self):
        r = subprocess.run(["git", "check-ignore", "-q", "plugins/gogogo/evals/results/x"], cwd=ROOT)
        self.assertEqual(r.returncode, 0)

    def test_this_repo_runs_the_suite_as_a_lane_after_unit(self):
        settings, _ = pc.split_profile((ROOT / ".agents" / "dev-process.md").read_text(encoding="utf-8"))
        lanes = {lane["name"]: lane for lane in settings["lanes"]}
        self.assertEqual(lanes["evals"]["run"], "python3 tools/eval_changed.py")
        self.assertEqual(lanes["evals"]["tests"], ["plugins/gogogo/evals/*"])
        rungs = settings["verify"]["rungs"]
        self.assertGreater(rungs.index("evals"), rungs.index("unit"))


if __name__ == "__main__":
    unittest.main()
