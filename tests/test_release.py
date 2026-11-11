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
from unittest import mock
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

    def test_a_tag_another_machine_pushed_for_this_commit_is_released(self):
        self.repo.git("tag", "-a", "deploy-3", "-m", "cut elsewhere")
        self.repo.git("push", "-q", "origin", "refs/tags/deploy-3")
        self.repo.git("tag", "-d", "deploy-3")
        self.repo.git("tag", "-a", "deploy-3", "-m", "cut here")
        code, out, err = self.run_main("tag", "--push", "origin")
        self.assertEqual(code, 0, err)
        self.assertIn("already on origin", out)

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



class Announce(ReleaseRepo):
    """gogogo#268: `announce` makes the Release, moves the cards and sends one message per tag."""

    commits = 2

    def setUp(self):
        super().setUp()
        self.repo.git("tag", "-a", "deploy-2", "-m", "deploy-2", self.shas[1])
        self.repo.commit("Fix the thing\n\nShips-issue: acme/issues#7\n")
        self.repo.git("tag", "-a", "deploy-3", "-m", "deploy-3")
        self.push_main()
        self.releases, self.calls, self.sent, self.fail = {}, [], [], set()
        self.view_error, self.created = "", ()
        world = self

        class Transport:
            def __init__(self, root):
                self.token = "x"

            def missing(self):
                return []

            def send(self, text, markup=False):
                world.sent.append(text)

        def gh(*args):
            self.calls.append(args[:2])
            verb, tag = args[1], args[2]
            if verb in self.fail:
                return subprocess.CompletedProcess(args, 1, "", f"{verb} refused")
            if verb == "view" and self.view_error:
                return subprocess.CompletedProcess(args, 1, "", self.view_error)
            if verb == "view":
                found = tag in self.releases
                return subprocess.CompletedProcess(args, 0 if found else 1, self.releases.get(tag, ""),
                                                   "" if found else "release not found")
            if verb == "create":
                self.created = args
            self.releases[tag] = Path(args[args.index("--notes-file") + 1]).read_text()
            return subprocess.CompletedProcess(args, 0, "", "")

        def sync(profile, tag, main_ref, dry_run):
            self.calls.append(("sync", tag, dry_run))
            print("MOVE      acme/issues#7  abc")
            if not dry_run:
                print("acme/issues#7: In Dev -> In Production")
            return 0

        for target, name, fake in ((release, "gh", gh), (release.stage_sync, "sync", sync),
                                   (release.stage_sync, "fetch_titles",
                                    lambda links: {("acme/issues", 7): "Fix the thing"}),
                                   (release.notify, "TRANSPORTS", {"telegram": Transport})):
            patcher = mock.patch.object(target, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def messages_on(self, text=None):
        text = text or profile_text()
        tmp = tempfile.TemporaryDirectory(prefix="release-profile-")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "dev-process.md"
        path.write_text(text.replace('notify = "none"', 'notify = "telegram"'))
        return str(path)

    def announce(self, *extra, profile=None):
        code, out, err = self.run_main("announce", "--tag", "deploy-3", *extra, profile=profile)
        return code, out.splitlines(), err

    def test_a_tag_this_clone_does_not_have(self):
        code, lines, err = self.announce_tag("deploy-99")
        self.assertEqual((code, lines, len(err.strip().splitlines())), (2, [], 1))
        self.assertEqual((self.calls, self.sent), ([], []))

    def announce_tag(self, tag):
        code, out, err = self.run_main("announce", "--tag", tag)
        return code, out.splitlines(), err

    def test_the_release_is_made_with_the_titles(self):
        code, lines, err = self.announce()
        self.assertEqual(code, 0, err)
        self.assertIn("release: created", lines)
        self.assertEqual(self.calls.count(("release", "create")), 1)
        self.assertIn("Fix the thing", self.releases["deploy-3"])

    def test_an_existing_release_is_not_made_again(self):
        self.releases["deploy-3"] = "notes\n"
        code, lines, _ = self.announce()
        self.assertIn("release: exists", lines)
        self.assertNotIn(("release", "create"), self.calls)

    def test_sync_runs_for_a_stage_that_takes_the_tag_and_is_skipped_without_one(self):
        code, lines, _ = self.announce()
        self.assertIn(("sync", "deploy-3", False), self.calls)
        self.assertIn("sync: 1 card(s) moved", lines)
        untagged = profile_text().replace('tag = "deploy-*"\n', "")
        self.assertNotEqual(untagged, profile_text())
        self.calls.clear()
        code, lines, _ = self.announce(profile=self.messages_on(untagged))
        self.assertEqual(code, 0)
        self.assertIn("sync: no stage takes deploy-3; skipped", lines)
        self.assertFalse([c for c in self.calls if c[0] == "sync"])
        self.assertTrue(any(line.startswith("notify: ") for line in lines))

    def test_one_message_per_tag(self):
        profile = self.messages_on()
        code, lines, err = self.announce(profile=profile)
        self.assertEqual(code, 0, err)
        self.assertIn("notify: sent", lines)
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.releases["deploy-3"].rstrip().endswith(release.ANNOUNCED))
        code, lines, _ = self.announce(profile=profile)
        self.assertIn("notify: already sent", lines)
        self.assertEqual(len(self.sent), 1)

    def test_messages_off_marks_nothing(self):
        code, lines, _ = self.announce()
        self.assertIn("notify: off; not marked", lines)
        self.assertNotIn(("release", "edit"), self.calls)
        self.assertNotIn(release.ANNOUNCED, self.releases.get("deploy-3", ""))

    def test_a_failed_release_names_its_retry_and_the_rest_still_run(self):
        self.fail.add("create")
        code, lines, _ = self.announce(profile=self.messages_on())
        self.assertEqual(code, 0)
        failed = next(line for line in lines if line.startswith("release: failed"))
        self.assertIn("announce --tag deploy-3 --only release", failed)
        self.assertIn(("sync", "deploy-3", False), self.calls)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("notify: sent; not marked (no Release)", lines)
        self.assertTrue(lines[-1].startswith("announce: deploy-3 release=failed"))

    def test_a_dry_run_writes_nothing(self):
        code, lines, _ = self.announce("--dry-run", profile=self.messages_on())
        self.assertEqual(code, 0)
        self.assertEqual(lines[:3], ["release: would create", "sync: would move 1 card(s)", "notify: would send"])
        self.assertFalse([c for c in self.calls if c[1] in ("create", "edit")])
        self.assertIn(("sync", "deploy-3", True), self.calls)
        self.assertEqual(self.sent, [])

    def test_only_one_job(self):
        code, lines, _ = self.announce("--only", "notify")
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("notify: "))
        self.assertTrue(lines[1].startswith("announce: deploy-3 notify="))
        self.assertFalse([c for c in self.calls if c[0] == "sync" or c[1] == "create"])


    def test_a_release_that_cannot_be_read_is_not_taken_as_missing(self):
        self.releases["deploy-3"] = f"notes\n\n{release.ANNOUNCED}\n"
        self.view_error = "HTTP 401: Bad credentials"
        code, lines, _ = self.announce(profile=self.messages_on())
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("release: failed: HTTP 401"), lines)
        self.assertTrue(lines[2].startswith("notify: failed: HTTP 401"), lines)
        self.assertEqual(self.sent, [])
        self.assertNotIn(("release", "create"), self.calls)

    def test_a_profile_with_no_production_fails_notify_rather_than_sending(self):
        broken = profile_text().replace('roles = ["production"]', 'roles = ["pre-production"]') \
                               .replace('tag = "deploy-*"\n', "")
        self.assertNotEqual(broken, profile_text())
        code, lines, _ = self.announce(profile=self.messages_on(broken))
        self.assertEqual(code, 0)
        self.assertTrue(lines[2].startswith("notify: failed: environments: no environment"), lines)
        self.assertEqual(self.sent, [])

    def test_a_dry_run_that_cannot_read_the_release_still_says_what_it_would_do(self):
        self.view_error = "HTTP 401: Bad credentials"
        code, lines, _ = self.announce("--dry-run", profile=self.messages_on())
        self.assertEqual((lines[0], lines[2]), ("release: would create", "notify: would send"))

    def test_the_release_is_made_only_from_the_tag_on_the_remote(self):
        self.announce()
        self.assertIn("--verify-tag", self.created)

    def test_a_branch_or_sha_is_not_a_tag(self):
        for name in ("main", self.shas[0]):
            with self.subTest(name):
                code, lines, err = self.announce_tag(name)
                self.assertEqual((code, lines, self.calls), (2, [], []))

    def test_a_profile_problem_fails_each_job_not_the_deploy(self):
        code, lines, _ = self.announce(profile=self.messages_on(profile_text().replace("[release]", "[release")))
        self.assertEqual(code, 0)
        self.assertEqual([line.split(":")[0] + ":" + line.split(":")[1] for line in lines[:3]],
                         ["release: failed", "sync: failed", "notify: failed"])

    def test_the_message_names_the_stage_environment_or_says_the_list_is_unavailable(self):
        staged = profile_text().replace('environment = "production"\ncolumn = "In Production"',
                                        'environment = "dev"\ncolumn = "In Production"')
        self.assertNotEqual(staged, profile_text())
        self.announce(profile=self.messages_on(staged))
        self.assertIn("to dev", self.sent[-1])
        with mock.patch.object(release.stage_sync, "shipped", side_effect=RuntimeError("git log failed")):
            self.releases.clear()
            code, lines, _ = self.announce(profile=self.messages_on())
        self.assertTrue(lines[2].startswith("notify: sent"), lines)
        self.assertIn("issue list unavailable", self.sent[-1])


class VersioningDoc(unittest.TestCase):
    def test_the_deploy_job_announces_and_no_tag_workflow_is_left(self):
        doc = (PLUGIN / "references" / "versioning.md").read_text(encoding="utf-8")
        part = doc.split("\n## 7")[1].split("\n## ")[0]
        self.assertIn("release.py announce", part)
        self.assertIsNone(re.search(r"^\s*on:\s*$[\s\S]*?^\s*tags:", part, re.M))

if __name__ == "__main__":
    unittest.main()
