#!/usr/bin/env python3
"""Tests for the spec-check record that /gogogo:dev §7 asks for on each issue.

The spec check in §5 is wording and is checked by scenario runs (CLAUDE.md §
Tests); the only tests of it here pin the reader's brief to what
`spec_check.py verify` accepts (gogogo#81). The record is a template `review_stats.py`
parses, so these pin its keys, its worked example, its allowed values, and
where the skills and README name the check (gogogo#44).

    python3 -m unittest tests.test_spec_check_record
"""

import contextlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
DEV = PLUGIN / "skills" / "dev" / "SKILL.md"
DEV_REVIEW = PLUGIN / "skills" / "dev" / "references" / "review.md"
AUTO_DEV = PLUGIN / "skills" / "auto-dev" / "SKILL.md"
SPEC = PLUGIN / "skills" / "spec" / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "scripts"))

import review_stats  # noqa: E402
import spec_check  # noqa: E402

KEYS = ["v", "items", "met", "missing", "differs", "na", "outside", "runs", "fixed", "declared", "reader", "end"]
MARKER = re.compile(r"<!-- gogogo:spec-check (.*?) -->")
# Design 4's worked example, verbatim.
EXAMPLE = ("<!-- gogogo:spec-check v=1 items=62 met=57 missing=1 differs=3 na=1 outside=1 runs=2 fixed=2 "
           "declared=3 reader=fresh end=declared -->")


def section(text, start, end):
    return text.split(f"\n## {start}")[1].split(f"\n## {end}")[0]


def template():
    lines = [line for line in section(DEV.read_text(encoding="utf-8"), "7.", "8.").splitlines()
             if "<!-- gogogo:spec-check " in line]
    return lines


class Template(unittest.TestCase):
    def test_one_template_with_its_keys_in_order(self):
        lines = template()
        self.assertEqual(len(lines), 1, lines)
        keys = [part.split("=", 1)[0] for part in MARKER.search(lines[0]).group(1).split(" ")]
        self.assertEqual(keys, KEYS)

    def test_allowed_values_match_the_parser(self):
        fields = dict(part.split("=", 1) for part in MARKER.search(template()[0]).group(1).split(" "))
        self.assertEqual(tuple(fields["end"].strip("<>").split("|")), review_stats.SPEC_CHECK_ENDS)
        self.assertEqual(tuple(fields["reader"].strip("<>").split("|")), review_stats.SPEC_CHECK_READERS)


class Example(unittest.TestCase):
    def test_the_example_parses_and_adds_up(self):
        record = review_stats.parse_spec_check(EXAMPLE)
        self.assertIsNotNone(record)
        self.assertEqual(record["items"], record["met"] + record["missing"] + record["differs"] + record["na"])


class Skill(unittest.TestCase):
    """§5's reader brief names only what `spec_check.py verify` accepts (gogogo#81)."""

    def brief(self):
        text = DEV_REVIEW.read_text(encoding="utf-8")
        return text[text.index("It is told:"):text.index("It does not judge quality")]

    def test_the_brief_names_only_evidence_forms_verify_accepts(self):
        forms = sorted(set(re.findall(r"`(path[^`]*)`", self.brief())))
        self.assertGreaterEqual(len(forms), 3, forms)
        self.assertFalse([f for f in re.findall(r"`([^`]*)`", self.brief()) if re.search(r":[^`]*-", f)])
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
            Path("a.py").write_text("def name():\n    pass\n")
            for form in forms:
                evidence = form.replace("path", "a.py", 1).replace("line", "1").replace("::name", "::name")
                self.assertIsNone(spec_check._resolves(evidence), form)

    def test_the_brief_names_which_items_need_evidence(self):
        bullets = [b for b in re.split(r"\n  - ", self.brief()) if "always have evidence" in b]
        self.assertEqual(len(bullets), 1, bullets)
        for letter in spec_check.NEEDS_EVIDENCE:
            self.assertIn(f"`{letter}`", bullets[0])


class Named(unittest.TestCase):
    def test_dev_names_the_script(self):
        self.assertIn("scripts/spec_check.py", DEV_REVIEW.read_text(encoding="utf-8"))

    def test_auto_dev_hands_a_stopped_check_to_needs_human(self):
        four = section(AUTO_DEV.read_text(encoding="utf-8"), "4.", "5.")
        bullets = re.split(r"\n- ", four)
        self.assertTrue([b for b in bullets if "spec check" in b and "needs_human" in b], four)

    def test_spec_names_the_file_groups(self):
        text = SPEC.read_text(encoding="utf-8")
        for marker in ("**Create:**", "**Edit:**", "**Explicitly not in scope:**"):
            self.assertIn(marker, text)

    def test_readme_lists_the_script(self):
        lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
        self.assertTrue([ln for ln in lines if ln.startswith("- `spec_check.py`")])


if __name__ == "__main__":
    unittest.main()
