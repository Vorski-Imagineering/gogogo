#!/usr/bin/env python3
"""Tests for the shared /gogogo:idea skill and the settings it reads.

The skill is prose, so these pin what a reader of it depends on: that it can
start (its name, and `profile_check.py --for idea` accepting a profile), that
every setting it names is one the checker knows, that its body template has
the idea's four headings and no spec heading, that such a body is not taken
for a spec, that it files with no label and never moves a card, and that no
project's facts leak into it.

    python3 -m unittest tests.test_idea_skill
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
SKILL = PLUGIN / "skills" / "idea" / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_check as pc  # noqa: E402
import spec_lint  # noqa: E402
from test_profile_check import COMPLETE, drop, parse  # noqa: E402
from test_tech_eval import PROJECT_NAMES  # noqa: E402

HEADINGS = ["## Request", "## What is there today", "## Ruled out",
            "## Things the spec will need to settle"]
SPEC_HEADINGS = ["## Verify by hand", "## Approvals", "## Hard-stop check", "## Design"]


def skill_text():
    return SKILL.read_text(encoding="utf-8")


def template():
    blocks = re.findall(r"```markdown\n(.*?)```", skill_text(), re.S)
    templates = [b for b in blocks if "## Request" in b]
    assert len(templates) == 1, "one fenced body template"
    return templates[0]


def run_check(settings_text):
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp) / "dev-process.md"
        profile.write_text(settings_text)
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = pc.main(["--for", "idea", "--path", str(profile)])
    return code, err.getvalue()


class Skill(unittest.TestCase):
    def test_frontmatter(self):
        front = skill_text().split("---")[1]
        self.assertRegex(front, r"(?m)^name: idea$")
        self.assertRegex(front, r"(?m)^description: Use when")
        self.assertNotIn("disable-model-invocation", front)

    def test_profile_command_and_check(self):
        self.assertIn('profile_check.py" --for idea --show', skill_text())
        self.assertEqual(run_check(COMPLETE)[0], pc.EXIT_OK)
        settings, _ = parse()
        missing = COMPLETE.replace(f'issues_repo = "{settings["tracker"]["issues_repo"]}"\n', "")
        self.assertNotEqual(missing, COMPLETE)
        code, err = run_check(missing)
        self.assertNotEqual(code, pc.EXIT_OK)
        self.assertIn("tracker.issues_repo", err)

    def test_every_setting_it_names_is_known(self):
        tops = {path.split(".")[0] for path in pc.FIELDS if "." in path}
        named = {f"{a}.{b}" for a, b in re.findall(r"[`<]([a-z_]+)\.([a-z_]+)[`>]", skill_text()) if a in tops}
        for setting in ("tracker.issues_repo", "tracker.public", "tracker.ready_marker", "tracker.kind",
                        "tracker.tool", "tracker.project_number", "tracker.project_owner"):
            self.assertIn(setting, named)
        for setting in sorted(named):
            self.assertIn(setting, pc.FIELDS, setting)

    def test_template_headings(self):
        headings = [line.strip() for line in template().splitlines() if line.startswith("## ")]
        self.assertEqual(headings, HEADINGS)
        for heading in SPEC_HEADINGS:
            self.assertNotIn(heading, template())

    def test_an_idea_is_not_a_spec(self):
        settings, _ = parse()
        errors = spec_lint.lint(template(), settings)[0]
        self.assertTrue(any("section missing" in e for e in errors), errors)

    def test_files_with_no_label_and_never_moves_a_card(self):
        text = skill_text()
        create = [line for line in text.splitlines() if "gh issue create" in line and "--title" in line]
        self.assertTrue(create)
        for line in create:
            self.assertIn("--body-file", line)
            self.assertIn("--repo", line)
        for flag in ("--label", "--add-label"):
            self.assertNotIn(flag, text)
        self.assertNotRegex(text, r'tracker\.py"? move')

    def test_upstream_target(self):
        text = skill_text()
        start = text.index("## The target")
        target = text[start:text.index("\n## ", start + 1)]
        self.assertIn("Vorski-Imagineering/gogogo", target)
        verbs = ("create", "comment", "list", "view")
        for verb in verbs:
            lines = [line for line in text.splitlines() if f"gh issue {verb}" in line]
            self.assertTrue(lines, verb)
            for line in lines:
                self.assertIn("--repo <target repo>", line)

    def test_description_names_gogogo_as_a_filing_target(self):
        front = skill_text().split("---")[1]
        self.assertRegex(front, r"(?m)^description: .*gogogo")

    def test_name_check_covers_the_title_and_is_bounded(self):
        text = skill_text()
        start = text.index("Then, wherever step 3 ends")
        para = text[start:text.index("Keep a list of what you removed", start)]
        grep = next(l for l in para.splitlines() if "grep -n -i -F" in l)
        self.assertIn("<draft file>", grep)
        self.assertIn("<title file>", grep)
        self.assertNotIn("sed -E", para)
        self.assertNotIn("check file", para)
        self.assertIn("test -e", para)
        self.assertIn("plugin's root", para)
        self.assertIn("empty", para)
        self.assertRegex(para, r"(?i)after three runs")
        step2 = text[text.index("## 2. Draft"):text.index("## 3. Public trackers")]
        self.assertRegex(step2, r"(?s)title file.*empty file for a comment")

    def test_name_check_command(self):
        self.assertTrue(any("grep -n -i -F" in line for line in skill_text().splitlines()))

    def test_no_project_names(self):
        self.assertIsNone(re.search(PROJECT_NAMES, skill_text(), re.I))


if __name__ == "__main__":
    unittest.main()
