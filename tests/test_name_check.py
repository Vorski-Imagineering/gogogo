#!/usr/bin/env python3
"""Tests for name_check.py: a draft's title and body are checked for the names of the repo it came from
(gogogo#163). Each test builds a real repo in a temporary folder and runs the script as a subprocess.

    python3 -m unittest tests.test_name_check
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "scripts" / "name_check.py"
sys.path.insert(0, str(SCRIPT.parent))

import name_check  # noqa: E402
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

PROFILE = """+++
profile = 1
[tracker]
kind = "github-project"
issues_repo = "acme/acme-ledger"
code_repo = "acme/acme-ledger"
public = true
{extra}
+++
"""


class NameCheck(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = self.tmp / "orbit-checkout"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "git@github.com:acme/acme-ledger.git")
        self.profile(PROFILE.format(extra=""))

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=ENV, check=True, capture_output=True, text=True)

    def profile(self, text):
        (self.repo / ".agents").mkdir(exist_ok=True)
        (self.repo / ".agents" / "dev-process.md").write_text(text)

    def check(self, body, title="a title", profile=None, title_text=None):
        body_file, title_file = self.tmp / "draft.md", self.tmp / "title.txt"
        body_file.write_text(body)
        if title_text is not False:
            title_file.write_text(title_text if title_text is not None else title + "\n")
        elif title_file.exists():
            title_file.unlink()
        args = [sys.executable, str(SCRIPT), "--profile", str(profile or self.repo / ".agents" / "dev-process.md"),
                "--title", str(title_file), str(body_file)]
        out = subprocess.run(args, cwd=self.repo, env=ENV, capture_output=True, text=True)
        return out.returncode, out.stdout.splitlines(), out.stderr

    def hits(self, body, **kw):
        code, lines, _ = self.check(body, **kw)
        return code, [ln.split(": ", 1)[1] for ln in lines if ": " in ln and not ln.startswith("name-check")]

    def test_a_name_from_the_profile_is_a_hit_with_its_file_and_line(self):
        code, lines, _ = self.check("first\nseen in acme-ledger today\n")
        self.assertEqual(code, 1)
        self.assertIn(f"{self.tmp / 'draft.md'}:2: acme-ledger", lines)

    def test_variants_of_a_name_hit_and_longer_words_do_not(self):
        for text in ("Acme Ledger", "acme_ledger", "ACME.LEDGER", "acme-ledger"):
            code, found = self.hits(f"see {text} here\n")
            self.assertEqual((code, found), (1, [text]), text)
        for text in ("acmeledgers", "xacme-ledger", "ledgerx"):
            self.assertEqual(self.hits(f"see {text} here\n")[0], 0, text)

    def test_the_remote_the_folder_the_main_worktree_a_host_and_a_listed_name_each_hit(self):
        self.git("remote", "set-url", "origin", "https://github.com/zenith/zenith-books.git")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        text = PROFILE.format(extra=(
            '[[environments]]\nname = "pre"\nroles = ["pre-merge"]\nurl = "https://staging.quartz-app.example/x"\n'
            '[publish]\nprivate_names = ["Tangerine Billing"]\n'))
        self.profile(text)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "profile")
        worktree = self.tmp / "side-folder"
        self.git("worktree", "add", "-q", "--detach", str(worktree))
        profile_path = worktree / ".agents" / "dev-process.md"
        for word in ("zenith/zenith-books", "orbit-checkout", "side-folder", "staging.quartz-app.example",
                     "tangerine billing"):
            code, found = self.hits(f"mentions {word} once\n", profile=profile_path)
            self.assertEqual((code, found), (1, [word]), word)

    def test_the_targets_own_names_are_not_checked(self):
        self.assertEqual(self.check("Vorski-Imagineering/gogogo and gogogo and vorski-imagineering\n")[0], 0)

    def test_an_existing_plugin_path_is_exempt_and_an_invented_one_is_not(self):
        self.profile(PROFILE.format(extra="").rstrip("\n")[:-3] + '[publish]\nprivate_names = ["notify"]\n+++\n')
        self.assertEqual(self.hits("see plugins/gogogo/scripts/notify.py and `scripts/notify.py`\n")[0], 0)
        code, found = self.hits("see scripts/notify-copy.py and the notify script\n")
        self.assertEqual(code, 1)
        self.assertEqual(found, ["notify", "notify"])

    def test_a_title_that_is_missing_empty_or_two_lines_is_refused(self):
        for title_text in (False, "", "\n\n", "one\ntwo\n"):
            code, lines, err = self.check("clean text\n", title_text=title_text)
            self.assertEqual((code, lines), (2, []), repr(title_text))
            self.assertIn("title", err)

    def test_a_title_with_a_name_is_a_hit(self):
        code, lines, _ = self.check("clean text\n", title="acme-ledger fails")
        self.assertEqual(code, 1)
        self.assertIn(f"{self.tmp / 'title.txt'}:1: acme-ledger", lines)

    def test_a_missing_body_or_profile_is_refused(self):
        title = self.tmp / "title.txt"
        title.write_text("t\n")
        out = subprocess.run([sys.executable, str(SCRIPT), "--profile", str(self.repo / ".agents" / "dev-process.md"),
                              "--title", str(title), str(self.tmp / "nope.md")],
                             cwd=self.repo, env=ENV, capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (2, ""))
        self.assertEqual(self.check("x\n", profile=self.tmp / "no-profile.md")[0], 2)

    def test_no_name_to_check_is_refused_not_passed(self):
        repo = self.tmp / "gogogo"
        repo.mkdir()
        self.git("init", "-q", "-b", "main", cwd=repo)
        self.git("remote", "add", "origin", "git@github.com:Vorski-Imagineering/gogogo.git", cwd=repo)
        (repo / ".agents").mkdir()
        profile = repo / ".agents" / "dev-process.md"
        profile.write_text(PROFILE.format(extra="").replace("acme/acme-ledger", "Vorski-Imagineering/gogogo"))
        code, lines, err = self.check("anything\n", profile=profile)
        self.assertEqual((code, lines), (2, []))
        self.assertIn("no names to check", err)

    def test_a_clean_draft_prints_the_pass_line(self):
        code, lines, _ = self.check("nothing private here\n")
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("name-check: clean ("), lines)
        self.assertIn(str(self.tmp / "title.txt"), lines[0])
        self.assertIn(str(self.tmp / "draft.md"), lines[0])

    def test_a_title_or_profile_that_is_not_text_is_refused(self):
        title = self.tmp / "title.txt"
        body = self.tmp / "draft.md"
        body.write_text("x\n")
        title.write_bytes(b"caf\xe9 \xff\n")
        args = [sys.executable, str(SCRIPT), "--profile", str(self.repo / ".agents" / "dev-process.md"),
                "--title", str(title), str(body)]
        out = subprocess.run(args, cwd=self.repo, env=ENV, capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (2, ""))
        title.write_text("t\n")
        bad = self.tmp / "bad-profile.md"
        bad.write_bytes(b"\xff\xfe")
        args[args.index("--profile") + 1] = str(bad)
        out = subprocess.run(args, cwd=self.repo, env=ENV, capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (2, ""))

    def test_the_title_option_is_required(self):
        body = self.tmp / "draft.md"
        body.write_text("x\n")
        out = subprocess.run([sys.executable, str(SCRIPT), str(body)], cwd=self.repo, env=ENV,
                             capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (2, ""))
        self.assertIn("--title", out.stderr)

    def test_the_reasons_say_what_is_wrong(self):
        code, _, err = self.check("x\n", title_text=False)
        self.assertIn("cannot read the title file", err)
        code, _, err = self.check("x\n", title_text="a\nb\n")
        self.assertIn("exactly one non-empty line", err)
        self.assertIn("name_check:", err)
        code, _, err = self.check("x\n", profile=self.tmp / "none.md")
        self.assertIn("cannot read the profile", err)


class Pieces(unittest.TestCase):
    """The parts the script is built from, one at a time."""

    def test_a_remote_url_gives_owner_and_name(self):
        for url, expected in (("git@github.com:acme/acme-ledger.git", "acme/acme-ledger"),
                              ("https://github.com/acme/acme-ledger.git", "acme/acme-ledger"),
                              ("git@host:acme/acme-ledger", "acme/acme-ledger"),
                              ("https://host/group/acme/acme-ledger", "acme/acme-ledger"),
                              ("https://host/Xavier/Xtra", "Xavier/Xtra"),
                              ("justaname", None)):
            self.assertEqual(name_check._remote_names(url), expected, url)

    def names(self, settings, root):
        return name_check.derive(settings, root)

    def test_names_are_derived_from_each_source_and_kept_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "plain-folder"
            root.mkdir()
            settings = {"tracker": {"issues_repo": "acme/issues-x", "code_repo": "acme/code-y"},
                        "environments": [{"name": "a"}, {"name": "b", "url": "https://stage.example.test/x"}],
                        "publish": {"private_names": ["abc", "ab", "Abc", "Vorski-Imagineering/gogogo"]}}
            found = self.names(settings, root)
        for expected in ("acme/issues-x", "issues-x", "acme/code-y", "code-y", "acme", "plain-folder",
                         "stage.example.test", "abc"):
            self.assertIn(expected, found)
        self.assertNotIn("ab", found, "under three characters")
        self.assertEqual([n for n in found if n.lower() == "abc"], ["abc"], "de-duplicated ignoring case")

    def test_the_repo_folder_is_the_git_toplevel_not_the_profiles_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve() / "top-level-name"
            (repo / "sub").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=ENV, check=True)
            self.assertIn("top-level-name", self.names({}, repo / "sub"))

    def test_a_folder_that_is_no_repo_is_still_a_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "not-a-repo-folder"
            root.mkdir()
            self.assertIn("not-a-repo-folder", self.names({}, root))

    def test_only_the_listed_separators_stand_for_each_other(self):
        pattern = name_check.pattern("acme-ledger")
        for text in ("acme ledger", "acme_ledger", "acme.ledger", "ACME-LEDGER"):
            self.assertTrue(pattern.search(text), text)
        for text in ("acmexledger", "acmeXledger", "acme/ledger", "acme--ledger"):
            self.assertFalse(pattern.search(text), text)

    def exempt(self, text, name):
        return name_check.hits("f", text, [name_check.pattern(name)])

    def test_the_exempt_path_is_the_whole_token_between_its_edges(self):
        for text in ("see plugins/gogogo/scripts/notify.py here", "see `plugins/gogogo/scripts/notify.py`, ok",
                     "(plugins/gogogo/scripts/notify.py)", "see plugins/gogogo/ here", "see scripts/notify.py"):
            self.assertEqual(self.exempt(text, "plugins" if "plugins" in text else "notify"), [], text)
        self.assertEqual(self.exempt("see plugins/gogogo/scripts/notify.pyX here", "notify")[0][3], "notify")
        self.assertEqual(self.exempt("end plugins/gogogo/scripts/notify.py", "notify py"), [])

    def test_only_a_relative_path_inside_the_plugin_is_exempt(self):
        for token in ("/Users/jdoe/cache/gogogo/scripts/notify.py", "~/gogogo/scripts/notify.py",
                      "scripts/jdoe/../notify.py", "../gogogo/scripts/notify.py"):
            self.assertEqual(len(self.exempt(f"see {token} here", "jdoe" if "jdoe" in token else "gogogo")), 1, token)

    def test_an_absolute_path_to_a_real_plugin_file_is_not_exempt(self):
        real = name_check.PLUGIN_ROOT / "scripts" / "notify.py"
        self.assertTrue(real.exists())
        private = name_check.PLUGIN_ROOT.parents[1].name
        self.assertTrue(self.exempt(f"see {real} here", private))

    def test_a_word_with_no_slash_is_never_a_path(self):
        self.assertTrue((name_check.PLUGIN_ROOT / "scripts").exists())
        self.assertEqual([h[3] for h in self.exempt("see scripts here", "scripts")], ["scripts"])

    def test_a_shorter_name_inside_a_longer_one_is_one_hit(self):
        found = name_check.hits("f", "in acme-ledger now\n", [name_check.pattern("acme-ledger"),
                                                              name_check.pattern("ledger"),
                                                              name_check.pattern("acme")])
        self.assertEqual([h[3] for h in found], ["acme-ledger"])

    def test_the_name_length_limit_is_three(self):
        settings = {"publish": {"private_names": ["abc", "ab"]}}
        with tempfile.TemporaryDirectory() as tmp:
            found = name_check.derive(settings, Path(tmp).resolve() / "x")
        self.assertIn("abc", found)
        self.assertNotIn("ab", found)


if __name__ == "__main__":
    unittest.main()
