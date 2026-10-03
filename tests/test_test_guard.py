#!/usr/bin/env python3
"""Tests for test_guard.py: the test hunks a change touched, listed and judged.

Each case builds a throwaway git repository with a profile naming its test
files, a base commit and a change, and runs the real script in it (gogogo#58).
The structure cases pin the names the skills depend on, never sentences
(CLAUDE.md § Tests).

    python3 -m unittest tests.test_test_guard
"""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
SCRIPT = PLUGIN / "scripts" / "test_guard.py"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_stats  # noqa: E402
from test_tech_eval import PROJECT_NAMES  # noqa: E402

PROFILE = """+++
profile = 1

[[lanes]]
name = "unit"
run = "make test"
{tests}
+++
"""

TEST_A = """def test_a():
    assert one() == 1
    assert two() == 2


def test_b():
    assert three() == 3
    assert four() == 4
"""

TEST_CLASS = """import unittest


class T(unittest.TestCase):
    def test_a(self):
        self.assertEqual(one(), 1)
        self.assertEqual(two(), 2)

    def test_b(self):
        self.assertEqual(three(), 3)
        self.assertEqual(four(), 4)
"""

BODY = """## Design

1. Change the parser.

## Test cases

{cases}

## Files

{files}
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


class Repo:
    def __init__(self, tests='tests = ["tests/*"]'):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.repo = self.dir / "repo"
        self.repo.mkdir()
        self.profile = self.dir / "dev-process.md"
        self.profile.write_text(PROFILE.format(tests=tests))
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.org")
        git(self.repo, "config", "user.name", "t")
        self.write("tests/test_a.py", TEST_A)
        self.write("tests/test_keep.py", "def test_keep():\n    assert True\n")
        self.write("app/code.py", "x = 1\n")
        self.commit("base")

    def write(self, path, text):
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / path).write_text(text)

    def commit(self, message):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)

    def run(self, *args, body=None, answers=None):
        argv = [sys.executable, str(SCRIPT), args[0]]
        if body is not None:
            (self.dir / "body.md").write_text(body)
            (self.dir / "answers.txt").write_text(answers or "")
            argv += [str(self.dir / "body.md"), str(self.dir / "answers.txt")]
        argv += ["--base", "main", "--profile", str(self.profile), *args[1:]]
        return subprocess.run(argv, cwd=self.repo, capture_output=True, text=True)

    def branch(self):
        git(self.repo, "switch", "-q", "-c", "change")

    def at_base(self, path, text):
        """Add a file to the base (main) and start the change branch again from it."""
        git(self.repo, "switch", "-q", "main")
        self.write(path, text)
        self.commit(f"base {path}")
        git(self.repo, "switch", "-q", "-C", "change")

    def close(self):
        self._tmp.cleanup()


class Listing(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.addCleanup(self.r.close)
        self.r.branch()

    def items(self):
        out = self.r.run("list")
        self.assertEqual(out.returncode, 0, out.stderr)
        return [ln for ln in out.stdout.splitlines() if re.match(r"H\d+  ", ln)], out.stdout

    def test_a_deleted_test_file_is_listed(self):
        (self.r.repo / "tests/test_a.py").unlink()
        self.r.commit("drop")
        items, out = self.items()
        self.assertEqual(items, ["H1  deleted  tests/test_a.py"])
        self.assertTrue(out.rstrip().endswith("test-guard: hunks=1"))

    def test_a_pure_rename_lists_nothing(self):
        git(self.r.repo, "mv", "tests/test_a.py", "tests/test_moved.py")
        self.r.commit("move")
        items, out = self.items()
        self.assertEqual(items, [])
        self.assertTrue(out.rstrip().endswith("test-guard: hunks=0"))

    def test_a_renamed_and_edited_file_lists_hunks_under_the_new_path(self):
        git(self.r.repo, "mv", "tests/test_a.py", "tests/test_moved.py")
        self.r.write("tests/test_moved.py", TEST_A.replace("    assert two() == 2\n", ""))
        self.r.commit("move and edit")
        items, _ = self.items()
        self.assertEqual(len(items), 1, items)
        self.assertIn("changed  tests/test_moved.py:3", items[0])
        self.assertIn("(renamed from tests/test_a.py)", items[0])
        self.assertEqual(items[0], "H1  changed  tests/test_moved.py:3  def test_a():  (renamed from tests/test_a.py)")

    def test_a_removed_line_is_listed_with_its_minus_line(self):
        self.r.write("tests/test_a.py", TEST_A.replace("    assert four() == 4\n", ""))
        self.r.commit("loosen")
        items, out = self.items()
        self.assertEqual(len(items), 1, items)
        self.assertTrue(items[0].startswith("H1  changed  tests/test_a.py:8"), items)
        self.assertIn("def test_b", items[0])
        self.assertIn("    -    assert four() == 4", out)

    def test_an_added_line_is_listed(self):
        self.r.write("tests/test_a.py", TEST_A.replace("def test_b():\n", "def test_b():\n    skip()\n"))
        self.r.commit("skip")
        items, out = self.items()
        self.assertEqual(len(items), 1, items)
        self.assertIn("    +    skip()", out)

    def test_a_new_test_file_and_a_non_test_file_list_nothing(self):
        self.r.write("tests/test_new.py", "def test_new():\n    assert False\n")
        self.r.write("app/code.py", "x = 2\n")
        self.r.commit("new")
        items, _ = self.items()
        self.assertEqual(items, [])

    def test_a_test_file_moved_out_of_the_patterns_is_deleted(self):
        (self.r.repo / "attic").mkdir()
        git(self.r.repo, "mv", "tests/test_a.py", "attic/test_a.py")
        self.r.commit("hide")
        items, _ = self.items()
        self.assertEqual(items, ["H1  deleted  tests/test_a.py"])

    def test_deleting_every_test_file_is_listed_not_unchecked(self):
        git(self.r.repo, "rm", "-q", "-r", "tests")
        self.r.commit("drop all")
        items, _ = self.items()
        self.assertEqual(sorted(items), ["H1  deleted  tests/test_a.py", "H2  deleted  tests/test_keep.py"])

    def test_a_deleted_binary_or_empty_test_file_is_listed(self):
        self.r.write("tests/empty.txt", "")
        (self.r.repo / "tests").joinpath("fixture.bin").write_bytes(bytes(range(256)))
        self.r.commit("fixtures")
        git(self.r.repo, "branch", "-f", "main")
        git(self.r.repo, "rm", "-q", "tests/empty.txt", "tests/fixture.bin")
        self.r.commit("drop fixtures")
        items, _ = self.items()
        self.assertEqual(sorted(items), ["H1  deleted  tests/empty.txt", "H2  deleted  tests/fixture.bin"])

    def test_a_name_with_a_space_keeps_its_path(self):
        self.r.write("tests/test b.py", TEST_A)
        self.r.commit("spaced")
        git(self.r.repo, "branch", "-f", "main")
        self.r.write("tests/test b.py", TEST_A.replace("    assert four() == 4\n", ""))
        out = self.r.run("list", "--json")
        import json
        paths = [i["path"] for i in json.loads(out.stdout)["items"]]
        self.assertEqual(paths, ["tests/test b.py"])

    def test_an_uncommitted_edit_is_listed(self):
        self.r.write("tests/test_keep.py", "def test_keep():\n    pass\n")
        items, _ = self.items()
        self.assertEqual(len(items), 1, items)
        self.assertIn("tests/test_keep.py", items[0])


class Enclosing(unittest.TestCase):
    """The line printed for a hunk is the innermost enclosing line at the base (gogogo#76)."""

    def setUp(self):
        self.r = Repo()
        self.addCleanup(self.r.close)
        self.r.branch()
        self.r.at_base("tests/test_c.py", TEST_CLASS)

    def items(self):
        out = self.r.run("list")
        self.assertEqual(out.returncode, 0, out.stderr)
        return [ln for ln in out.stdout.splitlines() if re.match(r"H\d+  ", ln)]

    def change(self, text):
        self.r.write("tests/test_c.py", text)
        self.r.commit("change")

    def test_a_method_hunk_shows_its_def_not_the_class(self):
        self.change(TEST_CLASS.replace("        self.assertEqual(two(), 2)\n", ""))
        self.assertEqual(self.items(), ["H1  changed  tests/test_c.py:7  def test_a(self):"])

    def test_json_keeps_the_chain_and_gits_header(self):
        self.change(TEST_CLASS.replace("        self.assertEqual(two(), 2)\n", ""))
        out = self.r.run("list", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        item = json.loads(out.stdout)["items"][0]
        self.assertEqual(item["enclosing"], ["def test_a(self):", "class T(unittest.TestCase):"])
        self.assertEqual(item["context"], "class T(unittest.TestCase):")

    def test_a_line_added_after_the_def_is_inside_it(self):
        self.change(TEST_CLASS.replace("    def test_b(self):\n",
                                       "    def test_b(self):\n        self.skipTest(\"x\")\n"))
        items = self.items()
        self.assertEqual(len(items), 1, items)
        self.assertTrue(items[0].endswith("def test_b(self):"), items)
        out = self.r.run("verify", body=body(cases="1. `tests/test_c.py::test_b` rewritten"),
                         answers="H1\tweaker\ta skip\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("H1  licensed", out.stdout)

    def test_a_removed_method_shows_the_class_and_is_licensed_by_its_name(self):
        self.change(TEST_CLASS.replace("\n    def test_b(self):\n        self.assertEqual(three(), 3)\n"
                                       "        self.assertEqual(four(), 4)\n", ""))
        items = self.items()
        self.assertEqual(len(items), 1, items)
        self.assertTrue(items[0].endswith("class T(unittest.TestCase):"), items)
        out = self.r.run("verify", body=body(cases="1. `tests/test_c.py::test_b` removed"),
                         answers="H1\tweaker\tthe test is gone\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("H1  licensed", out.stdout)

    def test_lines_are_counted_as_git_counts_them(self):
        base = TEST_CLASS.replace("import unittest\n", "import unittest\n\x0c\n")
        self.r.at_base("tests/test_c.py", base)
        self.change(base.replace("    def test_b(self):\n", "    def test_b(self):\n        self.skipTest(\"x\")\n"))
        items = self.items()
        self.assertEqual(len(items), 1, items)
        self.assertTrue(items[0].endswith("def test_b(self):"), items)

    def test_a_hunk_running_into_the_next_method_is_not_licensed_by_the_first(self):
        self.change(TEST_CLASS.replace("        self.assertEqual(two(), 2)\n\n    def test_b(self):\n"
                                       "        self.assertEqual(three(), 3)\n        self.assertEqual(four(), 4)\n", ""))
        out = self.r.run("verify", body=body(cases="1. `tests/test_c.py::test_a` rewritten"),
                         answers="H1\tweaker\ttest_b is gone\n")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("H1  NOT LICENSED", out.stdout)

    def test_a_hunk_of_blank_lines_has_no_enclosing_line(self):
        self.change(TEST_CLASS.replace("        self.assertEqual(two(), 2)\n\n", "        self.assertEqual(two(), 2)\n"))
        out = self.r.run("list", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["items"][0]["enclosing"], [])

    def test_no_context_and_no_enclosing_line_print_a_dash(self):
        self.r.write("tests/test_keep.py", "def test_kept():\n    assert True\n")
        self.r.commit("rename the test")
        self.assertEqual(self.items(), ["H1  changed  tests/test_keep.py:1  -"])

    def test_a_deleted_file_has_the_same_keys_as_a_hunk(self):
        (self.r.repo / "tests/test_a.py").unlink()
        self.r.commit("drop")
        out = self.r.run("list", "--json")
        item = json.loads(out.stdout)["items"][0]
        self.assertEqual((item["kind"], item["line"], item["context"], item["enclosing"]), ("deleted", None, "", []))

    def test_no_enclosing_line_falls_back_to_gits_header(self):
        self.r.at_base("tests/test_a.py", TEST_A + "\n\nX = 1\n")
        self.r.write("tests/test_a.py", TEST_A + "\n\nX = 2\n")
        self.r.commit("change X")
        items = self.items()
        self.assertEqual(len(items), 1, items)
        self.assertTrue(items[0].endswith("def test_b():"), items)
        out = self.r.run("list", "--json")
        self.assertEqual(json.loads(out.stdout)["items"][0]["enclosing"], [])


class EnclosingFunction(unittest.TestCase):
    """`enclosing()` on its own, for the edges the repository cases do not reach."""

    def setUp(self):
        import test_guard
        self.enclosing = test_guard.enclosing

    def test_an_addition_at_the_top_has_no_enclosing_line(self):
        self.assertEqual(self.enclosing(["def f():", "    x"], 0, 4), [])

    def test_blank_lines_are_passed_over(self):
        self.assertEqual(self.enclosing(["class T:", "    def f():", "", "        x"], 4, 8),
                         ["def f():", "class T:"])

    def test_a_failed_base_read_raises_gits_message(self):
        import test_guard
        r = Repo()
        self.addCleanup(r.close)
        fork = git(r.repo, "rev-parse", "HEAD").strip()
        cwd = Path.cwd()
        self.addCleanup(lambda: __import__("os").chdir(cwd))
        __import__("os").chdir(r.repo)
        # git's own output goes to /dev/null at the descriptor level: a mutant that
        # stops capturing it must not write a non-UTF-8 byte into the runner's pipe.
        os = __import__("os")
        saved = [os.dup(1), os.dup(2)]
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, 1)
        os.dup2(null, 2)
        try:
            with self.assertRaises(test_guard.GitError) as raised:
                test_guard._base_lines(fork, "tests/gone\udcff.py")
        finally:
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            for fd in (*saved, null):
                os.close(fd)
        self.assertIn("tests/gone", str(raised.exception))
        self.assertIn("fatal", str(raised.exception))

    def test_the_walk_goes_on_to_indentation_0(self):
        self.assertEqual(self.enclosing(["a:", " b:", "  c"], 3, 2), ["b:", "a:"])


class NotChecked(unittest.TestCase):
    def test_no_tests_key_exits_3(self):
        r = Repo(tests="")
        self.addCleanup(r.close)
        out = r.run("list")
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        self.assertIn("tests: not checked (no lane names its test files)", out.stdout)

    def test_patterns_matching_no_file_exit_3(self):
        r = Repo(tests='tests = ["spec/*"]')
        self.addCleanup(r.close)
        out = r.run("list")
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        self.assertIn("tests: not checked (no file matches", out.stdout)


def body(cases="1. The parser reads both forms.", files="**Edit:** `app/code.py`"):
    return BODY.format(cases=cases, files=files)


class Verify(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.addCleanup(self.r.close)
        self.r.branch()

    def two_hunks(self):
        text = TEST_A.replace("    assert two() == 2\n", "").replace("    assert four() == 4\n", "")
        self.r.write("tests/test_a.py", text)
        self.r.commit("loosen both")

    def verify(self, answers, **kw):
        return self.r.run("verify", body=body(**kw), answers=answers)

    def test_bad_answers_exit_2_naming_each_problem(self):
        self.two_hunks()
        out = self.verify("H1\tsame\tok\n")
        self.assertEqual(out.returncode, 2)
        self.assertIn("H2", out.stderr)
        out = self.verify("H1\tsame\tok\nH2\tsame\tok\nH3\tsame\tok\n")
        self.assertEqual(out.returncode, 2)
        self.assertIn("H3", out.stderr)
        out = self.verify("H1\tbetter\tok\nH2\tsame\tok\n")
        self.assertEqual(out.returncode, 2)
        self.assertIn("better", out.stderr)
        out = self.verify("H1\tweaker\t\nH2\tsame\tok\n")
        self.assertEqual(out.returncode, 2)
        self.assertIn("H1", out.stderr)

    def test_a_rewritten_file_licenses_its_hunks(self):
        self.two_hunks()
        out = self.verify("H1\tweaker\tdropped an assert\nH2\tweaker\tdropped an assert\n",
                          cases="1. `tests/test_a.py` rewritten for the new format")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("H1  licensed", out.stdout)
        self.assertIn("test-guard: hunks=2 same=0 stronger=0 weaker=2 licensed=2 unlicensed=0", out.stdout)

    def test_a_named_licence_covers_only_its_test(self):
        self.two_hunks()
        out = self.verify("H1\tweaker\tdropped\nH2\tweaker\tdropped\n",
                          cases="1. `tests/test_a.py::test_a` removed")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("H1  licensed", out.stdout)
        self.assertIn("H2  NOT LICENSED", out.stdout)
        self.assertIn("unlicensed=1", out.stdout)

    def method_hunks(self):
        self.r.at_base("tests/test_c.py", TEST_CLASS)
        self.r.write("tests/test_c.py", TEST_CLASS.replace("        self.assertEqual(two(), 2)\n", "")
                     .replace("        self.assertEqual(four(), 4)\n", ""))
        self.r.commit("loosen both methods")

    def test_a_method_licence_covers_only_its_method(self):
        self.method_hunks()
        for licence in ("tests/test_c.py::test_a", "tests/test_c.py::T::test_a"):
            with self.subTest(licence=licence):
                out = self.verify("H1\tweaker\tdropped\nH2\tweaker\tdropped\n", cases=f"1. `{licence}` removed")
                self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                self.assertIn("H1  licensed", out.stdout)
                self.assertIn("H2  NOT LICENSED", out.stdout)
                self.assertIn("unlicensed=1", out.stdout)

    def test_a_name_matches_as_a_whole_word(self):
        text = ("def test_parse():\n    assert a() == 1\n    assert b() == 2\n\n\n"
                "def test_parse_v2():\n    assert c() == 3\n    assert d() == 4\n")
        self.r.at_base("tests/test_p.py", text)
        self.r.write("tests/test_p.py", text.replace("    assert b() == 2\n", "").replace("    assert d() == 4\n", ""))
        self.r.commit("loosen both")
        out = self.verify("H1\tweaker\tdropped\nH2\tweaker\tdropped\n",
                          cases="1. `tests/test_p.py::test_parse` rewritten")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("H1  licensed", out.stdout)
        self.assertIn("H2  NOT LICENSED", out.stdout)

    def test_a_licence_in_files_or_without_the_word_licenses_nothing(self):
        self.two_hunks()
        answers = "H1\tweaker\tdropped\nH2\tsame\tok\n"
        out = self.verify(answers, files="**Edit:** `tests/test_a.py` rewritten")
        self.assertEqual(out.returncode, 1, out.stdout)
        out = self.verify(answers, cases="1. `tests/test_a.py` gains a case")
        self.assertEqual(out.returncode, 1, out.stdout)

    def test_a_deleted_file_licensed_by_its_path(self):
        (self.r.repo / "tests/test_a.py").unlink()
        self.r.commit("drop")
        out = self.verify("H1\tweaker\tthe file is gone\n", cases="1. `tests/test_a.py` removed with the old parser")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("H1  licensed", out.stdout)


def section(text, start):
    return text.split(f"\n## {start}")[1].split("\n## ")[0]


class Structure(unittest.TestCase):
    def test_the_skills_name_the_guard(self):
        dev = (PLUGIN / "skills" / "dev" / "SKILL.md").read_text(encoding="utf-8")
        six = section(dev, "6.")
        for name in ("test_guard.py", " list ", " verify "):
            self.assertIn(name, six)
        first_bullet = section(dev, "8.").split("\n- **")[1]
        self.assertIn("weakened test", first_bullet)
        four = section((PLUGIN / "skills" / "auto-dev" / "SKILL.md").read_text(encoding="utf-8"), "4.")
        self.assertIn("weakened test", four)

    def test_the_record_template_parses(self):
        seven = section((PLUGIN / "skills" / "dev" / "SKILL.md").read_text(encoding="utf-8"), "7.")
        lines = [ln for ln in seven.splitlines() if "<!-- gogogo:tests " in ln]
        self.assertEqual(len(lines), 1, lines)
        template = re.search(r"<!-- gogogo:tests .*? -->", lines[0]).group(0)
        keys = [p.split("=", 1)[0] for p in template[len("<!-- gogogo:tests "):-len(" -->")].split()]
        self.assertEqual(tuple(keys), review_stats.TESTS_KEYS)
        filled = re.sub(r"<([a-z]+)\|[^>]*>", r"\1", template.replace("<n>", "0"))
        record = review_stats.parse_tests(filled)
        self.assertIsNotNone(record, filled)

    def test_no_project_names(self):
        self.assertIsNone(re.search(PROJECT_NAMES, SCRIPT.read_text(encoding="utf-8"), re.I))


if __name__ == "__main__":
    unittest.main()
