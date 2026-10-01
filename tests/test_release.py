#!/usr/bin/env python3
"""Tests for release.py: the build number, the version, the deploy-<build> tag and its notes.

They run real `git` in a temp repo with a bare "origin", because what they guard
is what git does: a shallow count, a tag on the wrong branch, a second release
for one commit. Tags are read back through git, not through the script.

    python3 -m unittest tests.test_release
"""

import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import release  # noqa: E402
from test_profile_check import COMPLETE  # noqa: E402
from test_stage_sync import TempRepo  # noqa: E402
from test_tech_eval import PROJECT_NAMES  # noqa: E402


def profile_text(major=1):
    """COMPLETE with release.major set to `major`, or with no [release] table when it is None."""
    table = "[release]\nmajor = 1\n"
    assert table in COMPLETE
    return COMPLETE.replace(table, f"[release]\nmajor = {major}\n" if major is not None else "")


class ReleaseRepo(unittest.TestCase):
    """A temp repo with `commits` commits on main, pushed to a bare origin."""

    commits = 3

    def setUp(self):
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)
        self.shas = [self.repo.commit(f"commit {i + 1}") for i in range(self.commits)]
        self.origin = tempfile.TemporaryDirectory(prefix="release-origin-")
        self.addCleanup(self.origin.cleanup)
        subprocess.run(["git", "init", "-q", "--bare", self.origin.name], check=True)
        self.repo.git("remote", "add", "origin", self.origin.name)
        self.push_main()
        self.profile = self.write_profile()

    def push_main(self):
        self.repo.git("push", "-q", "origin", "main")
        self.repo.git("fetch", "-q", "origin")

    def write_profile(self, major=1):
        tmp = tempfile.TemporaryDirectory(prefix="release-profile-")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "dev-process.md"
        path.write_text(profile_text(major))
        return str(path)

    def run_main(self, *argv, profile=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = release.main(["--profile", profile or self.profile, *argv])
        return code, out.getvalue(), err.getvalue()

    def tags(self):
        return self.repo.git("tag", "-l", "deploy-*").split()

    def message(self, tag):
        return self.repo.git("for-each-ref", f"refs/tags/{tag}", "--format=%(contents)")


class Build(ReleaseRepo):
    def test_build_is_the_commit_count(self):
        code, out, _ = self.run_main("build")
        self.assertEqual((code, out.strip()), (0, "3"))

    def test_a_shallow_clone_is_refused(self):
        clone = Path(tempfile.mkdtemp(prefix="release-shallow-"))
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{self.repo.path}", str(clone)], check=True)
        here = Path.cwd()
        try:
            os.chdir(clone)
            code, _, err = self.run_main("build")
        finally:
            os.chdir(here)
        self.assertEqual(code, release.EXIT_REFUSED)
        self.assertIn("shallow", err)

    def test_version_is_major_zero_build(self):
        self.assertEqual(self.run_main("version")[1].strip(), "1.0.3")
        self.assertEqual(self.run_main("version", profile=self.write_profile(2))[1].strip(), "2.0.3")

    def test_version_without_release_major_is_a_profile_error(self):
        code, _, err = self.run_main("version", profile=self.write_profile(None))
        self.assertEqual(code, release.EXIT_PROFILE)
        self.assertIn("release.major", err)


class Tag(ReleaseRepo):
    def test_tag_creates_an_annotated_deploy_build_tag(self):
        code, out, err = self.run_main("tag")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.repo.git("cat-file", "-t", "deploy-3"), "tag")
        self.assertEqual(self.message("deploy-3").splitlines()[0], f"Release 1.0.3 · {self.shas[-1][:7]}")
        self.assertIn("to production", self.message("deploy-3").splitlines()[1])

    def test_first_release_says_so(self):
        self.run_main("tag")
        self.assertIn("first deploy-* release", self.message("deploy-3"))

    def test_rerun_on_the_same_commit_is_a_no_op(self):
        self.run_main("tag")
        before = self.message("deploy-3")
        code, out, _ = self.run_main("tag")
        self.assertEqual(code, 0)
        self.assertIn("already tagged", out)
        self.assertEqual(self.tags(), ["deploy-3"])
        self.assertEqual(self.message("deploy-3"), before)

    def test_a_name_taken_by_another_commit_is_refused(self):
        self.repo.git("switch", "-q", "-c", "side", self.shas[0])
        other = [self.repo.commit(f"side {i}") for i in range(2)][-1]
        self.repo.git("tag", "-a", "deploy-3", "-m", "x", other)
        self.repo.git("switch", "-q", "main")
        code, _, err = self.run_main("tag")
        self.assertEqual(code, release.EXIT_REFUSED)
        self.assertIn(other[:7], err)

    def test_a_commit_not_on_origin_base_is_refused(self):
        self.repo.commit("local only")
        code, _, err = self.run_main("tag")
        self.assertEqual(code, release.EXIT_REFUSED)
        self.assertIn("not on origin/main", err)
        self.assertEqual(self.tags(), [])

    def test_dry_run_creates_nothing(self):
        code, out, _ = self.run_main("tag", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "deploy-3")
        self.assertIn("Release 1.0.3", out)
        self.assertEqual(self.tags(), [])

    def test_push_reaches_the_remote(self):
        code, _, err = self.run_main("tag", "--push", "origin")
        self.assertEqual(code, 0, err)
        remote = subprocess.run(["git", "ls-remote", "--tags", self.origin.name],
                                capture_output=True, text=True, check=True).stdout
        self.assertIn("refs/tags/deploy-3", remote)

    def test_a_rerun_after_a_failed_push_pushes_the_tag(self):
        self.assertEqual(self.run_main("tag", "--push", "nowhere")[0], release.EXIT_NOT_PUSHED)
        code, out, err = self.run_main("tag", "--push", "origin")
        self.assertEqual(code, 0, err)
        self.assertIn("already tagged", out)
        remote = subprocess.run(["git", "ls-remote", "--tags", self.origin.name],
                                capture_output=True, text=True, check=True).stdout
        self.assertIn("refs/tags/deploy-3", remote)
        self.assertEqual(self.tags(), ["deploy-3"])

    def test_a_failed_push_keeps_the_local_tag_and_says_how_to_retry(self):
        code, _, err = self.run_main("tag", "--push", "nowhere")
        self.assertEqual(code, release.EXIT_NOT_PUSHED)
        self.assertEqual(self.tags(), ["deploy-3"])
        self.assertIn("git push nowhere refs/tags/deploy-3", err)


class Notes(ReleaseRepo):
    commits = 2

    def setUp(self):
        super().setUp()
        self.repo.git("tag", "-a", "deploy-2", "-m", "deploy-2", self.shas[1])
        self.repo.commit("Fix the thing\n\nShips-issue: acme/issues#7\n")
        self.repo.commit("Tidy, no issue")
        self.push_main()

    def test_tag_notes_list_linked_issues_and_count_the_rest(self):
        code, _, err = self.run_main("tag")
        self.assertEqual(code, 0, err)
        message = self.message("deploy-4")
        self.assertIn("#7", message)
        self.assertIn("+ 1 commit with no linked issue", message)

    def test_notes_print_the_tag_messages_body(self):
        self.run_main("tag")
        code, out, _ = self.run_main("notes", "--tag", "deploy-4")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "\n".join(self.message("deploy-4").splitlines()[3:]).strip())

    def test_notes_for_a_missing_tag_are_refused(self):
        code, _, err = self.run_main("notes", "--tag", "deploy-99")
        self.assertEqual(code, release.EXIT_REFUSED)
        self.assertIn("deploy-99", err)


class LegacyTag(ReleaseRepo):
    commits = 2

    def test_a_date_named_deploy_tag_is_the_previous_release(self):
        self.repo.git("tag", "-a", "deploy-2026Sep29-07.08", "-m", "old", self.shas[1])
        self.repo.commit("Fix it\n\nShips-issue: acme/issues#9\n")
        self.push_main()
        code, _, err = self.run_main("tag")
        self.assertEqual(code, 0, err)
        self.assertIn("#9", self.message("deploy-3"))
        self.assertNotIn("first deploy-* release", self.message("deploy-3"))


    def test_a_date_named_tag_on_the_same_commit_is_the_previous_release(self):
        self.repo.git("tag", "-a", "deploy-2026Sep29-07.08", "-m", "old", self.shas[0])
        self.repo.commit("Fix it\n\nShips-issue: acme/issues#9\n")
        self.repo.git("tag", "-a", "deploy-2026Sep30-07.08", "-m", "old", "HEAD")
        self.push_main()
        code, _, err = self.run_main("tag")
        self.assertEqual(code, 0, err)
        self.assertNotIn("#9", self.message("deploy-3"))
        code, out, _ = self.run_main("notes", "--tag", "deploy-3")
        self.assertNotIn("#9", out)


class Reference(unittest.TestCase):
    def test_versioning_reference_names_no_project(self):
        text = (PLUGIN / "references" / "versioning.md").read_text(encoding="utf-8")
        self.assertIsNone(re.search(PROJECT_NAMES, text, re.I))


if __name__ == "__main__":
    unittest.main()
