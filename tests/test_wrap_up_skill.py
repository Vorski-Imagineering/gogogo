#!/usr/bin/env python3
"""Tests for the shared /gogogo:wrap-up skill's memory review (gogogo#114).

The skill is prose, so these pin what a reader of it depends on: the pointer
from section 2 to the reference, the reference's outcomes, marker and privacy
step, the expiry test (a memory expires on "until #n", not on any issue
mention), and that memories never block closing. Whether it behaves is a
trigger run, not a phrase match.

    python3 -m unittest tests.test_wrap_up_skill
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "plugins" / "gogogo" / "skills" / "wrap-up"
SKILL = SKILL_DIR / "SKILL.md"
REVIEW = SKILL_DIR / "references" / "memory-review.md"
POINTER = "references/memory-review.md"


def skill_text():
    return SKILL.read_text(encoding="utf-8")


def review_text():
    return REVIEW.read_text(encoding="utf-8")


def between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def heading_section(text, heading):
    return between(text + "\n## END", heading, "\n## ")


class MemoryReview(unittest.TestCase):
    def test_section_two_points_at_memory_review(self):
        self.assertIn(POINTER, heading_section(skill_text(), "## 2. Capture learnings"))
        self.assertTrue(REVIEW.is_file())

    def test_memory_review_names_its_outcomes(self):
        text = review_text()
        for word in ("covered", "every-repo", "this-repo", "stays",
                     ".gogogo-memory-review", "/gogogo:idea"):
            with self.subTest(word=word):
                self.assertIn(word, text)

    def test_memory_review_names_privacy(self):
        self.assertIn("tracker.public", review_text())

    def test_expiry_matches_until_not_any_issue(self):
        text = review_text()
        step = heading_section(text, "## 1. Expiry")
        self.assertIn("until #", step)
        self.assertRegex(step, r"(?i)only when[^.]*until")
        self.assertRegex(step, r"(?i)never[^.]*(example|evidence)|(example|evidence)[^.]*never")

    def test_memories_never_block(self):
        sec = heading_section(skill_text(), "## 3. Verdict")
        blocking = between(sec, "**Blocks closing**", "**Doesn't block")
        self.assertNotRegex(blocking, r"(?i)memor.*review|memories")
        named = between(sec, "**Doesn't block", "Write the verdict")
        self.assertRegex(named, r"(?i)memories")

    def test_privacy_is_keyed_to_the_target(self):
        step = heading_section(review_text(), "## 3. Proposals")
        self.assertRegex(step, r"(?i)every-repo[^.]*always[^.]*(removed|stripped)")
        self.assertNotRegex(step, r"(?i)this-repo[^.]*(unstripped|always shown as it is)")
        self.assertRegex(step, r"(?i)this-repo[^.]*(stripped|removed)\s+whenever\s+`tracker\.public` is true")
        self.assertRegex(step, r"(?i)(as it is|unstripped)[^.]*only when[^.]*tracker\.public[^.]*false")

    def test_the_index_and_marker_are_never_scanned(self):
        text = review_text()
        for heading in ("## 1. Expiry", "## 2. Promotion"):
            with self.subTest(step=heading):
                step = heading_section(text, heading)
                self.assertIn("MEMORY.md", step)
                self.assertIn(".gogogo-memory-review", step)
                self.assertRegex(step, r"(?i)\b(skip|exclude)\b[^.]*\bboth\b")

    def test_a_failed_read_keeps_the_memory(self):
        step = heading_section(review_text(), "## 1. Expiry")
        self.assertIn("could not tell whether #", step)
        self.assertRegex(step, r"(?i)never delete on a failed read")
        self.assertRegex(step, r"(?i)another repo")

    def test_the_marker_waits_for_answers_and_reads(self):
        step = heading_section(review_text(), "## 4. Marker")
        self.assertRegex(step, r"(?i)only when every proposal[^.]*(yes|no)")
        self.assertRegex(step, r"(?i)every\s+expiry\s+read\s+succeeded")
        self.assertRegex(step, r"(?i)every\s+yes[^.]*(carried out|landed|filed or written)")
        self.assertRegex(step, r"(?i)do not touch")

    def test_the_pointer_says_covered_memories_are_deleted_or_shortened(self):
        sec = heading_section(skill_text(), "## 2. Capture learnings")
        para = sec[sec.index("**Memories saved before this session.**"):]
        self.assertIn("**REQUIRED REFERENCE:**", para)
        self.assertRegex(para, r"(?i)cover(ed|s)")
        self.assertRegex(para, r"(?i)shorten")

    def test_the_skill_stays_within_budget_and_names_no_project(self):
        self.assertLessEqual(len(skill_text().splitlines()), 500)
        for p in (SKILL, REVIEW):
            if p.is_file():
                self.assertIsNone(re.search(
                    r"(?i)manage\.py|npm |firebase|django|htmx|sentry",
                    p.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
