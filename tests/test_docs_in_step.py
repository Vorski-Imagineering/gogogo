#!/usr/bin/env python3
"""Tests that README.md and docs/git-process.md name only what exists.

The two docs drifted from the skills more than once (gogogo#61). What a test
can pin is the names they spell: every script they name is a file in the
plugin's scripts folder, README lists every script there, and every profile
setting they name is one `profile_check.py` knows. Whether a sentence about
behaviour is still true is caught by the re-read this repo's profile asks for
(`## Lane constraints`, *docs in step*), not here.

    python3 -m unittest tests.test_docs_in_step
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
SCRIPTS = PLUGIN / "scripts"
DOCS = [ROOT / "README.md", ROOT / "docs" / "git-process.md"]
sys.path.insert(0, str(SCRIPTS))

import profile_check as pc  # noqa: E402

SCRIPT = re.compile(r"\b([a-z_]+\.(?:py|sh))\b")
SPAN = re.compile(r"`([^`\n]+)`")
SETTING = re.compile(r"[a-z_]+(?:\.[a-z_]+)+")
EXTENSIONS = {"py", "sh", "md", "json", "yml", "yaml", "toml", "txt"}


def settings_named(text):
    found = set()
    for span in SPAN.findall(text):
        span = re.sub(r"\s*=.*", "", span)
        if "/" in span or "-" in span or not SETTING.fullmatch(span):
            continue
        if span.rsplit(".", 1)[1] in EXTENSIONS:
            continue
        found.add(span)
    return found


class DocsInStep(unittest.TestCase):
    def test_docs_name_only_existing_scripts(self):
        seen = set()
        for doc in DOCS:
            for name in set(SCRIPT.findall(doc.read_text(encoding="utf-8"))):
                seen.add(name)
                self.assertTrue((SCRIPTS / name).is_file(), f"{doc.name} names {name}, which is not in {SCRIPTS}")
        self.assertGreaterEqual(len(seen), 10, seen)

    def test_readme_lists_every_script(self):
        lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
        scripts = sorted(p.name for p in SCRIPTS.iterdir() if p.is_file() and p.suffix in (".py", ".sh"))
        self.assertTrue(scripts)
        for name in scripts:
            self.assertTrue([ln for ln in lines if ln.startswith(f"- `{name}`")], f"README does not list {name}")

    def test_readme_names_the_session_start_line_and_reverts(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("waiting.py", readme)
        self.assertRegex(readme, r"stage_sync\.py.*\breverts\b")

    def test_docs_name_only_known_settings(self):
        seen = set()
        for doc in DOCS:
            for name in settings_named(doc.read_text(encoding="utf-8")):
                seen.add(name)
                self.assertIn(name, pc.FIELDS, f"{doc.name} names the setting {name}, which profile_check does not know")
        self.assertGreaterEqual(len(seen), 8, seen)
        self.assertIn("handback.reporter", seen)

    def test_file_names_are_not_settings(self):
        text = ("`profile-schema.md` `.claude/settings.json` `stage-sync.md` `tests.yml` `spec_lint.py` "
                "`handback.reporter = \"trailer\"`")
        self.assertEqual(settings_named(text), {"handback.reporter"})

    def test_profile_points_at_the_docs(self):
        profile = (ROOT / ".agents" / "dev-process.md").read_text(encoding="utf-8")
        _, sections = pc.split_profile(profile)
        lanes = sections["Lane constraints"]
        self.assertIn("README.md", lanes)
        self.assertIn("docs/git-process.md", lanes)


if __name__ == "__main__":
    unittest.main()
