#!/usr/bin/env python3
"""Tests for gogogo's own release tagging: the workflow that cuts deploy-<build>.

Read as text, standard library only: the checks are the lines that make the
workflow safe (main only, after the tests, full history, write access).

    python3 -m unittest tests.test_release_workflow
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import profile_check as pc  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


class ReleaseWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_only_after_the_tests_pass_on_a_push_to_main(self):
        trigger = self.text.split("\non:", 1)[1].split("\npermissions:", 1)[0].split("\njobs:", 1)[0]
        self.assertNotIn("pull_request", trigger)
        self.assertRegex(trigger, r"workflow_run:\s*\n\s+workflows:\s*\[\s*\"?tests\"?\s*\]")
        self.assertRegex(trigger, r"branches:\s*\[\s*main\s*\]")
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.text)
        self.assertIn("github.event.workflow_run.event == 'push'", self.text)

    def test_tags_the_tested_commit_with_full_history_and_write_access(self):
        self.assertRegex(self.text, r"(?m)^\s*contents:\s*write\s*$")
        self.assertRegex(self.text, r"fetch-depth:\s*0\b")
        self.assertIn("ref: ${{ github.event.workflow_run.head_sha }}", self.text)
        self.assertRegex(self.text, r"release\.py --profile \.agents/dev-process\.md tag --push origin")

    def test_no_concurrency_group_so_no_queued_run_is_dropped(self):
        """A group keeps one pending run, so a merge's tag would be skipped under a burst; tags differ per commit."""
        self.assertNotIn("concurrency:", self.text)

    def test_the_profile_adopts_the_release_standard(self):
        settings, _ = pc.split_profile((ROOT / ".agents" / "dev-process.md").read_text(encoding="utf-8"))
        self.assertEqual(settings.get("release"), {"major": 1})


if __name__ == "__main__":
    unittest.main()
