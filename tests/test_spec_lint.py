import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import spec_lint as sl  # noqa: E402
from test_profile_check import COMPLETE  # noqa: E402

SETTINGS = {
    "hard_stops": {
        "items": ["Schema", "Auth / permissions"],
        "two_licence": [{"change": "migration", "apply": "migrate on the dev DB"}],
    },
    "lanes": [{"name": "automated", "run": "make test"}, {"name": "browser", "env": "dev"}],
    "environments": [{"name": "dev", "roles": ["pre-merge"], "url": "https://dev.example.org"},
                     {"name": "production", "roles": ["production"], "url": "https://app.example.org"}],
    "verify": {"human": "production"},
}

GOOD = """## Original report

> The list is empty.
> ## Steps
> 1. Open the page

---

## Verify by hand

Before, the Pages list showed no rows.

1. Log in as an editor and open https://app.example.org/holon/1708/. You should see the Pages list.
2. Click New page. You should see a form. If the list is still empty, it is still broken.

## Approvals

| Date | Question put to the user | Chosen | Rejected |
|---|---|---|---|
| 2026-09-30 | None — every Hard Stop item is no, implement directly. | — | — |

Not approved: none

## Context

The view filters on the wrong flag (`views.py:12`). Trap: a dead view looks like the path.

## Design

1. Change the filter.

## Test cases

1. Automated: `test_pages_listed`, guards the empty list.
2. Browser: open the page as an editor.

## Files

**Edit:** `views.py`.

**Explicitly not in scope:**

- The form.

## Verification

Run `make test`. Revert the fix and watch `test_pages_listed` go red.

## Hard-stop check

| Item | Triggered? | Why |
|---|---|---|
| Schema | no | no field changes |
| Auth / permissions | no | same access |

**Verdict: implement directly.**
"""


def run(body, settings=SETTINGS):
    return sl.lint(body, settings)


def errors(body, settings=SETTINGS):
    return run(body, settings)[0]


class GoodBody(unittest.TestCase):
    def test_no_errors_no_warnings_label_applies(self):
        errs, warns, withheld = run(GOOD)
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])
        self.assertIsNone(withheld)

    def test_headings_inside_the_quoted_report_are_not_sections(self):
        self.assertNotIn("Steps", [t for t, _, _ in sl.split_sections(GOOD)[1]])

    def test_headings_inside_a_code_fence_are_not_sections(self):
        body = GOOD.replace("1. Change the filter.", "```\n## Approvals\n```\n1. Change the filter.")
        self.assertEqual(errors(body), [])


class Layout(unittest.TestCase):
    def test_each_missing_section_is_named(self):
        for title in sl.SPEC_SECTIONS:
            body = GOOD.replace(f"## {title}\n", "")
            self.assertIn(f"## {title}: section missing", errors(body), title)

    def test_sections_out_of_order(self):
        a = GOOD.index("## Context")
        b = GOOD.index("## Design")
        c = GOOD.index("## Test cases")
        swapped = GOOD[:a] + GOOD[b:c] + GOOD[a:b] + GOOD[c:]
        self.assertTrue(any(e.startswith("layout: sections out of order") for e in errors(swapped)))

    def test_duplicate_section(self):
        body = GOOD + "\n## Files\n\nagain\n"
        self.assertIn("## Files: appears 2 times", errors(body))

    def test_report_must_be_first(self):
        report = GOOD[:GOOD.index("## Verify by hand")]
        body = GOOD[len(report):] + "\n" + report
        self.assertIn("layout: ## Original report must be the first section", errors(body))

    def test_report_must_be_blockquoted(self):
        body = GOOD.replace("> The list is empty.", "The list is empty.")
        self.assertTrue(any("every line must be a blockquote" in e for e in errors(body)))

    def test_report_needs_rule_before_spec(self):
        body = GOOD.replace("\n---\n", "\n")
        self.assertTrue(any("no --- rule" in e for e in errors(body)))

    def test_no_report_is_a_warning_not_an_error(self):
        body = GOOD[GOOD.index("## Verify by hand"):]
        errs, warns, _ = run(body)
        self.assertEqual(errs, [])
        self.assertTrue(any("no ## Original report" in w for w in warns))

    def test_text_before_first_heading(self):
        self.assertTrue(any(e.startswith("layout: text before") for e in errors("Spec follows.\n\n" + GOOD)))

    def test_unknown_section_warns(self):
        _, warns, _ = run(GOOD + "\n## Notes\n\nx\n")
        self.assertIn("## Notes: not one of the spec's sections", warns)


class VerifyByHand(unittest.TestCase):
    def test_needs_numbered_steps(self):
        body = GOOD.replace("1. Log in", "- Log in").replace("2. Click", "- Click")
        self.assertIn("## Verify by hand: no numbered steps", errors(body))

    def test_placeholder_url_is_an_error(self):
        body = GOOD.replace("/holon/1708/", "/holon/<slug>/")
        self.assertTrue(any("placeholder <slug>" in e for e in errors(body)))

    def test_autolink_is_not_a_placeholder(self):
        body = GOOD.replace("https://app.example.org/holon/1708/.", "<https://app.example.org/holon/1708/>.")
        self.assertEqual(errors(body), [])

    def test_runtime_value_in_prose_is_not_a_placeholder(self):
        body = GOOD.replace("Click New page.", "Click New page and search for <the code> it shows.")
        self.assertEqual(errors(body), [])

    def test_no_url_under_base_warns(self):
        body = GOOD.replace("https://app.example.org/holon/1708/", "the holon page")
        _, warns, _ = run(body)
        self.assertTrue(any("no URL under https://app.example.org (production" in w for w in warns))


class Approvals(unittest.TestCase):
    def test_needs_the_four_columns(self):
        body = GOOD.replace("| Date | Question put to the user | Chosen | Rejected |", "| Date | Question | Answer |")
        self.assertTrue(any(e.startswith("## Approvals: no table with the columns") for e in errors(body)))

    def test_empty_table_is_an_error(self):
        body = GOOD.replace("| 2026-09-30 | None — every Hard Stop item is no, implement directly. | — | — |\n", "")
        self.assertTrue(any("the table has no rows" in e for e in errors(body)))

    def test_needs_not_approved_line(self):
        body = GOOD.replace("Not approved: none\n", "")
        self.assertTrue(any("Not approved:" in e for e in errors(body)))


class HardStopCheck(unittest.TestCase):
    def test_missing_item_row(self):
        body = GOOD.replace("| Auth / permissions | no | same access |\n", "")
        self.assertIn('## Hard-stop check: no answer for "Auth / permissions"', errors(body))

    def test_answer_must_be_yes_or_no(self):
        body = GOOD.replace("| Schema | no |", "| Schema | probably not |")
        self.assertTrue(any('"Schema" must be answered yes or no' in e for e in errors(body)))

    def test_missing_verdict(self):
        body = GOOD.replace("**Verdict: implement directly.**\n", "")
        self.assertTrue(any("no \"**Verdict" in e for e in errors(body)))

    def test_yes_with_implement_directly_is_the_contradiction(self):
        body = GOOD.replace("| Schema | no |", "| Schema | yes |")
        self.assertTrue(any('"Schema" is answered yes, but the verdict neither names' in e for e in errors(body)))

    def test_all_no_with_proposal_verdict(self):
        body = GOOD.replace("implement directly.**", "proposal — Schema awaits approval.**")
        self.assertTrue(any("calls the spec a proposal, but every item is answered no" in e for e in errors(body)))

    def test_proposal_is_valid_and_withholds_the_label(self):
        body = GOOD.replace("| Schema | no |", "| Schema | yes |").replace(
            "implement directly.**", "proposal — Schema awaits approval.**")
        errs, _, withheld = run(body)
        self.assertEqual(errs, [])
        self.assertEqual(withheld, "a Hard Stop awaits approval")

    def test_approved_is_valid_and_applies_the_label(self):
        body = GOOD.replace("| Schema | no |", "| Schema | yes |").replace(
            "implement directly.**", "approved — Schema by Approvals row 1.**")
        errs, _, withheld = run(body)
        self.assertEqual(errs, [])
        self.assertIsNone(withheld)

    def test_verdict_must_name_every_yes_item(self):
        body = GOOD.replace("| Schema | no |", "| Schema | yes |").replace(
            "| Auth / permissions | no |", "| Auth / permissions | yes |").replace(
            "implement directly.**", "approved — Schema by Approvals row 1.**")
        errs = errors(body)
        self.assertTrue(any(e.startswith('## Hard-stop check: "Auth / permissions" is answered yes') for e in errs))
        self.assertFalse(any(e.startswith('## Hard-stop check: "Schema"') for e in errs))

    def test_unknown_verdict_word(self):
        body = GOOD.replace("implement directly.**", "all good.**")
        self.assertTrue(any('so the verdict says "implement directly"' in e for e in errors(body)))

    def test_answer_with_explanation_in_the_same_cell(self):
        body = GOOD.replace("| Schema | no | no field changes |", "| Schema | **No.** No field changes. |")
        self.assertEqual(errors(body), [])

    def test_list_form_with_questions(self):
        settings = {**SETTINGS, "hard_stops": {"items": ["Does it change state that outlives the deploy?",
                                                         "Will old and new clients be live against it at the same time?"]}}
        table = GOOD[GOOD.index("| Item | Triggered?"):GOOD.index("**Verdict")]
        listed = ("1. **Does it change state that outlives the deploy?** No. Nothing is written.\n"
                  "2. **Will old and new clients be live against it at the same time?** **No.** Rendering only.\n\n")
        body = GOOD.replace(table, listed).replace("implement directly.**", "both no. Implement directly; tests are the gate.**")
        self.assertEqual(errors(body, settings), [])
        self.assertTrue(any("is answered yes" in e for e in errors(body.replace("** No. Nothing", "** Yes. It writes"), settings)))

    def test_row_named_in_the_items_own_answer_licenses_it(self):
        body = GOOD.replace("| Schema | no | no field changes |", "| Schema | **Yes.** One field. Approved: Approvals row 1. |").replace(
            "implement directly.**", "approved.**")
        errs, _, withheld = run(body)
        self.assertEqual(errs, [])
        self.assertIsNone(withheld)

    def test_approved_without_a_row_is_a_warning(self):
        body = GOOD.replace("| Schema | no |", "| Schema | yes |").replace(
            "implement directly.**", "approved on 2026-09-16.**")
        errs, warns, _ = run(body)
        self.assertEqual(errs, [])
        self.assertTrue(any("without naming the Approvals row" in w for w in warns))

    def test_both_approved_covers_every_yes_item(self):
        body = GOOD.replace("| Schema | no |", "| Schema | yes |").replace(
            "| Auth / permissions | no |", "| Auth / permissions | yes |").replace(
            "implement directly.**", "two yes, both approved by the last row of Approvals.**")
        self.assertEqual(errors(body), [])

    def test_list_answer_wrapped_over_lines_is_read_whole(self):
        table = GOOD[GOOD.index("| Item | Triggered?"):GOOD.index("**Verdict")]
        listed = ("- **Schema — yes.** One data migration, additive.\n"
                  "  **Both approvals are on record**: the design (rows 2, 3).\n"
                  "- **Auth / permissions — no.** Same gate.\n\n")
        body = GOOD.replace(table, listed).replace("implement directly.**", "Schema is yes; Auth is no.**")
        self.assertEqual(errors(body), [])

    def test_list_answer_on_the_wrapped_line_is_found(self):
        table = GOOD[GOOD.index("| Item | Triggered?"):GOOD.index("**Verdict")]
        listed = ("**1. Schema**\nNo. Nothing stored changes.\n\n"
                  "**2. Auth / permissions** No. Same gate.\n\n")
        self.assertEqual(errors(GOOD.replace(table, listed)), [])

    def test_implement_directly_wins_over_a_passing_mention_of_proposal(self):
        body = GOOD.replace("implement directly.**", "all no. Implement directly; this is not a proposal.**")
        self.assertEqual(errors(body), [])

    def test_verdict_may_run_over_several_lines(self):
        body = GOOD.replace("| Schema | no |", "| Schema | yes |").replace(
            "**Verdict: implement directly.**", "**Verdict.** Schema is yes, so this is a\nproposal until it is approved.")
        errs, _, withheld = run(body)
        self.assertEqual(errs, [])
        self.assertEqual(withheld, "a Hard Stop awaits approval")


class OtherChecks(unittest.TestCase):
    def test_open_questions_heading_is_an_error(self):
        body = GOOD.replace("## Design", "### Open questions\n\n- which flag?\n\n## Design")
        self.assertTrue(any("lists open questions" in e for e in errors(body)))

    def test_open_questions_in_the_quoted_report_is_fine(self):
        body = GOOD.replace("> ## Steps", "> ## Open questions")
        self.assertEqual(errors(body), [])

    def test_red_flag_phrase_in_the_quoted_report_is_the_reporters_not_ours(self):
        body = GOOD.replace("> The list is empty.", "> It should be straightforward, either approach works.")
        self.assertEqual(run(body)[1], [])

    def test_red_flag_phrase_warns_with_line_number(self):
        body = GOOD.replace("1. Change the filter.", "1. Choose between the two filters.")
        _, warns, _ = run(body)
        self.assertTrue(any(w.startswith("line ") and "choose between" in w.lower() for w in warns))

    def test_lane_without_a_case_warns(self):
        body = GOOD.replace("\n2. Browser: open the page as an editor.", "")
        _, warns, _ = run(body)
        self.assertTrue(any('lane "browser" has no case' in w for w in warns))

    def test_two_licence_change_without_apply_row_warns(self):
        body = GOOD.replace("| 2026-09-30 | None — every Hard Stop item is no, implement directly. | — | — |",
                            "| 2026-09-30 | **Hard Stop** — approve the migration adding `x`? | yes | no |")
        _, warns, _ = run(body)
        self.assertTrue(any("no row about applying it" in w for w in warns))
        with_apply = body.replace("| yes | no |", "| yes | no |\n| 2026-09-30 | Apply it to dev during the run? | yes | no |")
        self.assertFalse(any("no row about applying it" in w for w in run(with_apply)[1]))

    def test_external_unknown_withholds_the_label(self):
        body = GOOD.replace("Not approved: none", "External unknown: the vendor's limit, from Sam by Friday.\n\nNot approved: none")
        errs, _, withheld = run(body)
        self.assertEqual(errs, [])
        self.assertEqual(withheld, "an external unknown is open")

    def test_errors_withhold_the_label(self):
        self.assertEqual(run(GOOD.replace("## Files\n", ""))[2], "lint errors")


class NumberedItemsAndFileGroups(unittest.TestCase):
    def withheld(self, body, error):
        errs, _, label = run(body)
        self.assertIn(error, errs)
        self.assertEqual(label, "lint errors")

    def test_design_with_no_numbered_item(self):
        self.withheld(GOOD.replace("1. Change the filter.", "Change the filter."),
                      "## Design: no numbered items; number each artefact 1., 2., 3. at the start of a line")

    def test_test_cases_numbered_out_of_order(self):
        body = GOOD.replace("2. Browser: open the page as an editor.",
                            "2. Browser: open the page as an editor.\n1. Again.")
        self.withheld(body, "## Test cases: items are numbered 1, 2, 1; number them 1, 2, 3 in order "
                            "through the section")

    def test_files_with_no_create_or_edit_group(self):
        self.withheld(GOOD.replace("**Edit:** `views.py`.", "We edit `views.py`."),
                      "## Files: no **Create** or **Edit** group naming a file in backticks")

    def test_files_with_no_not_in_scope_group(self):
        self.withheld(GOOD.replace("**Explicitly not in scope:**", "Leave alone:"),
                      "## Files: no **Explicitly not in scope** group")

    def test_a_numbered_line_in_a_fence_is_not_an_item(self):
        body = GOOD.replace("1. Change the filter.", "```\n1. Change the filter.\n```")
        self.assertIn("## Design: no numbered items; number each artefact 1., 2., 3. at the start of a line",
                      errors(body))

    def test_the_helpers(self):
        self.assertEqual(sl.numbered_items(["1. a", "  2. indented", "```", "2. fenced", "```", "3) b"]),
                         [(1, "1. a"), (3, "3) b")])
        groups = sl.file_groups(["**Create:** `a.py`", "- **Edit** `b.py`", "more `c.py`",
                                 "**explicitly not in scope:**", "- x"])
        self.assertEqual(groups, {"create": ["`a.py`"], "edit": ["`b.py`", "more `c.py`"],
                                  "not_in_scope": ["- x"]})


class CommandLine(unittest.TestCase):
    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sl.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "dev-process.md"
            profile.write_text(COMPLETE.replace('items = ["schema", "auth"]', 'items = ["Schema", "Auth / permissions"]'))
            good = Path(tmp) / "good.md"
            good.write_text(GOOD)
            bad = Path(tmp) / "bad.md"
            bad.write_text(GOOD.replace("## Files\n", ""))

            code, out, _ = self.call(str(good), "--profile", str(profile))
            self.assertEqual((code, out.strip()), (0, "label: apply"))

            code, out, _ = self.call(str(bad), "--profile", str(profile))
            self.assertEqual(code, 1)
            self.assertIn("error: ## Files: section missing", out)
            self.assertIn("label: withhold (lint errors)", out)

            code, _, err = self.call(str(good), "--profile", str(Path(tmp) / "nope.md"))
            self.assertEqual(code, 2)
            self.assertIn("no file at", err)


if __name__ == "__main__":
    unittest.main()
