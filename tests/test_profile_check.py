import copy
import io
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
sys.path.insert(0, str(PLUGIN / "scripts"))

import profile_check as pc  # noqa: E402

COMPLETE = """+++
profile = 1
observability = "sentry"
notify = "none"

[tracker]
kind = "github-project"
issues_repo = "acme/issues"
code_repo = "acme/code"
public = true
ready_marker = "dev ready"
tool = "python3 tools/board.py"
project_owner = "acme"
project_number = 2
queue = "Dev Priority"
columns = { in_progress = "In progress", needs_human = "Human!Help!" }

[hard_stops]
source = "CLAUDE.md#hard-stops"
form = "categories"
items = ["schema", "auth"]

[[hard_stops.two_licence]]
change = "migration"
apply = "migrate on the dev DB"

[design]
placement_rule = "CLAUDE.md#layers"

[technology]
register = "docs/technology-decisions.md"

[roadmap]
file = "docs/roadmap.md"

[release]
major = 1

[[lanes]]
name = "automated"
run = "make test"
ci = true

[[lanes]]
name = "browser"
env = "https://dev.example.org"

[[environments]]
name = "dev"
roles = ["pre-merge", "pre-production"]
url = "https://dev.example.org"

[[environments]]
name = "production"
roles = ["production"]
url = "https://app.example.org"
writes = "only through the app's own UI, inside the sandbox"

[[stages]]
code_is = "merged to main"
environment = "dev"
column = "In Dev"

[[stages]]
code_is = "deployed"
environment = "production"
column = "In Production"
tag = "deploy-*"

[verify]
agent = ["dev"]
human = "production"
rungs = ["seen-failing", "full-suite", "browser"]

[state]
read = "make shell"
forbidden = ["production-db"]

[report]
staleness_source = "commit hash in the report"

[gates]
always = ["make lint"]

[integration]
strategy = "merge-script"
base = "main"
command = "./merge.sh"
mode_check = "./require_bypass.sh"
ci_before_merge = false

[handback]
reporter = "trailer"

[preflight]
extra = ["check the dev db"]

[stop]
extra = ["a migrate fails"]

[auto_test]
pass_column = "Done"
fail_column = "New"
fail_label = "test fail"
human_label = "test needs human"
pass_closes = true
+++

# Process profile

## Recon traps
Dead views look live.

## Lane constraints
The test host must be dev.

## superpowers boundary
Tracker work stays in the tracker.

## Test data
### Running build
The settings page prints the deploy tag.
### Finding the change
A trailer in the squash commit.
### Sandbox and fixtures
None.
### Optional lanes
None.
### Extra step rules
None.
### Never call
None.
"""


def parse(text=COMPLETE):
    return pc.split_profile(text)


def drop(settings, path):
    out = copy.deepcopy(settings)
    node = out
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[part]
    del node[parts[-1]]
    return out


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = pc.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CompleteProfile(unittest.TestCase):
    def test_passes_for_every_skill(self):
        settings, sections = parse()
        for skill in (None, *pc.SKILLS):
            errors, warnings = pc.check(settings, sections, skill)
            self.assertEqual(errors, [], skill)
            self.assertEqual(warnings, [], skill)

    def test_fixture_sets_every_known_setting(self):
        # Otherwise "removing a field fails" below would skip fields silently.
        settings, _ = parse()
        for path in pc.FIELDS:
            _, present = pc._lookup(settings, path)
            if path == "gates.when" or path == "integration.final_target":
                continue
            self.assertTrue(present, path)


class MissingFields(unittest.TestCase):
    def test_each_required_field_is_named_when_removed(self):
        settings, sections = parse()
        for path, (_, required_by, _) in pc.FIELDS.items():
            if not required_by:
                continue
            errors, _ = pc.check(drop(settings, path), sections)
            self.assertTrue(any(e.startswith(f"{path}: missing") for e in errors),
                            f"{path} removed but not named in {errors}")

    def test_optional_field_removed_is_not_an_error(self):
        settings, sections = parse()
        errors, _ = pc.check(drop(settings, "observability"), sections)
        self.assertEqual(errors, [])

    def test_no_roadmap_file_is_not_an_error_for_any_skill(self):
        # roadmap.file is optional: a repo without a roadmap must still pass the
        # all-skills check that wrap-up and setup run.
        settings, sections = parse()
        self.assertEqual(pc.check(drop(settings, "roadmap.file"), sections)[0], [])

    def test_roadmap_needs_the_tracker_tool(self):
        settings, sections = parse()
        errors, _ = pc.check(drop(settings, "tracker.tool"), sections, pc.ROADMAP)
        self.assertTrue(any(e.startswith("tracker.tool: missing") for e in errors), errors)

    def test_for_skill_ignores_other_skills_fields(self):
        settings, sections = parse()
        trimmed = drop(settings, "integration.strategy")
        self.assertEqual(pc.check(trimmed, sections, pc.SPEC)[0], [])
        self.assertTrue(pc.check(trimmed, sections, pc.LOOP)[0])

    def test_each_required_section_is_named_when_removed(self):
        settings, sections = parse()
        for title in pc.SECTIONS:
            rest = {k: v for k, v in sections.items() if k != title}
            errors, _ = pc.check(settings, rest)
            self.assertIn(f"section '## {title}': missing", errors)

    def test_empty_section_is_an_error(self):
        settings, sections = parse()
        errors, _ = pc.check(settings, {**sections, "Recon traps": ""})
        self.assertIn("section '## Recon traps': empty", errors)


class Columns(unittest.TestCase):
    """tracker.columns: the keys dev and auto-dev move cards to (gogogo#26)."""

    def test_needs_human_is_required_by_dev_and_auto_dev_only(self):
        settings, sections = parse()
        dropped = drop(settings, "tracker.columns.needs_human")
        for skill in (pc.ONE, pc.LOOP):
            errors, _ = pc.check(dropped, sections, skill)
            self.assertTrue(any(e.startswith("tracker.columns.needs_human: missing") for e in errors), skill)
        for skill in (pc.SPEC, pc.TECH, pc.ROADMAP):
            errors, _ = pc.check(dropped, sections, skill)
            self.assertEqual(errors, [], skill)

    def test_back_to_queue_warns_but_passes(self):
        settings, sections = parse()
        settings["tracker"]["columns"]["back_to_queue"] = "Dev Ready"
        errors, warnings = pc.check(settings, sections)
        self.assertEqual(errors, [])
        self.assertTrue(any(w.startswith("tracker.columns.back_to_queue: unknown setting") for w in warnings),
                        warnings)

    def test_columns_must_be_a_table_of_names(self):
        settings, sections = parse()
        settings["tracker"]["columns"] = "In progress"
        errors, _ = pc.check(settings, sections, pc.ROADMAP)
        self.assertTrue(any(e.startswith("tracker.columns: expected a table") for e in errors), errors)
        settings, sections = parse()
        settings["tracker"]["columns"]["in_review"] = 5
        errors, _ = pc.check(settings, sections)
        self.assertTrue(any(e.startswith("tracker.columns.in_review: expected a column name") for e in errors),
                        errors)

    def test_a_bad_required_column_is_one_error(self):
        settings, sections = parse()
        settings["tracker"]["columns"]["in_progress"] = 5
        errors, _ = pc.check(settings, sections)
        self.assertEqual([e for e in errors if e.startswith("tracker.columns.in_progress")],
                         ["tracker.columns.in_progress: expected str, found int"])
        settings["tracker"]["columns"] = "In progress"
        _, warnings = pc.check(settings, sections, pc.ROADMAP)
        self.assertEqual([w for w in warnings if w.startswith("tracker.columns")], [])

    def test_a_columns_value_that_is_not_a_table_is_one_error(self):
        settings, sections = parse()
        settings["tracker"]["columns"] = "In progress"
        errors, _ = pc.check(settings, sections, pc.ONE)
        self.assertEqual([e for e in errors if e.startswith("tracker.columns")],
                         ["tracker.columns: expected a table of role = column name, found str"])

    def test_a_blank_required_column_name_is_an_error(self):
        settings, sections = parse()
        settings["tracker"]["columns"]["needs_human"] = "  "
        errors, _ = pc.check(settings, sections, pc.ONE)
        self.assertEqual([e for e in errors if e.startswith("tracker.columns")],
                         ["tracker.columns.needs_human: expected a column name, found '  '"])

    def test_an_empty_column_name_is_an_error_for_every_skill(self):
        settings, sections = parse()
        settings["tracker"]["columns"]["needs_human"] = ""
        for skill in (pc.ONE, pc.ROADMAP):
            errors, _ = pc.check(settings, sections, skill)
            self.assertEqual(len([e for e in errors if e.startswith("tracker.columns.needs_human")]), 1,
                             (skill, errors))

    def test_a_blank_retired_column_only_warns(self):
        settings, sections = parse()
        settings["tracker"]["columns"]["back_to_queue"] = ""
        errors, warnings = pc.check(settings, sections)
        self.assertEqual(errors, [])
        self.assertTrue(any(w.startswith("tracker.columns.back_to_queue") for w in warnings), warnings)

    def test_another_column_role_is_allowed(self):
        settings, sections = parse()
        settings["tracker"]["columns"]["in_review"] = "In review"
        self.assertEqual(pc.check(settings, sections), ([], []))


class WrongValues(unittest.TestCase):
    def test_wrong_type_is_named(self):
        settings, sections = parse()
        settings["tracker"]["public"] = "yes"
        errors, _ = pc.check(settings, sections)
        self.assertIn("tracker.public: expected bool, found str", errors)

    def test_bool_is_not_accepted_as_int(self):
        settings, sections = parse()
        settings["profile"] = True
        errors, _ = pc.check(settings, sections)
        self.assertIn("profile: expected int, found bool", errors)

    def test_release_major_must_be_a_whole_number_of_1_or_more(self):
        settings, sections = parse()
        settings["release"] = {"major": "1"}
        self.assertIn("release.major: expected int, found str", pc.check(settings, sections)[0])
        settings["release"] = {"major": 0}
        self.assertIn("release.major: must be 1 or more", pc.check(settings, sections)[0])
        settings["release"] = {"major": 1}
        self.assertEqual(pc.check(settings, sections), ([], []))

    def test_no_release_table_is_neither_error_nor_warning(self):
        settings, sections = parse()
        settings.pop("release", None)
        self.assertEqual(pc.check(settings, sections), ([], []))

    def test_value_outside_enum_is_named(self):
        settings, sections = parse()
        settings["integration"]["strategy"] = "yolo"
        errors, _ = pc.check(settings, sections)
        self.assertTrue(any(e.startswith("integration.strategy: 'yolo' is not one of") for e in errors))

    def test_unsupported_version(self):
        settings, sections = parse()
        settings["profile"] = 2
        errors, _ = pc.check(settings, sections)
        self.assertTrue(any(e.startswith("profile: version 2") for e in errors))

    def test_empty_required_value(self):
        settings, sections = parse()
        settings["hard_stops"]["items"] = []
        errors, _ = pc.check(settings, sections)
        self.assertTrue(any(e.startswith("hard_stops.items: empty") for e in errors))

    def test_lane_needs_name_and_run_or_env(self):
        settings, sections = parse()
        settings["lanes"] = [{"run": "x"}, {"name": "browser"}]
        errors, _ = pc.check(settings, sections)
        self.assertIn("lanes[0]: each lane needs a name", errors)
        self.assertTrue(any(e.startswith("lanes[1] (browser): needs run") for e in errors))

    def test_unknown_setting_warns_but_passes(self):
        settings, sections = parse()
        settings["tracker"]["redy_marker"] = "typo"
        errors, warnings = pc.check(settings, sections)
        self.assertEqual(errors, [])
        self.assertTrue(any(w.startswith("tracker.redy_marker: unknown setting") for w in warnings))


class Environments(unittest.TestCase):
    def check(self, mutate):
        settings, sections = parse()
        mutate(settings)
        return pc.check(settings, sections)[0]

    def test_unknown_role(self):
        errors = self.check(lambda s: s["environments"][0].update(roles=["staging"]))
        self.assertTrue(any("'staging' is not one of pre-merge, pre-production, production" in e for e in errors))

    def test_environment_needs_roles(self):
        errors = self.check(lambda s: s["environments"][0].pop("roles"))
        self.assertTrue(any(e.startswith("environments[0] (dev): needs roles") for e in errors))

    def test_duplicate_name(self):
        errors = self.check(lambda s: s["environments"][1].update(name="dev"))
        self.assertIn("environments[1] (dev): the name is used twice", errors)

    def test_production_and_pre_merge_are_required_roles(self):
        errors = self.check(lambda s: s["environments"].pop(1))
        self.assertIn("environments: none has the role production", errors)
        errors = self.check(lambda s: s["environments"][0].update(roles=["pre-production"]))
        self.assertIn("environments: none has the role pre-merge", errors)

    def test_no_pre_production_environment_is_valid(self):
        def mutate(s):
            s["environments"][0]["roles"] = ["pre-merge"]
        self.assertEqual(self.check(mutate), [])

    def test_stage_must_name_a_known_environment(self):
        errors = self.check(lambda s: s["stages"][0].update(environment="staging"))
        self.assertIn("stages[0] (In Dev): environment 'staging' is not in environments", errors)

    def test_stage_without_an_environment_is_valid(self):
        self.assertEqual(self.check(lambda s: s["stages"][0].pop("environment")), [])

    def test_stage_needs_code_is_and_column(self):
        errors = self.check(lambda s: s["stages"][0].pop("column"))
        self.assertIn("stages[0]: each stage needs code_is and column", errors)

    def test_verify_names_must_be_environments(self):
        errors = self.check(lambda s: s["verify"].update(human="staging", agent=["dev", "preview"]))
        self.assertIn("verify.human: 'staging' is not in environments", errors)
        self.assertIn("verify.agent: 'preview' is not in environments", errors)

    def test_each_bad_stage_tag_is_one_error(self):
        def third_stage(s):
            s["stages"].append({"code_is": "again", "environment": "production",
                                "column": "Again", "tag": "deploy-*"})
        cases = {
            "first stage": lambda s: s["stages"][0].update(tag="dev-*"),
            "empty": lambda s: s["stages"][1].update(tag=""),
            "not a string": lambda s: s["stages"][1].update(tag=3),
            "no environment": lambda s: s["stages"][1].pop("environment"),
            "a slash": lambda s: s["stages"][1].update(tag="deploy/*"),
            "on two stages": third_stage,
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                errors = [e for e in self.check(mutate) if e.startswith("stages[")]
                self.assertEqual(len(errors), 1, errors)
        self.assertIn("stages[0] (In Dev): tag is not allowed on the first stage (a merge puts a card "
                      "there, not a tag)", self.check(cases["first stage"]))

    def test_unknown_stage_key_warns(self):
        settings, sections = parse()
        settings["stages"][1]["tags"] = "deploy-*"
        errors, warnings = pc.check(settings, sections)
        self.assertEqual(errors, [])
        self.assertEqual([w for w in warnings if w.startswith("stages[")],
                         ["stages[1] (In Production): unknown key 'tags' (typo, or not in this profile version)"])

    def test_trailer_reporter_without_a_tagged_stage_warns(self):
        settings, sections = parse()
        del settings["stages"][1]["tag"]
        _, warnings = pc.check(settings, sections)
        self.assertTrue(any(w.startswith("handback.reporter: 'trailer', but no stage has a tag") for w in warnings))
        settings["handback"]["reporter"] = "none"
        self.assertEqual(pc.check(settings, sections), ([], []))

    def test_this_repos_own_profile_is_clean_for_every_skill(self):
        settings, sections = pc.split_profile((ROOT / ".agents" / "dev-process.md").read_text(encoding="utf-8"))
        for skill in (None, *pc.SKILLS):
            if skill == pc.TEST and "auto_test" not in settings:
                continue  # auto-test is opt-in; this repo has not opted in
            self.assertEqual(pc.check(settings, sections, skill), ([], []), skill)


AUTO_TEST_FIELDS = [p for p in pc.FIELDS if p.startswith("auto_test.")]
OTHER_SKILLS = (pc.SPEC, pc.ONE, pc.LOOP, pc.TECH)


class AutoTest(unittest.TestCase):
    """What /gogogo:auto-test needs, and that none of it leaks into the other skills."""

    def test_each_auto_test_setting_is_named_for_auto_test_only(self):
        settings, sections = parse()
        self.assertEqual(len(AUTO_TEST_FIELDS), 5, AUTO_TEST_FIELDS)
        for path in AUTO_TEST_FIELDS:
            trimmed = drop(settings, path)
            errors, _ = pc.check(trimmed, sections, pc.TEST)
            self.assertTrue(errors and errors[0].startswith(f"{path}: missing"), (path, errors))
            for skill in OTHER_SKILLS:
                self.assertEqual(pc.check(trimmed, sections, skill)[0], [], (path, skill))

    def test_tracker_tool_is_required_by_auto_test(self):
        settings, sections = parse()
        trimmed = drop(settings, "tracker.tool")
        for skill in (pc.TEST, pc.ONE, pc.LOOP):
            errors, _ = pc.check(trimmed, sections, skill)
            self.assertTrue(any(e.startswith("tracker.tool: missing") for e in errors), skill)
        self.assertEqual(pc.check(trimmed, sections, pc.SPEC)[0], [])

    def test_pass_closes_must_be_a_bool(self):
        settings, sections = parse()
        settings["auto_test"]["pass_closes"] = "yes"
        errors, _ = pc.check(settings, sections, pc.TEST)
        self.assertIn("auto_test.pass_closes: expected bool, found str", errors)

    def test_test_data_section_and_its_headings(self):
        settings, sections = parse()
        rest = {k: v for k, v in sections.items() if k != "Test data"}
        never = sections["Test data"].replace("### Never call\nNone.", "")
        for changed, error in (
            (rest, "section '## Test data': missing"),
            ({**sections, "Test data": ""}, "section '## Test data': empty"),
            ({**sections, "Test data": never}, "section '## Test data': no '### Never call'"),
        ):
            self.assertIn(error, pc.check(settings, changed, pc.TEST)[0])
            for skill in OTHER_SKILLS:
                self.assertEqual(pc.check(settings, changed, skill)[0], [], (error, skill))

    def test_the_human_environment_and_its_one_stage(self):
        def errors_for(mutate):
            settings, sections = parse()
            mutate(settings)
            for skill in OTHER_SKILLS:
                self.assertEqual(pc.check(settings, sections, skill)[0], [], skill)
            return pc.check(settings, sections, pc.TEST)[0]

        self.assertIn("verify.human: environment 'production' has no url",
                      errors_for(lambda s: s["environments"][1].pop("url")))
        self.assertIn("verify.human: environment 'production' has no writes",
                      errors_for(lambda s: s["environments"][1].pop("writes")))
        self.assertIn("stages: no stage has environment 'production', so there is no column to test",
                      errors_for(lambda s: s["stages"].pop(1)))
        self.assertIn("stages: 2 stages have environment 'production'; auto-test needs exactly one",
                      errors_for(lambda s: s["stages"].append(
                          {"code_is": "promoted", "environment": "production", "column": "Live"})))

    def test_no_skill_checks_auto_test_only_when_the_profile_has_auto_test(self):
        settings, sections = parse()
        bare = drop(settings, "auto_test")
        rest = {k: v for k, v in sections.items() if k != "Test data"}
        self.assertEqual(pc.check(bare, rest), ([], []))
        text = COMPLETE.split("[auto_test]")[0].rstrip() + "\n+++\n" + COMPLETE.split("+++", 2)[2]
        text = text.split("## Test data")[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dev-process.md"
            path.write_text(text)
            code, _, err = run_main("--path", str(path))
        self.assertEqual(code, pc.EXIT_OK, err)
        errors, _ = pc.check(drop(settings, "auto_test.pass_column"), sections)
        self.assertTrue(any(e.startswith("auto_test.pass_column: missing") for e in errors), errors)


class FrontMatter(unittest.TestCase):
    def test_no_opening_fence(self):
        with self.assertRaises(pc.ProfileError):
            pc.split_profile("# just markdown\n")

    def test_no_closing_fence(self):
        with self.assertRaises(pc.ProfileError):
            pc.split_profile("+++\nprofile = 1\n")

    def test_bad_toml(self):
        with self.assertRaises(pc.ProfileError):
            pc.split_profile("+++\nprofile = = 1\n+++\n")

    def test_sections_are_split_on_h2_only(self):
        _, sections = pc.split_profile("+++\nprofile = 1\n+++\n## A\ntext\n### sub\nmore\n## B\nb\n")
        self.assertEqual(sections, {"A": "text\n### sub\nmore", "B": "b"})


class ExitCodes(unittest.TestCase):
    def test_missing_file_is_2(self):
        code, _, err = run_main("--path", "/nonexistent/dev-process.md")
        self.assertEqual(code, pc.EXIT_MISSING)
        self.assertIn("no file at", err)

    def test_incomplete_is_3_and_complete_is_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.md"
            good.write_text(COMPLETE)
            bad = Path(tmp) / "bad.md"
            bad.write_text(COMPLETE.replace('ready_marker = "dev ready"\n', ""))
            self.assertEqual(run_main("--path", str(good))[0], pc.EXIT_OK)
            code, _, err = run_main("--path", str(bad), "--for", pc.SPEC)
            self.assertEqual(code, pc.EXIT_INVALID)
            self.assertIn("error: tracker.ready_marker: missing", err)

    def test_unreadable_is_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.md"
            bad.write_text("no front matter")
            self.assertEqual(run_main("--path", str(bad))[0], pc.EXIT_INVALID)

    def test_show_prints_settings_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.md"
            good.write_text(COMPLETE)
            code, out, _ = run_main("--path", str(good), "--show")
            self.assertEqual(code, pc.EXIT_OK)
            self.assertIn('"issues_repo": "acme/issues"', out)


class FindProfile(unittest.TestCase):
    def test_nearest_profile_above_wins_and_search_stops_at_the_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "outside.agents").mkdir()
            repo = root / "repo"
            app = repo / "apps" / "web" / "src"
            app.mkdir(parents=True)
            (repo / ".git").mkdir()
            # No profile anywhere: falls back to the default relative path.
            self.assertEqual(pc.find_profile(app), Path(pc.DEFAULT_PATH))
            # A profile above the repo root is not this repo's.
            (root / ".agents").mkdir()
            (root / ".agents" / "dev-process.md").write_text(COMPLETE)
            self.assertEqual(pc.find_profile(app), Path(pc.DEFAULT_PATH))
            # The repo's own profile is found from a subfolder.
            (repo / ".agents").mkdir()
            (repo / ".agents" / "dev-process.md").write_text(COMPLETE)
            self.assertEqual(pc.find_profile(app), repo / ".agents" / "dev-process.md")
            # An app's own profile is closer, so it wins.
            (repo / "apps" / "web" / ".agents").mkdir()
            (repo / "apps" / "web" / ".agents" / "dev-process.md").write_text(COMPLETE)
            self.assertEqual(pc.find_profile(app), repo / "apps" / "web" / ".agents" / "dev-process.md")


class SchemaDoc(unittest.TestCase):
    """references/profile-schema.md documents exactly the settings the checker knows."""

    def test_doc_and_checker_list_the_same_settings(self):
        doc = (PLUGIN / "references" / "profile-schema.md").read_text()
        table = doc.split("| Setting | Type | Required by | Meaning |")[1].split("\n### ")[0]
        documented = {line.split("`")[1] for line in table.splitlines() if line.startswith("| `")}
        self.assertEqual(documented, set(pc.FIELDS))

    def test_doc_and_checker_agree_on_who_requires_each_setting(self):
        doc = (PLUGIN / "references" / "profile-schema.md").read_text()
        table = doc.split("| Setting | Type | Required by | Meaning |")[1].split("\n### ")[0]
        for line in table.splitlines():
            if not line.startswith("| `"):
                continue
            cells = [c.strip() for c in line.split("|")]
            path, required = cells[1].strip("`"), cells[3]
            documented = (set(pc.SKILLS) if required == "all" else set() if required == "optional"
                          else set(required.replace("`", "").replace(" ", "").split(",")))
            self.assertEqual(documented, set(pc.FIELDS[path][1]), path)

    def test_doc_example_is_valid_toml(self):
        doc = (PLUGIN / "references" / "profile-schema.md").read_text()
        for block in doc.split("```toml\n")[1:]:
            tomllib.loads(block.split("```")[0])


if __name__ == "__main__":
    unittest.main()
