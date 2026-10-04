#!/usr/bin/env python3
"""Structure of /gogogo:dev and /gogogo:auto-dev: how a run is judged green
(gogogo#105) and how the whole issue is read (gogogo#108).

A lane or gate passes on its command's own exit status, with the output saved
to a file, never on filtered output. A comment from someone with write access
counts like the description once §2 folds it in. These pin the commands,
fields and names the rules depend on, never their sentences (CLAUDE.md §
Tests); whether it behaves is a scenario run.

    python3 -m unittest tests.test_dev_skill
"""

import re
import sys
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "skills"
DEV = SKILLS / "dev" / "SKILL.md"
AUTO_DEV = SKILLS / "auto-dev" / "SKILL.md"
DEV_VERIFY = SKILLS / "dev" / "references" / "verify.md"
DEV_HAND_BACK = SKILLS / "dev" / "references" / "hand-back.md"
SKILL = DEV
FOLD = "### Fold in comments the description does not hold yet"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tech_eval import PROJECT_NAMES  # noqa: E402


def section(text, heading):
    return text.split(f"\n## {heading}")[1].split("\n## ")[0]


def moved(path):
    """A reference file's text after its title, note and Contents list: the
    section it holds, as it stood in SKILL.md (gogogo#130)."""
    lines = path.read_text(encoding="utf-8").split("\n")
    i = next(n for n, ln in enumerate(lines) if ln.startswith("Part of ")) + 1
    while i < len(lines) and not lines[i]:
        i += 1
    if i < len(lines) and lines[i] == "## Contents":
        i += 1
        while i < len(lines) and (not lines[i] or lines[i].startswith("- ")):
            i += 1
    return "\n".join(lines[i:])


class WholeIssue(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")
        self.read = section(self.text, "1. ")
        self.triage = section(self.text, "2. ")

    def fold(self):
        self.assertIn(FOLD, self.triage)
        return self.triage.split(FOLD)[1].split("\n### ")[0]

    def test_the_old_rule_is_gone(self):
        self.assertNotIn("A comment does not count", self.triage)

    def test_the_fold_filters_are_named(self):
        for name in ("collaborators/", "/permission", "lastEditedAt", "<!-- gogogo:", "**Needs you:**"):
            self.assertIn(name, self.triage)

    def test_the_fold_is_linted_before_it_is_posted(self):
        lines = self.fold().splitlines()
        lint = next((i for i, line in enumerate(lines) if "spec_lint.py" in line), None)
        edit = next((i for i, line in enumerate(lines) if "gh issue edit" in line), None)
        self.assertIsNotNone(lint)
        self.assertIsNotNone(edit)
        self.assertLess(lint, edit)

    def test_read_fetches_the_comments_and_the_last_edit(self):
        for name in ("lastEditedAt", "comments(first:100)"):
            self.assertIn(name, self.read)


class ExitStatus(unittest.TestCase):
    def setUp(self):
        self.dev = DEV.read_text(encoding="utf-8")
        self.auto_dev = AUTO_DEV.read_text(encoding="utf-8")

    def test_verify_saves_the_output_and_reads_the_status(self):
        verify = moved(DEV_VERIFY)
        blocks = re.findall(r"```bash\n(.*?)```", verify, re.S)
        self.assertTrue(
            any('echo "exit=$?"' in b and "> <scratch>/" in b for b in blocks), blocks)

    def test_do_not_chain_a_commit_on_piped_output(self):
        lines = section(self.dev, "Do not").splitlines()
        self.assertTrue(any("piped" in l and "commit" in l for l in lines), lines)

    def test_auto_dev_gates_pass_on_exit_status(self):
        gates = section(self.auto_dev, "5.")
        for name in ("exit status", "/gogogo:dev` §6"):
            self.assertIn(name, gates)

    def test_hand_back_deletes_the_merged_local_branch_of_checkout_work(self):
        """Work done in the checkout leaves its local branch after a verified merge (gogogo#169)."""
        text = DEV_HAND_BACK.read_text(encoding="utf-8")
        paragraph = next(p for p in text.split("\n\n") if "git branch -D <branch>" in p)
        self.assertIn("--match-head-commit", paragraph)
        self.assertIn("git rev-parse <branch>", paragraph)
        self.assertIn("git switch <base>", paragraph)

    def test_no_project_names(self):
        for path in (DEV, AUTO_DEV):
            self.assertIsNone(re.search(PROJECT_NAMES, path.read_text(encoding="utf-8"), re.I), path)


if __name__ == "__main__":
    unittest.main()
