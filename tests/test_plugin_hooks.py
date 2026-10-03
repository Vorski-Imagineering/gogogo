#!/usr/bin/env python3
"""Tests for the plugin's hooks: what runs in every adopting repo at session start.

    python3 -m unittest tests.test_plugin_hooks
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
HOOKS = PLUGIN / "hooks" / "hooks.json"


class PluginHooks(unittest.TestCase):
    def test_one_session_start_hook_runs_waiting_within_its_timeout(self):
        events = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(list(events), ["SessionStart"])
        hooks = [h for group in events["SessionStart"] for h in group["hooks"]]
        self.assertEqual(len(hooks), 1, hooks)
        self.assertEqual(hooks[0]["type"], "command")
        self.assertIn("scripts/waiting.py\" --hook", hooks[0]["command"])
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", hooks[0]["command"])
        self.assertLessEqual(hooks[0]["timeout"], 30)
        self.assertTrue((PLUGIN / "scripts" / "waiting.py").is_file())


if __name__ == "__main__":
    unittest.main()
