import json
import subprocess
import sys
import tempfile
import unittest
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
        self.assertEqual([r["level"] for r in on.rows], ["PASS"])

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
                         ["tracker: cards without a column", "tracker: issues missing from the board"])

    def test_drafts_and_recovered_cards_are_not_double_reported(self):
        rep = sc.Report()
        cards = [{"number": None, "status": None, "state": None},
                 {"number": 9, "status": None, "state": "OPEN"}]
        sc.check_board_hygiene(cards, [{"number": 9}], ["Backlog"], {"backlog"}, rep)
        self.assertEqual([r["check"] for r in rep.rows], ["tracker: issues missing from the board"])

    def test_new_column_matches_with_or_without_the_emoji_selector(self):
        rep = sc.Report()
        sc.check_board_hygiene([], [], ["\u26a1\ufe0f New", "\u26a1 New"], {"\u26a1 new"}, rep)
        self.assertEqual(rep.rows, [])

    def test_clean_board_is_quiet(self):
        rep = sc.Report()
        sc.check_board_hygiene([{"number": 1, "status": "Backlog", "state": "OPEN"}], [], ["Backlog"],
                               {"backlog"}, rep)
        self.assertEqual(rep.rows, [])

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


if __name__ == "__main__":
    unittest.main()
