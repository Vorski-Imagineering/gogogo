#!/usr/bin/env python3
"""The plugin's build agents for an authorised effort (gogogo#159): each names its effort, inherits the
session's model, and carries no permission, hook or server key a plugin agent may not set.

    python3 -m unittest tests.test_build_agents
"""

import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "agents"
FORBIDDEN = ("permissionMode", "hooks", "mcpServers")


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    head, _, _ = text[len("---\n"):].partition("\n---\n")
    return dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)


class BuildAgents(unittest.TestCase):
    def test_each_effort_has_an_agent_that_names_it(self):
        for effort in ("high", "xhigh", "max"):
            with self.subTest(effort=effort):
                fm = frontmatter(AGENTS / f"build-{effort}.md")
                self.assertEqual(fm["effort"], effort)
                self.assertEqual(fm["model"], "inherit")
                self.assertEqual(fm["name"], f"build-{effort}")

    def test_no_agent_sets_a_key_a_plugin_agent_may_not(self):
        for path in AGENTS.glob("build-*.md"):
            fm = frontmatter(path)
            for key in FORBIDDEN:
                with self.subTest(agent=path.name, key=key):
                    self.assertNotIn(key, fm)


if __name__ == "__main__":
    unittest.main()
