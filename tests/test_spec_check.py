#!/usr/bin/env python3
"""Tests for spec_check.py: a spec's items listed, and a reader's answers checked.

Every `git` call goes through `spec_check._git`, patched here except in the
temp-repo case, so the item and answer rules are tested without a repo
(gogogo#44).

    python3 -m unittest tests.test_spec_check
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins" / "gogogo" / "scripts" / "spec_check.py"
sys.path.insert(0, str(SCRIPT.parent))

import spec_check as sc  # noqa: E402

BODY = """## Original report

> 1. Open the page
> 2. See nothing

---

## Verify by hand

Before, the list was empty.

1. Open the page. You should see rows.
2. Click New. You should see a form.

## Approvals

| Date | Question put to the user | Chosen | Rejected |
|---|---|---|---|
| 2026-10-02 | Which filter? Hard Stop: Schema. | the flag | the name |
| 2026-10-02 | Keep the old list? | no | yes |

Not approved: a new column.

## Context

1. Not an item: Context is not read.

## Design

1. **The filter** changes.

```
2. Inside a fence, not an item.
```

2. **The list** shows rows.

## Test cases

1. The list has rows.
2. The form opens.
3. An empty list says so.

## Files

**Create:** `tests/test_list.py`.

**Edit:** `app/views.py` (reads `release.major` and `handback.reporter`), `dev/SKILL.md`.

**Explicitly not in scope:**

- The form's fields.
- Any other repo.

## Verification

Run the tests.

## Hard-stop check

**Verdict: implement directly.**
"""

IDS = ["V1", "V2", "A1", "A2", "A0", "D1", "D2", "T1", "T2", "T3", "N1", "N2",
       "F:tests/test_list.py", "F:app/views.py", "F:dev/SKILL.md"]
ANSWERED = [i for i in IDS if not i.startswith("F:")]


def items(body, **kw):
    return sc.list_items(body, **kw)


class Items(unittest.TestCase):
    def test_ids_by_position_in_order(self):
        listed = items(BODY)
        self.assertEqual([i["id"] for i in listed["items"]], IDS)
        texts = {i["id"]: i["text"] for i in listed["items"]}
        self.assertIn("Which filter?", texts["A1"])
        self.assertIn("a new column", texts["A0"])
        self.assertIn("The list", texts["D2"])

    def test_none_row_and_not_approved_none_give_no_item(self):
        body = (BODY.replace("| 2026-10-02 | Which filter? Hard Stop: Schema. | the flag | the name |\n"
                             "| 2026-10-02 | Keep the old list? | no | yes |",
                             "| 2026-10-02 | None — every Hard Stop item is no, implement directly. | — | — |")
                .replace("Not approved: a new column.", "Not approved: none"))
        ids = [i["id"] for i in items(body)["items"]]
        self.assertFalse([i for i in ids if i.startswith("A")], ids)

    def test_design_with_no_numbered_item_is_one_item(self):
        body = BODY.replace("1. **The filter** changes.", "The filter changes.").replace(
            "2. **The list** shows rows.", "The list shows rows.")
        listed = items(body)
        ids = [i["id"] for i in listed["items"]]
        self.assertIn("D0", ids)
        self.assertFalse([i for i in ids if i.startswith("D") and i != "D0"])
        self.assertEqual(listed["unlisted"], ["Design"])

    def test_fenced_and_quoted_numbers_are_not_items(self):
        listed = items(BODY)
        texts = " ".join(i["text"] for i in listed["items"])
        self.assertNotIn("Inside a fence", texts)
        self.assertNotIn("See nothing", texts)
        self.assertNotIn("Context is not read", texts)

    def test_files_groups_and_parentheses(self):
        ids = [i["id"] for i in items(BODY)["items"]]
        f_items = [i for i in ids if i.startswith("F:")]
        self.assertEqual(f_items, ["F:tests/test_list.py", "F:app/views.py", "F:dev/SKILL.md"])
        self.assertNotIn("F:release.major", ids)
        n_texts = [i["text"] for i in items(BODY)["items"] if i["id"].startswith("N")]
        self.assertEqual(n_texts, ["The form's fields.", "Any other repo."])

    def test_files_with_no_groups_is_unlisted_and_nothing_is_outside(self):
        body = BODY.replace("**Create:** `tests/test_list.py`.", "Create `tests/test_list.py`.").replace(
            "**Edit:** `app/views.py`", "Edit `app/views.py`")
        listed = items(body, changed=["app/views.py", "README.md"])
        self.assertIn("Files", listed["unlisted"])
        self.assertEqual(listed["outside"], [])
        self.assertFalse([i for i in listed["items"] if i["id"].startswith("F:")])

    def test_no_files_section_is_unlisted_too(self):
        body = "## Design\n\n1. Change it.\n"
        listed = items(body, changed=["app/views.py"])
        self.assertEqual(listed["unlisted"], ["Files"])
        self.assertEqual(listed["outside"], [])

    def test_bold_numbered_design_items_are_items(self):
        body = BODY.replace("1. **The filter** changes.", "**1. The filter** changes.").replace(
            "2. **The list** shows rows.", "**2.** The list shows rows.")
        listed = items(body)
        texts = {i["id"]: i["text"] for i in listed["items"]}
        self.assertEqual([i for i in texts if i.startswith("D")], ["D1", "D2"])
        self.assertTrue(texts["D1"].startswith("The filter"), texts["D1"])
        self.assertEqual(texts["D2"], "The list shows rows.")
        self.assertNotIn("Design", listed["unlisted"])

    EDIT_SLASHLESS = "**Edit:** `README.md`, `review_stats.py` and `preflight.extra`."

    def test_a_slashless_edit_name_is_a_file_only_when_the_tree_has_it(self):
        body = BODY.replace(BODY[BODY.index("**Edit:**"):BODY.index("\n", BODY.index("**Edit:**"))],
                            self.EDIT_SLASHLESS)
        listed = items(body, tree=lambda: ["README.md", "plugins/x/review_stats.py"])
        self.assertEqual([i["id"] for i in listed["items"] if i["id"].startswith("F:")],
                         ["F:tests/test_list.py", "F:README.md", "F:review_stats.py"])
        body = body.replace(self.EDIT_SLASHLESS, "**Edit:** `preflight.extra` and `README.md`.")
        listed = items(body, tree=lambda: ["README.md"])
        self.assertIn("F:README.md", [i["id"] for i in listed["items"]])

    def test_create_names_are_not_checked_against_the_tree(self):
        body = BODY.replace("**Create:** `tests/test_list.py`.",
                            "**Create:** `README.md`, `review_stats.py` and `preflight.extra`.")
        listed = items(body, tree=lambda: [])
        f_ids = [i["id"] for i in listed["items"] if i["id"].startswith("F:")]
        for name in ("README.md", "review_stats.py", "preflight.extra"):
            self.assertIn(f"F:{name}", f_ids)

    def test_the_tree_is_read_only_for_a_slashless_edit_name(self):
        listed = items(BODY, tree=lambda: (_ for _ in ()).throw(AssertionError("tree read")))
        self.assertEqual([i["id"] for i in listed["items"]], IDS)

    def test_a_failed_tree_read_exits_2_without_a_traceback(self):
        body = BODY.replace(BODY[BODY.index("**Edit:**"):BODY.index("\n", BODY.index("**Edit:**"))],
                            "**Edit:** `preflight.extra`.")

        def fake_git(a):
            if a[0] == "ls-files":
                raise sc.GitError("fatal: not a git repository")
            return ""

        out, code = call("items", body=body, git=fake_git)
        self.assertEqual(code, 2)
        self.assertIn("fatal: not a git repository", out)

    def test_no_spec_in_this_body(self):
        out, code = call("items", body="## Request\n\nPlease fix it.\n")
        self.assertEqual(code, 1)
        self.assertIn("no spec in this body", out)

    def f_items(self, group, line, **kw):
        body = BODY.replace(BODY[BODY.index(group):BODY.index("\n", BODY.index(group))], line)
        return [i["id"] for i in items(body, **kw)["items"] if i["id"].startswith("F:") and i["id"] != "F:tests/test_list.py"]

    def test_brace_path_is_one_item_per_file(self):
        # Guards Design 1-2: `scripts/{a,b}.py` is two files, not one with braces in its name.
        got = self.f_items("**Create:**", "**Create:** `scripts/{a,b}.py`.", tree=lambda: [])
        self.assertEqual([g for g in got if g.startswith("F:scripts/")], ["F:scripts/a.py", "F:scripts/b.py"])
        self.assertFalse([g for g in got if "{" in g], got)

    def test_several_brace_groups_expand_in_order(self):
        # Guards several groups, first slowest.
        got = self.f_items("**Edit:**", "**Edit:** `src/{x,y}/{m,n}.py`.", tree=lambda: [])
        self.assertEqual(got[:4], ["F:src/x/m.py", "F:src/x/n.py", "F:src/y/m.py", "F:src/y/n.py"])

    def test_slashless_filter_runs_on_each_expanded_name(self):
        # Guards trap 1: expansion before the slash-less filter.
        got = self.f_items("**Edit:**", "**Edit:** `{tracker,nope}.py`.",
                           tree=lambda: [".claude/scripts/tracker.py"])
        self.assertEqual(got, ["F:tracker.py"])

    def test_brace_files_met_and_not_outside(self):
        # Guards the report's symptom: missing plus outside.
        body = BODY.replace(BODY[BODY.index("**Create:**"):BODY.index("\n", BODY.index("**Create:**"))],
                            "**Create:** `scripts/{a,b}.py`.")
        listed = items(body, changed=["scripts/a.py", "scripts/b.py"], tree=lambda: [])
        status = {i["id"]: i.get("status") for i in listed["items"]}
        self.assertEqual(status["F:scripts/a.py"], "met")
        self.assertEqual(status["F:scripts/b.py"], "met")
        self.assertEqual([o for o in listed["outside"] if o.startswith("scripts/")], [])

    def test_unexpandable_braces_stay_as_written(self):
        # Guards Design 1's unchanged cases.
        for path in ("a/{b.py", "a/{b}.py", "a/{b,{c,d}}.py"):
            got = self.f_items("**Create:**", f"**Create:** `{path}`.", tree=lambda: [])
            self.assertEqual([g for g in got if g.startswith("F:a/")], [f"F:{path}"], path)


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


class ChangedFiles(unittest.TestCase):
    def test_files_against_a_real_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "t@example.org")
            git(repo, "config", "user.name", "t")
            for path in ("app/views.py", "plugins/x/skills/dev/SKILL.md", "README.md"):
                (repo / path).parent.mkdir(parents=True, exist_ok=True)
                (repo / path).write_text("one\n")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "base")
            (repo / "plugins/x/skills/dev/SKILL.md").write_text("two\n")
            (repo / "README.md").write_text("two\n")
            (repo / "tests").mkdir()
            (repo / "tests/test_list.py").write_text("new\n")
            (repo / "body.md").write_text(BODY)
            (repo / ".gitignore").write_text("body.md\n.gitignore\n")
            out = subprocess.run([sys.executable, str(SCRIPT), "items", "body.md", "--base", "main"],
                                 cwd=repo, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.splitlines()
        self.assertIn("F:dev/SKILL.md\tdev/SKILL.md\tmet", lines)
        self.assertIn("F:tests/test_list.py\ttests/test_list.py\tmet", lines)
        self.assertIn("F:app/views.py\tapp/views.py\tmissing", lines)
        self.assertIn("outside: README.md", lines)
        self.assertFalse([ln for ln in lines if ln.startswith("outside: plugins/")], lines)

    def slashless_repo(self, tmp, edit_line):
        repo = Path(tmp)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "t@example.org")
        git(repo, "config", "user.name", "t")
        for path in ("old.py", "README.md", "sub/x.py"):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text("one\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        body = BODY.replace(BODY[BODY.index("**Edit:**"):BODY.index("\n", BODY.index("**Edit:**"))], edit_line)
        (repo / "body.md").write_text(body)
        (repo / ".gitignore").write_text("body.md\n.gitignore\n")
        return repo

    def test_a_top_level_edit_file_the_change_deletes_is_still_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.slashless_repo(tmp, "**Edit:** `old.py`, `README.md`.")
            git(repo, "switch", "-q", "-c", "change")
            git(repo, "rm", "-q", "old.py")
            git(repo, "commit", "-q", "-m", "drop old.py")
            out = subprocess.run([sys.executable, str(SCRIPT), "items", "body.md", "--base", "main"],
                                 cwd=repo, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.splitlines()
        self.assertIn("F:old.py\told.py\tmet", lines)
        self.assertNotIn("outside: old.py", lines)

    def test_a_top_level_edit_file_the_change_renames_is_still_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.slashless_repo(tmp, "**Edit:** `old.py`, `README.md`.")
            git(repo, "switch", "-q", "-c", "change")
            git(repo, "mv", "old.py", "new.py")
            git(repo, "commit", "-q", "-m", "rename old.py")
            out = subprocess.run([sys.executable, str(SCRIPT), "items", "body.md", "--base", "main"],
                                 cwd=repo, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("F:old.py", [ln.split("\t")[0] for ln in out.stdout.splitlines()])

    def test_slashless_edit_names_are_read_from_the_repo_top_in_a_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.slashless_repo(tmp, "**Edit:** `README.md`, `x.py`.")
            out = subprocess.run([sys.executable, str(SCRIPT), "items", "../body.md"],
                                 cwd=repo / "sub", capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        f_ids = [ln.split("\t")[0] for ln in out.stdout.splitlines() if ln.startswith("F:")]
        self.assertIn("F:README.md", f_ids)
        self.assertIn("F:x.py", f_ids)

    def test_an_untracked_file_counts_and_an_ignored_one_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.slashless_repo(tmp, "**Edit:** `notes.md`, `secret.md`.")
            (repo / "notes.md").write_text("local\n")
            (repo / "secret.md").write_text("local\n")
            (repo / ".gitignore").write_text("body.md\n.gitignore\nsecret.md\n")
            out = subprocess.run([sys.executable, str(SCRIPT), "items", "body.md"],
                                 cwd=repo, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        f_ids = [ln.split("\t")[0] for ln in out.stdout.splitlines() if ln.startswith("F:")]
        self.assertIn("F:notes.md", f_ids)
        self.assertNotIn("F:secret.md", f_ids)

    def test_slashless_edit_names_against_a_real_tree(self):
        body = BODY.replace(BODY[BODY.index("**Edit:**"):BODY.index("\n", BODY.index("**Edit:**"))],
                            "**Edit:** `README.md`, `views.py`, `preflight.extra`.")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "t@example.org")
            git(repo, "config", "user.name", "t")
            for path in ("app/views.py", "README.md"):
                (repo / path).parent.mkdir(parents=True, exist_ok=True)
                (repo / path).write_text("one\n")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "base")
            (repo / "README.md").write_text("two\n")
            (repo / "body.md").write_text(body)
            (repo / ".gitignore").write_text("body.md\n.gitignore\n")
            out = subprocess.run([sys.executable, str(SCRIPT), "items", "body.md", "--base", "main"],
                                 cwd=repo, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.splitlines()
        self.assertIn("F:README.md\tREADME.md\tmet", lines)
        self.assertIn("F:views.py\tviews.py\tmissing", lines)
        self.assertFalse([ln for ln in lines if "preflight.extra" in ln], lines)
        self.assertNotIn("outside: README.md", lines)


def call(*argv, body=BODY, answers=None, changed=None, cwd=None, git=None):
    """Run main() with the body (and answers) in temp files; returns (stdout+stderr, exit)."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(cwd or tmp)
        (Path(tmp) / "body.md").write_text(body)
        args = [argv[0], str(Path(tmp) / "body.md")]
        if answers is not None:
            (Path(tmp) / "answers.txt").write_text(answers)
            args.append(str(Path(tmp) / "answers.txt"))
        args += list(argv[1:])

        def fake_git(a):
            if git is not None:
                return git(a)
            if a[0] == "merge-base":
                return "abc\n"
            if a[0] == "diff":
                return "".join(f"{p}\n" for p in (changed or []))
            return ""

        out = io.StringIO()
        with mock.patch.object(sc, "_git", side_effect=fake_git), contextlib.chdir(base), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = sc.main(args)
        return out.getvalue(), code


class Verify(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "app").mkdir()
        (self.dir / "app" / "views.py").write_text("def listed():\n    return rows\n")
        self.changed = ["tests/test_list.py", "app/views.py", "plugins/x/skills/dev/SKILL.md"]

    def answers(self, **override):
        lines = []
        for item in ANSWERED:
            lines.append(override.get(item, f"{item} | met | app/views.py:2 | "))
        return "# reader's answers\n\n" + "\n".join(line for line in lines if line is not None) + "\n"

    def verify(self, answers, changed=None):
        return call("verify", "--base", "main", answers=answers,
                    changed=self.changed if changed is None else changed, cwd=self.dir)

    def test_all_met_passes(self):
        out, code = self.verify(self.answers())
        self.assertEqual(code, 0, out)
        last = out.strip().splitlines()[-1]
        self.assertEqual(last, f"spec-check: items={len(IDS)} met={len(IDS)} missing=0 differs=0 na=0 outside=0")

    def test_an_item_with_no_line_is_refused(self):
        out, code = self.verify(self.answers(T2=None))
        self.assertEqual(code, 2)
        self.assertIn("error:", out)
        self.assertIn("T2", out)
        self.assertNotIn("spec-check:", out)

    def test_met_without_evidence(self):
        out, code = self.verify(self.answers(D1="D1 | met | - | "))
        self.assertEqual(code, 2, out)
        out, code = self.verify(self.answers(N1="N1 | met | - | "))
        self.assertEqual(code, 0, out)

    def test_evidence_must_resolve(self):
        for evidence in ("app/nope.py", "app/views.py:3", "app/views.py::not_there"):
            out, code = self.verify(self.answers(D1=f"D1 | met | {evidence} | "))
            self.assertEqual(code, 2, evidence + "\n" + out)
        out, code = self.verify(self.answers(D1="D1 | met | app/views.py::listed, app/views.py | "))
        self.assertEqual(code, 0, out)

    def test_class_form_evidence_resolves(self):
        # Guards the report's (b): Class.name and Class::name.
        (self.dir / "app" / "views.py").write_text("class Listing:\n    def listed():\n        return rows\n")
        for evidence in ("app/views.py::Listing.listed", "app/views.py::Listing::listed"):
            out, code = self.verify(self.answers(D1=f"D1 | met | {evidence} | "))
            self.assertEqual(code, 0, evidence + "\n" + out)

    def test_class_form_evidence_still_refused_when_wrong(self):
        # Guards Design 3: not everything with a dot is accepted.
        (self.dir / "app" / "views.py").write_text("class Listing:\n    def listed():\n        return rows\n")
        for evidence in ("Nope.listed", "Listing.nope", "listed.Listing", "Listing."):
            out, code = self.verify(self.answers(D1=f"D1 | met | app/views.py::{evidence} | "))
            self.assertEqual(code, 2, evidence + "\n" + out)
            self.assertIn("not in the file", out)

    def test_evidence_outside_the_working_tree_is_refused(self):
        outside = self.dir.parent / "elsewhere.txt"
        outside.write_text("x\n")
        self.addCleanup(outside.unlink)
        for evidence in (str(outside), "../elsewhere.txt", str(self.dir / "app" / "views.py")):
            out, code = self.verify(self.answers(D1=f"D1 | met | {evidence} | "))
            self.assertEqual(code, 2, evidence + "\n" + out)

    def test_differs_needs_a_note(self):
        out, code = self.verify(self.answers(D2="D2 | differs | app/views.py:1 | "))
        self.assertEqual(code, 2, out)

    def test_missing_differs_and_outside_fail_and_are_counted(self):
        answers = self.answers(T3="T3 | missing | - | no test for the empty list",
                               D2="D2 | differs | app/views.py:1 | spec says rows; change shows a count")
        out, code = self.verify(answers, changed=self.changed + ["README.md"])
        self.assertEqual(code, 1, out)
        self.assertIn("T3 | missing", out)
        self.assertIn("D2 | differs", out)
        self.assertIn("outside: README.md", out)
        n = len(IDS)
        self.assertIn(f"spec-check: items={n} met={n - 2} missing=1 differs=1 na=0 outside=1", out)

    def test_unknown_id_and_two_lines_for_one_id(self):
        out, code = self.verify(self.answers() + "D9 | met | app/views.py | \n")
        self.assertEqual(code, 2, out)
        self.assertIn("D9", out)
        out, code = self.verify(self.answers() + "D1 | met | app/views.py | \n")
        self.assertEqual(code, 2, out)
        self.assertIn("D1", out)

    def test_json(self):
        out, code = call("items", "--json")
        self.assertEqual(code, 0)
        self.assertEqual([i["id"] for i in json.loads(out)["items"]], IDS)


if __name__ == "__main__":
    unittest.main()
