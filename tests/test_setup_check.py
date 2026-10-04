import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import setup_check as sc  # noqa: E402


def repo(files):
    tmp = Path(tempfile.mkdtemp()).resolve()
    subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    for name, text in files.items():
        path = tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp


def levels(rep, check_prefix):
    return [r["level"] for r in rep.rows if r["check"].startswith(check_prefix)]


GOOD_SETTINGS = json.dumps({
    "extraKnownMarketplaces": {"vorski-skills": {"source": {"source": "github", "repo": "Vorski-Imagineering/gogogo"}, "autoUpdate": True}},
    "enabledPlugins": {"gogogo@vorski-skills": True},
})


class Settings(unittest.TestCase):
    def test_no_settings_file_fails_with_the_install_commands(self):
        rep = sc.Report()
        sc.check_settings(repo({}), rep)
        self.assertEqual(levels(rep, "plugin settings"), ["FAIL"])
        self.assertIn("claude plugin install gogogo@vorski-skills", rep.rows[0]["fix"])

    def test_complete_settings_pass_and_untracked_file_warns(self):
        rep = sc.Report()
        sc.check_settings(repo({".claude/settings.json": GOOD_SETTINGS}), rep)
        self.assertEqual(levels(rep, "plugin settings: marketplace"), ["PASS"])
        self.assertEqual(levels(rep, "plugin settings: enabled"), ["PASS"])
        self.assertEqual(levels(rep, "plugin settings: committed"), ["WARN"])

    def test_auto_update_off_warns(self):
        settings = json.loads(GOOD_SETTINGS)
        settings["extraKnownMarketplaces"]["vorski-skills"]["autoUpdate"] = False
        rep = sc.Report()
        sc.check_settings(repo({".claude/settings.json": json.dumps(settings)}), rep)
        self.assertEqual(levels(rep, "plugin settings: auto-update"), ["WARN"])

    def test_plugin_not_enabled_fails(self):
        settings = json.loads(GOOD_SETTINGS)
        settings["enabledPlugins"] = {}
        rep = sc.Report()
        sc.check_settings(repo({".claude/settings.json": json.dumps(settings)}), rep)
        self.assertEqual(levels(rep, "plugin settings: enabled"), ["FAIL"])


class HardStopSource(unittest.TestCase):
    ROOT = None

    def setUp(self):
        self.root = repo({"CLAUDE.md": "# Project\n\n## Hard Stops — Ask Before Changing\n\n- schema\n"})

    def test_an_existing_heading_passes(self):
        rep = sc.Report()
        sc.check_hard_stop_source(self.root, "CLAUDE.md § Hard Stops — Ask Before Changing", rep)
        self.assertEqual(levels(rep, "hard stops"), ["PASS"])

    def test_a_missing_heading_fails(self):
        rep = sc.Report()
        sc.check_hard_stop_source(self.root, "CLAUDE.md § Non-Negotiables", rep)
        self.assertEqual(levels(rep, "hard stops"), ["FAIL"])

    def test_a_missing_file_fails(self):
        rep = sc.Report()
        sc.check_hard_stop_source(self.root, "RULES.md § Hard Stops", rep)
        self.assertEqual(levels(rep, "hard stops"), ["FAIL"])


class LocalSkillsAndClaudeMd(unittest.TestCase):
    def test_a_replaced_local_skill_warns_by_name(self):
        rep = sc.Report()
        sc.check_local_skills(repo({".claude/skills/fix-issue/SKILL.md": "x"}), rep)
        self.assertEqual(levels(rep, "local skills"), ["WARN"])
        self.assertIn("fix-issue", rep.rows[0]["detail"])

    def test_the_local_roadmap_skill_warns_by_name(self):
        rep = sc.Report()
        sc.check_local_skills(repo({".claude/skills/update-milestone-doc/SKILL.md": "x"}), rep)
        self.assertEqual(levels(rep, "local skills"), ["WARN"])
        self.assertIn("update-milestone-doc", rep.rows[0]["detail"])

    def test_a_retired_skill_does_not_warn(self):
        rep = sc.Report()
        sc.check_local_skills(repo({".claude/skills-retired/fix-issue/SKILL.md": "x"}), rep)
        self.assertEqual(levels(rep, "local skills"), ["PASS"])

    def test_the_local_auto_test_skill_warns_until_retired(self):
        rep = sc.Report()
        sc.check_local_skills(repo({".claude/skills/gogogo-auto-test/SKILL.md": "x"}), rep)
        self.assertEqual(levels(rep, "local skills"), ["WARN"])
        self.assertIn("gogogo-auto-test", rep.rows[0]["detail"])
        rep = sc.Report()
        sc.check_local_skills(repo({".claude/skills-retired/gogogo-auto-test/SKILL.md": "x"}), rep)
        self.assertEqual(levels(rep, "local skills"), ["PASS"])

    def test_a_local_skill_named_auto_test_warns(self):
        rep = sc.Report()
        sc.check_local_skills(repo({".claude/skills/auto-test/SKILL.md": "x"}), rep)
        self.assertEqual(levels(rep, "local skills"), ["WARN"])
        self.assertIn("auto-test", rep.rows[0]["detail"])

    def test_claude_md_without_a_pointer_warns(self):
        rep = sc.Report()
        sc.check_claude_md(repo({"CLAUDE.md": "# x\n"}), rep)
        self.assertEqual(levels(rep, "CLAUDE.md"), ["WARN"])


class ProfileSkills(unittest.TestCase):
    def rows(self, settings, sections):
        rep = sc.Report()
        sc.check_profile_skills(settings, sections, rep)
        return rep.rows

    def test_a_profile_without_auto_test_is_info_not_fail(self):
        import profile_check
        from test_profile_check import COMPLETE
        settings, sections = profile_check.split_profile(COMPLETE)
        del settings["auto_test"]
        del sections["Test data"]
        rows = self.rows(settings, sections)
        self.assertEqual([r["level"] for r in rows if r["check"] == "profile for /gogogo:auto-test"], ["INFO"])
        self.assertNotIn("FAIL", [r["level"] for r in rows])

    def test_a_profile_with_auto_test_is_checked(self):
        import profile_check
        from test_profile_check import COMPLETE
        settings, sections = profile_check.split_profile(COMPLETE)
        del settings["auto_test"]["fail_label"]
        rows = [r for r in self.rows(settings, sections) if r["check"] == "profile for /gogogo:auto-test"]
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("auto_test.fail_label", rows[0]["detail"])


class ColumnCheck(unittest.TestCase):
    """The board-columns row reads the profile with its defaults filled in (gogogo#87)."""

    def test_a_profile_without_needs_human_needs_no_extra_column(self):
        import tracker
        from test_profile_check import NO_NEEDS_HUMAN
        root = repo({".agents/dev-process.md": NO_NEEDS_HUMAN.replace('tool = "python3 tools/board.py"',
                                                                       'tool = "shared"')})
        import profile_check
        settings, _ = profile_check.split_profile((root / ".agents" / "dev-process.md").read_text())
        self.assertEqual(settings["tracker"]["tool"], "shared")
        meta = {"title": "t", "total": 0, "options": {"Dev Priority": "a", "In progress": "b",
                                                      "In Dev": "c", "In Production": "d"}}
        ok = subprocess.CompletedProcess([], 0, "[]", "")
        rep = sc.Report()
        saved = (tracker.ORG, tracker.PROJECT_NUMBER, tracker.DEFAULT_REPO, dict(tracker.COLUMNS))
        try:
            with mock.patch.object(sc, "run", return_value=ok), \
                 mock.patch.object(tracker, "board_meta", return_value=meta), \
                 mock.patch.object(tracker, "list_cards", side_effect=tracker.BoardError("offline")), \
                 mock.patch.object(tracker, "graphql", side_effect=tracker.BoardError("offline")), \
                 mock.patch.object(sc, "check_board_tidiness"):
                sc.check_tracker(root, settings, rep)
        finally:
            tracker.ORG, tracker.PROJECT_NUMBER, tracker.DEFAULT_REPO = saved[:3]
            tracker.COLUMNS.clear()
            tracker.COLUMNS.update(saved[3])
        rows = [r for r in rep.rows if r["check"] == "tracker: columns"]
        self.assertEqual([r["level"] for r in rows], ["PASS"], rep.rows)
        self.assertEqual(rows[0]["detail"].split(", ").count("In progress"), 1, rows[0]["detail"])
        self.assertNotIn("Human!Help!", rows[0]["detail"])


def shape_rows(settings):
    rep = sc.Report()
    sc.check_release_shape(settings, rep)
    return rep.rows


LOCAL = {"name": "local", "roles": ["pre-merge"]}
STAGING = {"name": "staging", "roles": ["pre-merge", "pre-production"]}
PRODUCTION = {"name": "production", "roles": ["production"]}
RELEASED = {"code_is": "merged to main", "environment": "production", "column": "Released"}
STRAIGHT = {"environments": [LOCAL, PRODUCTION], "stages": [RELEASED],
            "verify": {"agent": ["local"], "human": "production"}}
STAGED = {"environments": [LOCAL, STAGING, PRODUCTION],
          "stages": [{"code_is": "on staging", "environment": "staging", "column": "In Staging"},
                     {"code_is": "released", "environment": "production", "column": "In Production"}],
          "verify": {"agent": ["staging"], "human": "production"}}


def warns(rows):
    return [r["check"] for r in rows if r["level"] == "WARN"]


class ReleaseShape(unittest.TestCase):
    def test_this_repos_own_profile_is_straight_to_production(self):
        import profile_check
        text = (ROOT / ".agents" / "dev-process.md").read_text(encoding="utf-8")
        settings, _ = profile_check.split_profile(text)
        rows = shape_rows(settings)
        self.assertEqual([r["level"] for r in rows], ["INFO"])
        self.assertIn("straight to production", rows[0]["detail"])
        self.assertIn("Released", rows[0]["detail"])

    def test_staged_profile_is_not_called_straight(self):
        rows = shape_rows(STAGED)
        self.assertEqual([r["level"] for r in rows], ["INFO"])
        self.assertIn("staged", rows[0]["detail"])
        self.assertIn("In Staging -> In Production", rows[0]["detail"])

    def test_extra_stage_is_surfaced(self):
        s = dict(STRAIGHT, stages=[RELEASED, {"code_is": "x", "column": "In Dev"}])
        rows = shape_rows(s)
        self.assertEqual(warns(rows), ["release shape: stages"])
        self.assertIn("Released -> In Dev", rows[-1]["detail"])

    def test_released_stage_must_point_at_production(self):
        s = dict(STRAIGHT, stages=[dict(RELEASED, environment="local")])
        self.assertEqual(warns(shape_rows(s)), ["release shape: stage environment"])

    def test_agent_never_verifies_on_production(self):
        s = dict(STRAIGHT, verify={"agent": ["production"], "human": "production"})
        self.assertEqual(warns(shape_rows(s)), ["release shape: verify.agent"])

    def test_staged_pre_production_must_be_reached_by_a_stage(self):
        s = dict(STAGED, stages=[{"code_is": "released", "environment": "production", "column": "In Production"}])
        self.assertEqual(warns(shape_rows(s)), ["release shape: stages"])

    def test_no_evidence_reports_nothing(self):
        self.assertEqual(shape_rows({}), [])
        self.assertEqual(shape_rows({"environments": [LOCAL]}), [])

    def test_shape_is_read_from_roles_not_environment_count(self):
        s = dict(STAGED, environments=[STAGING, PRODUCTION])
        self.assertIn("staged", shape_rows(s)[0]["detail"])

    def test_malformed_settings_do_not_crash(self):
        shape_rows(dict(STRAIGHT, verify="agent"))
        shape_rows(dict(STRAIGHT, environments=[LOCAL, dict(PRODUCTION, name=["x"])]))

    def test_a_tagged_stage_gets_a_stage_sync_row(self):
        tagged = dict(STAGED, stages=[STAGED["stages"][0], dict(STAGED["stages"][1], tag="deploy-*")])
        rows = [r for r in shape_rows(tagged) if r["check"] == "release shape: stage sync"]
        self.assertEqual([r["level"] for r in rows], ["INFO"])
        for needle in ("In Production", "deploy-*", "from In Staging"):
            self.assertIn(needle, rows[0]["detail"])
        self.assertEqual([r for r in shape_rows(STAGED) if r["check"] == "release shape: stage sync"], [])

    def test_a_tagged_stage_is_not_counted_against_straight_to_production(self):
        tagged = {"code_is": "in a deploy tag", "environment": "production", "column": "Live", "tag": "deploy-*"}
        self.assertEqual(warns(shape_rows(dict(STRAIGHT, stages=[RELEASED, tagged]))), [])
        # Two untagged stages still warn.
        self.assertEqual(warns(shape_rows(dict(STRAIGHT, stages=[RELEASED, dict(tagged, tag=None)]))),
                         ["release shape: stages"])

    def test_the_schema_example_with_a_tagged_stage_gives_no_warning(self):
        import tomllib
        doc = (ROOT / "plugins" / "gogogo" / "references" / "profile-schema.md").read_text(encoding="utf-8")
        blocks = [tomllib.loads(b.split("```")[0]) for b in doc.split("```toml\n")[1:]]
        envs = next(b for b in blocks if b.get("environments") and len(b) == 1)
        stages = next(b for b in blocks if any("tag" in s for s in b.get("stages", [])))
        rows = shape_rows({**envs, **stages})
        self.assertEqual(warns(rows), [])
        self.assertIn("release shape: stage sync", [r["check"] for r in rows])

    def test_a_tagged_stage_needs_a_deployed_environment(self):
        for env in ("local", "nowhere"):
            with self.subTest(env=env):
                s = dict(STAGED, stages=[STAGED["stages"][0],
                                         dict(STAGED["stages"][1], environment=env, tag="deploy-*")])
                self.assertIn("release shape: stage sync", warns(shape_rows(s)))
        ok = dict(STAGED, stages=[STAGED["stages"][0], dict(STAGED["stages"][1], tag="deploy-*")])
        self.assertEqual(warns(shape_rows(ok)), [])

    def test_a_tag_on_the_first_stage_warns(self):
        s = dict(STAGED, stages=[dict(STAGED["stages"][0], tag="staging-*"), STAGED["stages"][1]])
        self.assertIn("release shape: stage sync", warns(shape_rows(s)))

    def test_never_fails(self):
        for s in (STRAIGHT, STAGED, dict(STRAIGHT, stages=[]),
                  dict(STRAIGHT, verify={"agent": ["production"]})):
            self.assertTrue(all(r["level"] in ("INFO", "WARN") for r in shape_rows(s)))

    def test_setup_skill_names_only_settings_that_exist(self):
        import profile_check
        text = (ROOT / "plugins" / "gogogo" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        section = text[text.index("**No profile.**"):text.index("**No board")]
        for key in ("environments", "stages", "verify.agent", "verify.human"):
            self.assertIn(key, section)
            self.assertIn(key, profile_check.FIELDS)


class Audit(unittest.TestCase):
    def test_old_marketplace_name_warns(self):
        rep = sc.Report()
        sc.check_marketplace_source({"source": {"source": "github", "repo": "x/old-repo-name"}}, rep)
        self.assertEqual(levels(rep, "plugin settings: marketplace source"), ["WARN"])
        self.assertIn(sc.MARKETPLACE_REPO, rep.rows[0]["detail"])

    def test_current_marketplace_name_is_quiet_any_case(self):
        rep = sc.Report()
        sc.check_marketplace_source({"source": {"repo": sc.MARKETPLACE_REPO.upper()}}, rep)
        sc.check_marketplace_source({"source": "not a dict"}, rep)
        self.assertEqual(rep.rows, [])

    def test_workflows_off_warn_and_on_pass(self):
        off = sc.Report()
        sc.check_board_workflows([{"name": "Auto-add to project", "enabled": False},
                                  {"name": "Item added to project", "enabled": True}], off)
        self.assertEqual([r["level"] for r in off.rows], ["WARN"])
        self.assertIn("Auto-add to project", off.rows[0]["detail"])
        self.assertTrue(off.rows[0]["detail"].startswith("not enabled: Auto-add to project."))
        on = sc.Report()
        sc.check_board_workflows([{"name": n, "enabled": True} for n in sc.BOARD_WORKFLOWS], on)
        self.assertEqual([r["level"] for r in on.rows], ["PASS", "INFO"])

    def test_unreadable_workflows_say_so_without_failing(self):
        rep = sc.Report()
        sc.check_board_workflows(None, rep)
        self.assertEqual([r["level"] for r in rep.rows], ["INFO"])

    def test_unused_column_names_its_cards(self):
        cards = [{"number": 7, "status": "Dev Priority", "state": "OPEN"},
                 {"number": 8, "status": "Backlog", "state": "OPEN"}]
        rep = sc.Report()
        sc.check_board_hygiene(cards, [], ["Backlog", "Dev Priority", "Empty old"], {"backlog"}, rep)
        details = {r["detail"].split("'")[1]: r["detail"] for r in rep.rows}
        self.assertIn("holds 1 card", details["Dev Priority"])
        self.assertIn("holds 0 card", details["Empty old"])
        self.assertNotIn("Backlog", details)

    def test_issues_without_a_card_and_cards_without_a_column(self):
        rep = sc.Report()
        sc.check_board_hygiene([{"number": 3, "status": None, "state": "OPEN"}],
                               [{"number": 9}], ["Backlog"], {"backlog"}, rep)
        self.assertEqual(sorted(r["check"] for r in rep.rows),
                         ["tracker: cards the board's index missed", "tracker: cards without a column"])

    def test_drafts_and_recovered_cards_are_not_double_reported(self):
        rep = sc.Report()
        cards = [{"number": None, "status": None, "state": None},
                 {"number": 9, "status": None, "state": "OPEN"}]
        sc.check_board_hygiene(cards, [{"number": 9}], ["Backlog"], {"backlog"}, rep)
        self.assertEqual([r["check"] for r in rep.rows], ["tracker: cards the board's index missed"])

    def test_new_column_matches_with_or_without_the_emoji_selector(self):
        rep = sc.Report()
        sc.check_board_hygiene([], [], ["\u26a1\ufe0f New", "\u26a1 New"], {"\u26a1 new"}, rep)
        self.assertEqual(rep.rows, [])

    def test_clean_board_is_quiet(self):
        rep = sc.Report()
        sc.check_board_hygiene([{"number": 1, "status": "Backlog", "state": "OPEN"}], [], ["Backlog"],
                               {"backlog"}, rep)
        self.assertEqual(rep.rows, [])

    # check_board_origin: where the cards come from (issue #11)
    OWN = ("Vorski-Imagineering/gogogo",)

    @staticmethod
    def _card(n, repo, status, state="OPEN", kind="Issue"):
        return {"kind": kind, "number": n, "repo": repo, "state": state, "status": status}

    def _origin(self, cards, queue="Dev Ready", own=OWN):
        rep = sc.Report()
        sc.check_board_origin(cards, own, queue, rep)
        return rep

    def test_the_2026_10_01_board_warns_on_foreign_and_closed_queue_cards(self):
        cards = [self._card(i, "Vorski-Imagineering/gogogo", "Backlog") for i in range(3)]
        cards += [self._card(100 + i, "Vorski-Imagineering/old", "Released", "CLOSED") for i in range(22)]
        cards += [self._card(200 + i, "Vorski-Imagineering/old", "Dev Ready", "CLOSED") for i in range(2)]
        rep = self._origin(cards)
        by = {r["check"]: r for r in rep.rows}
        foreign = by["tracker: cards from another repo"]
        self.assertEqual(foreign["level"], "WARN")
        for text in ("24 of 27", "Vorski-Imagineering/old ×24", "Released ×22", "Dev Ready ×2"):
            self.assertIn(text, foreign["detail"])
        closed = by["tracker: closed cards in the queue"]["detail"]
        self.assertIn("Vorski-Imagineering/old#200", closed)
        self.assertIn("Vorski-Imagineering/old#201", closed)

    def test_own_repos_pass_whatever_their_case(self):
        own = ("Vorski-Imagineering/gogogo", "Vorski-Imagineering/code")
        cards = [self._card(1, "vorski-imagineering/Gogogo", "Backlog"),
                 self._card(2, "VORSKI-IMAGINEERING/code", "Backlog")]
        self.assertEqual(self._origin(cards, own=own).rows, [])

    def test_drafts_are_not_foreign(self):
        self.assertEqual(self._origin([self._card(None, None, "Backlog", None, "DraftIssue")]).rows, [])

    def test_unreadable_cards_are_reported_not_passed(self):
        import tracker
        for kind in ("ISSUE", "PULL_REQUEST", "REDACTED", None):
            card = tracker.flatten({"id": "i", "type": kind, "content": None,
                                    "fieldValueByName": {"name": "Backlog"}})
            rep = self._origin([card])
            self.assertEqual([(r["level"], r["check"]) for r in rep.rows],
                             [("INFO", "tracker: card origin")], kind)

    def test_closed_own_cards_in_the_queue_warn_and_others_do_not(self):
        cards = [self._card(1, self.OWN[0], "Dev Ready", "CLOSED"),
                 self._card(2, self.OWN[0], "Dev Ready", "MERGED", "PullRequest"),
                 self._card(3, self.OWN[0], "Dev Ready"),
                 self._card(4, self.OWN[0], "Released", "CLOSED")]
        rep = self._origin(cards)
        self.assertEqual([r["check"] for r in rep.rows],
                         ["tracker: pull requests on the board", "tracker: closed cards in the queue"])
        rep.rows.pop(0)
        self.assertIn("#1", rep.rows[0]["detail"])
        self.assertIn("#2", rep.rows[0]["detail"])
        self.assertNotIn("#3", rep.rows[0]["detail"])
        self.assertNotIn("#4", rep.rows[0]["detail"])
        new = self._origin([self._card(5, self.OWN[0], "\u26a1\ufe0f New", "CLOSED")], queue="\u26a1 New")
        self.assertEqual([r["check"] for r in new.rows], ["tracker: closed cards in the queue"])

    def test_origin_reads_the_fields_flatten_writes(self):
        import tracker
        item = {"id": "i1", "type": "ISSUE", "fieldValueByName": {"name": "Released"},
                "content": {"__typename": "Issue", "number": 7, "state": "CLOSED",
                            "repository": {"nameWithOwner": "other/repo"}}}
        rep = self._origin([tracker.flatten(item)])
        self.assertEqual([r["check"] for r in rep.rows], ["tracker: cards from another repo"])

    def test_no_queue_gives_no_closed_row_but_foreign_still_warns(self):
        rep = self._origin([self._card(1, "other/x", "Dev Ready", "CLOSED")], queue="")
        self.assertEqual([r["check"] for r in rep.rows], ["tracker: cards from another repo"])

    # pull requests as cards (issue #85)
    PR_ROW = "tracker: pull requests on the board"

    def _pr_rows(self, rep):
        return [r for r in rep.rows if r["check"] == self.PR_ROW]

    def test_own_pull_request_cards_warn_once_with_columns_and_numbers(self):
        cards = [self._card(11, self.OWN[0], "\u26a1\ufe0f New", kind="PullRequest"),
                 self._card(12, self.OWN[0], "Dev Ready", kind="PullRequest"),
                 self._card(13, self.OWN[0], "Backlog")]
        rows = self._pr_rows(self._origin(cards))
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        detail = rows[0]["detail"]
        for text in ("2 pull request(s)", "\u26a1\ufe0f New", "Dev Ready", "#11", "#12", "is:issue is:open"):
            self.assertIn(text, detail)
        self.assertNotIn("#13", detail)

    def test_merged_and_closed_pull_request_cards_count(self):
        cards = [self._card(21, self.OWN[0], "Done", "MERGED", "PullRequest"),
                 self._card(22, self.OWN[0], "Done", "CLOSED", "PullRequest")]
        rows = self._pr_rows(self._origin(cards))
        self.assertEqual(len(rows), 1)
        self.assertIn("2 pull request(s)", rows[0]["detail"])
        self.assertIn("Done", rows[0]["detail"])

    def test_another_repos_pull_request_is_reported_once_as_foreign(self):
        rep = self._origin([self._card(31, "other/x", "Backlog", kind="PullRequest")])
        self.assertEqual([r["check"] for r in rep.rows], ["tracker: cards from another repo"])

    def test_an_unreadable_pull_request_card_is_not_a_pr_row(self):
        rep = self._origin([self._card(None, None, "Backlog", None, "PULL_REQUEST")])
        self.assertEqual(self._pr_rows(rep), [])

    def test_pr_row_reads_the_fields_flatten_writes(self):
        import tracker
        item = {"id": "i2", "type": "PULL_REQUEST", "fieldValueByName": {"name": "\u26a1\ufe0f New"},
                "content": {"__typename": "PullRequest", "number": 9, "state": "OPEN",
                            "repository": {"nameWithOwner": "Vorski-Imagineering/gogogo"}}}
        rows = self._pr_rows(self._origin([tracker.flatten(item)]))
        self.assertEqual(len(rows), 1)
        self.assertIn("#9", rows[0]["detail"])

    def test_a_long_pr_list_shows_ten_numbers_then_more(self):
        cards = [self._card(100 + i, self.OWN[0], "Done", kind="PullRequest") for i in range(12)]
        detail = self._pr_rows(self._origin(cards))[0]["detail"]
        self.assertIn("12 pull request(s)", detail)
        self.assertIn("#109, ...", detail)
        self.assertNotIn("#110", detail)

    def test_pr_row_separates_numbers_and_names_a_card_with_no_column(self):
        cards = [self._card(41, self.OWN[0], None, kind="PullRequest"),
                 self._card(42, self.OWN[0], "Done", kind="PullRequest")]
        detail = self._pr_rows(self._origin(cards))[0]["detail"]
        self.assertIn("no status", detail)
        self.assertIn("#41, #42. ", detail)

    def test_ten_pr_cards_are_all_listed_without_more_and_eleven_add_it(self):
        ten = [self._card(100 + i, self.OWN[0], "Done", kind="PullRequest") for i in range(10)]
        detail = self._pr_rows(self._origin(ten))[0]["detail"]
        self.assertIn("#109. ", detail)
        self.assertNotIn("...", detail)
        eleven = ten + [self._card(110, self.OWN[0], "Done", kind="PullRequest")]
        self.assertIn("#109, .... ", self._pr_rows(self._origin(eleven))[0]["detail"])

    def test_auto_add_row_names_the_repo_and_says_the_api_is_blind(self):
        rep = sc.Report()
        sc.check_board_workflows([{"name": n, "enabled": True} for n in sc.BOARD_WORKFLOWS], rep, ("a/b",))
        info = [r for r in rep.rows if r["check"] == "tracker: Auto-add repository"]
        self.assertEqual(len(info), 1)
        self.assertIn("a/b", info[0]["detail"])
        self.assertIn("does not say", info[0]["detail"])
        self.assertIn("is:issue is:open", info[0]["detail"])
        off = sc.Report()
        sc.check_board_workflows([{"name": "Auto-add to project", "enabled": False}], off, ("a/b",))
        self.assertNotIn("tracker: Auto-add repository", [r["check"] for r in off.rows])

    def test_origin_checks_never_fail(self):
        rep = sc.Report()
        worst = [self._card(1, "x/y", "Dev Ready", "CLOSED"), self._card(None, None, None, None, "Unknown"),
                 self._card(2, self.OWN[0], "Dev Ready", kind="PullRequest")]
        sc.check_board_origin(worst, self.OWN, "Dev Ready", rep)
        sc.check_board_workflows([{"name": "Auto-add to project", "enabled": True}], rep, self.OWN)
        self.assertTrue(rep.rows and not rep.failed())
    # check_ready_label: one standard colour (issue #18)
    def _label(self, listing, label="dev ready"):
        rep = sc.Report()
        sc.check_ready_label("owner/repo", label, listing, rep)
        return rep

    def test_missing_ready_label_is_created_in_the_standard_colour(self):
        rep = self._label([])
        self.assertEqual([(r["level"], r["check"]) for r in rep.rows], [("FAIL", "tracker: ready label")])
        fix = rep.rows[0]["fix"]
        for text in ("--color 0E8A16", '"dev ready"', "owner/repo"):
            self.assertIn(text, fix)

    def test_ready_label_in_the_standard_colour_passes_in_any_case(self):
        for colour in ("0e8a16", "0E8A16"):
            rep = self._label([{"name": "dev ready", "color": colour, "description": ""}])
            self.assertEqual([r["level"] for r in rep.rows], ["PASS"], colour)

    def test_ready_label_in_another_colour_warns_with_the_edit(self):
        rep = self._label([{"name": "dev ready", "color": "BFD4F2", "description": "x"}])
        self.assertEqual([r["level"] for r in rep.rows], ["PASS", "WARN"])
        detail = rep.rows[1]["detail"]
        self.assertEqual(rep.rows[1]["check"], sc.READY_LABEL_COLOUR_CHECK)
        for text in ("#BFD4F2", "#0E8A16", 'gh label edit "dev ready" --repo owner/repo --color 0E8A16'):
            self.assertIn(text, detail)

    def test_ready_label_commands_use_the_profiles_name(self):
        rep = self._label([{"name": "dev.ready", "color": "bfd4f2"}], label="dev.ready")
        self.assertIn('gh label edit "dev.ready"', rep.rows[1]["detail"])

    def test_ready_label_colour_never_fails_and_gh_failure_reads_as_missing(self):
        rep = sc.Report()
        for colour in ("0e8a16", "BFD4F2"):
            sc.check_ready_label("owner/repo", "dev ready", [{"name": "dev ready", "color": colour}], rep)
        self.assertFalse(rep.failed())
        broken = self._label(None)
        self.assertEqual([(r["level"], r["check"]) for r in broken.rows], [("FAIL", "tracker: ready label")])

    def test_ready_label_name_matches_in_any_case(self):
        rep = self._label([{"name": "Dev Ready", "color": "0E8A16"}])
        self.assertEqual([r["level"] for r in rep.rows], ["PASS"])

    def test_ready_label_of_the_wrong_type_is_missing_not_a_crash(self):
        rep = self._label([{"name": "dev ready", "color": "0E8A16"}], label=1)
        self.assertEqual([(r["level"], r["check"]) for r in rep.rows], [("FAIL", "tracker: ready label")])

    def test_ready_label_edit_changes_only_the_colour(self):
        detail = self._label([{"name": "dev ready", "color": "BFD4F2"}]).rows[1]["detail"]
        edit = detail[detail.index("gh label edit"):]
        self.assertNotIn("--description", edit)
        self.assertNotIn("--name", edit)

    def test_setup_skill_names_the_ready_label_colour_row(self):
        text = (ROOT / "plugins" / "gogogo" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(sc.READY_LABEL_COLOUR_CHECK, text)
        self.assertIn("gh label edit", text)
    # check_delete_branch: GitHub deletes a PR's branch when it merges (issue #42)
    def _delete(self, setting, error=None):
        rep = sc.Report()
        sc.check_delete_branch("owner/repo", setting, error, rep)
        return rep.rows

    def test_delete_branch_on_passes(self):
        self.assertEqual([(r["level"], r["check"]) for r in self._delete(True)],
                         [("PASS", "code repo: delete merged branches")])

    def test_delete_branch_off_fails_with_the_patch_and_its_undo(self):
        rows = self._delete(False)
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("gh api -X PATCH repos/owner/repo -F delete_branch_on_merge=true", rows[0]["fix"])
        self.assertIn("=false", rows[0]["fix"])

    def test_delete_branch_unreadable_warns_never_passes(self):
        self.assertEqual([r["level"] for r in self._delete(None)], ["WARN"])

    def test_delete_branch_read_failure_warns_with_the_reason(self):
        rows = self._delete(None, error="HTTP 404")
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertIn("HTTP 404", rows[0]["detail"])

    def test_setup_skill_names_the_delete_branch_row(self):
        text = (ROOT / "plugins" / "gogogo" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(sc.DELETE_BRANCH_CHECK, text)
        self.assertIn("gh api -X PATCH", text)

    def test_setup_skill_names_the_pull_requests_row(self):
        text = (ROOT / "plugins" / "gogogo" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("is:issue is:open", text)
        self.assertNotIn("is:issue,pr", text)
        self.assertIn("pull requests on the board", text)

    def test_setup_skill_archives_inside_the_pull_requests_bullet(self):
        text = (ROOT / "plugins" / "gogogo" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        bullet = re.search(r"(?ms)^- \*\*Pull requests on the board\*\*.*?(?=^- \*\*)", text)
        self.assertIsNotNone(bullet)
        self.assertIn("gh project item-archive", bullet.group(0))

    def test_check_tracker_reads_the_code_repo(self):
        calls = []

        def fake_run(*cmd, cwd=None):
            calls.append(cmd)
            out = json.dumps({"delete_branch_on_merge": False}) if cmd[:2] == ("gh", "api") else ""
            return subprocess.CompletedProcess(cmd, 0, out, "")

        rep = sc.Report()
        with mock.patch.object(sc, "run", fake_run):
            sc.check_tracker(Path("."), {"tracker": {"issues_repo": "o/issues", "code_repo": "o/code"}}, rep)
        fails = [r for r in rep.rows if r["level"] == "FAIL"]
        self.assertEqual([r["check"] for r in fails], ["code repo: delete merged branches"])
        self.assertIn("o/code", fails[0]["detail"])
        self.assertIn(("gh", "api", "repos/o/code"), calls)
        self.assertNotIn(("gh", "api", "repos/o/issues"), calls)

    # check_branch_rules: GitHub refuses force pushes, deletion and red merges (issue #57)
    FULL = [{"type": "deletion", "ruleset_id": 7, "bypass_actors": []},
            {"type": "non_fast_forward", "ruleset_id": 7, "bypass_actors": []},
            {"type": "required_status_checks", "ruleset_id": 7, "bypass_actors": []}]

    def _rules(self, rules=None, classic=None, checks=("tests",), wants_check=True, needs_ci=False, target=True):
        rep = sc.Report()
        sc.check_branch_rules("o/r", "main", self.FULL if rules is None else rules, {} if classic is None else classic,
                              list(checks) if isinstance(checks, tuple) else checks, wants_check, needs_ci, rep,
                              target=target)
        return rep.rows

    def test_branch_rules_all_present_pass(self):
        self.assertEqual([(r["level"], r["check"]) for r in self._rules()], [("PASS", "code repo: branch rules (main)")])

    def test_branch_rules_none_fail_with_the_ruleset_command(self):
        rows = self._rules(rules=[])
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("force push", rows[0]["detail"])
        self.assertIn("deletion", rows[0]["detail"])
        self.assertIn("--ruleset main", rows[0]["fix"])
        self.assertIn("rulesets --input -", rows[0]["fix"])
        self.assertIn("-X DELETE", rows[0]["fix"])

    def test_branch_rules_partial_fails_naming_what_is_missing(self):
        rows = self._rules(rules=[self.FULL[1]])
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("deletion", rows[0]["detail"])
        self.assertIn("required check", rows[0]["detail"])
        self.assertNotIn("force push", rows[0]["detail"])

    def test_branch_rules_missing_check_is_warn_or_fail_by_ci_before_merge(self):
        warned = self._rules(rules=self.FULL[:2], needs_ci=False)
        self.assertEqual([r["level"] for r in warned], ["WARN"])
        self.assertIn("--ruleset main", warned[0]["fix"])
        self.assertEqual([r["level"] for r in self._rules(rules=self.FULL[:2], needs_ci=True)], ["FAIL"])

    def test_branch_rules_unreadable_warns_never_passes(self):
        rows = self._rules(rules="HTTP 404")
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertIn("HTTP 404", rows[0]["detail"])

    def test_branch_rules_classic_unread_warns(self):
        rows = self._rules(rules=[], classic="HTTP 403")
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertIn("classic", rows[0]["detail"])
        self.assertIn("--ruleset main", rows[0]["fix"])

    def test_an_unreadable_ruleset_is_an_unreadable_rules_read(self):
        def fake_run(*cmd, cwd=None):
            if "/rulesets/" in " ".join(cmd):
                return subprocess.CompletedProcess(cmd, 1, "", "gh: Not Found (HTTP 404)")
            return self._gh([], rules=json.dumps(self.FULL))(*cmd, cwd=cwd)
        rep = sc.Report()
        with mock.patch.object(sc, "run", fake_run):
            sc.check_branches("o/code", {"integration": {"strategy": "pr-squash", "base": "main"}}, "main", rep)
        self.assertEqual([r["level"] for r in rep.rows], ["WARN"])
        self.assertIn("ruleset 7", rep.rows[0]["detail"])

    def test_branch_rules_read_from_classic_protection(self):
        classic = {"allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
                   "required_status_checks": {"contexts": ["tests"], "checks": []},
                   "enforce_admins": {"enabled": True}}
        self.assertEqual([r["level"] for r in self._rules(rules=[], classic=classic)], ["PASS"])

    def test_branch_rules_a_bypass_fails(self):
        rules = [dict(r, bypass_actors=[{"actor_type": "RepositoryRole", "actor_id": 5}]) for r in self.FULL]
        rows = self._rules(rules=rules)
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("RepositoryRole", rows[0]["detail"])

    def test_branch_rules_merge_script_base_gets_info_for_the_check(self):
        rows = self._rules(rules=self.FULL[:2], wants_check=False, needs_ci=True)
        self.assertEqual([r["level"] for r in rows], ["INFO"])

    def test_branch_rules_no_check_to_require_says_add_ci(self):
        rows = self._rules(rules=self.FULL[:2], checks=[], needs_ci=True)
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("CI workflow", rows[0]["fix"])
        self.assertNotIn("--ruleset", rows[0]["fix"])

    def test_branch_rules_default_branch_with_no_check_name_warns(self):
        rows = self._rules(rules=self.FULL[:2], checks=[], needs_ci=True, target=False)
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertIn("no check name can be derived", rows[0]["detail"])
        body = sc.ruleset_body("main", [], True)
        self.assertNotIn("required_status_checks", [r["type"] for r in body["rules"]])

    def test_ruleset_body(self):
        body = sc.ruleset_body("main", ["tests"], True)
        self.assertEqual(body["bypass_actors"], [])
        self.assertEqual(body["conditions"]["ref_name"]["include"], ["refs/heads/main"])
        check = next(r for r in body["rules"] if r["type"] == "required_status_checks")
        self.assertFalse(check["parameters"]["strict_required_status_checks_policy"])
        self.assertEqual(check["parameters"]["required_status_checks"], [{"context": "tests"}])
        no_check = sc.ruleset_body("dev", ["tests"], False)
        self.assertEqual(sorted(r["type"] for r in no_check["rules"]), ["deletion", "non_fast_forward"])

    def _gh(self, calls, *, default="main", checks=(("tests", "pass"),), rules="[]"):
        def fake_run(*cmd, cwd=None):
            calls.append(cmd)
            joined = " ".join(cmd)
            if cmd[:2] == ("gh", "api") and cmd[2].endswith("/rulesets"):
                out = "[]"
            elif cmd[:2] == ("gh", "api") and "/rulesets/" in cmd[2]:
                out = json.dumps({"bypass_actors": []})
            elif cmd[:2] == ("gh", "api") and "/rules/branches/" in cmd[2]:
                out = rules
            elif cmd[:2] == ("gh", "api") and cmd[2].endswith("/protection"):
                return subprocess.CompletedProcess(cmd, 1, "", "gh: Branch not protected (HTTP 404)")
            elif "pr list" in joined:
                out = json.dumps([{"number": 12}])
            elif "pr checks" in joined:
                out = json.dumps([{"name": n, "bucket": b} for n, b in checks])
            else:
                out = ""
            return subprocess.CompletedProcess(cmd, 0, out, "")
        return fake_run

    def _branches(self, integration, default="main", checks=(("tests", "pass"),), rules="[]"):
        calls, rep = [], sc.Report()
        settings = {"tracker": {"issues_repo": "o/issues", "code_repo": "o/code"}, "integration": integration}
        with mock.patch.object(sc, "run", self._gh(calls, default=default, checks=checks, rules=rules)):
            plan = sc.check_branches("o/code", settings, default, rep)
        return calls, rep.rows, plan

    def test_branches_pr_squash_reads_only_the_code_repo(self):
        calls, rows, _ = self._branches({"strategy": "pr-squash", "base": "main"})
        self.assertIn(("gh", "api", "repos/o/code/rules/branches/main"), calls)
        self.assertTrue([c for c in calls if c[:3] == ("gh", "pr", "list") and "o/code" in c and "main" in c])
        self.assertFalse([c for c in calls if any("o/issues" in part for part in c)])
        self.assertEqual([r["check"] for r in rows], ["code repo: branch rules (main)"])

    def test_branches_run_branch_pr_checks_final_target_and_default(self):
        calls, rows, plan = self._branches({"strategy": "run-branch-pr", "base": "auto-{date}",
                                            "final_target": "staging"})
        self.assertEqual([r["check"] for r in rows],
                         ["code repo: branch rules (staging)", "code repo: branch rules (main)"])
        self.assertEqual([(b, w) for b, w, _ in plan], [("staging", True), ("main", True)])
        self.assertTrue([c for c in calls if c[:3] == ("gh", "pr", "list") and "main" in c])
        self.assertFalse([c for c in calls if any("rules/branches/auto" in part for part in c)])

    def test_branches_merge_script_base_has_no_check_and_default_does(self):
        basic = json.dumps([{"type": "deletion", "ruleset_id": 3}, {"type": "non_fast_forward", "ruleset_id": 3}])
        _, rows, plan = self._branches({"strategy": "merge-script", "base": "dev"}, rules=basic)
        self.assertEqual([(b, w) for b, w, _ in plan], [("dev", False), ("main", True)])
        self.assertEqual([(r["level"], r["check"]) for r in rows][0], ("INFO", "code repo: branch rules (dev)"))
        self.assertNotIn("required_status_checks", [r["type"] for r in sc.ruleset_body("dev", ["tests"], False)["rules"]])

    def test_branches_take_only_passing_check_names(self):
        calls = []
        with mock.patch.object(sc, "run", self._gh(calls, checks=(("tests", "pass"), ("lint", "fail")))):
            self.assertEqual(sc.check_names("o/code", "main"), ["tests"])

    def test_a_refused_rules_read_warns_with_githubs_reason(self):
        def fake_run(*cmd, cwd=None):
            if "/rules/branches/" in " ".join(cmd):
                return subprocess.CompletedProcess(cmd, 1, '{"message":"Upgrade to GitHub Pro","status":"403"}',
                                                   "gh: Upgrade to GitHub Pro (HTTP 403)")
            return self._gh([])(*cmd, cwd=cwd)
        rep = sc.Report()
        settings = {"integration": {"strategy": "pr-squash", "base": "main"}}
        with mock.patch.object(sc, "run", fake_run):
            sc.check_branches("o/code", settings, "main", rep)
        self.assertEqual([r["level"] for r in rep.rows], ["WARN"])
        self.assertIn("Upgrade to GitHub Pro", rep.rows[0]["detail"])

    def test_a_ruleset_read_without_a_bypass_list_is_unreadable(self):
        def fake_run(*cmd, cwd=None):
            if "/rulesets/" in " ".join(cmd):
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": 7, "rules": []}), "")
            return self._gh([], rules=json.dumps(self.FULL))(*cmd, cwd=cwd)
        rep = sc.Report()
        with mock.patch.object(sc, "run", fake_run):
            sc.check_branches("o/code", {"integration": {"strategy": "pr-squash", "base": "main"}}, "main", rep)
        self.assertEqual([r["level"] for r in rep.rows], ["WARN"])

    def _print_ruleset_with_unreadable_checks(self, rulesets):
        def fake_run(*cmd, cwd=None):
            joined = " ".join(cmd)
            if "pr list" in joined:
                return subprocess.CompletedProcess(cmd, 1, "", "gh: HTTP 502")
            if cmd[:2] == ("gh", "api") and cmd[2].endswith("/rulesets"):
                return subprocess.CompletedProcess(cmd, 0, json.dumps(rulesets), "")
            return self._gh([])(*cmd, cwd=cwd)
        settings = {"tracker": {"code_repo": "o/code"}, "integration": {"strategy": "pr-squash", "base": "main"}}
        out = io.StringIO()
        with mock.patch.object(sc, "run", fake_run), mock.patch("sys.stdout", out), mock.patch("sys.stderr"):
            code = sc.print_ruleset(settings, "main", "main")
        return code, out.getvalue()

    def test_ruleset_refuses_to_replace_an_existing_one_when_the_check_names_cannot_be_read(self):
        code, out = self._print_ruleset_with_unreadable_checks([{"id": 7, "name": "gogogo: main"}])
        self.assertEqual((code, out), (2, ""))

    def test_a_new_ruleset_still_prints_without_a_check_when_the_names_cannot_be_read(self):
        code, out = self._print_ruleset_with_unreadable_checks([])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(r["type"] for r in json.loads(out)["rules"]), ["deletion", "non_fast_forward"])

    def test_a_missing_check_with_classic_unread_is_uncertain(self):
        rows = self._rules(rules=self.FULL[:2], classic="HTTP 403", needs_ci=True)
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertIn("classic", rows[0]["detail"])

    def test_a_bypass_on_the_gogogo_ruleset_carries_the_put(self):
        rules = [dict(r, bypass_actors=[{"actor_type": "RepositoryRole", "actor_id": 5}]) for r in self.FULL]
        rep = sc.Report()
        sc.check_branch_rules("o/r", "main", rules, {}, ["tests"], True, False, rep, existing=7)
        self.assertEqual([r["level"] for r in rep.rows], ["FAIL"])
        self.assertIn("-X PUT repos/o/r/rulesets/7", rep.rows[0]["fix"])

    BYPASSABLE_CHECK = {"required_status_checks": {"contexts": ["tests"], "checks": []},
                        "enforce_admins": {"enabled": False}}

    def test_a_bypassable_classic_check_on_a_merge_script_base_is_info(self):
        rows = self._rules(rules=self.FULL[:2], classic=self.BYPASSABLE_CHECK, wants_check=False, needs_ci=True)
        self.assertEqual([r["level"] for r in rows], ["INFO"])

    def test_a_bypassable_classic_check_is_graded_as_missing(self):
        rows = self._rules(rules=self.FULL[:2], classic=self.BYPASSABLE_CHECK, checks=[], needs_ci=False)
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        rows = self._rules(rules=self.FULL[:2], classic=self.BYPASSABLE_CHECK, needs_ci=True)
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("--ruleset main", rows[0]["fix"])

    def test_a_bypassable_classic_check_is_named_not_called_absent(self):
        for checks in (["tests"], []):
            rows = self._rules(rules=self.FULL[:2], classic=self.BYPASSABLE_CHECK, checks=checks, needs_ci=True)
            self.assertNotIn("requires no check", rows[0]["detail"], checks)
            self.assertIn("only in classic branch protection", rows[0]["detail"])
            self.assertNotIn("add a CI workflow", rows[0]["fix"])

    def test_an_unreadable_checks_read_reaches_the_classic_detail(self):
        rows = self._rules(rules=self.FULL[:2], classic=self.BYPASSABLE_CHECK, checks="HTTP 502", needs_ci=True)
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        for text in ("tests", "classic branch protection", "HTTP 502"):
            self.assertIn(text, rows[0]["detail"])
        self.assertNotIn("whose checks pass", rows[0]["fix"])
        rows = self._rules(rules=self.FULL[:2], classic=self.BYPASSABLE_CHECK, checks=[], needs_ci=True)
        self.assertIn("whose checks pass", rows[0]["fix"])
        self.assertTrue(rows[0]["detail"].endswith("(enforce admins is off)"), rows[0]["detail"])

    def test_the_put_fix_saves_first_and_its_undo_restores(self):
        rules = [dict(r, bypass_actors=[{"actor_type": "RepositoryRole", "actor_id": 5}]) for r in self.FULL]
        rep = sc.Report()
        sc.check_branch_rules("o/r", "main", rules, {}, ["tests"], True, False, rep, existing=7)
        fix = rep.rows[0]["fix"]
        fix_part, undo = fix.split("undo", 1)
        order = [fix_part.index(t) for t in ("gh api repos/o/r/rulesets/7 --jq", "gogogo-ruleset-7-before.json",
                                             "-X PUT repos/o/r/rulesets/7 --input -")]
        self.assertEqual(order, sorted(order))
        self.assertIn("-X PUT repos/o/r/rulesets/7 --input", undo)
        self.assertIn("gogogo-ruleset-7-before.json", undo)
        self.assertNotIn("-X DELETE", fix)
        rep = sc.Report()
        sc.check_branch_rules("o/r", "main", self.FULL[:2], {}, ["tests"], True, True, rep)
        self.assertIn("-X POST repos/o/r/rulesets", rep.rows[0]["fix"])
        self.assertIn("-X DELETE repos/o/r/rulesets/", rep.rows[0]["fix"])

    def test_classic_protection_admins_can_bypass_fails(self):
        classic = {"allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
                   "required_status_checks": {"contexts": ["tests"], "checks": []},
                   "enforce_admins": {"enabled": False}}
        rows = self._rules(rules=[], classic=classic)
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("admins", rows[0]["detail"])
        self.assertIn("--ruleset main", rows[0]["fix"])

    # Test cases 7 and 23-26 of issue #57, each as the spec words it.
    def test_t7_classic_protection_counts_only_with_enforce_admins(self):
        classic = {"allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
                   "required_status_checks": {"contexts": ["tests"], "checks": []},
                   "enforce_admins": {"enabled": True}}
        self.assertEqual([r["level"] for r in self._rules(rules=[], classic=classic)], ["PASS"])
        rows = self._rules(rules=[], classic=dict(classic, enforce_admins={"enabled": False}))
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        for text in ("force push", "deletion", "required check"):
            self.assertIn(text, rows[0]["detail"])

    def test_t23_force_push_and_deletion_only_in_bypassable_classic_fail(self):
        classic = {"allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
                   "enforce_admins": {"enabled": False}}
        rows = self._rules(rules=[{"type": "required_status_checks"}], classic=classic)
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        for text in ("force push", "deletion", "classic branch protection", "admins can bypass"):
            self.assertIn(text, rows[0]["detail"])
        self.assertIn("--ruleset main", rows[0]["fix"])

    def _bypassed_ruleset(self, name):
        """check_branches over FULL held by ruleset 9 named `name`, whose bypass list is not empty."""
        rules = json.dumps([dict(r, ruleset_id=9) for r in self.FULL])

        def fake_run(*cmd, cwd=None):
            if cmd[:2] == ("gh", "api") and cmd[2].endswith("/rulesets"):
                return subprocess.CompletedProcess(cmd, 0, json.dumps([{"id": 9, "name": name}]), "")
            if cmd[:2] == ("gh", "api") and cmd[2].endswith("/rulesets/9"):
                return subprocess.CompletedProcess(cmd, 0, json.dumps(
                    {"id": 9, "name": name, "bypass_actors": [{"actor_type": "RepositoryRole", "actor_id": 5}]}), "")
            return self._gh([], rules=rules)(*cmd, cwd=cwd)
        rep = sc.Report()
        with mock.patch.object(sc, "run", fake_run):
            sc.check_branches("o/code", {"integration": {"strategy": "pr-squash", "base": "main"}}, "main", rep)
        return rep.rows

    def test_t24_a_bypass_on_another_ruleset_names_it_in_settings(self):
        rows = self._bypassed_ruleset("other")
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("Settings > Rules", rows[0]["fix"])
        self.assertIn("other", rows[0]["fix"])
        self.assertNotIn("--ruleset", rows[0]["fix"])
        rows = self._bypassed_ruleset("gogogo: main")
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        self.assertIn("--ruleset main", rows[0]["fix"])

    def test_t25_a_missing_check_with_classic_unread_warns_with_the_error(self):
        rows = self._rules(rules=self.FULL[:2], classic="HTTP 403", needs_ci=True)
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertIn("HTTP 403", rows[0]["detail"])

    def _print_ruleset_failing(self, failing, rulesets):
        """print_ruleset for main with the `gh pr checks` read failing, and the rulesets read too when asked."""
        def fake_run(*cmd, cwd=None):
            if "pr checks" in " ".join(cmd):
                return subprocess.CompletedProcess(cmd, 1, "", "gh: HTTP 502")
            if cmd[:2] == ("gh", "api") and cmd[2].endswith("/rulesets"):
                if failing == "rulesets":
                    return subprocess.CompletedProcess(cmd, 1, "", "gh: HTTP 403")
                return subprocess.CompletedProcess(cmd, 0, json.dumps(rulesets), "")
            return self._gh([])(*cmd, cwd=cwd)
        settings = {"tracker": {"code_repo": "o/code"}, "integration": {"strategy": "pr-squash", "base": "main"}}
        out = io.StringIO()
        with mock.patch.object(sc, "run", fake_run), mock.patch("sys.stdout", out), mock.patch("sys.stderr"):
            code = sc.print_ruleset(settings, "main", "main")
        return code, out.getvalue()

    def test_t26_ruleset_refuses_rather_than_drop_the_check(self):
        self.assertEqual(self._print_ruleset_failing("checks", [{"id": 7, "name": "gogogo: main"}]), (2, ""))
        self.assertEqual(self._print_ruleset_failing("rulesets", []), (2, ""))
        code, out = self._print_ruleset_failing("checks", [])
        self.assertEqual(code, 0)
        self.assertNotIn("required_status_checks", [r["type"] for r in json.loads(out)["rules"]])

    def test_ruleset_for_a_branch_the_profile_does_not_give_exits_2(self):
        calls = []
        settings = {"tracker": {"code_repo": "o/code"}, "integration": {"strategy": "pr-squash", "base": "main"}}
        with mock.patch.object(sc, "run", self._gh(calls)), mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(sc.print_ruleset(settings, "main", "elsewhere"), 2)

    def test_setup_and_auto_dev_name_the_branch_rules(self):
        setup = (ROOT / "plugins" / "gogogo" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(sc.BRANCH_RULES_CHECK, setup)
        self.assertIn("--ruleset", setup)
        auto_dev = (ROOT / "plugins" / "gogogo" / "skills" / "auto-dev" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('setup_check.py" --branch-rules', auto_dev)

    # check_release: references/versioning.md (issue #15)
    def _release(self, settings):
        rep = sc.Report()
        sc.check_release(settings, rep, shallow=False)
        return rep.rows

    def test_release_not_adopted_is_info(self):
        rows = self._release({"stages": []})
        self.assertEqual([(r["level"], r["check"]) for r in rows], [("INFO", "release")])
        self.assertIn("not adopted", rows[0]["detail"])

    PROD = [{"name": "prod", "roles": ["production"]}, {"name": "stage", "roles": ["pre-production"]}]

    def test_release_warns_on_a_stage_tag_deploy_tags_never_match(self):
        stage = {"column": "In Production", "environment": "prod", "tag": "v*"}
        rows = self._release({"release": {"major": 1}, "stages": [stage], "environments": self.PROD})
        self.assertIn(("WARN", "release: stage sync"), [(r["level"], r["check"]) for r in rows])
        stage["tag"] = "deploy-*"
        rows = self._release({"release": {"major": 1}, "stages": [stage], "environments": self.PROD})
        self.assertNotIn("release: stage sync", [r["check"] for r in rows])

    def test_release_ignores_tags_on_stages_before_production(self):
        stages = [{"column": "Staging", "environment": "stage", "tag": "staging-*"},
                  {"column": "In Production", "environment": "prod", "tag": "deploy-*"}]
        rows = self._release({"release": {"major": 1}, "stages": stages, "environments": self.PROD})
        self.assertNotIn("release: stage sync", [r["check"] for r in rows])

    def test_release_table_without_major_warns(self):
        rows = self._release({"release": {}, "stages": []})
        self.assertIn(("WARN", "release: major"), [(r["level"], r["check"]) for r in rows])

    def test_release_warns_on_a_shallow_clone_and_never_fails(self):
        rep = sc.Report()
        sc.check_release({"release": {"major": 1}, "stages": [{"tag": "v*", "environment": "prod"}],
                          "environments": self.PROD}, rep, shallow=True)
        self.assertIn("release: build number", [r["check"] for r in rep.rows])
        self.assertFalse(rep.failed())

    def test_audit_checks_never_fail(self):
        rep = sc.Report()
        sc.check_marketplace_source({"source": {"repo": "a/b"}}, rep)
        sc.check_board_workflows([], rep)
        sc.check_board_hygiene([{"number": 1, "status": "X", "state": "OPEN"}], [{"number": 2}], ["X"], set(), rep)
        self.assertTrue(rep.rows and not rep.failed())


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def origin_and_clone():
    """A bare origin whose default branch is main, and a clone of it level with origin."""
    base = Path(tempfile.mkdtemp()).resolve()
    seed = base / "seed"
    git("init", "-q", "-b", "main", str(seed), cwd=base)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "seed", cwd=seed)
    git("clone", "-q", "--bare", str(seed), str(base / "origin.git"), cwd=base)
    git("clone", "-q", str(base / "origin.git"), str(base / "work"), cwd=base)
    return base / "origin.git", base / "work"


def commit(cwd, msg="c"):
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", msg, cwd=cwd)


class GitState(unittest.TestCase):
    def check(self, work):
        rep = sc.Report()
        sc.check_git_state(work, rep)
        return [(r["level"], r["check"]) for r in rep.rows]

    def test_clean_default_branch_level_with_origin_passes(self):
        _, work = origin_and_clone()
        self.assertEqual(self.check(work), [("PASS", "git: clean main")])

    def test_another_branch_fails(self):
        _, work = origin_and_clone()
        git("switch", "-q", "-c", "feature", cwd=work)
        self.assertIn(("FAIL", "git: clean main"), self.check(work))

    def test_uncommitted_tracked_change_fails_and_untracked_only_warns(self):
        _, work = origin_and_clone()
        (work / "f").write_text("x")
        self.assertEqual(self.check(work), [("WARN", "git: untracked files"), ("PASS", "git: clean main")])
        git("add", "f", cwd=work)
        self.assertIn(("FAIL", "git: clean main"), self.check(work))

    def test_behind_origin_fails(self):
        origin, work = origin_and_clone()
        other = work.parent / "other"
        git("clone", "-q", str(origin), str(other), cwd=work.parent)
        commit(other)
        git("push", "-q", "origin", "main", cwd=other)
        self.assertIn(("FAIL", "git: clean main"), self.check(work))

    def test_ahead_of_origin_fails(self):
        _, work = origin_and_clone()
        commit(work)
        self.assertIn(("FAIL", "git: clean main"), self.check(work))

    def test_detached_head_fails(self):
        _, work = origin_and_clone()
        git("switch", "-q", "--detach", cwd=work)
        self.assertIn(("FAIL", "git: clean main"), self.check(work))

    def test_no_origin_says_so_and_still_checks_the_tree(self):
        tmp = repo({"f": "x"})
        git("add", "f", cwd=tmp)
        rows = self.check(tmp)
        self.assertIn(("INFO", "git: origin"), rows)
        self.assertIn(("FAIL", "git: clean main"), rows)


def view(name, layout="BOARD_LAYOUT", filt="", fields=("Title", "Status", "Labels"), sort=()):
    return {"name": name, "layout": layout, "filter": filt, "fields": list(fields), "sort": list(sort)}


BACKLOG = view("Backlog", filt="-status:Done,Future", sort=[("Created", "DESC")])
READY = view("Dev Ready", filt='-status:Done,Future,Released label:"dev ready"')


class BoardViews(unittest.TestCase):
    def check(self, views, ready="dev ready", stages=("Released",)):
        rep = sc.Report()
        sc.check_board_views(views, ready, list(stages), rep)
        return rep

    def test_both_kanban_views_pass(self):
        rep = self.check([view("View 1", layout="TABLE_LAYOUT", fields=("Title",)), BACKLOG, READY])
        self.assertEqual([r["level"] for r in rep.rows], ["PASS"])

    def test_missing_ready_view_names_its_filter(self):
        rep = self.check([BACKLOG], stages=("In Dev", "In Production"))
        self.assertEqual([r["check"] for r in rep.rows], ["tracker: board views"])
        self.assertIn('-status:Done,Future,"In Dev","In Production" label:"dev ready"', rep.rows[0]["detail"])

    def test_missing_backlog_view_warns(self):
        rep = self.check([READY])
        self.assertEqual([r["level"] for r in rep.rows], ["WARN"])
        self.assertIn("-status:Done,Future", rep.rows[0]["detail"])

    def test_a_table_filtered_on_the_label_is_not_the_kanban(self):
        rep = self.check([BACKLOG, view("Dev Ready", layout="TABLE_LAYOUT", filt='label:"dev ready"')])
        self.assertEqual([r["level"] for r in rep.rows], ["WARN"])

    def test_a_board_view_without_labels_warns_by_name(self):
        rep = self.check([BACKLOG, view("Dev Ready", filt='label:"dev ready"', fields=("Title",))])
        self.assertEqual([r["check"] for r in rep.rows], ["tracker: labels in board views"])
        self.assertIn("'Dev Ready'", rep.rows[0]["detail"])

    def test_backlog_not_newest_first_warns(self):
        rep = self.check([view("Backlog", filt="-status:Done,Future"), READY])
        self.assertEqual([r["check"] for r in rep.rows], ["tracker: board views"])
        self.assertIn("newest first", rep.rows[0]["detail"])

    def test_unreadable_views_say_so_and_views_never_fail(self):
        rep = self.check(None)
        self.assertEqual([r["level"] for r in rep.rows], ["INFO"])
        rep = self.check([])
        self.assertTrue(rep.rows and not rep.failed())


class ConfigHeader(unittest.TestCase):
    """The `config:` block at the top of setup_check's output (issue #12)."""
    NAMES = ["config: board", "config: tracker", "config: release", "config: hard stops",
             "config: lanes", "config: install", "config: profile"]

    def settings(self, **tracker):
        import profile_check
        from test_profile_check import COMPLETE
        settings, _ = profile_check.split_profile(COMPLETE)
        settings["tracker"].update({"tool": "shared"}, **tracker)
        return settings

    def header(self, settings, files=None, gh=None, profile=".agents/dev-process.md"):
        root = repo(files if files is not None else {".claude/settings.json": GOOD_SETTINGS})
        gh = gh or subprocess.CompletedProcess([], 0, "https://github.com/orgs/acme/projects/2\n", "")
        calls = []
        rep = sc.Report()
        with mock.patch.object(sc, "run", lambda *a, **k: calls.append(a) or gh):
            sc.config_header(root, settings, rep, root / profile if profile else None)
        return {r["check"]: r["detail"] for r in rep.rows}, [r["check"] for r in rep.rows], calls

    def test_rows_in_order_with_values(self):
        rows, order, _ = self.header(self.settings())
        self.assertEqual(order, self.NAMES)
        self.assertEqual(rows["config: board"], "https://github.com/orgs/acme/projects/2")
        for check, text in [("config: tracker", '"dev ready"'), ("config: tracker", '"Dev Priority"'),
                            ("config: tracker", "acme/issues"), ("config: release", "integration "),
                            ("config: hard stops", "schema, auth"), ("config: lanes", "make test"),
                            ("config: lanes", "always: make lint"), ("config: profile", ".agents/dev-process.md")]:
            self.assertIn(text, rows[check], check)

    def test_release_row_says_where_work_happens(self):
        s = self.settings()
        s["integration"]["workspace"] = "worktree"
        self.assertTrue(self.header(s)[0]["config: release"].endswith(
            "; integration merge-script into main, work in worktree"))
        del s["integration"]["workspace"]
        self.assertTrue(self.header(s)[0]["config: release"].endswith(
            "; integration merge-script into main, work in missing"))

    def test_no_profile_prints_missing(self):
        rows, order, calls = self.header({}, profile=None)
        self.assertEqual(order, self.NAMES)
        for name in self.NAMES:
            if name != "config: install":
                self.assertEqual(rows[name], "missing", name)
        self.assertIn("settings file present", rows["config: install"])
        self.assertEqual(calls, [])

    def test_gh_failure_is_unreadable_not_empty(self):
        failed = subprocess.CompletedProcess([], 1, "", "HTTP 404: not found\nmore\n")
        rows, order, _ = self.header(self.settings(), gh=failed)
        self.assertEqual(rows["config: board"], "unreadable (HTTP 404: not found)")
        self.assertEqual(order, self.NAMES)

    def test_own_tool_not_shown(self):
        rows, _, calls = self.header(self.settings(tool="bespoke"))
        self.assertEqual(rows["config: board"], "not shown: the repo's own tool bespoke")
        self.assertEqual(calls, [])

    def test_install_row(self):
        s = self.settings()
        off = json.dumps({"extraKnownMarketplaces": {"vorski-skills": {"autoUpdate": False}},
                          "enabledPlugins": {"gogogo@vorski-skills": False}})
        for files, words in [({}, "settings file absent"),
                             ({".claude/settings.json": "{not json"}, "settings file unreadable"),
                             ({".claude/settings.json": off}, "plugin enabled no, auto-update off"),
                             ({".claude/settings.json": GOOD_SETTINGS}, "plugin enabled yes, auto-update on")]:
            self.assertIn(words, self.header(s, files=files)[0]["config: install"], words)

    def test_header_comes_first_in_real_output(self):
        from test_profile_check import COMPLETE
        root = repo({".agents/dev-process.md": COMPLETE, ".claude/settings.json": GOOD_SETTINGS})
        bin_dir = Path(tempfile.mkdtemp())
        (bin_dir / "gh").write_text("#!/bin/sh\necho 'offline' >&2\nexit 1\n")
        (bin_dir / "gh").chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        script = ROOT / "plugins" / "gogogo" / "scripts" / "setup_check.py"
        out = subprocess.run([sys.executable, str(script)], cwd=root, env=env,
                             capture_output=True, text=True).stdout.splitlines()
        self.assertEqual([line.split(":")[0] + ":" + line.split(":")[1] for line in out[:7]],
                         [f"INFO  {n}" for n in self.NAMES])
        self.assertFalse(any(line.startswith("INFO  config:") for line in out[7:]))
        rows = json.loads(subprocess.run([sys.executable, str(script), "--json"], cwd=root, env=env,
                                         capture_output=True, text=True).stdout)
        self.assertEqual([r["check"] for r in rows[:7]], self.NAMES)

    def test_wrong_typed_profile_values_do_not_crash(self):
        s = self.settings()
        s.update(verify="dev", integration="pr-squash", gates=["make lint"], stages="x")
        s["tracker"]["columns"] = "In progress"
        s["environments"][0]["roles"] = "production"
        rows, order, _ = self.header(s)
        self.assertEqual(order, self.NAMES)
        self.assertIn("(production)", rows["config: release"])

    def test_scalar_profile_values_do_not_crash(self):
        s = self.settings(project_owner=5)
        s["verify"] = {"agent": True}
        s["environments"][0]["roles"] = 1
        s["hard_stops"]["items"] = 3
        rows, order, _ = self.header(s)
        self.assertEqual(order, self.NAMES)
        self.assertIn("verify agent True", rows["config: release"])

    def test_unset_tool_is_missing_not_an_own_tool(self):
        s = self.settings()
        del s["tracker"]["tool"]
        rows, _, calls = self.header(s)
        self.assertEqual(rows["config: board"], "missing")
        self.assertEqual(calls, [])

    def test_setup_skill_mentions_header(self):
        text = (ROOT / "plugins" / "gogogo" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("config:", text)
class BoardTidiness(unittest.TestCase):
    """The board stays current: views hide closed issues, no card is left behind. Warn only."""

    import tracker as real

    def shared(self, views, closed=(), off_board=()):
        fake = mock.Mock()
        fake.DONE_COLUMN, fake.BoardError = "Done", self.real.BoardError
        fake.views_showing_closed = self.real.views_showing_closed
        fake.board_views.return_value = views
        fake.untidy.return_value = (list(closed), list(off_board))
        return fake

    def test_a_tidy_board_passes(self):
        rep = sc.Report()
        sc.check_board_tidiness(self.shared([{"name": "Board", "filter": "is:open"}]), "a/b", rep)
        self.assertEqual([(r["level"], r["check"]) for r in rep.rows],
                         [("PASS", "tracker: views"), ("PASS", "tracker: cards")])

    def test_each_gap_warns_with_its_own_command(self):
        rep = sc.Report()
        sc.check_board_tidiness(self.shared([{"name": "Board", "filter": ""}],
                                            closed=[{"number": 7}], off_board=[{"number": 9}]), "a/b", rep)
        rows = {r["check"]: r for r in rep.rows}
        self.assertEqual([r["level"] for r in rep.rows], ["WARN", "WARN"])
        self.assertFalse(rep.failed())
        self.assertIn("views --hide-closed", rows["tracker: views"]["detail"])
        self.assertIn("#7", rows["tracker: cards"]["detail"])
        self.assertIn("#9", rows["tracker: cards"]["detail"])
        self.assertIn("tidy", rows["tracker: cards"]["detail"])

    def test_open_issues_off_the_board_warn_on_their_own(self):
        rep = sc.Report()
        sc.check_board_tidiness(self.shared([{"name": "Board", "filter": "is:open"}], off_board=[{"number": 9}]),
                                "a/b", rep)
        cards = [r for r in rep.rows if r["check"] == "tracker: cards"]
        self.assertEqual([r["level"] for r in cards], ["WARN"])
        self.assertNotIn("closed but not in", cards[0]["detail"])

    def test_an_unreadable_board_is_info_never_pass(self):
        fake = self.shared([])
        fake.board_views.side_effect = self.real.BoardError("no access")
        rep = sc.Report()
        sc.check_board_tidiness(fake, "a/b", rep)
        self.assertEqual([(r["level"], r["check"]) for r in rep.rows], [("INFO", "tracker: views and cards")])

    def test_an_odd_api_shape_is_info_not_a_crash(self):
        fake = self.shared([])
        fake.untidy.side_effect = TypeError("'NoneType' object is not subscriptable")
        rep = sc.Report()
        sc.check_board_tidiness(fake, "a/b", rep)
        self.assertEqual([r["level"] for r in rep.rows], ["INFO"])

    def test_a_null_view_is_info_not_a_crash(self):
        rep = sc.Report()
        sc.check_board_tidiness(self.shared([None]), "a/b", rep)
        self.assertEqual([r["level"] for r in rep.rows], ["INFO"])

    def test_the_index_row_does_not_claim_the_issues_have_no_card(self):
        rep = sc.Report()
        sc.check_board_hygiene([], [{"number": 9}], ["Backlog"], {"backlog"}, rep)
        self.assertEqual([r["check"] for r in rep.rows], ["tracker: cards the board's index missed"])
        self.assertNotIn("have no card", rep.rows[0]["detail"])


class Notify(unittest.TestCase):
    """The notify row: one per state, never a FAIL, so it never changes the exit code."""

    def row(self, state, line):
        rep = sc.Report()
        with mock.patch("notify.status", return_value=(state, line, "")):
            sc.check_notify("profile.md", rep)
        rows = [r for r in rep.rows if r["check"] == "notify"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rep.failed())
        return rows[0]

    def test_each_state_gives_its_row(self):
        import notify
        off = self.row(notify.OFF, "notify: off")
        self.assertEqual(off["level"], "INFO")
        self.assertTrue(off["detail"].startswith("off"))
        ready = self.row(notify.READY, "notify: telegram: bot @b -> Vic")
        self.assertEqual((ready["level"], ready["detail"]), ("PASS", "telegram: bot @b -> Vic"))
        self.assertEqual(self.row(notify.NO_CREDENTIALS, "notify: telegram, but no bot credentials")["level"], "WARN")
        failed = self.row(notify.FAILED, "notify: telegram: Unauthorized")
        self.assertEqual((failed["level"], failed["detail"]), ("WARN", "telegram: Unauthorized"))

    def real_row(self, repo_file_ignored):
        """The row from notify's own status, in a temp repo with no `notify` line and full credentials."""
        import notify
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        (tmp / ".gitignore").write_text(".claude/gogogo/\n" if repo_file_ignored else "")
        creds = tmp / "home-notify.env"
        creds.write_text(f"{notify.TOKEN_KEY}=1:abc\n{notify.CHAT_KEY}=7\n")
        repo_file = tmp / ".claude" / "gogogo" / "notify.env"
        repo_file.parent.mkdir(parents=True)
        repo_file.write_text(f"{notify.CHAT_KEY}=8\n")
        profile = tmp / ".agents" / "dev-process.md"
        profile.parent.mkdir()
        profile.write_text("+++\nprofile = 1\n+++\n\n## superpowers boundary\nx\n")
        answers = [{"ok": True, "result": {"username": "b"}}, {"ok": True, "result": {"first_name": "Vic"}}]
        rep = sc.Report()
        with mock.patch.object(notify, "CREDENTIALS", creds), \
                mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(notify, "_call", side_effect=lambda *a, **k: answers.pop(0)["result"]):
            sc.check_notify(profile, rep)
        rows = [r for r in rep.rows if r["check"] == "notify"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rep.failed())
        return rows[0]

    def test_the_default_passes_and_a_file_that_is_not_ignored_warns(self):
        default = self.real_row(True)
        self.assertEqual(default["level"], "PASS")
        self.assertIn("(by default)", default["detail"])
        unread = self.real_row(False)
        self.assertEqual(unread["level"], "WARN")
        self.assertIn("not git-ignored", unread["detail"])


class Workspace(unittest.TestCase):
    """Where dev and auto-dev do an issue's work: the `workspace` row and the live-checkout
    reasons behind it (gogogo#94). Read only; never a FAIL."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.root = self.home / "dev" / "repo"
        self.root.mkdir(parents=True)

    def hooks(self, *pairs):
        """Write <home>/.claude/settings.json with one hook per (event, command)."""
        hooks = {}
        for event, command in pairs:
            hooks.setdefault(event, []).append({"hooks": [{"type": "command", "command": command}]})
        path = self.home / ".claude" / "settings.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"hooks": hooks}))

    def rows(self, workspace=None, lanes="The test host must be dev."):
        settings = {"integration": {"strategy": "pr-squash", "base": "main"}}
        if workspace is not None:
            settings["integration"]["workspace"] = workspace
        rep = sc.Report()
        sc.check_workspace(self.root, settings, {"Lane constraints": lanes}, rep, self.home)
        self.assertFalse(rep.failed())
        return [r for r in rep.rows if r["check"] == "workspace"]

    def test_absent_warns_not_decided(self):
        rows = self.rows()
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertTrue(rows[0]["detail"].startswith("not decided"), rows[0]["detail"])
        self.assertNotIn("Lane constraints", rows[0]["detail"])

    def test_absent_with_worktree_prose_names_lane_constraints(self):
        rows = self.rows(lanes="Put each issue in its own git Worktree.")
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertIn("## Lane constraints", rows[0]["detail"])

    def test_set_is_info_with_its_value(self):
        rows = self.rows("checkout")
        self.assertEqual([(r["level"], r["detail"]) for r in rows], [("INFO", "checkout")])

    def test_a_plugin_repo_is_a_live_checkout(self):
        (self.root / ".claude-plugin").mkdir()
        reasons = sc.live_checkout(self.root, self.home)
        self.assertEqual(len(reasons), 1)
        self.assertIn("Claude Code plugin", reasons[0])
        rows = self.rows("worktree")
        self.assertEqual(rows[0]["level"], "INFO")
        self.assertTrue(rows[0]["detail"].startswith("worktree; live checkout: "), rows[0]["detail"])

    def test_a_user_hook_inside_the_checkout_is_named_by_its_path_and_event(self):
        self.hooks(("SessionStart", "python3 ~/dev/repo/scripts/h.py"),
                   ("Stop", "sh $HOME/dev/repo/bin/stop.sh"),
                   ("PreToolUse", "python3 ~/dev/repo-other/x.py"),
                   ("PostToolUse", "python3 /usr/local/bin/x.py"))
        self.assertEqual(sc.live_checkout(self.root, self.home),
                         ["your Claude Code settings run scripts/h.py on SessionStart",
                          "your Claude Code settings run bin/stop.sh on Stop"])

    def test_the_exact_rows_design_3_fixes(self):
        self.assertEqual(self.rows()[0]["detail"], "not decided: dev and auto-dev work in the checkout")
        self.assertEqual(self.rows(lanes="Put each issue in its own git Worktree")[0]["detail"],
                         "not decided: dev and auto-dev work in the checkout; ## Lane constraints mention a "
                         "worktree, so dev and auto-dev stop until it is set")
        (self.root / ".claude-plugin").mkdir()
        self.hooks(("SessionStart", "python3 ~/dev/repo/scripts/h.py"))
        self.assertEqual(self.rows("worktree")[0]["detail"],
                         "worktree; live checkout: this repo is a Claude Code plugin; sessions may load it "
                         "from here with --plugin-dir; your Claude Code settings run scripts/h.py on SessionStart")

    def test_a_hook_without_a_command_does_not_hide_the_next(self):
        path = self.home / ".claude" / "settings.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": 5},
            {"type": "command", "command": "python3 ~/dev/repo/scripts/h.py"}]}]}}))
        self.assertEqual(sc.live_checkout(self.root, self.home),
                         ["your Claude Code settings run scripts/h.py on SessionStart"])

    def test_a_hook_naming_the_checkout_itself_is_named_as_dot(self):
        self.hooks(("Stop", "cd ~/dev/repo && make"))
        self.assertEqual(sc.live_checkout(self.root, self.home), ["your Claude Code settings run . on Stop"])

    def run_main(self, cwd):
        """setup_check.py's rows, run in `cwd` with HOME at this test's home and gh offline."""
        bin_dir = self.home / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "gh").write_text("#!/bin/sh\necho offline >&2\nexit 1\n")
        (bin_dir / "gh").chmod(0o755)
        env = {**os.environ, "HOME": str(self.home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        script = ROOT / "plugins" / "gogogo" / "scripts" / "setup_check.py"
        out = subprocess.run([sys.executable, str(script), "--json"], cwd=cwd, env=env,
                             capture_output=True, text=True)
        return [r for r in json.loads(out.stdout) if r["check"] == "workspace"]

    def test_no_profile_still_names_a_live_checkout(self):
        # Setup asks the question while drafting a profile, so the live reasons must be there then too.
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.assertEqual(self.run_main(self.root), [])
        (self.root / ".claude-plugin").mkdir()
        rows = self.run_main(self.root)
        self.assertEqual([(r["level"], r["detail"]) for r in rows],
                         [("WARN", "not decided: dev and auto-dev work in the checkout; live checkout: this repo "
                                   "is a Claude Code plugin; sessions may load it from here with --plugin-dir")])
        (self.root / ".agents").mkdir()
        (self.root / ".agents" / "dev-process.md").write_text("no front matter\n")
        self.assertEqual([r["level"] for r in self.run_main(self.root)], ["WARN"])

    def test_run_from_a_worktree_it_reads_hooks_naming_the_main_checkout(self):
        git = ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        wt = self.home / "dev" / "repo-wt-1"
        subprocess.run([*git, "worktree", "add", "-q", "-b", "fix/1-x", str(wt)], check=True)
        self.hooks(("SessionStart", "python3 ~/dev/repo/scripts/h.py"))
        self.assertEqual(sc.main_worktree(wt), self.root)
        self.assertEqual(sc.main_worktree(self.home), self.home)  # not a repo: falls back
        rows = self.run_main(wt)
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertTrue(rows[0]["detail"].endswith("; live checkout: your Claude Code settings run scripts/h.py "
                                                   "on SessionStart"), rows[0]["detail"])

    def test_the_printed_path_stops_where_the_command_goes_on(self):
        self.hooks(("SessionStart", "python3 ~/dev/repo/scripts/h.py>~/log"),
                   ("Stop", "python3 ~/dev/repo/h.py,abc"),
                   ("PreToolUse", "python3 ~/dev/repo/a.py<in"),
                   ("PostToolUse", "x --f=~/dev/repo/b.py=1:2"))
        self.assertEqual(sc.live_checkout(self.root, self.home),
                         ["your Claude Code settings run scripts/h.py on SessionStart",
                          "your Claude Code settings run h.py on Stop",
                          "your Claude Code settings run a.py on PreToolUse",
                          "your Claude Code settings run b.py on PostToolUse"])

    def test_a_hook_outside_the_checkout_is_no_reason(self):
        self.hooks(("SessionStart", "python3 ~/other/h.py"))
        self.assertEqual(sc.live_checkout(self.root, self.home), [])

    def test_a_missing_or_invalid_settings_file_gives_no_reasons(self):
        self.assertEqual(sc.live_checkout(self.root, self.home), [])
        path = self.home / ".claude" / "settings.json"
        path.parent.mkdir()
        for text in ("{not json", json.dumps({"hooks": "x"}), json.dumps({"hooks": {"Stop": [1, {"hooks": 2}]}}),
                     json.dumps([1])):
            path.write_text(text)
            self.assertEqual(sc.live_checkout(self.root, self.home), [], text)

    def test_the_reason_never_carries_the_rest_of_the_command(self):
        self.hooks(("SessionStart", "python3 ~/dev/repo/scripts/h.py --token abc"))
        rows = self.rows("checkout")
        self.assertIn("scripts/h.py on SessionStart", rows[0]["detail"])
        self.assertNotIn("abc", rows[0]["detail"])
        self.assertNotIn("--token", rows[0]["detail"])

    def test_live_reasons_are_added_to_the_warning_too(self):
        self.hooks(("SessionStart", "python3 ~/dev/repo/scripts/h.py"))
        rows = self.rows()
        self.assertEqual(rows[0]["level"], "WARN")
        self.assertIn("; live checkout: your Claude Code settings run scripts/h.py on SessionStart",
                      rows[0]["detail"])


class SessionHook(unittest.TestCase):
    """The plugin's own SessionStart hook: reported, never a FAIL."""

    def row(self, files):
        rep = sc.Report()
        sc.check_session_hook(repo(files), rep)
        rows = [r for r in rep.rows if r["check"] == "session-status"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rep.failed())
        return rows[0]

    def test_main_checks_this_plugin(self):
        self.assertEqual(sc.PLUGIN_ROOT, ROOT / "plugins" / "gogogo")

    def test_the_shipped_hook_is_info(self):
        rep = sc.Report()
        sc.check_session_hook(ROOT / "plugins" / "gogogo", rep)
        self.assertEqual([(r["level"], r["check"]) for r in rep.rows], [("INFO", "session-status")])
        self.assertEqual(rep.rows[0]["detail"], "shown at session start (plugin hook)")

    def test_hook_present_is_info(self):
        hooks = {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [
            {"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session_status.py"'}]}]}}
        self.assertEqual(self.row({"hooks/hooks.json": json.dumps(hooks)})["level"], "INFO")

    def test_no_hooks_file_warns(self):
        row = self.row({})
        self.assertEqual((row["level"], row["detail"]), ("WARN", "the plugin's session-status hook is missing"))

    def test_hook_under_another_event_or_unreadable_warns(self):
        other = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "session_status.py"}]}]}}
        self.assertEqual(self.row({"hooks/hooks.json": json.dumps(other)})["level"], "WARN")
        self.assertEqual(self.row({"hooks/hooks.json": "{not json"})["level"], "WARN")
        self.assertEqual(self.row({"hooks/hooks.json": "[]"})["level"], "WARN")
        no_command = {"hooks": {"SessionStart": [{"hooks": [{"type": "command"}]}]}}
        self.assertEqual(self.row({"hooks/hooks.json": json.dumps(no_command)})["level"], "WARN")



def gh_stub(calls, replies):
    """A stand-in for `run`: records each command and answers `gh <args>` by its exact
    argument string from `replies` ({"api repos/o/code": (0, out, err)}); anything else
    gets exit 0 and no output."""
    def fake_run(*cmd, cwd=None):
        calls.append(cmd)
        rc, out, err = replies.get(" ".join(cmd[1:]), (0, "", ""))
        return subprocess.CompletedProcess(cmd, rc, out, err)
    return fake_run


def listed(detail, after, before=None):
    """The comma-separated names in `detail` between `after` and `before` (or the end)."""
    start = detail.index(after) + len(after)
    end = detail.index(before, start) if before else len(detail)
    return detail[start:end].split(", ")


class BranchRulesExact(unittest.TestCase):
    """Issue #57: what the spec fixes word for word, asserted exactly, and each name a row lists."""
    CHECK = "code repo: branch rules (main)"
    FULL = [{"type": "deletion", "ruleset_id": 7, "bypass_actors": []},
            {"type": "non_fast_forward", "ruleset_id": 7, "bypass_actors": []},
            {"type": "required_status_checks", "ruleset_id": 7, "bypass_actors": []}]
    NOT_PROTECTED = (1, "", "gh: Branch not protected (HTTP 404)")
    PR_LIST = "pr list --repo o/code --base main --state merged --limit 1 --json number"
    PR_CHECKS = "pr checks 12 --repo o/code --json name,bucket"

    def rows(self, rules, classic=None, checks=("tests",), wants_check=True, needs_ci=False, **kw):
        rep = sc.Report()
        sc.check_branch_rules("o/r", "main", rules, {} if classic is None else classic,
                              list(checks) if isinstance(checks, tuple) else checks, wants_check, needs_ci, rep, **kw)
        return rep.rows

    def classic(self, enforce, checks=None, **extra):
        body = {"allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
                "enforce_admins": {"enabled": enforce}}
        if checks is not None:
            body["required_status_checks"] = checks
        return dict(body, **extra)

    # The ruleset body and the fix commands (Design 3)
    def test_the_ruleset_body_is_the_specs(self):
        self.assertEqual(sc.ruleset_body("main", ["tests", "lint"], True), {
            "name": "gogogo: main", "target": "branch", "enforcement": "active", "bypass_actors": [],
            "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                      {"type": "required_status_checks", "parameters": {
                          "strict_required_status_checks_policy": False,
                          "required_status_checks": [{"context": "tests"}, {"context": "lint"}]}}]})

    def test_the_post_and_put_fixes_are_the_specs_commands(self):
        script = Path(sc.__file__).resolve()
        post = self.rows(self.FULL[:2], needs_ci=True)[0]["fix"]
        self.assertEqual(post, f'`python3 "{script}" --ruleset main | gh api -X POST repos/o/r/rulesets --input -` '
                               "(undo: `gh api -X DELETE repos/o/r/rulesets/<id from the POST's output>`)")
        put = self.rows(self.FULL[:2], needs_ci=True, existing=7)[0]["fix"]
        saved = '"$(git rev-parse --git-dir)/gogogo-ruleset-7-before.json"'
        self.assertEqual(put, "first save the existing ruleset: `gh api repos/o/r/rulesets/7 "
                              f"--jq '{{name,target,enforcement,bypass_actors,conditions,rules}}' > {saved}`, then "
                              f'`python3 "{script}" --ruleset main | gh api -X PUT repos/o/r/rulesets/7 --input -` '
                              f"(undo: `gh api -X PUT repos/o/r/rulesets/7 --input {saved}`; undo before applying "
                              "this fix a second time, or the save holds the state after the first PUT)")

    # Design 1's levels and the names each row lists
    def test_a_branch_is_the_merge_target_unless_told_otherwise(self):
        rep = sc.Report()
        sc.check_branch_rules("o/r", "main", self.FULL[:2], {}, [], True, True, rep)
        self.assertEqual([r["level"] for r in rep.rows], ["FAIL"])

    def test_a_classic_check_given_only_as_checks_counts(self):
        classic = self.classic(True, {"contexts": [], "checks": [{"context": "tests", "app_id": 1}]})
        self.assertEqual([r["level"] for r in self.rows([], classic)], ["PASS"])

    def test_unreadable_classic_protection_says_it_needs_admin_with_the_error(self):
        for rules in ([], self.FULL[:2]):
            row = self.rows(rules, "HTTP 403", needs_ci=True)[0]
            self.assertEqual(row["level"], "WARN")
            self.assertIn("classic branch protection, which needs admin to read (HTTP 403)", row["detail"])
        row = self.rows([], "HTTP 403")[0]
        self.assertEqual(listed(row["detail"], "has no ruleset for ", "; "), ["no force push", "no deletion"])

    def test_a_fail_lists_each_missing_rule_by_name(self):
        row = self.rows([self.FULL[1]])[0]
        self.assertEqual(listed(row["detail"], "is missing: "), ["no deletion", "a required check"])
        row = self.rows([self.FULL[2]])[0]
        self.assertEqual(listed(row["detail"], "is missing: "), ["no force push", "no deletion"])

    def test_a_bypass_lists_each_actor(self):
        actors = [{"actor_type": "RepositoryRole", "actor_id": 5}, {"actor_type": "Integration", "actor_id": 9}]
        row = self.rows([dict(r, bypass_actors=actors) for r in self.FULL])[0]
        self.assertEqual(listed(row["detail"], "can be bypassed by: "), ["Integration 9", "RepositoryRole 5"])

    def test_a_bypass_on_other_rulesets_names_each_in_settings(self):
        actor = [{"actor_type": "RepositoryRole", "actor_id": 5}]
        one = [dict(r, ruleset_id=9, ruleset_name="other", bypass_actors=actor) for r in self.FULL]
        self.assertEqual(self.rows(one)[0]["fix"], "empty the bypass list in Settings > Rules for the ruleset 'other'")
        two = [dict(self.FULL[0], ruleset_id=3, ruleset_name="a", bypass_actors=actor),
               dict(self.FULL[1], ruleset_id=4, bypass_actors=actor), dict(self.FULL[2], ruleset_id=4)]
        self.assertEqual(self.rows(two)[0]["fix"],
                         "empty the bypass list in Settings > Rules for the rulesets 'a', id 4")

    def test_a_classic_block_also_held_by_a_ruleset_passes(self):
        self.assertEqual([r["level"] for r in self.rows(self.FULL, {"allow_force_pushes": {"enabled": False}})],
                         ["PASS"])

    def test_bypassable_classic_rules_are_each_named_once(self):
        def held(rules, classic):
            row = self.rows(rules, classic)[0]
            self.assertEqual(row["level"], "FAIL")
            return row["detail"], listed(row["detail"], " has ", " only in classic")
        tests = {"contexts": ["tests"], "checks": []}
        detail, names = held([self.FULL[0], self.FULL[2]], dict(self.classic(False, tests),
                                                                allow_deletions={"enabled": True}))
        self.assertEqual(names, ["no force push"])
        self.assertNotIn("a required check", detail)
        detail, names = held([self.FULL[2]], self.classic(False))
        self.assertEqual(names, ["no force push", "no deletion"])
        self.assertNotIn("a required check", detail)
        detail, names = held([], self.classic(False, tests))
        self.assertEqual(names, ["no force push", "no deletion", "a required check"])
        self.assertEqual(detail.count("a required check"), 1)
        detail, names = held([], self.classic(False))
        self.assertEqual(names, ["no force push", "no deletion"])
        self.assertTrue(detail.startswith("o/r main has "), detail)
        self.assertIn("a required check", detail)

    def test_the_merge_script_info_is_the_specs(self):
        self.assertEqual(self.rows(self.FULL[:2], wants_check=False, needs_ci=True), [
            {"level": "INFO", "check": self.CHECK, "fix": "",
             "detail": "a required check is not offered: the merge script pushes to main directly"}])

    def test_no_derivable_name_on_the_default_branch_is_the_specs_warn(self):
        self.assertEqual(self.rows(self.FULL[:2], checks=[], needs_ci=True, target=False), [
            {"level": "WARN", "check": self.CHECK, "fix": "",
             "detail": "no check name can be derived: no PR with a passing check has been merged into main"}])

    def test_a_bypassable_classic_check_lists_its_names(self):
        for tests in ({"contexts": [], "checks": [{"context": "tests"}, {"context": "lint"}]},
                      {"contexts": ["tests", "lint"], "checks": []}):
            row = self.rows(self.FULL[:2], {"required_status_checks": tests, "enforce_admins": {"enabled": False}},
                            needs_ci=True)[0]
            self.assertEqual(listed(row["detail"], " requires ", " only in classic"), ["tests", "lint"])

    def test_design_9_fixes_are_the_specs(self):
        classic = {"required_status_checks": {"contexts": ["tests"]}, "enforce_admins": {"enabled": False}}
        row = self.rows(self.FULL[:2], classic, checks="HTTP 502", needs_ci=True)[0]
        self.assertTrue(row["detail"].endswith(" (HTTP 502)"), row["detail"])
        self.assertEqual(row["fix"], "re-run once the latest merged PR's checks can be read, to get the ruleset command")
        row = self.rows(self.FULL[:2], classic, checks=[], needs_ci=True)[0]
        self.assertEqual(row["fix"], "merge a PR into `main` whose checks pass, then re-run to get the ruleset command")

    def test_no_check_on_the_merge_target_asks_for_ci(self):
        row = self.rows(self.FULL[:2], checks=[], needs_ci=True)[0]
        self.assertTrue(row["detail"].endswith("no check passed on the latest PR merged into main"), row["detail"])
        self.assertEqual(row["fix"], "add a CI workflow that runs on every pull request to `main`, merge one PR, re-run")
        row = self.rows(self.FULL[:2], checks="HTTP 502", needs_ci=True)[0]
        self.assertTrue(row["detail"].endswith("no check passed on the latest PR merged into main (HTTP 502)"),
                        row["detail"])

    def test_a_missing_check_names_what_passed(self):
        row = self.rows(self.FULL[:2], checks=["tests", "lint"], needs_ci=True)[0]
        self.assertEqual(re.search(r"passed: (.*)\)$", row["detail"]).group(1).split(", "), ["tests", "lint"])

    # The reads (Designs 2 and 4)
    def test_gh_json_reads_json_only_where_the_caller_allows_a_failed_exit(self):
        replies = {"x": (0, "not json", ""), "y": (1, '[{"a": 1}]', "gh: failed"), "z": (1, "", "gh: boom")}
        with mock.patch.object(sc, "run", gh_stub([], replies)):
            value, error = sc._gh_json("x")
            self.assertIsNone(value)
            self.assertTrue(error)
            self.assertEqual(sc._gh_json("y", json_on_failure=True), ([{"a": 1}], None))
            self.assertEqual(sc._gh_json("y"), (None, "gh: failed"))
            self.assertEqual(sc._gh_json("z", json_on_failure=True), (None, "gh: boom"))

    def test_check_names_asks_gh_exactly_and_reads_a_failed_checks_exit(self):
        calls = []
        replies = {self.PR_LIST: (0, json.dumps([{"number": 12}]), ""),
                   self.PR_CHECKS: (8, json.dumps([{"name": "tests", "bucket": "pass"},
                                                   {"name": "lint", "bucket": "fail"}]), "")}
        with mock.patch.object(sc, "run", gh_stub(calls, replies)):
            self.assertEqual(sc.check_names("o/code", "main"), ["tests"])
        self.assertEqual(calls, [("gh", *self.PR_LIST.split()), ("gh", *self.PR_CHECKS.split())])

    def test_a_merged_pr_with_no_checks_has_no_check_names(self):
        # gh 2.96: `gh pr checks` on a PR with no checks exits 1 with this line on stderr.
        none = (1, "", "no checks reported on the 'fix-1' branch")
        replies = {self.PR_LIST: (0, json.dumps([{"number": 12}]), ""), self.PR_CHECKS: none,
                   "api repos/o/code/rulesets": (0, json.dumps([{"id": 7, "name": "gogogo: main"}]), "")}
        with mock.patch.object(sc, "run", gh_stub([], replies)):
            self.assertEqual(sc.check_names("o/code", "main"), [])
        settings = {"tracker": {"code_repo": "o/code"}, "integration": {"strategy": "pr-squash", "base": "main"}}
        out = io.StringIO()
        with mock.patch.object(sc, "run", gh_stub([], replies)), mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr"):
            self.assertEqual(sc.print_ruleset(settings, "main", "main"), 0)
        self.assertEqual(json.loads(out.getvalue()), sc.ruleset_body("main", [], True))

    def test_the_branch_plan_is_design_4s(self):
        plan = sc.branch_plan
        self.assertEqual(plan({"integration": {"strategy": "run-branch-pr", "final_target": "staging"}}, "main"),
                         ([("staging", True, True), ("main", True, False)], None))
        self.assertEqual(plan({"integration": {"strategy": "run-branch-pr"}}, "main"),
                         ([("main", True, False)], "integration.final_target is not set; nothing to check"))
        self.assertEqual(plan({"integration": {"strategy": "merge-script", "base": "dev"}}, "main"),
                         ([("dev", False, True), ("main", True, False)], None))
        self.assertEqual(plan({"integration": {"strategy": "pr-squash", "base": "main"}}, "main"),
                         ([("main", True, True)], None))

    def branches(self, replies, integration=None):
        calls, rep = [], sc.Report()
        settings = {"integration": integration or {"strategy": "pr-squash", "base": "main"}}
        base = {"api repos/o/code/rules/branches/main": (0, "[]", ""),
                "api repos/o/code/rulesets/7": (0, json.dumps({"bypass_actors": []}), ""),
                "api repos/o/code/branches/main/protection": self.NOT_PROTECTED,
                self.PR_LIST: (0, json.dumps([{"number": 12}]), ""),
                self.PR_CHECKS: (0, json.dumps([{"name": "tests", "bucket": "pass"}]), "")}
        with mock.patch.object(sc, "run", gh_stub(calls, dict(base, **replies))):
            sc.check_branches("o/code", settings, "main", rep)
        return calls, rep.rows

    def test_a_ruleset_read_that_is_not_an_object_warns(self):
        rules = {"api repos/o/code/rules/branches/main": (0, json.dumps(self.FULL), "")}
        for body in ('"bypass_actors"', "[]"):
            _, rows = self.branches(dict(rules, **{"api repos/o/code/rulesets/7": (0, body, "")}))
            self.assertEqual([r["level"] for r in rows], ["WARN"])
            self.assertIn("ruleset 7", rows[0]["detail"])
            self.assertNotIn("None", rows[0]["detail"])

    def test_classic_protection_is_read_from_its_endpoint(self):
        calls, rows = self.branches({"api repos/o/code/branches/main/protection": (
            0, json.dumps(self.classic(True, {"contexts": ["tests"]})), "")})
        self.assertIn(("gh", "api", "repos/o/code/branches/main/protection"), calls)
        self.assertEqual([r["level"] for r in rows], ["PASS"])
        _, rows = self.branches({})
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        _, rows = self.branches({"api repos/o/code/branches/main/protection": (1, "", "gh: HTTP 500\nmore")})
        self.assertEqual([r["level"] for r in rows], ["WARN"])
        self.assertIn("(gh: HTTP 500)", rows[0]["detail"])

    def test_no_branch_to_check_warns_once(self):
        rep = sc.Report()
        with mock.patch.object(sc, "run", gh_stub([], {})):
            sc.check_branches("o/code", {"integration": {"strategy": "pr-squash"}}, None, rep)
        self.assertEqual([(r["level"], r["check"]) for r in rep.rows], [("WARN", sc.BRANCH_RULES_CHECK)])

    def test_ci_before_merge_makes_a_missing_check_fail(self):
        rules = {"api repos/o/code/rules/branches/main": (0, json.dumps(self.FULL[:2]), "")}
        _, rows = self.branches(rules, {"strategy": "pr-squash", "base": "main", "ci_before_merge": True})
        self.assertEqual([r["level"] for r in rows], ["FAIL"])
        _, rows = self.branches(rules, {"strategy": "pr-squash", "base": "main"})
        self.assertEqual([r["level"] for r in rows], ["WARN"])

    def test_ruleset_prints_for_a_new_ruleset_beside_another_one(self):
        replies = {self.PR_LIST: (1, "", "gh: HTTP 502"),
                   "api repos/o/code/rulesets": (0, json.dumps([{"id": 3, "name": "other"}]), "")}
        settings = {"tracker": {"code_repo": "o/code"}, "integration": {"strategy": "pr-squash", "base": "main"}}
        out = io.StringIO()
        with mock.patch.object(sc, "run", gh_stub([], replies)), mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr"):
            self.assertEqual(sc.print_ruleset(settings, "main", "main"), 0)
        self.assertEqual(out.getvalue(), json.dumps(sc.ruleset_body("main", [], True), indent=2) + "\n")

    def test_check_tracker_takes_the_default_branch_from_the_repo_read(self):
        calls = []
        replies = {"api repos/o/code": (0, json.dumps({"delete_branch_on_merge": True, "default_branch": "trunk"}), "")}
        settings = {"tracker": {"issues_repo": "o/issues", "code_repo": "o/code"},
                    "integration": {"strategy": "pr-squash"}}
        with mock.patch.object(sc, "run", gh_stub(calls, replies)):
            sc.check_tracker(Path("."), settings, sc.Report())
        self.assertIn(("gh", "api", "repos/o/code/rules/branches/trunk"), calls)

    # The --branch-rules and --ruleset flags (Designs 3 and 5)
    PROFILE = ('+++\n[tracker]\nissues_repo = "o/issues"\ncode_repo = "o/code"\n'
               '[integration]\nstrategy = "pr-squash"\nci_before_merge = true\n+++\n')

    def main(self, argv, rules, profile=PROFILE):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        path = folder / "dev-process.md"
        if profile is not None:
            path.write_text(profile, encoding="utf-8")
        calls, out, err = [], io.StringIO(), io.StringIO()
        replies = {"api repos/o/code": (0, json.dumps({"default_branch": "main"}), ""),
                   "api repos/o/code/rules/branches/main": (0, json.dumps(rules), ""),
                   "api repos/o/code/rulesets/7": (0, json.dumps({"bypass_actors": []}), ""),
                   "api repos/o/code/branches/main/protection": self.NOT_PROTECTED,
                   self.PR_LIST: (0, json.dumps([{"number": 12}]), ""),
                   self.PR_CHECKS: (0, json.dumps([{"name": "tests", "bucket": "pass"}]), "")}
        with mock.patch.object(sc.profile_check, "find_profile", return_value=path), \
                mock.patch.object(sc, "run", gh_stub(calls, replies)), mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr", err):
            code = sc.main(argv)
        return code, out.getvalue(), calls

    def test_branch_rules_flag_prints_only_the_branch_rows_and_exits_by_fail(self):
        code, out, calls = self.main(["--branch-rules", "--json"], self.FULL)
        rows = json.loads(out)
        self.assertEqual((code, [(r["level"], r["check"]) for r in rows]), (0, [("PASS", self.CHECK)]))
        self.assertEqual(out, json.dumps(rows, indent=2) + "\n")
        self.assertIn(("gh", "api", "repos/o/code"), calls)
        code, out, _ = self.main(["--branch-rules", "--json"], [])
        self.assertEqual((code, [r["level"] for r in json.loads(out)]), (1, ["FAIL"]))

    def test_ruleset_flag_prints_the_body_from_the_profile(self):
        code, out, _ = self.main(["--ruleset", "main"], [])
        self.assertEqual((code, json.loads(out)), (0, sc.ruleset_body("main", ["tests"], True)))

    def test_flags_exit_2_without_a_profile_or_a_code_repo(self):
        self.assertEqual(self.main(["--branch-rules"], [], profile=None)[0], 2)
        no_repo = '+++\n[tracker]\nissues_repo = "o/issues"\n+++\n'
        self.assertEqual(self.main(["--branch-rules"], [], profile=no_repo)[0], 2)
        self.assertEqual(self.main(["--ruleset", "main"], [], profile=no_repo)[0], 2)

if __name__ == "__main__":
    unittest.main()
