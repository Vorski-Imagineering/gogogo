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


if __name__ == "__main__":
    unittest.main()
