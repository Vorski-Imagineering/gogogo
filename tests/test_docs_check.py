#!/usr/bin/env python3
"""Tests for docs_check.py, the read-only check /gogogo:docs runs first (gogogo#270).

Each case builds a small repo in a temp folder with a profile, runs the script
on it, and reads its findings and exit code.

    python3 -m unittest tests.test_docs_check
"""

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import docs_check as dc  # noqa: E402

PROFILE = """+++
profile = 1
{docs}
[publish]
private_names = ["Acme Internal"]
+++

## superpowers boundary
x
"""


class DocsCheck(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "plugins").mkdir()

    def repo(self, files, docs=""):
        (self.root / ".agents").mkdir(exist_ok=True)
        (self.root / ".agents" / "dev-process.md").write_text(PROFILE.format(docs=docs))
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def run_it(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = dc.main(["--profile", str(self.root / ".agents" / "dev-process.md"), *extra])
        return code, out.getvalue().splitlines(), err.getvalue()

    def findings(self, lines, kind):
        return [ln for ln in lines if ln.startswith(kind + " ")]

    def test_a_broken_link_is_found_at_its_line(self):
        self.repo({"README.md": "# x\n\n[a](docs/a.md) and [gone](docs/missing.md#part)\n", "docs/a.md": "a\n"})
        code, lines, _ = self.run_it()
        self.assertEqual(code, 1)
        self.assertEqual(self.findings(lines, "link"), ["link README.md:3: docs/missing.md#part does not exist"])
        self.assertEqual(lines[-1], "docs: files=2 findings=1")

    def test_a_doc_the_index_does_not_link(self):
        self.repo({"docs/README.md": "[a](a.md)\n", "docs/a.md": "a\n", "docs/b.md": "b\n"},
                  docs='[docs]\nindex = "docs/README.md"\n')
        code, lines, _ = self.run_it()
        self.assertEqual(code, 1)
        self.assertEqual(self.findings(lines, "index"), ["index docs/b.md:1: not linked from docs/README.md"])

    def test_a_missing_backticked_path_but_not_a_placeholder_or_glob(self):
        self.repo({"docs/a.md": "See `plugins/x/gone.py`, `plugins/<name>.py`, `plugins/*.py`, `plugins/` and `/gogogo:dev`.\n"
                                "```\n`plugins/in/a/fence.py`\n```\n"})
        code, lines, _ = self.run_it()
        self.assertEqual(code, 1)
        self.assertEqual(self.findings(lines, "path"), ["path docs/a.md:1: `plugins/x/gone.py` does not exist"])

    def test_internal_detail_only_in_public_docs(self):
        text = "Run /home/me/x on 10.0.0.1, write to a@b.example, ask acme internal.\n"
        lines_of = text.replace("on ", "\non ").replace("write", "\nwrite").replace("ask", "\nask")
        self.repo({"docs/public/p.md": lines_of, "docs/a.md": lines_of}, docs='[docs]\npublic = "docs/public"\n')
        code, lines, _ = self.run_it()
        self.assertEqual(code, 1)
        self.assertEqual(self.findings(lines, "public"), [
            "public docs/public/p.md:1: holds an absolute path", "public docs/public/p.md:2: holds an IP address",
            "public docs/public/p.md:3: holds an email address", "public docs/public/p.md:4: holds a private name"])

    def test_no_file_in_scope_is_not_a_pass(self):
        self.repo({})
        code, lines, err = self.run_it()
        self.assertEqual(code, 2)
        self.assertEqual(lines[-1], "docs: files=0 findings=0")
        self.assertIn("no file in scope", err)

    def test_no_docs_folder_reads_the_readme_alone(self):
        self.repo({"README.md": "# x\n"})
        code, lines, _ = self.run_it()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["docs: no docs/ folder; README.md only", "docs: files=1 findings=0"])

    def test_an_index_or_public_folder_that_does_not_exist_stops(self):
        for docs in ('[docs]\nindex = "docs/README.md"\n', '[docs]\npublic = "docs/public"\n'):
            with self.subTest(docs):
                self.repo({"docs/a.md": "a\n"}, docs=docs)
                code, _, err = self.run_it()
                self.assertEqual(code, 2)
                self.assertIn("does not exist", err)

    def test_json_gives_the_same_findings_and_exit(self):
        self.repo({"README.md": "[gone](docs/missing.md)\n", "docs/a.md": "a\n"})
        plain_code, plain, _ = self.run_it()
        code, lines, _ = self.run_it("--json")
        data = json.loads("\n".join(lines))
        self.assertEqual((code, plain_code), (1, 1))
        self.assertEqual(data["files"], 2)
        self.assertEqual(len(data["findings"]), 1)
        self.assertEqual([f"{f['kind']} {f['file']}:{f['line']}: {f['detail']}" for f in data["findings"]], plain[:-1])

    def test_a_missing_path_git_ignores_is_not_reported(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.repo({".gitignore": "plugins/cache/\n", "docs/a.md": "See `plugins/cache/x` and `plugins/gone.py`.\n"})
        code, lines, _ = self.run_it()
        self.assertEqual(self.findings(lines, "path"), ["path docs/a.md:1: `plugins/gone.py` does not exist"])

    def test_a_doc_that_cannot_be_read_stops(self):
        self.repo({"README.md": "x\n"})
        (self.root / "docs").mkdir()
        (self.root / "docs" / "a.md").write_bytes(b"caf\xe9\n")
        code, _, err = self.run_it()
        self.assertEqual(code, 2)
        self.assertIn("docs/a.md", err)

    def test_a_folder_named_like_a_doc_is_not_one(self):
        self.repo({"README.md": "x\n", "docs/a.md": "a\n"})
        (self.root / "docs" / "dir.md").mkdir()
        code, lines, _ = self.run_it()
        self.assertEqual((code, lines[-1]), (0, "docs: files=2 findings=0"))

    def test_a_root_relative_link_resolves_from_the_repo_root(self):
        self.repo({"docs/a.md": "[x](/plugins/here.md) [y](/plugins/gone.md)\n", "plugins/here.md": "x\n"})
        code, lines, _ = self.run_it()
        self.assertEqual(self.findings(lines, "link"), ["link docs/a.md:1: /plugins/gone.md does not exist"])

    def test_public_text_that_only_looks_internal(self):
        self.repo({"docs/public/p.md": "Install `react@18.3.1`, clone git@github.com:o/r.git, "
                                       "see https://x.example/tmp/y and ~/x.\n"}, docs='[docs]\npublic = "docs/public"\n')
        code, lines, _ = self.run_it()
        self.assertEqual((code, self.findings(lines, "public")), (0, []))

    def test_an_unreadable_profile_stops(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = dc.main(["--profile", str(self.root / "nope.md")])
        self.assertEqual(code, 2)
        self.assertIn("profile", err.getvalue())


if __name__ == "__main__":
    unittest.main()
