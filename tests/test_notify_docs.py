#!/usr/bin/env python3
"""The places that tell an agent or a person how messages are sent.

Structure, not sentences: each names the sender and the commands it relies on,
and the README carries the launch line that names a run's session.

    python3 -m unittest tests.test_notify_docs
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"


def text(path):
    return path.read_text(encoding="utf-8")


def section(doc, heading):
    """The text under a `### ` or `## ` heading, up to the next heading of that level or above."""
    level = heading.split(" ", 1)[0]
    start = doc.index(heading + "\n")
    rest = doc[start + len(heading):]
    stop = re.search(rf"(?m)^#{{1,{len(level)}}} ", rest)
    return rest[:stop.start()] if stop else rest


class NotifyDocs(unittest.TestCase):
    def test_13_auto_dev_sends_and_checks_through_the_script(self):
        doc = text(PLUGIN / "skills" / "auto-dev" / "SKILL.md")
        self.assertIn('scripts/notify.py" send', doc)
        self.assertIn('scripts/notify.py" status', doc)

    def test_14_setup_walks_through_the_script(self):
        doc = text(PLUGIN / "skills" / "setup" / "SKILL.md")
        self.assertIn('notify.py" init', doc)
        self.assertIn('notify.py" chat-id --save', doc)
        self.assertIn("INFO notify: off", doc)

    def test_12_setup_offers_this_repo_and_no_messages(self):
        doc = text(PLUGIN / "skills" / "setup" / "SKILL.md")
        notifications = doc.split("- **Notifications**", 1)[1].split("\n## ", 1)[0]
        self.assertIn('notify.py" init --repo', notifications)
        self.assertIn(".claude/gogogo/", notifications)
        self.assertIn('notify = "none"', notifications)
        self.assertNotIn('notify = "telegram"', notifications)

    def test_15_stage_sync_uses_the_same_sender(self):
        doc = text(PLUGIN / "references" / "stage-sync.md")
        self.assertIn("notify.py", section(doc, "### Notification"))
        self.assertIn("notify.py", section(doc, "### Vendoring"))
        self.assertNotIn("repo's own transport", doc)

    def test_16_readme_launch_line_names_the_session(self):
        lines = [line for line in text(ROOT / "README.md").splitlines()
                 if "claude -n" in line and '-autodev"' in line and "/gogogo:auto-dev" in line]
        self.assertTrue(lines)


if __name__ == "__main__":
    unittest.main()
