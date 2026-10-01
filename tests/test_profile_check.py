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
columns = { in_progress = "In progress", back_to_queue = "New" }

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

[[stages]]
code_is = "merged to main"
environment = "dev"
column = "In Dev"

[[stages]]
code_is = "deployed"
environment = "production"
column = "In Production"

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
+++

# Process profile

## Recon traps
Dead views look live.

## Lane constraints
The test host must be dev.

## superpowers boundary
Tracker work stays in the tracker.
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

    def test_doc_example_is_valid_toml(self):
        doc = (PLUGIN / "references" / "profile-schema.md").read_text()
        for block in doc.split("```toml\n")[1:]:
            tomllib.loads(block.split("```")[0])


if __name__ == "__main__":
    unittest.main()
