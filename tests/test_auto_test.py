#!/usr/bin/env python3
"""Tests for the shared /gogogo:auto-test skill and the settings it reads.

The skill is prose, so these pin what a reader of it depends on: that it can
start (its name, and `profile_check.py --for auto-test` accepting a complete
profile), that it names every auto-test setting and `## Test data` heading
and none the checker lacks, that this repo's own profile still passes every
other skill while auto-test stops on its first missing setting, and that no
project's facts leak into it.

    python3 -m unittest tests.test_auto_test
"""

import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
SKILL = PLUGIN / "skills" / "auto-test" / "SKILL.md"
SCRIPT = PLUGIN / "scripts" / "record_outcome.py"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_check as pc  # noqa: E402
from test_profile_check import COMPLETE  # noqa: E402
from test_tech_eval import PROJECT_NAMES  # noqa: E402

OUTCOMES = ("PASS", "FAIL", "NEEDS HUMAN", "NOT DEPLOYED", "HELD")


def skill_text():
    return SKILL.read_text(encoding="utf-8")


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = pc.main(list(argv))
    return code, err.getvalue()


class Skill(unittest.TestCase):
    def test_name_model_and_profile_command(self):
        text = skill_text()
        front = text.split("---")[1]
        self.assertRegex(front, r"(?m)^name: auto-test$")
        self.assertRegex(front, r"(?m)^description: \S")
        self.assertRegex(front, r"(?m)^model: \S")
        self.assertIn('profile_check.py" --for auto-test --show', text)
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            profile.write_text(COMPLETE)
            self.assertEqual(run_main("--for", "auto-test", "--path", str(profile))[0], pc.EXIT_OK)

    def test_names_what_it_needs_and_nothing_the_checker_lacks(self):
        text = skill_text()
        own = [p for p, (_, by, _) in pc.FIELDS.items() if pc.TEST in by and p.startswith("auto_test.")]
        self.assertEqual(len(own), 5, own)
        for name in (*own, "## Test data", *pc.TEST_DATA_HEADINGS, "record_outcome.py", "--triage-only",
                     *OUTCOMES):
            self.assertIn(name, text, name)
        tops = {path.split(".")[0] for path in pc.FIELDS if "." in path}
        # Backticked (`verify.human`) or a placeholder in a command (<tracker.issues_repo>).
        named = {f"{a}.{b}" for a, b in re.findall(r"[`<]([a-z_]+)\.([a-z_]+)[`>]", text) if a in tops}
        self.assertTrue(set(own) <= named, named)
        for setting in sorted(named):
            self.assertIn(setting, pc.FIELDS, setting)

    def test_no_project_names(self):
        for path in (SKILL, SCRIPT):
            self.assertIsNone(re.search(PROJECT_NAMES, path.read_text(encoding="utf-8"), re.I), path)


class ThisReposProfile(unittest.TestCase):
    """trap 9: every skill reads profile_check.py, so the real profile is the regression test."""

    PROFILE = str(ROOT / ".agents" / "dev-process.md")

    def test_other_skills_still_pass_and_auto_test_names_its_first_setting(self):
        for skill in (pc.SPEC, pc.ONE, pc.LOOP, pc.TECH):
            code, err = run_main("--for", skill, "--path", self.PROFILE)
            self.assertEqual(code, pc.EXIT_OK, (skill, err))
        code, err = run_main("--path", self.PROFILE)
        self.assertEqual(code, pc.EXIT_OK, err)
        code, err = run_main("--for", "auto-test", "--path", self.PROFILE)
        self.assertEqual(code, pc.EXIT_INVALID)
        errors = [line for line in err.splitlines() if line.startswith("error: ")]
        self.assertTrue(errors[0].startswith("error: auto_test.pass_column"), errors)


if __name__ == "__main__":
    unittest.main()
