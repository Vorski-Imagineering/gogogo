#!/usr/bin/env python3
"""Length of each skill's SKILL.md, and how its reference files hang off it
(gogogo#130).

Anthropic's skill guidance keeps a SKILL.md under 500 lines and puts a step's
full rules in reference files, one level deep, each read when its step starts.
These pin that shape: the limit, every reference named from its skill, no
reference naming another, a contents list on a long one, and a pointer under
each heading whose text moved. Whether an agent then reads the reference is a
scenario run, not a test here (CLAUDE.md § Tests).

    python3 -m unittest tests.test_skill_budget
"""

import re
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "skills"
LIMIT = 500

# Each heading whose text moved to a reference file, and that file (#130).
MOVED = {
    "dev": [("## 5. Review", "review.md"),
            ("## 6. Verify", "verify.md"),
            ("## 8. Hand back", "hand-back.md")],
    "auto-dev": [("## 3. Branch from a fresh base", "branch.md"),
                 ("## 6. Merge", "merge.md")],
    "spec": [("## Several issues in one run", "several-issues.md"),
             ("## `## Verify by hand`", "verify-by-hand.md"),
             ("## Posting", "posting.md")],
}


def skill_files(root=SKILLS):
    return sorted(root.glob("*/SKILL.md"))


def references(root=SKILLS):
    return sorted(root.glob("*/references/*.md"))


def section(text, heading):
    """The lines under the first line starting with `heading`, up to the next `## `."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    body = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


class Budget(unittest.TestCase):
    def test_every_skill_is_within_the_limit(self):
        over = [f"{p.parent.name}: {n}" for p in skill_files()
                if (n := len(p.read_text(encoding="utf-8").splitlines())) > LIMIT]
        self.assertEqual(over, [], f"SKILL.md over {LIMIT} lines")

    def test_the_skills_were_found(self):
        names = {p.parent.name for p in skill_files()}
        self.assertLessEqual({"dev", "auto-dev", "spec"}, names)

    def test_every_reference_is_named_in_its_skill(self):
        unnamed = [str(p.relative_to(SKILLS)) for p in references()
                   if f"references/{p.name}" not in (p.parents[1] / "SKILL.md").read_text(encoding="utf-8")]
        self.assertEqual(unnamed, [])

    def test_no_reference_names_another(self):
        nested = []
        for p in references():
            text = p.read_text(encoding="utf-8")
            for other in p.parent.glob("*.md"):
                if other != p and f"references/{other.name}" in text:
                    nested.append(f"{p.relative_to(SKILLS)} names {other.name}")
        self.assertEqual(nested, [])

    def test_a_long_reference_opens_with_contents(self):
        missing = [str(p.relative_to(SKILLS)) for p in references()
                   if len(lines := p.read_text(encoding="utf-8").splitlines()) > 100
                   and "## Contents" not in lines[:10]]
        self.assertEqual(missing, [])

    def test_each_moved_step_points_at_its_file(self):
        for skill, moves in MOVED.items():
            text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            for heading, name in moves:
                with self.subTest(skill=skill, heading=heading):
                    self.assertIn(f"references/{name}", section(text, heading))
                    self.assertTrue((SKILLS / skill / "references" / name).is_file())
                    self.assertIsNone(re.search(r"^### ", section(text, heading), re.M),
                                      "a moved step keeps no subsection in SKILL.md")


if __name__ == "__main__":
    unittest.main()
