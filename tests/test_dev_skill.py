#!/usr/bin/env python3
"""Structure of how /gogogo:dev and /gogogo:auto-dev judge a run green (gogogo#105).

A lane or gate passes on its command's own exit status, with the output saved
to a file, never on filtered output. These pin the command and the names the
rule depends on, never its sentences (CLAUDE.md § Tests); whether it behaves
is a scenario run.

    python3 -m unittest tests.test_dev_skill
"""

import re
import sys
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "skills"
DEV = SKILLS / "dev" / "SKILL.md"
AUTO_DEV = SKILLS / "auto-dev" / "SKILL.md"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tech_eval import PROJECT_NAMES  # noqa: E402


def section(text, heading):
    return text.split(f"\n## {heading}")[1].split("\n## ")[0]


class ExitStatus(unittest.TestCase):
    def setUp(self):
        self.dev = DEV.read_text(encoding="utf-8")
        self.auto_dev = AUTO_DEV.read_text(encoding="utf-8")

    def test_verify_saves_the_output_and_reads_the_status(self):
        verify = section(self.dev, "6.")
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

    def test_no_project_names(self):
        for path in (DEV, AUTO_DEV):
            self.assertIsNone(re.search(PROJECT_NAMES, path.read_text(encoding="utf-8"), re.I), path)


if __name__ == "__main__":
    unittest.main()
