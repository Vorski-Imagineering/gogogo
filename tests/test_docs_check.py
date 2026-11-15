#!/usr/bin/env python3
"""Tests for docs_check.py, the read-only check /gogogo:docs runs first (gogogo#270).

Each case builds a small repo in a temp folder with a profile, runs the script
on it, and reads its findings and exit code.

    python3 -m unittest tests.test_docs_check
"""

import io
import json
import shutil
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

    def test_a_doc_that_cannot_be_read_stops(self):
        self.repo({"README.md": "x\n"})
        (self.root / "docs").mkdir()
        (self.root / "docs" / "a.md").write_bytes(b"caf\xe9\n")
        code, _, err = self.run_it()
        self.assertEqual(code, 2)
        self.assertIn("docs/a.md", err)

    def test_an_index_that_cannot_be_read_stops(self):
        self.repo({"README.md": "x\n"}, docs='[docs]\nindex = "INDEX.md"\n')
        (self.root / "INDEX.md").write_bytes(b"caf\xe9\n")
        code, _, err = self.run_it()
        self.assertEqual(code, 2)
        self.assertIn("INDEX.md", err)

    def test_an_index_outside_the_repo_that_cannot_be_read_stops(self):
        repo = self.root / "repo"
        (repo / ".agents").mkdir(parents=True)
        index = self.root / "INDEX.md"
        (repo / ".agents" / "dev-process.md").write_text(PROFILE.format(docs=f'[docs]\nindex = "{index}"\n'))
        (repo / "README.md").write_text("x\n")
        (self.root / "INDEX.md").write_bytes(b"caf\xe9\n")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = dc.main(["--profile", str(repo / ".agents" / "dev-process.md")])
        self.assertEqual(code, 2)
        self.assertIn("INDEX.md", err.getvalue())

    def test_internal_detail_at_a_sentence_end_or_in_a_file_url(self):
        self.repo({"docs/public/p.md": "Write to ops@corp.example.\nOpen file:///home/me/x\nPATH=$PATH:/home/me/bin\n"},
                  docs='[docs]\npublic = "docs/public"\n')
        code, lines, _ = self.run_it()
        self.assertEqual(self.findings(lines, "public"), [
            "public docs/public/p.md:1: holds an email address", "public docs/public/p.md:2: holds an absolute path",
            "public docs/public/p.md:3: holds an absolute path"])

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
                                       "see https://x.example/tmp/y and ~/x.\n"
                                       "Edit `src/home/page.tsx`, [Home](../home/index.md), app/Users/list.tsx, "
                                       "ftp://mirror.example.org/tmp/p, http://[::1]/tmp/x and pkg@beta.rc.1.\n"
                                       "[Guide](/docs/home/index.md), GET /api/v1/Users/{id}, /srv/www/tmp/uploads/, "
                                       "https://en.wikipedia.org/wiki/X_(y)/tmp/z\n"
                                       "${HOME}/tmp/build, {project}/tmp/cache, %TEMP%/tmp/x, GET /users/42/orders, /Home/Index/, ABC:\\x, abc:\\x, 1c:\\x\n",
                   "docs/home/index.md": "x\n"},
                  docs='[docs]\npublic = "docs/public"\n')
        code, lines, _ = self.run_it()
        # gogogo#267: the two links into docs/home/ leave the public folder, a public-link each.
        self.assertEqual((code, self.findings(lines, "public")), (1, []))
        self.assertEqual(self.findings(lines, "public-link"), [
            "public-link docs/public/p.md:2: ../home/index.md leaves docs/public",
            "public-link docs/public/p.md:3: /docs/home/index.md leaves docs/public"])

    def test_an_absolute_path_under_another_folder(self):
        self.repo({"docs/public/p.md": "Cache in /private/tmp/x\nLogs in /var/tmp/x\nOpen /mnt/c/Users/me\n"
                                       "[/home/me/app](setup.md)\n**/home/me/app**\n_/var/tmp/x_\n{/tmp/x}\n"
                                       "https://x.example/?dir=/home/me\n*/tmp/cache*\n#!/home/alice/.venv/bin/python\n+/tmp/build-cache/\n"
                                       "**/Users/me/My Project**\nIn c:\\users\\alice\\project\n_C:\\Users\\alice\\app_\n"
                                       "\u8def\u5f84/home/alice/app\nOpen /mnt/C/Users/alice\n\u8def\u5f84C:\\Users\\alice\n"},
                  docs='[docs]\npublic = "docs/public"\n')
        code, lines, _ = self.run_it()
        self.assertEqual(self.findings(lines, "public"), [
            f"public docs/public/p.md:{n}: holds an absolute path" for n in range(1, 18)])

    def test_a_docs_folder_outside_the_repo_is_reported_not_a_crash(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        (outside / "a.md").write_text("[x](gone.md)\n")
        self.repo({}, docs=f'[docs]\ndir = "{outside}"\n')
        code, lines, _ = self.run_it()
        self.assertEqual((code, self.findings(lines, "link")), (1, [f"link {outside / 'a.md'}:1: gone.md does not exist"]))

    def test_fenced_blocks_of_either_kind_are_skipped_and_reading_goes_on(self):
        self.repo({"docs/a.md": "```\n[a](g1.md)\n```\n~~~\n[b](g2.md)\n~~~\n[c](g3.md)\n"})
        code, lines, _ = self.run_it()
        self.assertEqual(self.findings(lines, "link"), ["link docs/a.md:7: g3.md does not exist"])

    def test_links_that_are_not_relative_files_or_carry_an_anchor(self):
        self.repo({"docs/a.md": "[w](https://x.example/gone) [m](mailto:a@b.example) [s](here.md#part) "
                                "[r](/Xroot.md)\n", "docs/here.md": "x\n", "Xroot.md": "x\n"})
        code, lines, _ = self.run_it()
        self.assertEqual((code, self.findings(lines, "link")), (0, []))

    def test_a_path_with_a_space_is_not_a_path_and_line_or_test_suffixes_are_dropped(self):
        self.repo({"docs/a.md": "`plugins/a b` `plugins/here.py::T.name` `plugins/here.py:12` `plugins/here.py:3-9`\n",
                   "plugins/here.py": "x\n"})
        code, lines, _ = self.run_it()
        self.assertEqual((code, self.findings(lines, "path")), (0, []))

    def test_the_configured_folder_is_named_when_it_is_missing(self):
        self.repo({"README.md": "x\n"}, docs='[docs]\ndir = "guide"\n')
        code, lines, _ = self.run_it()
        self.assertEqual((code, lines[0]), (0, "docs: no guide/ folder; README.md only"))
        (self.root / "README.md").unlink()
        code, lines, err = self.run_it()
        self.assertEqual(code, 2)
        self.assertIn("no README.md and no guide/ folder", err)

    def test_no_file_in_scope_names_the_default_folder_and_json_prints_an_empty_result(self):
        self.repo({})
        code, lines, err = self.run_it("--json")
        self.assertEqual((code, lines), (2, ['{"files": 0, "findings": []}']))
        self.assertIn("no README.md and no docs/ folder", err)

    def test_an_empty_private_name_matches_nothing(self):
        self.repo({"docs/public/p.md": "plain words.\n"})
        (self.root / ".agents" / "dev-process.md").write_text(
            PROFILE.format(docs='[docs]\npublic = "docs/public"\n').replace('["Acme Internal"]', '["", "Acme Internal"]'))
        code, lines, _ = self.run_it()
        self.assertEqual((code, self.findings(lines, "public")), (0, []))

    def test_it_runs_as_a_script(self):
        import subprocess
        run = subprocess.run([sys.executable, str(ROOT / "plugins" / "gogogo" / "scripts" / "docs_check.py"),
                              "--profile", str(self.root / "nope.md")], capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout), (2, "docs: files=0 findings=0\n"))

    def test_an_unreadable_profile_stops(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = dc.main(["--profile", str(self.root / "nope.md")])
        self.assertEqual(code, 2)
        self.assertIn("profile", err.getvalue())


NAV_DOCS = '[docs]\npublic = "docs/pub"\nnav = "docs/pub/SUMMARY.md"\ntags = "docs/pub/tags.yml"\n'
MENU = "- [Home](README.md)\n- Guides\n    - [A](a.md)\n    - [B C](b%20c.md)\n"
TAGS = "# tags\nvocabulary:\n  api: the API\n\npages:\n  a.md: [api]\n"


class PublicMenuAndTags(unittest.TestCase):
    """gogogo#267: a public docs folder's menu, links and tags, checked before merge."""

    def setUp(self):
        self.case = DocsCheck("run_it")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def public(self, menu=MENU, tags=TAGS, docs=NAV_DOCS, **extra):
        files = {"docs/pub/README.md": "home\n", "docs/pub/a.md": "a\n", "docs/pub/b c.md": "b\n",
                 "docs/pub/SUMMARY.md": menu, "docs/pub/tags.yml": tags, **extra}
        self.case.repo(files, docs=docs)
        return self.case.run_it("--public")

    def kind(self, lines, kind):
        return self.case.findings(lines, kind)

    def test_a_nested_menu_with_an_encoded_name_passes(self):
        code, lines, err = self.public()
        self.assertEqual((code, lines[-1]), (0, "docs: files=4 findings=0"), err)

    def test_a_page_missing_from_the_menu(self):
        code, lines, _ = self.public(menu=MENU.replace("    - [A](a.md)\n", ""))
        self.assertEqual(code, 1)
        self.assertEqual(self.kind(lines, "nav"), ["nav docs/pub/SUMMARY.md:1: docs/pub/a.md missing from the menu"])

    def test_a_page_listed_twice(self):
        code, lines, _ = self.public(menu=MENU + "- [A again](a.md)\n")
        self.assertEqual(self.kind(lines, "nav"), ["nav docs/pub/SUMMARY.md:5: a.md listed twice"])

    def test_a_first_entry_that_is_not_the_landing_page(self):
        code, lines, _ = self.public(menu="- [A](a.md)\n- [Home](README.md)\n- [B](b%20c.md)\n")
        self.assertEqual(self.kind(lines, "nav"),
                         ["nav docs/pub/SUMMARY.md:1: first entry is not the landing page: a.md"])

    def test_a_menu_entry_for_a_missing_page(self):
        code, lines, _ = self.public(menu=MENU + "- [Gone](gone.md)\n")
        self.assertEqual(self.kind(lines, "nav"), ["nav docs/pub/SUMMARY.md:5: menu names a missing page: gone.md"])

    def test_a_menu_in_another_format_is_refused(self):
        code, lines, err = self.public(docs=NAV_DOCS.replace("SUMMARY.md", "nav.yml"))
        self.assertEqual(code, 2)
        self.assertIn("nav: unsupported format docs/pub/nav.yml; a Markdown list of links is read", err)

    def test_a_link_that_resolves_but_leaves_the_public_folder(self):
        self.case.repo({"README.md": "root\n"})
        code, lines, _ = self.public(**{"docs/pub/a.md": "[root](../../README.md)\n"})
        self.assertEqual(self.kind(lines, "public-link"),
                         ["public-link docs/pub/a.md:1: ../../README.md leaves docs/pub"])
        code, lines, _ = self.case.run_it()
        self.assertEqual(self.kind(lines, "link"), [])

    def test_an_unknown_tag_and_a_tags_key_for_a_missing_page(self):
        code, lines, _ = self.public(tags=TAGS.replace("[api]", "[api, nope]") + "  gone.md: [api]\n")
        self.assertEqual(code, 1)
        self.assertEqual(self.kind(lines, "tags"), ["tags docs/pub/tags.yml:6: a.md: tag nope is not in the vocabulary",
                                                    "tags docs/pub/tags.yml:7: gone.md does not exist"])

    def test_quoted_names_paths_and_tags_are_read(self):
        code, lines, err = self.public(tags='vocabulary:\n  "api": the API\npages:\n  "a.md": ["api"]\n')
        self.assertEqual((code, lines[-1]), (0, "docs: files=4 findings=0"), lines)

    def test_a_markdown_menu_with_no_list_is_refused(self):
        code, lines, err = self.public(menu="[Home](README.md) [A](a.md) [B](b%20c.md)\n")
        self.assertEqual(code, 2)
        self.assertIn("nav: unsupported format docs/pub/SUMMARY.md", err)

    def test_a_menu_of_outside_links_is_read_and_a_symlinked_page_named_where_it_sits(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        (outside / "e.md").write_text("e\n")
        self.public(menu="- [Ext](https://x.example/)\n")
        (self.case.root / "docs" / "pub" / "e.md").symlink_to(outside / "e.md")
        code, lines, err = self.case.run_it("--public")
        self.assertEqual(code, 1, err)
        self.assertIn("nav docs/pub/SUMMARY.md:1: docs/pub/e.md missing from the menu", lines)

    def test_a_public_folder_outside_the_repo_is_named_not_a_crash(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        for name, text in (("README.md", "home\n"), ("a.md", "a\n"), ("SUMMARY.md", "- [Home](README.md)\n")):
            (outside / name).write_text(text)
        self.case.repo({"docs/x.md": "x\n"}, docs=f'[docs]\npublic = "{outside}"\nnav = "{outside}/SUMMARY.md"\n')
        code, lines, err = self.case.run_it("--public")
        self.assertEqual(code, 1, err)
        self.assertIn(f"nav {outside}/SUMMARY.md:1: {outside}/a.md missing from the menu", lines)

    def test_quoted_names_keep_their_own_letters(self):
        # Only quotes are stripped, never a name's own first or last letter.
        code, lines, err = self.public(menu=MENU + "- [X](X.md)\n", **{"docs/pub/X.md": "x\n"},
                                       tags='vocabulary:\n  "XML": XML\npages:\n  "X.md": ["XML"]\n')
        self.assertEqual((code, lines[-1]), (0, "docs: files=5 findings=0"), lines)

    def test_a_menu_ending_in_a_section_line_and_an_index_landing_page(self):
        menu = "- [Home](index.md)\n- [A](a.md)\n- [B](b%20c.md)\n- [R](README.md)\n- Later\n"
        code, lines, err = self.public(menu=menu, **{"docs/pub/index.md": "i\n"})
        self.assertEqual((code, lines[-1]), (0, "docs: files=5 findings=0"), lines + [err])

    def test_a_missing_menu_tags_file_or_public_page_is_refused(self):
        for docs, said in ((NAV_DOCS.replace("SUMMARY.md", "GONE.md"), "docs.nav names docs/pub/GONE.md"),
                           (NAV_DOCS.replace("tags.yml", "gone.yml"), "docs.tags names docs/pub/gone.yml"),
                           ('[docs]\ntags = "docs/pub/tags.yml"\n', "docs.tags is set without docs.public")):
            with self.subTest(said):
                code, lines, err = self.public(docs=docs)
                self.assertEqual(code, 2)
                self.assertIn(said, err)
        (self.case.root / "docs" / "empty").mkdir()
        self.case.repo({}, docs='[docs]\npublic = "docs/empty"\n')
        code, lines, err = self.case.run_it("--public")
        self.assertEqual(code, 2)
        self.assertIn("no file in scope: no *.md under docs/empty", err)

    def test_a_tags_line_in_another_shape_is_refused(self):
        code, lines, err = self.public(tags=TAGS + "  - api\n")
        self.assertEqual(code, 2)
        self.assertIn("docs/pub/tags.yml:7", err)

    def test_a_menu_without_a_public_folder_is_refused(self):
        self.case.repo({"docs/a.md": "a\n", "docs/SUMMARY.md": "- [A](a.md)\n"}, docs='[docs]\nnav = "docs/SUMMARY.md"\n')
        code, lines, err = self.case.run_it()
        self.assertEqual(code, 2)
        self.assertIn("docs.nav is set without docs.public", err)

    def test_public_reads_only_the_public_folder(self):
        code, lines, _ = self.public(**{"docs/x.md": "[gone](gone.md)\n"})
        self.assertEqual((code, lines[-1]), (0, "docs: files=4 findings=0"))
        code, lines, _ = self.case.run_it()
        self.assertEqual(self.kind(lines, "link"), ["link docs/x.md:1: gone.md does not exist"])


if __name__ == "__main__":
    unittest.main()
