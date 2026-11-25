#!/usr/bin/env python3
"""Structure of /gogogo:dev and /gogogo:auto-dev: how a run is judged green
(gogogo#105) and how the whole issue is read (gogogo#108).

A lane or gate passes on its command's own exit status, with the output saved
to a file, never on filtered output. A comment from someone with write access
counts like the description once §2 folds it in. These pin the commands,
fields and names the rules depend on, never their sentences (CLAUDE.md §
Tests); whether it behaves is a scenario run.

    python3 -m unittest tests.test_dev_skill
"""

import re
import sys
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "skills"
DEV = SKILLS / "dev" / "SKILL.md"
AUTO_DEV = SKILLS / "auto-dev" / "SKILL.md"
DEV_VERIFY = SKILLS / "dev" / "references" / "verify.md"
DEV_HAND_BACK = SKILLS / "dev" / "references" / "hand-back.md"
SKILL = DEV
FOLD = "### Fold in comments the description does not hold yet"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tech_eval import PROJECT_NAMES  # noqa: E402


def section(text, heading):
    return text.split(f"\n## {heading}")[1].split("\n## ")[0]


def moved(path):
    """A reference file's text after its title, note and Contents list: the
    section it holds, as it stood in SKILL.md (gogogo#130)."""
    lines = path.read_text(encoding="utf-8").split("\n")
    i = next(n for n, ln in enumerate(lines) if ln.startswith("Part of ")) + 1
    while i < len(lines) and not lines[i]:
        i += 1
    if i < len(lines) and lines[i] == "## Contents":
        i += 1
        while i < len(lines) and (not lines[i] or lines[i].startswith("- ")):
            i += 1
    return "\n".join(lines[i:])


class WholeIssue(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")
        self.read = section(self.text, "1. ")
        self.triage = section(self.text, "2. ")

    def fold(self):
        self.assertIn(FOLD, self.triage)
        return self.triage.split(FOLD)[1].split("\n### ")[0]

    def test_the_old_rule_is_gone(self):
        self.assertNotIn("A comment does not count", self.triage)

    def test_the_fold_filters_are_named(self):
        for name in ("collaborators/", "/permission", "lastEditedAt", "<!-- gogogo:", "**Needs you:**"):
            self.assertIn(name, self.triage)

    def test_the_fold_is_linted_before_it_is_posted(self):
        lines = self.fold().splitlines()
        lint = next((i for i, line in enumerate(lines) if "spec_lint.py" in line), None)
        edit = next((i for i, line in enumerate(lines) if "gh issue edit" in line), None)
        self.assertIsNotNone(lint)
        self.assertIsNotNone(edit)
        self.assertLess(lint, edit)

    def test_read_fetches_the_comments_and_the_last_edit(self):
        for name in ("lastEditedAt", "comments(first:100)"):
            self.assertIn(name, self.read)


class ExitStatus(unittest.TestCase):
    def setUp(self):
        self.dev = DEV.read_text(encoding="utf-8")
        self.auto_dev = AUTO_DEV.read_text(encoding="utf-8")

    def test_verify_saves_the_output_and_reads_the_status(self):
        verify = moved(DEV_VERIFY)
        blocks = re.findall(r"```bash\n(.*?)```", verify, re.S)
        self.assertTrue(
            any('echo "exit=$?"' in b and "> <scratch>/" in b for b in blocks), blocks)

    def test_a_refusal_the_spec_contradicts_stops_before_any_restore(self):
        # gogogo#260: step 5 stops at once, reason `tests`, quoting the spec line, before it restores.
        step = re.search(r"^5\. Exit 1:.*?(?=^6\. )", moved(DEV_VERIFY), re.S | re.M).group(0)
        stop, _, rest = step.partition("Otherwise")
        self.assertIn("restore what the test guarded", rest)
        for name in ("`tests`", "§8", "quot"):
            self.assertIn(name, stop, "the quoted stop comes before the restore, not after it")

    def test_do_not_chain_a_commit_on_piped_output(self):
        lines = section(self.dev, "Do not").splitlines()
        self.assertTrue(any("piped" in l and "commit" in l for l in lines), lines)

    def test_auto_dev_gates_pass_on_exit_status(self):
        gates = section(self.auto_dev, "5.")
        for name in ("exit status", "/gogogo:dev` §6"):
            self.assertIn(name, gates)

    def test_hand_back_deletes_the_merged_local_branch_of_checkout_work(self):
        """Work done in the checkout leaves its local branch after a verified merge (gogogo#169)."""
        text = DEV_HAND_BACK.read_text(encoding="utf-8")
        paragraph = next(p for p in text.split("\n\n") if "git branch -D <branch>" in p)
        self.assertIn("--match-head-commit", paragraph)
        self.assertIn("git rev-parse <branch>", paragraph)
        self.assertIn("git switch <base>", paragraph)

    def test_no_project_names(self):
        for path in (DEV, AUTO_DEV):
            self.assertIsNone(re.search(PROJECT_NAMES, path.read_text(encoding="utf-8"), re.I), path)



DEV_REVIEW = SKILLS / "dev" / "references" / "review.md"


class Authorisation(unittest.TestCase):
    """An authorisation from /gogogo:human-help is read and obeyed (gogogo#159)."""

    def test_reads_the_authorisation(self):
        text = DEV.read_text(encoding="utf-8")
        self.assertIn('human_help.py" authorised', section(text, "1. "))
        self.assertIn("gogogo:build-", text)
        self.assertIn("Authorised:", section(text, "7. "))

    def test_until_clean_at_each_limit(self):
        text = DEV_REVIEW.read_text(encoding="utf-8")
        rule = {n: text.split(f"\n{n}. **")[1].split(f"\n{n + 1}. **")[0] for n in (3, 4, 7, 8)}
        for n in (3, 7, 8):
            self.assertIn("review=until-clean", rule[n], f"rule {n}")
        self.assertNotIn("review=until-clean", rule[4], "a reversal still stops an authorised review")

    def test_until_clean_prose_has_a_refix_brake(self):
        # gogogo#259: under until-clean, a prose file that keeps fixing its own fixes ends `prose`.
        text = DEV_REVIEW.read_text(encoding="utf-8")
        rule = {n: text.split(f"\n{n}. **")[1].split(f"\n{n + 1}. **")[0] for n in (7, 8)}
        clean7 = rule[7][rule[7].index("review=until-clean"):]
        for name in ("refix", "`prose`"):
            self.assertIn(name, clean7)
        clean8 = rule[8][rule[8].index("review=until-clean"):]
        for name in ("`prose`", "rule 7"):
            self.assertIn(name, clean8, "prose ends an until-clean review only by rule 7's brake")


class TakeTheCard(unittest.TestCase):
    """§4 takes the card into In progress once the work has its place (gogogo#228)."""

    def setUp(self):
        self.lines = section(SKILL.read_text(encoding="utf-8"), "4. ").splitlines()

    def take(self):
        return [i for i, ln in enumerate(self.lines) if " move <n>" in ln and "--to in_progress" in ln]

    def test_one_take_with_from_to_in_progress(self):
        takes = self.take()
        self.assertEqual(len(takes), 1, takes)
        self.assertIn("--from", self.lines[takes[0]])

    def test_the_take_comes_after_the_placement(self):
        placed = max(i for i, ln in enumerate(self.lines) if "git worktree add -b fix/" in ln)
        self.assertGreater(self.take()[0], placed)

    def test_the_take_reads_the_card_first(self):
        placed = max(i for i, ln in enumerate(self.lines) if "git worktree add -b fix/" in ln)
        reads = [i for i, ln in enumerate(self.lines) if " show <n>" in ln]
        self.assertTrue(any(placed < i < self.take()[0] for i in reads), reads)

    def test_the_take_never_adds_a_card(self):
        self.assertNotIn("--add-missing", "\n".join(self.lines))



class ReachLine(unittest.TestCase):
    """gogogo#248: a bug finding says how production reaches it before anything changes."""

    def setUp(self):
        self.text = DEV_REVIEW.read_text(encoding="utf-8")
        self.rows = {int(m.group(1)): line for line in self.text.splitlines()
                     if (m := re.match(r"\s*\| (\d+) \|", line))}

    def test_the_reach_line_is_in_the_review(self):
        self.assertIn("**The reach line.**", self.text)
        self.assertLess(self.text.index(self.rows[7]), self.text.index("**The reach line.**"))

    def test_the_table_names_it_on_test_3_only(self):
        for row in (3, 7):
            self.assertIn("reach line", self.rows[row])
        for row in (1, 2, 4):
            self.assertNotIn("reach line", self.rows[row])


class NewCaseInCorrection(unittest.TestCase):
    """gogogo#296: a new case in a correction's lines is a new finding, not another attempt."""

    def test_rule_3_names_both_kinds(self):
        text = DEV_REVIEW.read_text(encoding="utf-8")
        rule = text.split("\n3. **")[1].split("\n4. **")[0]
        for name in ("**Again**", "**New**", "hypothetical"):
            self.assertIn(name, rule)

    def test_the_reach_line_points_at_rule_3(self):
        text = DEV_REVIEW.read_text(encoding="utf-8")
        paragraph = text.split("**The reach line.**")[1].split("\n3. **")[0]
        self.assertIn("rule 3", paragraph)

    def test_findings_table_has_a_kind_column(self):
        text = DEV.read_text(encoding="utf-8")
        self.assertIn("`| Id | Round | Test | Recorded as | Re-fixes | Kind |`", text)
        refix = text.split("`refix` counts")[1].split("\n  - ")[0]
        self.assertIn("both kinds", refix)


class SpecWording(unittest.TestCase):
    """gogogo#291: a bug finding about a rule is weighed against the spec's own words first."""

    def paragraph(self):
        text = DEV_REVIEW.read_text(encoding="utf-8")
        return text.split("**The spec's own wording.**")[1].split("\n3. **")[0]

    def test_the_paragraph_is_after_the_reach_line(self):
        text = DEV_REVIEW.read_text(encoding="utf-8")
        at = text.index("**The spec's own wording.**")
        self.assertLess(text.index("**The reach line.**"), at)
        self.assertLess(at, text.index("\n3. **"))

    def test_it_names_its_tests(self):
        for name in ("test 7", "settled", "test 5", "test 1, 2 or 4"):
            self.assertIn(name, self.paragraph())

    def test_the_brief_asks_for_the_spec_line(self):
        text = DEV_REVIEW.read_text(encoding="utf-8")
        rule = text.split("\n1. **")[1].split("\n2. **")[0]
        self.assertIn("spec's line", rule)

    def test_the_declined_line_quotes_the_spec(self):
        text = DEV.read_text(encoding="utf-8")
        rest = text.split("**Declined**:")[1]
        self.assertRegex(rest, r"more than\s+five\.")
        declined = re.split(r"more than\s+five\.", rest)[0]
        self.assertIn("quoted words", declined)


class AttemptLimit(unittest.TestCase):
    """gogogo#294: the attempt limit comes from until-clean, the run, the profile, or 3."""

    def test_rule_3_names_every_source(self):
        rule = DEV_REVIEW.read_text(encoding="utf-8").split("\n3. **")[1].split("\n4. **")[0]
        for name in ("review.attempts", "--attempts", "review=until-clean"):
            self.assertIn(name, rule)

    def test_the_report_names_the_limit(self):
        text = DEV.read_text(encoding="utf-8")
        reviewed = text.split("- **How it was reviewed**")[1].split("\n- **")[0]
        self.assertIn("attempt limit", reviewed)


class Excess(unittest.TestCase):
    """The review's table names only reasons review_stats.py counts, and the size is measured (gogogo#231)."""

    def test_recorded_as_words_are_the_counted_reasons(self):
        sys.path.insert(0, str(SKILLS.parent / "scripts"))
        import review_stats
        rows = [line for line in DEV_REVIEW.read_text(encoding="utf-8").splitlines()
                if re.match(r"\s*\| \d+ \|", line)]
        words = {w for row in rows for w in re.findall(r"`([a-z-]+)`", row.rstrip(" |").rsplit(" | ", 1)[1])}
        self.assertEqual(words, set(review_stats.APPLIED_AS) | set(review_stats.DECLINED_AS))

    def test_the_review_measures_the_size(self):
        text = DEV_REVIEW.read_text(encoding="utf-8")
        self.assertIn("git diff --shortstat", text)
        self.assertIn("`size`", text)



class ShipWait(unittest.TestCase):
    """gogogo#238: dev holds the merge for a ref the spec marks (shipped)."""

    def test_dev_holds_a_merge_for_a_shipped_ref(self):
        dev = DEV.read_text(encoding="utf-8")
        paragraph = dev.split("**A blocked issue.**", 1)[1].split("\n\n", 1)[0]
        self.assertIn("not shipped", paragraph)
        hand_back = DEV_HAND_BACK.read_text(encoding="utf-8")
        case = hand_back.split("- **blocked by another issue**", 1)[1].split("\n- **stopped for a person**", 1)[0]
        self.assertIn("(shipped)", case)
        self.assertIn("taken once <B> ships", case)


class ItemConflictTriage(unittest.TestCase):
    def test_triage_reads_the_items(self):
        """Guards the triage read of a spec's items against each other, by the same ids (gogogo#295 case 3)."""
        text = DEV.read_text(encoding="utf-8")
        triage = text[text.index("## 2. Triage"):text.index(FOLD)]
        for part in ('spec_check.py" items', "certain"):
            self.assertIn(part, triage)


class LateCommits(unittest.TestCase):
    """A commit after the clean round gets a round of its own before the merge (gogogo#322)."""

    def test_rule_12_follows_rule_11(self):
        text = DEV_REVIEW.read_text(encoding="utf-8")
        at = text.index("\n12. **Commits after the clean round.**")
        self.assertLess(text.index("\n11. **"), at)
        end = text.index("When the spec moves content unchanged")
        self.assertLess(at, end)
        rule = text[at:end]
        for name in ("--no-merges", "^origin/<base>", "precise", "merge-script"):
            self.assertIn(name, rule)

    def test_merge_step_two_waits_for_the_review(self):
        text = DEV_HAND_BACK.read_text(encoding="utf-8")
        step = text[text.index("2. **Record what was verified.**"):text.index("3. **Closing references.**")]
        self.assertIn("§5 rule 12", step)


class DeclaredMoveRule(unittest.TestCase):
    def test_the_reader_rules_name_the_move_line(self):
        # gogogo#328: a planned file built at another path is declared, not missing.
        text = DEV_REVIEW.read_text(encoding="utf-8")
        for name in ("F:<planned path> | differs | <actual path>", "a declared move counts as inside when"):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
