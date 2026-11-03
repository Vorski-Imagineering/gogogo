#!/usr/bin/env python3
"""Structure of /gogogo:log-review.

These pin the settings and commands the skill depends on, never its sentences
(CLAUDE.md § Tests); whether it behaves is its eval cases.

    python3 -m unittest tests.test_log_review_skill
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "plugins" / "gogogo" / "skills" / "log-review"
SKILL = SKILL_DIR / "SKILL.md"
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import profile_check as pc  # noqa: E402


def text():
    return SKILL.read_text(encoding="utf-8")


class SkillNamesTheSettingsItDependsOn(unittest.TestCase):
    def test_names_each_setting_and_its_profile_check(self):
        body = text()
        for word in ('profile_check.py" --for log-review --show', "`logs`", "tracker.issues_repo",
                     "tracker.public", "`stages`", "`tag`", "`writes`", "/gogogo:setup"):
            self.assertIn(word, body)

    def test_the_skill_folder_and_the_checker_use_one_name(self):
        self.assertEqual(SKILL_DIR.name, pc.LOG)
        self.assertIn(pc.LOG, pc.SKILLS)
        self.assertIn(f"name: {pc.LOG}\n", text())


class TheCommandsItRuns(unittest.TestCase):
    def test_reads_the_label_the_deploy_tags_and_the_deployed_commit(self):
        body = text()
        for word in ("--label log-review --state all", "git tag -l '<tag>'",
                     "git merge-base --is-ancestor <fix> <deployed commit>"):
            self.assertIn(word, body)

    def test_closes_nothing_and_never_force_pushes(self):
        body = text()
        self.assertIsNone(re.search(r"gh issue close|--force\b|push -f\b", body))


class Size(unittest.TestCase):
    def test_at_most_200_lines(self):
        self.assertLessEqual(len(text().splitlines()), 200)


class NoProjectNames(unittest.TestCase):
    def test_no_stack_server_or_repo_names(self):
        for path in SKILL_DIR.rglob("*"):
            if not path.is_file():
                continue
            body = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"manage\.py|npm |firebase|django|htmx|sentry", body, re.I), path)
            # Which logs and services a repo has is its own, in the doc `logs` names.
            self.assertIsNone(re.search(r"nginx|journalctl|journald|gunicorn|systemd|/var/log|/srv/", body, re.I),
                              path)
            self.assertIsNone(re.search(r"[A-Za-z0-9-]+/[A-Za-z0-9-]*-pub\b|vvorski|METIS", body), path)


if __name__ == "__main__":
    unittest.main()
