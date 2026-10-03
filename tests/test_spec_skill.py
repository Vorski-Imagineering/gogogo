#!/usr/bin/env python3
"""Tests for the shared /gogogo:spec skill's structure.

The skill is prose, so these pin what a reader of it depends on: the
declined-question subsection and its four choices, the Posting step that
moves the card, that every setting it names is one the checker
knows, that the move adds no profile requirement, and that no project's
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
SEVERAL = SKILL.parent / "references" / "several-issues.md"
VERIFY_BY_HAND = SKILL.parent / "references" / "verify-by-hand.md"
POSTING = SKILL.parent / "references" / "posting.md"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_check as pc  # noqa: E402
from test_dev_skill import moved  # noqa: E402
from test_profile_check import COMPLETE  # noqa: E402

# The project-name grep in CLAUDE.md, as a regex.
PROJECT_NAMES = r"manage\.py|npm |firebase|django|htmx|sentry"
DECLINED = "### When the user declines a question"


def skill_text():
    return SKILL.read_text(encoding="utf-8")


def with_moved():
    """SKILL.md, then the three sections it moved to references (gogogo#130)."""
    return "\n".join([skill_text()] + [moved(p) for p in (SEVERAL, VERIFY_BY_HAND, POSTING)])


def several_lines():
    return moved(SEVERAL).splitlines()


def posting_lines():
    return moved(POSTING).splitlines()


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

    def test_move_step_in_posting(self):
        posting = posting_lines()
        steps = {int(m.group(1)): i for i, line in enumerate(posting) if (m := re.match(r"(\d+)\. ", line))}
        self.assertIn(7, steps)
        self.assertIn(8, steps)
        seven = "\n".join(posting[steps[7]:steps[8]])
        eight = "\n".join(posting[steps[8]:])
        self.assertIn("ready_marker", seven)
        self.assertIn("move", eight)
        self.assertIn("`tracker.queue`", eight)
        for name in ("`tracker.columns.in_progress`", "`tracker.columns.needs_human`", "`stages`", "--add-missing"):
            self.assertIn(name, eight)
        for setting in ("tracker.tool", "tracker.queue", "tracker.ready_marker"):
            self.assertIn(setting, pc.FIELDS, setting)
        queue_moves = [ln for ln in eight.splitlines()
                       if re.search(r"move <N> .*--to \"<tracker\.queue>\"", ln) and "--add-missing" not in ln]
        self.assertTrue(queue_moves, eight)
        for line in queue_moves:
            self.assertIn("--from", line)
        named = set(re.findall(r"`(tracker\.[a-z_]+(?:\.[a-z_]+)*)`", with_moved()))
        for setting in named:
            self.assertIn(setting, pc.FIELDS, setting)

    def several_rules(self):
        several = "\n".join(several_lines())
        return re.findall(r"^(\d+)\. (.*?)(?=^\d+\. |\Z)", several, re.M | re.S)

    def test_no_end_of_run_move_rule(self):
        rules = self.several_rules()
        self.assertEqual([int(n) for n, _ in rules], list(range(1, 8)))
        self.assertFalse([n for n, text in rules if "tracker.queue" in text])

    def test_rule_references_resolve(self):
        count = len(self.several_rules())
        refs = [int(n) for n in re.findall(r"\brule (\d+)\b", with_moved())]
        self.assertTrue(refs)
        self.assertFalse([n for n in refs if not 1 <= n <= count], refs)

    def test_profile_still_does_not_require_queue(self):
        settings, sections = pc.split_profile(COMPLETE)
        del settings["tracker"]["tool"]
        del settings["tracker"]["queue"]
        errors, _ = pc.check(settings, sections, pc.SPEC)
        self.assertFalse([e for e in errors if e.startswith(("tracker.tool", "tracker.queue"))], errors)


RUN = "## Several issues in one run"


class ChangedMeanwhile(unittest.TestCase):
    """Posting compares the issue with a snapshot taken when it started (gogogo#91)."""

    def test_before_you_write_takes_the_start_snapshot(self):
        before = "\n".join(section(skill_text(), "## Before you write"))
        self.assertIn("issue-<N>-start.json", before)
        self.assertIn("--json body,labels", before)

    def test_posting_step_one_compares_and_asks(self):
        posting = posting_lines()
        steps = {int(m.group(1)): i for i, line in enumerate(posting) if (m := re.match(r"(\d+)\. ", line))}
        one = "\n".join(posting[steps[1]:steps[2]])
        for text in ("issue-<N>-start.json", "issue-<N>-now.json", "keep", "replace"):
            self.assertIn(text, one)

    def test_the_final_report_names_a_changed_issue(self):
        rules = "\n".join(several_lines())
        self.assertIn("changed by someone else meanwhile", rules)

    def test_red_flags_name_the_start_snapshot(self):
        flags = [l for l in section(skill_text(), "## Red flags") if l.startswith("|")]
        self.assertTrue(any("start snapshot" in l for l in flags))


class Dependents(unittest.TestCase):
    """Posting step 4 checks the open specs that read this issue's body (gogogo#93)."""

    def posting(self):
        return posting_lines()

    def step(self, number):
        posting = self.posting()
        steps = {int(m.group(1)): i for i, line in enumerate(posting) if (m := re.match(r"(\d+)\. ", line))}
        return "\n".join(posting[steps[number]:steps[number + 1]])

    def test_step_four_lists_the_open_specs(self):
        four = self.step(4)
        for text in ("gh issue list", "--state open", "tracker.issues_repo"):
            self.assertIn(text, four)

    def test_the_check_comes_before_the_post(self):
        posting = self.posting()
        listing = next(i for i, line in enumerate(posting) if "gh issue list" in line)
        post = next(i for i, line in enumerate(posting) if "gh issue edit <N> --body-file" in line)
        self.assertLess(listing, post)

    def test_test_rules_has_five_rules(self):
        rules = (SKILL.parent / "references" / "test-rules.md").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"(?m)^## ", rules)), 5)

    def test_the_pattern_matches_commands_not_mentions(self):
        found = re.search(r'test\("([^"]+)"\)', self.step(4))
        self.assertIsNotNone(found)
        pattern = found.group(1).replace("\\\\", "\\").replace("<N>", "57")
        self.assertRegex("gh issue view 57 --json body", pattern)
        self.assertNotRegex("such as #57", pattern)
        self.assertNotRegex("gh issue view 157", pattern)


class SeveralIssues(unittest.TestCase):
    """A list or a column is specced one issue at a time (gogogo#70)."""

    def test_several_issues_section_placed(self):
        lines = skill_text().splitlines()
        heads = [i for i, line in enumerate(lines) if line.startswith(RUN)]
        self.assertEqual(len(heads), 1)
        profile = next(i for i, line in enumerate(lines) if line.startswith("## First: read this repo's profile"))
        body = next(i for i, line in enumerate(lines) if line.startswith("## The issue body IS"))
        self.assertLess(profile, heads[0])
        self.assertLess(heads[0], body)

    def test_several_issues_rules(self):
        sub = "\n".join(several_lines())
        self.assertEqual([int(m) for m in re.findall(r"^(\d+)\. ", sub, re.M)], list(range(1, 8)))
        for name in ("list --status", "--issues-only", "--open-only", "spec_lint.py", "tracker.ready_marker"):
            self.assertIn(name, sub)
        for setting in re.findall(r"`(tracker\.[a-z_.]+)`", sub):
            self.assertIn(setting, pc.FIELDS, setting)

    def test_choice_four_points_at_run_rule(self):
        sub = section(skill_text(), DECLINED, "### ")
        start = next(i for i, line in enumerate(sub) if line.startswith("4. "))
        end = next((i for i in range(start + 1, len(sub)) if not sub[i].startswith("   ")), len(sub))
        self.assertIn("Several issues in one run", " ".join(sub[start:end]))
        self.assertIn(RUN, skill_text().splitlines(), "the section it points at is gone")

    def test_step_eight_deferred_in_run(self):
        lines = posting_lines()
        start = next(i for i, line in enumerate(lines) if line.startswith("8. "))
        end = next((i for i in range(start + 1, len(lines)) if re.match(r"\S", lines[i])), len(lines))
        self.assertIn("Several issues in one run", "\n".join(lines[start:end]))
        self.assertIn(RUN, skill_text().splitlines(), "the section it points at is gone")

    def test_claude_specific_names_fork(self):
        sub = "\n".join(section(skill_text(), "## Claude-specific"))
        self.assertIn("subagent_type", sub)
        self.assertIn('"fork"', sub)

    def test_readme_shows_list_example(self):
        self.assertRegex((ROOT / "README.md").read_text(encoding="utf-8"), r"`/gogogo:spec #\d+ #\d+")


BUILDING = "## Is someone building it already?"
BEFORE = "## Before you write"


class BeforeYouWrite(unittest.TestCase):
    """In-flight check, the today check and prior work (gogogo#97)."""

    def before_steps(self):
        before = "\n".join(section(skill_text(), BEFORE))
        return re.findall(r"^(\d+)\. (.*?)(?=^\d+\. |^\*\*REQUIRED|\Z)", before, re.M | re.S)

    def test_building_section_directly_before_before_you_write(self):
        lines = skill_text().splitlines()
        heads = [i for i, line in enumerate(lines) if line.startswith(BUILDING)]
        self.assertEqual(len(heads), 1)
        nxt = next(line for line in lines[heads[0] + 1:] if line.startswith("## "))
        self.assertTrue(nxt.startswith(BEFORE), nxt)
        sub = "\n".join(section(skill_text(), BUILDING))
        for name in ("tracker.columns.in_progress", "tracker.columns.needs_human", "gh pr list"):
            self.assertIn(name, sub)

    def test_before_you_write_steps_zero_to_seven(self):
        steps = self.before_steps()
        self.assertEqual([int(n) for n, _ in steps], list(range(0, 8)))
        self.assertIn("today", steps[6][1])
        self.assertIn("Prior work", steps[7][1])

    def test_close_command_has_reopen_comment(self):
        six = self.before_steps()[6][1]
        close = re.search(r"gh issue close[^`]*`", six)
        self.assertIsNotNone(close, "no close command in step 6")
        self.assertIn('--reason "not planned"', close.group(0))
        self.assertIn("--comment", close.group(0))

    def test_claude_specific_names_web_search(self):
        self.assertIn("WebSearch", "\n".join(section(skill_text(), "## Claude-specific")))


if __name__ == "__main__":
    unittest.main()
