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
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "plugins" / "gogogo" / "evals"
SKILLS = ROOT / "plugins" / "gogogo" / "skills"
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import profile_check as pc  # noqa: E402

CASES = {
    "dev-third-attempt", "dev-reversal", "dev-unlicensed-weaker-test",
    "dev-round-checks-focused-tests", "dev-silent-review-restarts", "dev-wording-survivors-declined",
    "auto-dev-label-less-card", "auto-dev-open-decision", "auto-dev-list-fails",
    "auto-dev-review-wait", "auto-dev-late-run-pr", "dev-merge-refused",
    "dev-deletes-merged-local-branch", "dev-blocked-goes-to-queue", "auto-dev-skips-blocked",
    "spec-declined-question", "spec-being-built", "spec-nothing-hits-today",
    "spec-no-argument-offers-new", "spec-pr-mentions-only",
    "spec-reverses-tested-behaviour",
    "roadmap-shared-checkout", "roadmap-milestones-ask-first",
    "status-sweep-lists-only", "status-shows-independence",
    "wrap-up-asks-before-removing", "wrap-up-reviews-memories",
    "dev-suspected-fault", "auto-dev-fault-in-close-report",
    "wrap-up-fault-goes-upstream",
    "setup-connected-message", "setup-leaves-out-plugin-steps",
    "setup-machine-has-bot",
    "idea-files-upstream-checked",
    "auto-dev-sends-event-json",
}
TAGS = re.compile(r"^tags:\s*\[([^\]]*)\]\s*$", re.M)
TYPE = re.compile(r"^type:\s*(\S+)\s*$", re.M)


PATTERN = re.compile(r"^pattern:\s*(.*)$", re.M)
# An inline flag group, `(?i)` or `(?i:…)`: JavaScript's RegExp refuses it. `(?:…)` and `(?<!…)` are fine.
INLINE_FLAGS = re.compile(r"\(\?[a-zA-Z]+[:)]")


def inline_flag_graders(root):
    """The grader files under `root` whose pattern holds an inline flag group."""
    return [str(g.relative_to(root)) for g in sorted(root.glob("*/graders/*.md"))
            if INLINE_FLAGS.search("\n".join(PATTERN.findall(g.read_text(encoding="utf-8"))))]


def unclosed_quote_graders(root):
    """The grader files under `root` whose single-quoted pattern holds a lone `'`: it ends the YAML
    string early, and the eval runner refuses the whole case. Inside the string `'` is written `''`."""
    def bad(value):
        value = value.strip()
        return value.startswith("'") and (len(value) < 2 or not value.endswith("'")
                                          or "'" in value[1:-1].replace("''", ""))
    return [str(g.relative_to(root)) for g in sorted(root.glob("*/graders/*.md"))
            if any(bad(v) for v in PATTERN.findall(g.read_text(encoding="utf-8")))]


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

    def test_the_merge_refused_case_does_not_accept_what_an_answer_without_the_plugin_says(self):
        text = (EVALS / "dev-merge-refused" / "graders" / "names-the-way-out.md").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?i)needs")
        self.assertIn("Human!Help!", text)

    def test_no_grader_pattern_has_an_inline_flag_group(self):
        """A flag goes in the grader's `flags:` line, as `flags: i` (the guide: docs/writing-eval-cases.md)."""
        self.assertEqual(inline_flag_graders(EVALS), [])

    def test_the_inline_flag_check_rejects_flag_groups_and_allows_the_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, pattern in (("flag", "'(?i)abc'"), ("scoped", "'(?i:abc)'"),
                                  ("plain", "'(?:abc)'"), ("lookbehind", "'(?<!not )abc'")):
                grader = root / name / "graders"
                grader.mkdir(parents=True)
                (grader / "g.md").write_text(f"---\ntype: regex\npattern: {pattern}\n---\n", encoding="utf-8")
            self.assertEqual(inline_flag_graders(root), ["flag/graders/g.md", "scoped/graders/g.md"])

    def test_no_grader_pattern_ends_its_quotes_early(self):
        self.assertEqual(unclosed_quote_graders(EVALS), [])

    def test_the_quote_check_rejects_a_lone_quote_and_allows_a_doubled_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, pattern in (("lone", "'[\'\"]abc'"), ("doubled", "'it''s'"), ("escaped", "'[\\x27]'")):
                grader = root / name / "graders"
                grader.mkdir(parents=True)
                (grader / "g.md").write_text(f"---\ntype: regex\npattern: {pattern}\n---\n", encoding="utf-8")
            self.assertEqual(unclosed_quote_graders(root), ["lone/graders/g.md"])

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
