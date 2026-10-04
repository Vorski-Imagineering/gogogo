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

    def test_every_merge_command_is_pinned_to_the_verified_head(self):
        docs = ROOT / "docs" / "git-process.md"
        for path in (*self.FILES, docs):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"gh pr merge <pr>", line):
                    self.assertIn("--match-head-commit", line, f"{path.name}:{number}: {line}")

    def test_the_merge_comes_in_squash_and_merge_commit_forms_with_and_without_a_body(self):
        body = self.FILES[0].read_text(encoding="utf-8")
        commands = [line.strip() for line in body.splitlines() if line.strip().startswith("gh pr merge <pr>")]
        self.assertTrue(any("--squash" in c and "--body-file" in c for c in commands), commands)
        self.assertTrue(any("--squash" in c and "--body-file" not in c for c in commands), commands)
        self.assertTrue(any("--merge " in c for c in commands), commands)

    def test_the_branch_must_contain_the_base_before_it_is_recorded_as_verified(self):
        body = self.FILES[0].read_text(encoding="utf-8")
        self.assertIn("git merge-base --is-ancestor origin/<base> HEAD", body)

    def test_a_non_zero_merge_exit_is_checked_with_verify_merged(self):
        body = self.FILES[0].read_text(encoding="utf-8")
        step = body.split("8. **After the command.**")[1].split("\n**The base moved**")[0]
        after = step.split("A non-zero exit")[1]
        self.assertLess(after.index("verify_merged.py"), after.index("stop reason"))

    def test_an_unreadable_pr_and_a_changed_head_have_an_outcome(self):
        body = self.FILES[0].read_text(encoding="utf-8")
        step = body.split("6. **By the outcome**")[1].split("7. **Merge only")[0]
        self.assertIn("exit 2", step)
        self.assertIn("<verified sha>", step)

    def test_a_head_that_changed_is_fetched_and_merged_in_before_it_is_recorded_again(self):
        body = self.FILES[0].read_text(encoding="utf-8")
        branch = body.split("`ready`: the sha after it")[1].split("go on to 7")[0]
        self.assertIn("git fetch origin <headRefName>", branch)
        self.assertIn("git merge origin/<headRefName>", branch)
        self.assertLess(branch.index("git merge origin/<headRefName>"), branch.index("step 2"))
        self.assertIn("the head changed after verification", branch)

    def test_the_merge_stop_is_a_stop_reason(self):
        import sys
        sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))
        import review_stats
        self.assertIn("merge", review_stats.STOPS)


if __name__ == "__main__":
    unittest.main()
