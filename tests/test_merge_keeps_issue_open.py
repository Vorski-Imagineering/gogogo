"""A merge leaves its issue open (gogogo#34).

A structure test: it pins the flag and the commands the skills run, not
sentences.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "gogogo" / "skills"


def text(skill):
    return (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")


class MergeKeepsIssueOpen(unittest.TestCase):
    def test_every_verify_merged_command_checks_the_issue_is_open(self):
        for skill in ("dev", "auto-dev"):
            runs = [line for line in text(skill).splitlines()
                    if "python3" in line and "verify_merged.py" in line]
            self.assertTrue(runs, skill)
            for line in runs:
                self.assertIn("--open", line, f"{skill}: {line}")

    def test_dev_checks_closing_references_and_reopens(self):
        dev = text("dev")
        self.assertIn("closingIssuesReferences", dev)
        self.assertIn("gh issue reopen", dev)

    def test_dev_names_the_issue_without_a_closing_keyword(self):
        self.assertIn("Refs #", text("dev"))


if __name__ == "__main__":
    unittest.main()
