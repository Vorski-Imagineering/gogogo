#!/usr/bin/env python3
"""Tests for stage_sync.py: the issue link in git, and the move a tag makes.

The link tests run real `git` in a temp repo, because the failure they guard is
git silently not parsing a trailer — a fake git would agree with whatever the
writer wrote. The sync tests fake the board and every write, and assert on the
order of the writes, because a card moved without its comment is the one
outcome the order exists to prevent.

    python3 -m unittest tests.test_stage_sync
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
SCRIPTS = PLUGIN / "scripts"
DEV_HAND_BACK = PLUGIN / "skills" / "dev" / "references" / "hand-back.md"
AUTO_DEV_MERGE = PLUGIN / "skills" / "auto-dev" / "references" / "merge.md"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stage_sync as ss  # noqa: E402
from test_tech_eval import PROJECT_NAMES  # noqa: E402

KNOWN = {"issues": "acme/issues", "code": "acme/code"}

PROFILE = """+++
profile = 1

[tracker]
kind = "github-project"
issues_repo = "{issues}"
code_repo = "acme/code"
public = true
tool = "shared"
project_owner = "acme"
project_number = 2
queue = "Dev Ready"
columns = {{ in_progress = "In progress", back_to_queue = "Dev Ready" }}

[[environments]]
name = "local"
roles = ["pre-merge"]

[[environments]]
name = "staging"
roles = ["pre-production"]
url = "https://staging.example.org"

[[environments]]
name = "production"
roles = ["production"]
{production_url}

[[stages]]
code_is = "merged to main"
environment = "local"
column = "Merged"
{middle}
[[stages]]
code_is = "in a deploy tag"
environment = "production"
column = "Released"
tag = "{deploy_tag}"

[handback]
reporter = "{reporter}"
+++
"""

STAGING_STAGE = """
[[stages]]
code_is = "in a staging tag"
environment = "staging"
column = "In Staging"
tag = "{staging_tag}"
"""


def profile_text(reporter="trailer", three_stages=False, url=True, issues="acme/issues",
                 staging_tag="staging-*", deploy_tag="deploy-*"):
    return PROFILE.format(
        reporter=reporter,
        issues=issues,
        deploy_tag=deploy_tag,
        middle=STAGING_STAGE.format(staging_tag=staging_tag) if three_stages else "",
        production_url='url = "https://app.example.org"' if url else "",
    )


class TrackerState(unittest.TestCase):
    """tracker.configure() sets module globals other test modules rely on."""

    def setUp(self):
        t = ss.tracker
        saved = (t.ORG, t.PROJECT_NUMBER, t.DEFAULT_REPO, dict(t.COLUMNS))

        def restore():
            t.ORG, t.PROJECT_NUMBER, t.DEFAULT_REPO = saved[:3]
            t.COLUMNS.clear()
            t.COLUMNS.update(saved[3])
        self.addCleanup(restore)
        # A real board read from a test would be a bug: refuse it.
        no_network = mock.patch.object(t, "graphql", side_effect=AssertionError("graphql called"))
        no_network.start()
        self.addCleanup(no_network.stop)

    def write_profile(self, **kw):
        tmp = tempfile.TemporaryDirectory(prefix="stage-sync-profile-")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "dev-process.md"
        path.write_text(profile_text(**kw))
        return str(path)


class TempRepo:
    """A throwaway git repo; every test that touches git runs inside one."""

    def __init__(self):
        self._dir = tempfile.TemporaryDirectory(prefix="stage-sync-")
        self.path = self._dir.name
        self._cwd = os.getcwd()
        os.chdir(self.path)
        env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "user.name", "t")
        self._n = 0

    def git(self, *args):
        return subprocess.run(["git", *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, message):
        self._n += 1
        Path(f"f{self._n}").write_text(str(self._n))
        self.git("add", ".")
        self.commit_staged(message)
        return self.git("rev-parse", "HEAD")

    def commit_staged(self, message):
        with tempfile.NamedTemporaryFile("w", delete=False) as msg:
            msg.write(message)
        self.git("commit", "-q", "-F", msg.name)
        os.unlink(msg.name)

    def tag(self, name):
        self.git("tag", "-a", name, "-m", name)

    def close(self):
        os.chdir(self._cwd)
        self._env.stop()
        self._dir.cleanup()


class RepoTestCase(TrackerState):
    def setUp(self):
        super().setUp()
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)


def squash_body(*trailer_lines, after=None):
    body = "Fix the thing (#999)\n\n* fix the thing\n* test it\n\n"
    body += "\n".join(trailer_lines) + "\n"
    if after:
        body += after + "\n"
    return body


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ss.main(list(argv))
    return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------
# the link
# --------------------------------------------------------------------------


class TrailerInGit(RepoTestCase):
    def test_the_written_trailer_is_one_git_parses(self):
        sha = self.repo.commit(squash_body(
            ss.format_trailer(ss.IssueLink("acme/issues", 450, "jdoe")),
            "Co-Authored-By: Someone <s@example.invalid>",
        ))
        links = ss.trailer_links("HEAD", KNOWN)
        self.assertEqual(list(links), [("acme/issues", 450)])
        self.assertEqual(links[("acme/issues", 450)].shas, [sha])
        self.assertEqual(links[("acme/issues", 450)].reporters, ["jdoe"])

    def test_a_prose_line_after_the_trailers_is_not_a_link(self):
        self.repo.commit(squash_body(
            ss.format_trailer(ss.IssueLink("acme/issues", 450)),
            after="and a prose line git will not treat as a trailer",
        ))
        self.assertEqual(ss.trailer_links("HEAD", KNOWN), {})

    def test_two_issues_in_one_commit(self):
        self.repo.commit(squash_body(
            ss.format_trailer(ss.IssueLink("acme/issues", 1)),
            ss.format_trailer(ss.IssueLink("acme/code", 2)),
        ))
        self.assertEqual(set(ss.trailer_links("HEAD", KNOWN)),
                         {("acme/issues", 1), ("acme/code", 2)})

    def test_the_legacy_short_form_is_still_read(self):
        self.repo.commit(squash_body("Ships-issue: issues#7 reporter=jdoe"))
        self.repo.commit(squash_body("Ships-issue: code#8"))
        self.repo.commit(squash_body("Ships-issue: other#9"))
        err = io.StringIO()
        with redirect_stderr(err):
            links = ss.trailer_links("HEAD", KNOWN)
        self.assertEqual(set(links), {("acme/issues", 7), ("acme/code", 8)})
        self.assertEqual(links[("acme/issues", 7)].reporters, ["jdoe"])
        self.assertEqual(err.getvalue().count("unreadable"), 1)
        self.assertIn("other#9", err.getvalue())


class Parse(unittest.TestCase):
    def test_parse_issue_arg_forms(self):
        self.assertEqual(ss.parse_issue_arg("450", KNOWN), ss.IssueLink("acme/issues", 450))
        self.assertEqual(ss.parse_issue_arg("450=jdoe", KNOWN), ss.IssueLink("acme/issues", 450, "jdoe"))
        self.assertEqual(ss.parse_issue_arg("acme/code#12", KNOWN), ss.IssueLink("acme/code", 12))
        self.assertEqual(ss.parse_issue_arg("acme/code#12=jdoe", KNOWN),
                         ss.IssueLink("acme/code", 12, "jdoe"))
        self.assertEqual(ss.parse_issue_arg("code#12", KNOWN), ss.IssueLink("acme/code", 12))
        for bad in ("#450", "450==", "", "0", "other#3", "450=", "450=a b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ss.parse_issue_arg(bad, KNOWN)

    def test_parse_trailer_is_the_inverse_of_format(self):
        for link in (ss.IssueLink("acme/issues", 450, "jdoe"), ss.IssueLink("acme/code", 3)):
            value = ss.format_trailer(link).split(": ", 1)[1]
            self.assertEqual(ss.parse_trailer(value, KNOWN), link)
        with self.assertRaises(ValueError):
            ss.parse_trailer("acme/issues#450 fixed=yes", KNOWN)

    def test_the_key_is_not_a_github_closing_keyword(self):
        """`Fixes:` would close the issue at merge, before anyone saw it live."""
        closing = {"close", "closes", "closed", "fix", "fixes", "fixed",
                   "resolve", "resolves", "resolved"}
        self.assertNotIn(ss.TRAILER_KEY.lower(), closing)


class TrailerCommand(TrackerState):
    def test_branch_names_the_issue_and_issue_wins(self):
        profile = self.write_profile()
        code, out, _ = run_main("--profile", profile, "trailer", "--branch", "fix/450-slug")
        self.assertEqual((code, out), (0, "Ships-issue: acme/issues#450\n"))

        code, out, err = run_main("--profile", profile, "trailer", "--branch", "feature/x")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--issue", err)

        code, out, _ = run_main("--profile", profile, "trailer", "--branch", "fix/450-x", "--issue", "451")
        self.assertEqual((code, out), (0, "Ships-issue: acme/issues#451\n"))

    def test_verify_exit_codes(self):
        """A skill retries without the login only on 3; 2 means do not merge."""
        profile = self.write_profile()

        def gh(fail):
            def fake(cmd, **_):
                return mock.Mock(returncode=1 if fail(cmd) else 0, stdout="", stderr="")
            return fake

        cases = [
            (lambda c: c[1:3] == ["issue", "view"], "9999", 2, "acme/issues#9999 does not exist"),
            (lambda c: c[-2].endswith("assignees/nobody"), "450=nobody", 3, "'nobody' cannot be assigned"),
            (lambda c: False, "450=jdoe", 0, ""),
        ]
        for fail, issue, want, message in cases:
            with self.subTest(issue=issue), \
                 mock.patch.object(ss.subprocess, "run", side_effect=gh(fail)):
                code, out, err = run_main("--profile", profile, "trailer", "--issue", issue, "--verify")
            self.assertEqual(code, want)
            self.assertIn(message, err)
            if want:
                self.assertEqual(out, "")
            else:
                self.assertEqual(out, "Ships-issue: acme/issues#450 reporter=jdoe\n")


class SquashRecipe(RepoTestCase):
    def test_the_link_survives_a_squash_built_by_the_skill_recipe(self):
        """The body as /gogogo:dev §8 builds it: bullets, a blank line, and the
        `trailer --co-authors-from` output as the final paragraph."""
        profile = self.write_profile()
        self.repo.commit("base")
        self.repo.git("switch", "-q", "-c", "fix/450-thing")
        self.repo.commit("first change\n\nCo-Authored-By: A <a@x>\n")
        self.repo.commit("second change\n\nCo-authored-by: A <a@x>\n")

        bullets = self.repo.git("log", "--reverse", "--format=* %s", "main..fix/450-thing")
        code, trailers, _ = run_main("--profile", profile, "trailer", "--issue", "450=jdoe",
                                     "--co-authors-from", "main..fix/450-thing")
        self.assertEqual(code, 0)
        body = f"Fix the thing (#7)\n\n{bullets}\n\n{trailers}"

        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "--squash", "-q", "fix/450-thing")
        self.repo.commit_staged(body)
        squash = self.repo.git("rev-parse", "HEAD")

        parsed = subprocess.run(["git", "interpret-trailers", "--parse"], input=body,
                                capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertIn("Ships-issue: acme/issues#450 reporter=jdoe", parsed)
        self.assertEqual(len([t for t in parsed if t.lower().startswith("co-authored-by:")]), 1)
        links = ss.trailer_links("main", KNOWN)
        self.assertEqual(links[("acme/issues", 450)].shas, [squash])


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------


def card(number, repo="acme/issues", assignees=("maint",), status="Merged"):
    return {"number": number, "repo": repo, "state": "OPEN", "kind": "Issue",
            "status": status, "assignees": list(assignees), "title": f"issue {number}"}


class Plan(unittest.TestCase):
    LINKS = {("acme/issues", 406): ss.Linked(["ce2e31e2", "ec9721cb"], [])}

    def plan(self, c, links=None, shipped=lambda s: True):
        return ss.plan(c, self.LINKS if links is None else links, shipped, "acme/issues")

    def test_every_commit_shipped_moves_and_one_missing_stays(self):
        self.assertEqual(self.plan(card(406)).kind, ss.MOVE)
        stay = self.plan(card(406), shipped=lambda s: s == "ce2e31e2")
        self.assertEqual(stay.kind, ss.STAY)
        self.assertEqual(stay.missing, ("ec9721cb",))

    def test_card_with_no_link_is_unlinked(self):
        self.assertEqual(self.plan(card(7)).kind, ss.UNLINKED)

    def test_a_code_repo_card_is_keyed_by_its_own_repo(self):
        links = {("acme/code", 406): ss.Linked(["abc"], [])}
        self.assertEqual(self.plan(card(406, repo="acme/code"), links).kind, ss.MOVE)
        self.assertEqual(self.plan(card(406), links).kind, ss.UNLINKED)

    def test_repo_names_meet_cards_case_insensitively(self):
        """GitHub owner and repo names are case-insensitive; a card's spelling
        and a trailer's must still meet, in the full and the short form."""
        known = ss.Profile(Path("p"), {"tracker": {"issues_repo": "acme-corp/app",
                                                   "code_repo": "acme-corp/code"}}).known
        for value in ("acme-corp/app#5", "Acme-Corp/App#5", "App#5", "app#5"):
            with self.subTest(value=value):
                link = ss.parse_trailer(value, known)
                links = {link.key: ss.Linked(["abc"], [])}
                decision = ss.plan(card(5, repo="Acme-Corp/app"), links, lambda s: True, "acme-corp/app")
                self.assertEqual(decision.kind, ss.MOVE)
                self.assertEqual(decision.ref(), "Acme-Corp/app#5")


# --------------------------------------------------------------------------
# the sync
# --------------------------------------------------------------------------

LINKED = {("acme/issues", 450): ss.Linked(["1a6e11b7ffff"], ["jdoe"])}
BOARD = {"options": {"Merged": "a", "In Staging": "s", "Released": "b"}}


class Sync(TrackerState):
    """`sync` with the board, the tag and every write faked."""

    def _sync(self, cards, links=LINKED, *, tag="deploy-x", shipped=lambda sha: True,
              results=None, dry_run=False, tag_ok=True, announced=False, list_error=None,
              board_meta=BOARD, me="maint", profile=None, fail=None, comments=None):
        """`comments`: the issue's comment bodies, read by the real
        already_announced; None fakes already_announced with `announced`."""
        self.profile = profile or self.write_profile()
        calls, self.statuses, self.bodies = [], [], []
        results = results or {}

        def fake_list_cards(*, status=None, repo=None, **_):
            # The real list_cards binds its default `repo` at import, before
            # configure() runs, so a caller that omits it reads no repo live.
            if not repo:
                raise ValueError("list_cards needs repo=tracker.DEFAULT_REPO")
            self.statuses.append(status)
            return cards, [], 0

        def fake_run(cmd):
            calls.append(cmd)
            if "--body-file" in cmd:
                self.bodies.append(Path(cmd[cmd.index("--body-file") + 1]).read_text())
            if fail and fail(cmd):
                return 1
            for verb, code in results.items():
                if verb in cmd:
                    return code
            return 0

        def fake_resolve(t):
            if not tag_ok:
                raise ss.SyncError(f"no such tag: {t}")
            return "deadbeef"

        def fake_login():
            calls.append(["gh", "api", "user"])
            return me

        listing = {"side_effect": list_error or fake_list_cards}
        self.board_meta = mock.Mock(return_value=board_meta)
        self.list_cards = mock.Mock(**listing)
        argv = ["--profile", self.profile, "sync", "--tag", tag] + (["--dry-run"] if dry_run else [])
        if comments is None:
            announcing = mock.patch.object(ss, "already_announced", return_value=announced)
        else:
            real_run = subprocess.run

            def comments_only(cmd, *a, **kw):
                # Only the comment read is faked; any other subprocess call
                # takes its real path.
                if cmd[:3] == ["gh", "issue", "view"] and "comments" in cmd:
                    return mock.Mock(returncode=0, stdout=comments)
                return real_run(cmd, *a, **kw)
            announcing = mock.patch.object(ss.subprocess, "run", side_effect=comments_only)
        with mock.patch.object(ss, "resolve_tag", side_effect=fake_resolve), announcing, \
             mock.patch.object(ss, "trailer_links", return_value=links), \
             mock.patch.object(ss.tracker, "list_cards", self.list_cards), \
             mock.patch.object(ss.tracker, "board_meta", self.board_meta), \
             mock.patch.object(ss, "is_ancestor", side_effect=lambda s, t: shipped(s)), \
             mock.patch.object(ss, "run", side_effect=fake_run), \
             mock.patch.object(ss, "authenticated_login", side_effect=fake_login):
            code, self.out, self.err = run_main(*argv)
        return code, calls

    @staticmethod
    def writes(calls):
        return [c for c in calls if c[:3] != ["gh", "api", "user"]]

    @classmethod
    def verbs(cls, calls):
        """Each write reduced to what it does: show/move from the tracker, gh's verb."""
        out = []
        for cmd in cls.writes(calls):
            if cmd[0] == "gh":
                out.append(f"issue {cmd[2]}")
            else:
                # [python, tracker.py, "--profile", <path>, <verb>, ...]
                out.append(cmd[4] + (" --expect" if "--expect" in cmd else ""))
        return out

    def test_write_order_is_expect_comment_assign_move(self):
        code, calls = self._sync([card(450)])
        self.assertEqual(code, 0, self.err)
        self.assertEqual(self.verbs(calls), ["show --expect", "issue comment", "issue edit", "move"])
        writes = self.writes(calls)
        edit, move = writes[2], writes[3]
        self.assertEqual(edit[edit.index("--add-assignee") + 1], "jdoe")
        self.assertEqual(edit[edit.index("--remove-assignee") + 1], "maint")
        self.assertEqual(move[move.index("--to") + 1], "Released")
        self.assertEqual(writes[0][writes[0].index("--expect") + 1], "Merged")
        self.assertIn("acme/issues#450: Merged -> Released", self.out)

    def test_every_tracker_call_names_this_profile(self):
        """A CI run must never read whatever profile its working directory finds."""
        _, calls = self._sync([card(450)])
        tracker_calls = [c for c in self.writes(calls) if c[0] != "gh"]
        self.assertEqual(len(tracker_calls), 2)
        for cmd in tracker_calls:
            self.assertEqual(cmd[:4], [sys.executable, str(SCRIPTS / "tracker.py"), "--profile", self.profile])

    def test_card_moved_by_a_person_writes_nothing(self):
        code, calls = self._sync([card(450)], results={"show": 3})
        self.assertEqual(code, 0)
        self.assertEqual(self.verbs(calls), ["show --expect"])

    def test_no_reporter_moves_without_assigning(self):
        links = {("acme/issues", 450): ss.Linked(["1a6e11b7"], [])}
        code, calls = self._sync([card(450)], links)
        self.assertEqual(code, 0)
        self.assertEqual(self.verbs(calls), ["show --expect", "issue comment", "move"])

    def test_an_announced_card_is_not_commented_on_again(self):
        code, calls = self._sync([card(450)], announced=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.verbs(calls), ["show --expect", "issue edit", "move"])

    def test_a_failed_assignment_still_moves_and_does_not_block_the_rest(self):
        links = {**LINKED, ("acme/issues", 451): ss.Linked(["bbbb"], [])}
        code, calls = self._sync([card(450), card(451)], links, results={"edit": 1})
        self.assertEqual(code, 1)
        self.assertEqual(self.verbs(calls), [
            "show --expect", "issue comment", "issue edit", "move",
            "show --expect", "issue comment", "move",
        ])
        self.assertIn("could not assign jdoe", self.err)

    def test_comment_failure_stops_before_move(self):
        code, calls = self._sync([card(450)], results={"comment": 1})
        self.assertEqual(code, 2)
        self.assertNotIn("move", self.verbs(calls))
        self.assertIn("comment failed; card not moved", self.err)

    def test_a_failed_comment_does_not_stop_the_other_cards(self):
        links = {**LINKED, ("acme/issues", 451): ss.Linked(["bbbb"], [])}
        code, calls = self._sync([card(450), card(451)], links,
                                 fail=lambda cmd: "comment" in cmd and "450" in cmd)
        self.assertEqual(code, 2)
        self.assertEqual(self.verbs(calls), [
            "show --expect", "issue comment",
            "show --expect", "issue comment", "move",
        ])
        self.assertIn("acme/issues#451: Merged -> Released", self.out)
        self.assertRegex(self.err, r"(?m)^1 card\(s\) not moved, their comment failed: acme/issues#450$")

    def test_dry_run_makes_no_call_at_all(self):
        code, calls = self._sync([card(450)], dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("dry run: nothing written", self.out)

    def test_unlinked_card_exits_1_after_the_other_moves(self):
        code, calls = self._sync([card(7), card(450)])
        self.assertEqual(code, 1)
        self.assertEqual(self.verbs(calls), ["show --expect", "issue comment", "issue edit", "move"])
        self.assertIn("1 card(s) in Merged have no linked commit", self.err)

    def test_a_card_not_fully_shipped_is_not_touched(self):
        code, calls = self._sync([card(450)], shipped=lambda s: False)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertRegex(self.out, r"STAY +acme/issues#450  1a6e11b7  \(not in tag: 1a6e11b7\)")

    def test_unknown_tag_exits_2_before_the_board_is_read(self):
        code, calls = self._sync([card(450)], tag_ok=False)
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])
        self.list_cards.assert_not_called()
        self.board_meta.assert_not_called()

    def test_a_tag_no_stage_matches_exits_2_naming_the_globs(self):
        code, calls = self._sync([card(450)], tag="v1.0")
        self.assertEqual(code, 2)
        self.assertIn("deploy-*", self.err)
        self.assertEqual(calls, [])
        self.list_cards.assert_not_called()
        self.board_meta.assert_not_called()

    def test_an_unreadable_board_or_missing_column_writes_nothing(self):
        code, calls = self._sync([card(450)], list_error=ss.tracker.BoardError("short read"))
        self.assertEqual((code, calls), (2, []))
        for options in ({"Released": "b"}, {"Merged": "a", "Done": "c"}):
            with self.subTest(options=options):
                code, calls = self._sync([card(450)], board_meta={"options": options})
                self.assertEqual((code, calls), (2, []))
                self.list_cards.assert_not_called()

    def moves(self, calls):
        """{issue number: --to column} for every move written."""
        return {cmd[5]: cmd[cmd.index("--to") + 1] for cmd in self.writes(calls)
                if cmd[0] != "gh" and cmd[4] == "move"}

    def test_reads_the_board_once_and_plans_only_the_source_column(self):
        links = {**LINKED, ("acme/issues", 451): ss.Linked(["bbbb"], [])}
        code, calls = self._sync([card(450), card(451, status="Released")], links)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(self.list_cards.call_count, 1)
        self.assertEqual(self.moves(calls), {"450": "Released"})

    def test_three_stages_each_tag_reads_the_stage_before_it(self):
        profile = self.write_profile(three_stages=True)
        links = {**LINKED, ("acme/issues", 451): ss.Linked(["bbbb"], [])}
        cards = [card(450), card(451, status="In Staging")]
        code, calls = self._sync(cards, links, tag="staging-1", profile=profile)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(self.moves(calls), {"450": "In Staging"})

        code, calls = self._sync(cards, links, tag="deploy-1", profile=profile)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(self.moves(calls), {"451": "Released"})
        self.assertIn("https://app.example.org", self.bodies[0])

    def test_overlapping_globs_read_once_and_move_a_card_one_stage(self):
        """`deploy-prod-1` matches both stages: one board read, every card
        planned from it, and a card moved into In Staging is not then moved on."""
        profile = self.write_profile(three_stages=True, staging_tag="deploy-*", deploy_tag="deploy-prod-*")
        links = {**LINKED, ("acme/issues", 451): ss.Linked(["bbbb"], [])}
        code, calls = self._sync([card(450), card(451, status="In Staging")], links,
                                 tag="deploy-prod-1", profile=profile)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(self.list_cards.call_count, 1)
        self.assertEqual(self.moves(calls), {"450": "In Staging", "451": "Released"})
        self.assertEqual(self.verbs(calls).count("move"), 2)

    def test_a_comment_for_another_stage_does_not_count(self):
        """A card announced for staging-1 is announced again when deploy-1 ships it."""
        profile = self.write_profile(three_stages=True)
        staged = ss.Decision(ss.MOVE, ("acme/issues", 450), ("1a6e11b7ffff",))
        body = ss.live_comment("staging-1", staged, "https://staging.example.org", False, "In Staging")
        code, calls = self._sync([card(450, status="In Staging")], tag="deploy-1",
                                 profile=profile, comments=body)
        self.assertEqual(code, 0, self.err)
        self.assertIn("issue comment", self.verbs(calls))

        code, calls = self._sync([card(450)], tag="staging-2", profile=profile, comments=body)
        self.assertEqual(code, 0, self.err)
        self.assertNotIn("issue comment", self.verbs(calls))

    def test_overlapping_globs_a_staging_comment_does_not_suppress_the_release_one(self):
        """deploy-prod-1 matches both globs: the In Staging comment carries that
        tag, and must still not stand in for the Released one."""
        profile = self.write_profile(three_stages=True, staging_tag="deploy-*", deploy_tag="deploy-prod-*")
        staged = ss.Decision(ss.MOVE, ("acme/issues", 450), ("1a6e11b7ffff",))
        body = ss.live_comment("deploy-prod-1", staged, "https://staging.example.org", False, "In Staging")
        code, calls = self._sync([card(450, status="In Staging")], tag="deploy-prod-1",
                                 profile=profile, comments=body)
        self.assertEqual(code, 0, self.err)
        self.assertIn("issue comment", self.verbs(calls))
        self.assertIn("stage=Released", self.bodies[0])

    def test_a_failed_move_reports_what_it_knows_before_stopping(self):
        links = {("acme/issues", n): ss.Linked([f"{n}aaaa"], []) for n in (449, 450, 451)}
        fail = lambda cmd: ("comment" in cmd and "449" in cmd) or ("move" in cmd and "450" in cmd)
        code, calls = self._sync([card(449), card(450), card(451), card(7)], links, fail=fail)
        self.assertEqual(code, 2)
        self.assertEqual(self.verbs(calls), ["show --expect", "issue comment",
                                             "show --expect", "issue comment", "move"])
        self.assertIn("acme/issues#450: commented, but the move did not verify", self.err)
        self.assertIn("1 card(s) not moved, their comment failed: acme/issues#449", self.err)
        self.assertIn("1 card(s) in Merged have no linked commit; move them by hand: acme/issues#7", self.err)
        self.assertIn("1 card(s) not attempted: acme/issues#451", self.err)

    def test_the_source_column_is_resolved_as_list_cards_resolves_it(self):
        """A stage column that is also a role key's value (the queue) is read
        under the name tracker.column() gives it."""
        profile = Path(self.write_profile())
        profile.write_text(profile.read_text().replace('column = "Merged"', 'column = "Dev Ready"'))
        board = {"options": {"Dev Ready": "q", "Released": "b"}}
        code, calls = self._sync([card(450, status="dev ready")], profile=str(profile), board_meta=board)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(self.moves(calls), {"450": "Released"})

    def test_reporter_none_neither_assigns_nor_mentions(self):
        code, calls = self._sync([card(450)], profile=self.write_profile(reporter="none"))
        self.assertEqual(code, 0)
        self.assertEqual(self.verbs(calls), ["show --expect", "issue comment", "move"])
        self.assertNotIn("@", self.bodies[0])

    def test_remove_assignee_only_for_the_authenticated_non_reporter(self):
        for me, assignees in (("jdoe", ("jdoe", "maint")), ("maint", ("other",)), (None, ("maint",))):
            with self.subTest(me=me):
                code, calls = self._sync([card(450, assignees=assignees)], me=me)
                self.assertEqual(code, 0)
                self.assertEqual(self.verbs(calls), ["show --expect", "issue comment", "issue edit", "move"])
                self.assertNotIn("--remove-assignee", self.writes(calls)[2])

    def test_comment_names_the_environment_when_it_has_no_url(self):
        code, _ = self._sync([card(450)], profile=self.write_profile(url=False))
        self.assertEqual(code, 0)
        self.assertIn("**Now live on production** in `deploy-x`.", self.bodies[0])

    def test_a_crash_exits_2_not_1(self):
        """Exit 1 claims every possible move was made; a crash has not."""
        profile = self.write_profile()
        with mock.patch.object(ss, "resolve_tag", return_value="deadbeef"), \
             mock.patch.object(ss.tracker, "board_meta", return_value=BOARD), \
             mock.patch.object(ss, "trailer_links", side_effect=KeyError("x")), \
             mock.patch.object(ss, "run") as wrote:
            code, _, err = run_main("--profile", profile, "sync", "--tag", "deploy-x")
        self.assertEqual(code, 2)
        self.assertIn("KeyError", err)
        wrote.assert_not_called()


class AlreadyAnnounced(unittest.TestCase):
    def test_reads_the_marker_for_these_shas_under_either_name(self):
        decision = ss.Decision(ss.MOVE, ("acme/issues", 450), ("1a6e11b7ffff",))
        other = ss.Decision(ss.MOVE, ("acme/issues", 450), ("1a6e11b7ffff", "2b2b2b2b"))
        def announced(body, d=decision, glob="deploy-*", stage="Released"):
            with mock.patch.object(ss.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=body)):
                return ss.already_announced("acme/issues", "450", d, glob, stage)

        posted = ss.live_comment("deploy-a", decision, "https://app.example.org", True, "Released")
        self.assertIn("<!-- stage-sync stage=Released tag=deploy-a shas=1a6e11b7 -->", posted)
        # New form: the stage decides, case-insensitively; the tag does not.
        self.assertTrue(announced(posted))
        self.assertTrue(announced(posted, stage="released", glob="nothing-*"))
        self.assertFalse(announced(posted, stage="In Staging"))
        self.assertFalse(announced(posted, d=other))
        # Markers without stage= (the older names) keep the tag-glob rule.
        for prefix in ("<!-- stage-sync ", "<!-- board-sync "):
            legacy = f"{prefix}tag=deploy-a shas=1a6e11b7 -->\n"
            self.assertTrue(announced(legacy, stage="In Staging"))
            self.assertFalse(announced(legacy, glob="staging-*"))
            self.assertFalse(announced(legacy, d=other))
        failed = mock.Mock(returncode=1, stdout=posted)
        with mock.patch.object(ss.subprocess, "run", return_value=failed):
            self.assertFalse(ss.already_announced("acme/issues", "450", decision, "deploy-*", "Released"))


class LiveComment(unittest.TestCase):
    def test_comment_names_the_place_the_tag_and_the_reporter(self):
        decision = ss.Decision(ss.MOVE, ("acme/issues", 450), ("1a6e11b7aaaa",), (), ("jdoe",))
        body = ss.live_comment("deploy-2026Sep27-10.00", decision, "https://app.example.org", True, "Released")
        self.assertIn("https://app.example.org", body)
        self.assertIn("`deploy-2026Sep27-10.00`", body)
        self.assertIn("@jdoe", body)
        self.assertIn("<!-- stage-sync stage=Released tag=deploy-2026Sep27-10.00 shas=1a6e11b7 -->", body)


class SyncAgainstRealGit(RepoTestCase):
    def test_unknown_tag_against_real_git(self):
        """The real resolve_tag, not the fake: `deploy-nope` must not read as empty."""
        profile = self.write_profile()
        self.repo.commit("first")
        with mock.patch.object(ss, "run") as wrote, \
             mock.patch.object(ss.tracker, "list_cards") as listed, \
             mock.patch.object(ss.tracker, "board_meta") as meta:
            code, _, err = run_main("--profile", profile, "sync", "--tag", "deploy-nope", "--main-ref", "HEAD")
        self.assertEqual(code, 2)
        self.assertIn("no such tag: deploy-nope", err)
        wrote.assert_not_called()
        listed.assert_not_called()
        meta.assert_not_called()


# --------------------------------------------------------------------------
# reverts: a shipped fix taken back out
# --------------------------------------------------------------------------


def stage_card(number, status="Released", state="OPEN"):
    return dict(card(number, status=status), state=state)


class Reverts(RepoTestCase):
    """`reverts` against real git; the board, the comment read and every write faked."""

    STOP = "<!-- gogogo:stop v=1 reason=reverted -->"

    def setUp(self):
        super().setUp()
        profile = Path(self.write_profile())
        profile.write_text(profile.read_text().replace(
            'back_to_queue = "Dev Ready" }', 'back_to_queue = "Dev Ready", needs_human = "Human!Help!" }'))
        self.profile = str(profile)
        self.repo.commit("base")
        self.fix = self.repo.commit("fix: x (Refs #12)")
        self.repo.commit("unrelated work")

    def revert(self, sha, subject='Revert "fix: x (Refs #12)"'):
        return self.repo.commit(f"{subject}\n\nThis reverts commit {sha}.\n")

    def reverts(self, *extra, cards=None, newest="", fail=None, main_ref="main"):
        cards = [stage_card(12)] if cards is None else cards
        self.calls, self.bodies, self.list_kwargs = [], [], {}
        ref_args = ["--main-ref", main_ref] if main_ref else []

        def fake_run(cmd):
            self.calls.append(cmd)
            if "--body-file" in cmd:
                self.bodies.append(Path(cmd[cmd.index("--body-file") + 1]).read_text())
            return 1 if fail and fail(cmd) else 0

        def fake_list_cards(*, repo=None, **_):
            if not repo:
                raise ValueError("list_cards needs repo=tracker.DEFAULT_REPO")
            self.list_kwargs = {"repo": repo, **_}
            return cards, [], 0

        with mock.patch.object(ss.tracker, "list_cards", side_effect=fake_list_cards), \
             mock.patch.object(ss.tracker, "board_meta", return_value={"options": {"Released": "r", "Human!Help!": "h"}}), \
             mock.patch.object(ss.tracker, "newest_comment", return_value=newest), \
             mock.patch.object(ss, "run", side_effect=fake_run):
            code, self.out, self.err = run_main("--profile", self.profile, "reverts", *ref_args, *extra)
        return code

    def test_a_reverted_fix_is_named_with_both_commits(self):
        undo = self.revert(self.fix)
        self.assertEqual(self.reverts(), 1, self.err)
        self.assertIn(f"#12: shipped by {self.fix[:7]}, reverted by {undo[:7]} (Revert \"fix: x (Refs #12)\")",
                      self.out)
        self.assertEqual(self.calls, [])

    def test_a_fix_landed_again_after_its_revert_is_not_named(self):
        """Reland by a new commit: else the card is handed back again on every run."""
        self.revert(self.fix)
        self.repo.commit("fix: x again (Refs #12)")
        self.assertEqual(self.reverts(), 0, self.out)

    def test_a_revert_that_was_itself_reverted_is_not_named(self):
        """Reland by revert-of-revert; the revert's own subject carries the Refs and is no fix."""
        undo = self.revert(self.fix)
        self.revert(undo, 'Revert "Revert "fix: x (Refs #12)""')
        self.assertEqual(self.reverts(), 0, self.out)

    def test_a_second_revert_that_was_reverted_leaves_the_first_one_named(self):
        """The fix stays out while an earlier revert stands: undoing the later revert re-lands nothing."""
        first = self.revert(self.fix)
        again = self.revert(self.fix, 'Revert "fix: x (Refs #12)" again')
        self.revert(again, 'Revert "Revert "fix: x (Refs #12)" again"')
        self.assertEqual(self.reverts(), 1, self.err)
        self.assertIn(f"reverted by {first[:7]}", self.out)

    def test_nothing_reverted_exits_0(self):
        self.assertEqual(self.reverts(), 0, self.err)
        self.assertNotIn("reverted by", self.out)

    def test_an_abbreviated_sha_of_seven_is_read_and_six_is_not(self):
        self.revert(self.fix[:6])
        self.assertEqual(self.reverts(), 0, self.out)
        self.revert(self.fix[:7])
        self.assertEqual(self.reverts(), 1, self.err)
        self.assertIn(f"#12: shipped by {self.fix[:7]}", self.out)

    def test_the_ships_issue_trailer_and_the_full_repo_form_link_too(self):
        other = self.repo.commit(squash_body(ss.format_trailer(ss.IssueLink("acme/issues", 13))))
        full = self.repo.commit("fix: y (Refs acme/issues#14)")
        self.revert(other, "Revert trailer")
        self.revert(full, "Revert full")
        self.assertEqual(self.reverts(cards=[stage_card(13), stage_card(14)]), 1, self.err)
        self.assertIn(f"#13: shipped by {other[:7]}", self.out)
        self.assertIn(f"#14: shipped by {full[:7]}", self.out)

    def test_a_revert_of_another_issues_commit_or_a_closed_issue_is_not_named(self):
        other = self.repo.commit("fix: z (Refs #99)")
        self.revert(other, 'Revert "fix: z"')
        self.assertEqual(self.reverts(), 0, self.out)
        self.assertNotIn("#12", self.out)
        self.revert(self.fix)
        self.assertEqual(self.reverts(cards=[stage_card(12, state="CLOSED")]), 0, self.out)
        self.assertEqual(self.reverts(cards=[stage_card(12, status="Dev Ready")]), 0, self.out)

    def test_apply_comments_with_the_stop_marker_then_moves_to_needs_human(self):
        undo = self.revert(self.fix)
        self.assertEqual(self.reverts("--apply"), 1, self.err)
        self.assertEqual([c[:3] for c in self.calls if c[0] == "gh"], [["gh", "issue", "comment"]])
        move = self.calls[-1]
        self.assertEqual(move[4:6], ["move", "12"])
        self.assertEqual(move[move.index("--to") + 1], "needs_human")
        self.assertEqual(move[:4], [sys.executable, str(SCRIPTS / "tracker.py"), "--profile", self.profile])
        body = self.bodies[0]
        self.assertIn(undo[:7], body)
        lines = body.splitlines()
        self.assertIn(self.STOP, lines)
        self.assertTrue(lines[lines.index(self.STOP) - 1].startswith("**Needs you:**"))
        self.assertTrue(ss.tracker.has_reason(body))

    def test_apply_with_a_failed_comment_does_not_move_that_card(self):
        self.revert(self.fix)
        self.assertEqual(self.reverts("--apply", fail=lambda cmd: "comment" in cmd), 2)
        self.assertNotIn("move", [c[4] for c in self.calls if c[0] != "gh"])
        self.assertIn("comment failed", self.err)

    def test_apply_again_after_the_comment_writes_nothing(self):
        undo = self.revert(self.fix)
        self.assertEqual(self.reverts("--apply"), 1, self.err)
        posted = self.bodies[0]
        self.assertEqual(self.reverts("--apply", newest=posted), 1, self.err)
        self.assertEqual(self.calls, [])
        self.assertIn(undo[:7], self.out)

    def hit(self, issues_repo="acme/issues"):
        return ss.Revert(("acme/issues", 12), "a" * 40, "b" * 40, 'Revert "x"')

    def test_a_hit_is_a_line_naming_the_issue_the_two_commits_and_the_subject(self):
        hit = self.hit()
        self.assertEqual(hit.line("Acme/Issues"), '#12: shipped by aaaaaaa, reverted by bbbbbbb (Revert "x")')
        other = ss.Revert(("acme/other", 3), "a" * 40, "b" * 40, "s")
        self.assertEqual(other.line("acme/issues"), "acme/other#3: shipped by aaaaaaa, reverted by bbbbbbb (s)")
        with self.assertRaises(Exception):
            hit.sha = "c"

    def test_the_comment_is_exactly_the_one_the_spec_gives(self):
        self.assertEqual(ss.revert_comment(self.hit(), "main"),
                         'The fix for this issue was reverted by bbbbbbb on main: Revert "x".\n\n'
                         "**Needs you:** decide whether to fix again or close\n"
                         "<!-- gogogo:stop v=1 reason=reverted -->\n")

    def test_a_commit_message_ending_in_an_x_is_read_whole(self):
        self.repo.commit("subject\n\nbody ends X")
        sha, subject, body = ss.log_records("main")[0]
        self.assertEqual((subject, body), ("subject", "subject\n\nbody ends X"))

    def test_apply_hands_exactly_these_commands_to_gh_and_the_tracker(self):
        self.revert(self.fix)
        self.assertEqual(self.reverts("--apply"), 1, self.err)
        comment, move = self.calls
        body_file = comment[-1]
        self.assertEqual(comment[:-1], ["gh", "issue", "comment", "12", "--repo", "acme/issues", "--body-file"])
        self.assertTrue(body_file.endswith(".md"), body_file)
        self.assertEqual(move, [sys.executable, str(SCRIPTS / "tracker.py"), "--profile", self.profile,
                                "move", "12", "--repo", "acme/issues", "--to", "needs_human"])
        self.assertIn("acme/issues#12: -> Human!Help!\n", self.out)
        self.assertNotIn("Traceback", self.err)

    def test_apply_reads_the_board_for_open_issue_cards_only(self):
        self.revert(self.fix)
        self.reverts()
        self.assertIs(self.list_kwargs["open_only"], True)
        self.assertIs(self.list_kwargs["issues_only"], True)

    def test_a_card_with_no_column_is_not_in_a_column_named_like_a_placeholder(self):
        profile = Path(self.profile)
        profile.write_text(profile.read_text().replace('column = "Released"', 'column = "Xxxx"'))
        self.revert(self.fix)
        self.assertEqual(self.reverts(cards=[stage_card(12, status=None)]), 0, self.out)

    def test_nothing_reverted_says_so_exactly(self):
        self.assertEqual(self.reverts(), 0)
        self.assertEqual(self.out, "no shipped fix has been reverted\n")

    def test_the_base_is_origin_slash_the_profiles_base_or_main(self):
        self.revert(self.fix)
        self.repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual(self.reverts("--apply", main_ref=None), 1, self.err)
        self.assertIn(" on main: ", self.bodies[0])
        profile = Path(self.profile)
        profile.write_text(profile.read_text().replace("[handback]", '[integration]\nbase = "trunk"\n\n[handback]'))
        self.repo.git("update-ref", "refs/remotes/origin/trunk", "HEAD")
        self.repo.git("update-ref", "-d", "refs/remotes/origin/main")
        self.assertEqual(self.reverts("--apply", main_ref=None), 1, self.err)
        self.assertIn(" on trunk: ", self.bodies[0])
        self.assertNotIn("origin/", self.bodies[0])

    def test_two_reverts_of_one_fix_still_hand_back_every_issue(self):
        self.revert(self.fix)
        self.revert(self.fix, "Revert again")
        other = self.repo.commit("fix: y (Refs #13)")
        self.revert(other, "Revert y")
        self.assertEqual(self.reverts("--apply", cards=[stage_card(12), stage_card(13)]), 1, self.err)
        commented = [c[c.index("comment") + 1] for c in self.calls if c[0] == "gh"]
        self.assertEqual(commented, ["12", "13"])
        self.assertIn("acme/issues#13: -> Human!Help!", self.out)

    def test_an_issue_already_commented_on_is_reported_as_such_and_not_moved(self):
        undo = self.revert(self.fix)
        self.reverts("--apply")
        code = self.reverts("--apply", newest=self.bodies[0])
        self.assertEqual((code, self.calls), (1, []))
        self.assertRegex(self.out, rf"acme/issues#12: its newest comment already names {undo[:7]} -")
        self.assertNotIn("->", self.out)

    def test_a_move_that_fails_is_exit_2_and_not_a_crash(self):
        self.revert(self.fix)
        self.assertEqual(self.reverts("--apply", fail=lambda cmd: cmd[0] != "gh"), 2)
        self.assertNotIn("Traceback", self.err)
        self.assertNotIn("->", self.out.split("\n", 1)[1])

    def test_a_failed_comment_is_not_a_crash(self):
        self.revert(self.fix)
        self.assertEqual(self.reverts("--apply", fail=lambda cmd: cmd[0] == "gh"), 2)
        self.assertNotIn("Traceback", self.err)

    def apply_one(self, newest="", fail=None, wipe=False):
        profile = ss.load_profile(self.profile)
        calls = []

        def fake_run(cmd):
            calls.append(cmd)
            if wipe and cmd[0] == "gh":
                Path(cmd[-1]).unlink()
            return 1 if fail and fail(cmd) else 0
        with mock.patch.object(ss.tracker, "newest_comment", return_value=newest), \
             mock.patch.object(ss, "run", side_effect=fake_run):
            return ss.apply_revert(profile, self.hit(), "main"), calls

    def test_apply_revert_says_what_it_did(self):
        self.assertEqual(self.apply_one()[0], "moved")
        self.assertEqual(self.apply_one(newest="reverted by bbbbbbb earlier")[0], "already")
        self.assertEqual(self.apply_one(newest="reverted by bbbbbbb earlier")[1], [])
        self.assertEqual(self.apply_one(fail=lambda cmd: cmd[0] == "gh")[0], "comment-failed")
        self.assertEqual(self.apply_one(fail=lambda cmd: cmd[0] != "gh")[0], "move-failed")

    def test_the_comment_file_is_removed_even_when_the_stand_in_already_took_it(self):
        self.assertEqual(self.apply_one(wipe=True)[0], "moved")

    def test_an_unreadable_newest_comment_still_comments_and_moves(self):
        profile = ss.load_profile(self.profile)
        with mock.patch.object(ss.tracker, "newest_comment", side_effect=ss.tracker.BoardError("x")), \
             mock.patch.object(ss, "run", return_value=0) as ran:
            self.assertEqual(ss.apply_revert(profile, self.hit(), "main"), "moved")
        self.assertEqual(ran.call_count, 2)



# --------------------------------------------------------------------------
# what a tag ships
# --------------------------------------------------------------------------


class ShippedInGit(RepoTestCase):
    def test_lists_links_in_range_and_counts_the_rest(self):
        self.repo.commit(squash_body(ss.format_trailer(ss.IssueLink("acme/issues", 99))))
        self.repo.tag("deploy-A")
        self.repo.commit(squash_body(ss.format_trailer(ss.IssueLink("acme/issues", 1))))
        self.repo.commit("a commit with no trailer")
        self.repo.tag("deploy-B")
        result = ss.shipped("deploy-B", "deploy-A", KNOWN)
        self.assertEqual([link.key for link in result.links], [("acme/issues", 1)])
        self.assertEqual(result.unlinked_commits, 1)

    def test_refs_in_a_subject_link_a_commit_once(self):
        self.repo.commit("base")
        self.repo.tag("deploy-A")
        self.repo.commit("fix: x (Refs #12)")
        self.repo.commit("fix: y (Refs #12)\n\n" + ss.format_trailer(ss.IssueLink("acme/issues", 12)))
        self.repo.commit("feat: z (Refs acme/other#3)")
        self.repo.commit("a commit with no link")
        self.repo.tag("deploy-B")
        result = ss.shipped("deploy-B", "deploy-A", KNOWN, issues_repo="acme/issues")
        self.assertEqual([link.key for link in result.links], [("acme/issues", 12), ("acme/other", 3)])
        self.assertEqual(result.unlinked_commits, 1)

    def test_a_revert_commit_does_not_ship_the_issue_in_its_subject(self):
        self.repo.commit("base")
        fix = self.repo.commit("fix: x (Refs #12)")
        self.repo.tag("deploy-A")
        self.repo.commit(f'Revert "fix: x (Refs #12)"\n\nThis reverts commit {fix}.\n')
        self.repo.tag("deploy-B")
        result = ss.shipped("deploy-B", "deploy-A", KNOWN, issues_repo="acme/issues")
        self.assertEqual(result.links, [])

    def test_a_revert_in_the_range_does_not_hide_the_fixes_older_than_it(self):
        self.repo.commit("base")
        self.repo.tag("deploy-A")
        self.repo.commit("fix: y (Refs #13)")
        old = self.repo.commit("fix: x (Refs #12)")
        self.repo.commit(f'Revert "fix: x (Refs #12)"\n\nThis reverts commit {old}.\n')
        self.repo.tag("deploy-B")
        result = ss.shipped("deploy-B", "deploy-A", KNOWN, issues_repo="acme/issues")
        self.assertEqual(sorted(link.key for link in result.links), [("acme/issues", 12), ("acme/issues", 13)])

    def test_without_an_issues_repo_a_refs_subject_links_nothing(self):
        self.repo.commit("base")
        self.repo.tag("deploy-A")
        self.repo.commit("fix: x (Refs #12)")
        self.repo.tag("deploy-B")
        result = ss.shipped("deploy-B", "deploy-A", KNOWN)
        self.assertEqual((result.links, result.unlinked_commits), ([], 1))

    def test_previous_tag_skips_other_tags(self):
        self.repo.commit("one")
        self.repo.tag("deploy-1")
        self.repo.commit("two")
        self.repo.tag("v2")
        self.repo.commit("three")
        self.repo.tag("deploy-3")
        self.assertEqual(ss.previous_tag("deploy-3", "deploy-*"), "deploy-1")
        self.assertIsNone(ss.previous_tag("deploy-1", "deploy-*"))

    def test_a_second_tag_on_the_same_commit_ships_nothing(self):
        self.repo.commit(squash_body(ss.format_trailer(ss.IssueLink("acme/issues", 1))))
        self.repo.tag("deploy-1")
        self.repo.git("tag", "-a", "deploy-2", "-m", "again")
        self.assertEqual(ss.previous_tag("deploy-2", "deploy-*"), "deploy-1")
        self.assertEqual(ss.shipped("deploy-2", "deploy-1", KNOWN).links, [])

    def test_the_first_tag_has_nothing_to_compare_with(self):
        profile = self.write_profile()
        self.repo.commit("one")
        self.repo.tag("deploy-1")
        code, out, _ = run_main("--profile", profile, "shipped", "--tag", "deploy-1")
        self.assertEqual(code, 0)
        self.assertEqual(out, "Deployed deploy-1 to production\n\n"
                              "first tag matching deploy-*; nothing to compare with\n")


class RenderShipped(TrackerState):
    def test_caps_at_25_and_counts_the_rest(self):
        links = [ss.IssueLink("acme/issues", n) for n in range(1, 31)]
        titles = {link.key: "x" * 200 for link in links}
        text = ss.render_shipped("deploy-x", "production", ss.Shipped(links, 0), titles)
        bullets = [ln for ln in text.splitlines() if ln.startswith("• ")]
        self.assertEqual(len(bullets), 25)
        self.assertIn("… and 5 more", text)
        self.assertLess(len(text), 4096)

    def test_without_titles_prints_short_references(self):
        text = ss.render_shipped("deploy-x", "production",
                                 ss.Shipped([ss.IssueLink("acme/issues", 450)], 2), None)
        self.assertTrue(text.startswith("Deployed deploy-x to production\n"))
        self.assertIn("Ships 1 issue:\n", text)
        self.assertIn("• issues#450\n", text)
        self.assertIn("+ 2 commits with no linked issue", text)

    def test_with_no_links_says_so(self):
        text = ss.render_shipped("deploy-x", "production", ss.Shipped([], 3), None)
        self.assertIn("Ships no linked issues (3 commits)", text)

    def test_title_lookup_failure_still_exits_0(self):
        profile = self.write_profile()
        failed = mock.Mock(returncode=1, stdout="", stderr="HTTP 401")
        result = ss.Shipped([ss.IssueLink("acme/issues", 450)], 0)
        with mock.patch.object(ss, "resolve_tag", return_value="abc"), \
             mock.patch.object(ss, "previous_tag", return_value="deploy-0"), \
             mock.patch.object(ss, "shipped", return_value=result), \
             mock.patch.object(ss.subprocess, "run", return_value=failed):
            code, out, _ = run_main("--profile", profile, "shipped", "--tag", "deploy-x", "--titles")
        self.assertEqual(code, 0)
        self.assertIn("• issues#450\n", out)


class ShippedJson(TrackerState):
    """`shipped --json` prints the deployed event for the notification script (gogogo#157)."""

    def run_json(self, result, titles=None, prev="deploy-0"):
        profile = self.write_profile()
        with mock.patch.object(ss, "resolve_tag", return_value="abc"), \
             mock.patch.object(ss, "previous_tag", return_value=prev), \
             mock.patch.object(ss, "shipped", return_value=result), \
             mock.patch.object(ss, "fetch_titles", return_value=titles or {}):
            args = ["--profile", profile, "shipped", "--tag", "deploy-x", "--json"]
            return run_main(*args, *(["--titles"] if titles is not None else []))

    def test_the_event_lists_the_issues_with_titles_and_counts_the_rest(self):
        links = [ss.IssueLink("acme/issues", n) for n in range(1, 31)]
        titles = {link.key: "x" * 200 for link in links[:25]}
        code, out, _ = self.run_json(ss.Shipped(links, 2), titles)
        event = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((event["event"], event["tag"], event["environment"]), ("deployed", "deploy-x", "production"))
        self.assertEqual(len(event["issues"]), 25)
        self.assertEqual(event["issues"][0], {"repo": "acme/issues", "issue": 1, "title": "x" * 119 + "…"})
        self.assertEqual((event["more"], event["unlinked_commits"]), (5, 2))

    def test_without_titles_the_titles_are_null(self):
        code, out, _ = self.run_json(ss.Shipped([ss.IssueLink("acme/issues", 450)], 0))
        self.assertEqual(json.loads(out)["issues"], [{"repo": "acme/issues", "issue": 450, "title": None}])
        self.assertEqual(json.loads(out)["more"], 0)

    def test_a_title_of_exactly_the_most_is_kept_whole(self):
        link = ss.IssueLink("acme/issues", 1)
        _, out, _ = self.run_json(ss.Shipped([link], 0), {link.key: "y" * ss.TITLE_MAX})
        self.assertEqual(json.loads(out)["issues"][0]["title"], "y" * ss.TITLE_MAX)

    def test_the_first_tag_is_a_first_event(self):
        code, out, _ = self.run_json(ss.Shipped([], 0), prev=None)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"event": "deployed", "tag": "deploy-x", "environment": "production",
                                           "first": True})

    def test_without_json_the_output_is_the_old_text(self):
        profile = self.write_profile()
        result = ss.Shipped([ss.IssueLink("acme/issues", 450)], 2)
        with mock.patch.object(ss, "resolve_tag", return_value="abc"), \
             mock.patch.object(ss, "previous_tag", return_value="deploy-0"), \
             mock.patch.object(ss, "shipped", return_value=result):
            code, out, _ = run_main("--profile", profile, "shipped", "--tag", "deploy-x")
        self.assertTrue(out.startswith("Deployed deploy-x to production\n"))
        self.assertNotIn("{", out)


# --------------------------------------------------------------------------
# structure of the shared files
# --------------------------------------------------------------------------


def fenced(text):
    return re.findall(r"```[^\n]*\n(.*?)```", text, re.S)


class SharedFiles(unittest.TestCase):
    REFERENCE = PLUGIN / "references" / "stage-sync.md"

    def test_no_project_names(self):
        for path in (SCRIPTS / "stage_sync.py", self.REFERENCE):
            with self.subTest(path=path.name):
                self.assertIsNone(re.search(PROJECT_NAMES, path.read_text(encoding="utf-8"), re.I))

    def test_the_reference_carries_a_workflow_example(self):
        blocks = [b for b in fenced(self.REFERENCE.read_text(encoding="utf-8")) if "on:" in b]
        self.assertEqual(len(blocks), 1, "one workflow example")
        for needle in ("fetch-depth: 0", "--profile", "sync --tag", "concurrency:"):
            self.assertIn(needle, blocks[0])

    def test_the_dev_skill_carries_the_merge_recipe(self):
        """Commands, not sentences: the trailer command, the merge that takes
        its body, and the merge check that reads it back."""
        blocks = fenced(DEV_HAND_BACK.read_text(encoding="utf-8"))
        self.assertTrue(any(re.search(r'stage_sync\.py" .*\btrailer\b', b) and "--co-authors-from" in b
                            for b in blocks))
        self.assertTrue(any("gh pr merge" in b and "--body-file" in b for b in blocks))

    def test_auto_dev_runs_the_same_commands(self):
        text = AUTO_DEV_MERGE.read_text(encoding="utf-8")
        self.assertRegex(text, r'stage_sync\.py" .*\btrailer\b')
        self.assertRegex(text, r"verify_merged\.py.*--profile <profile>.*--ships")


if __name__ == "__main__":
    unittest.main()
