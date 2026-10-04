"""A merge leaves its issue open (gogogo#34).

A structure test: it pins the flag and the commands the skills run, not
sentences.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "gogogo" / "skills"


def text(skill):
    """The skill as the agent reads it: SKILL.md, then the references it
    points to, which hold its hand-back and merge steps (gogogo#130)."""
    paths = [SKILLS / skill / "SKILL.md"] + sorted((SKILLS / skill / "references").glob("*.md"))
    return "\n".join(p.read_text(encoding="utf-8") for p in paths)


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


class OneMergeProcedure(unittest.TestCase):
    """Both skills merge through `merge_ready.py` and pin the head they verified (gogogo#88)."""

    FILES = (SKILLS / "dev" / "references" / "hand-back.md", SKILLS / "auto-dev" / "references" / "merge.md")

    def test_each_names_the_script_and_the_pinned_head(self):
        for path in self.FILES:
            body = path.read_text(encoding="utf-8")
            for name in ("merge_ready.py", "--match-head-commit"):
                self.assertIn(name, body, f"{path.name}: {name}")

    def test_neither_uses_admin_or_auto_except_to_forbid_them(self):
        for path in self.FILES:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"--admin|--auto\b|--disable-auto", line):
                    self.assertRegex(line, r"(?i)\bnever\b", f"{path.name}:{number}: {line}")

    def test_the_merge_stop_is_a_stop_reason(self):
        import sys
        sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))
        import review_stats
        self.assertIn("merge", review_stats.STOPS)


if __name__ == "__main__":
    unittest.main()
