#!/usr/bin/env python3
"""Tests for the shared /gogogo:spec skill's structure.

The skill is prose, so these pin what a reader of it depends on: the
declined-question subsection and its four choices, the Posting step that
offers to move the card, that every setting it names is one the checker
knows, that the offer adds no profile requirement, and that no project's
facts leak into it. Whether it behaves is a trigger run, not a phrase match.

    python3 -m unittest tests.test_spec_skill
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
SKILL = PLUGIN / "skills" / "spec" / "SKILL.md"
SETUP = PLUGIN / "skills" / "setup" / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_check as pc  # noqa: E402
from test_profile_check import COMPLETE  # noqa: E402

# The project-name grep in CLAUDE.md, as a regex.
PROJECT_NAMES = r"manage\.py|npm |firebase|django|htmx|sentry"
DECLINED = "### When the user declines a question"


def skill_text():
    return SKILL.read_text(encoding="utf-8")


def section(text, prefix, level="## "):
    """The lines from the heading starting `prefix` to the next heading of the same level."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith(level) and not lines[i].startswith(level + "#")), len(lines))
    return lines[start:end]


class DeclinedQuestion(unittest.TestCase):
    def test_declined_question_subsection(self):
        lines = skill_text().splitlines()
        heads = [i for i, line in enumerate(lines) if line.startswith(DECLINED)]
        self.assertEqual(len(heads), 1)
        ask = next(i for i, line in enumerate(lines) if line.startswith("## Ask in rounds"))
        verdict = next(i for i, line in enumerate(lines) if line.startswith("## Hard-stop verdict"))
        self.assertLess(ask, heads[0])
        self.assertLess(heads[0], verdict)

    def test_four_choices_listed(self):
        sub = section(skill_text(), DECLINED, "### ")
        self.assertEqual(len([line for line in sub if re.match(r"\d+\. ", line)]), 4)

    def test_delegation_names_the_record(self):
        self.assertIn("Chosen: delegated", "\n".join(section(skill_text(), DECLINED, "### ")))

    def test_setup_untouched(self):
        self.assertFalse(any(line.startswith("### When the user declines")
                             for line in SETUP.read_text(encoding="utf-8").splitlines()))


class Skill(unittest.TestCase):
    def test_no_project_names(self):
        self.assertIsNone(re.search(PROJECT_NAMES, skill_text(), re.I))

    def test_name_and_profile_command(self):
        text = skill_text()
        self.assertRegex(text.split("---")[1], r"(?m)^name: spec$")
        self.assertIn('profile_check.py" --for spec --show', text)

    def test_offer_step_in_posting(self):
        posting = section(skill_text(), "## Posting")
        steps = {int(m.group(1)): i for i, line in enumerate(posting) if (m := re.match(r"(\d+)\. ", line))}
        self.assertIn(7, steps)
        self.assertIn(8, steps)
        seven = "\n".join(posting[steps[7]:steps[8]])
        eight = "\n".join(posting[steps[8]:])
        self.assertIn("ready_marker", seven)
        self.assertIn("move", eight)
        self.assertIn("`tracker.queue`", eight)
        for setting in ("tracker.tool", "tracker.queue", "tracker.ready_marker"):
            self.assertIn(setting, pc.FIELDS, setting)
        named = set(re.findall(r"`(tracker\.[a-z_]+)`", skill_text()))
        for setting in named:
            self.assertIn(setting, pc.FIELDS, setting)

    def test_profile_still_does_not_require_queue(self):
        settings, sections = pc.split_profile(COMPLETE)
        del settings["tracker"]["tool"]
        del settings["tracker"]["queue"]
        errors, _ = pc.check(settings, sections, pc.SPEC)
        self.assertFalse([e for e in errors if e.startswith(("tracker.tool", "tracker.queue"))], errors)


if __name__ == "__main__":
    unittest.main()
