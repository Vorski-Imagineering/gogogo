#!/usr/bin/env python3
"""Check a repo's process profile (.agents/dev-process.md).

    profile_check.py [--for SKILL] [--path FILE] [--show]

The profile is a markdown file whose first block is TOML between two `+++`
lines (the settings), followed by `## ` sections (project knowledge the skills
point at). A skill runs this before doing anything else, so a missing setting
is a named error instead of a guess.

With no --for it checks what every skill needs, except that `auto-test` is
checked only when the profile has an [auto_test] table: a repo that never
adopted auto-test still passes.

Exit codes: 0 ok (warnings allowed), 2 no profile file, 3 profile unreadable or
incomplete. Problems go to stderr, one per line, each naming the field.

Standard library only (tomllib needs Python 3.11+).
"""
import argparse
import copy
import json
import sys
import tomllib
from pathlib import Path

DEFAULT_PATH = ".agents/dev-process.md"
PROFILE_VERSION = 1
# The versions this checker reads. A change with no safe default bumps
# PROFILE_VERSION and keeps the previous version here, with warnings, until the
# bump after it (references/profile-schema.md § Versions and defaults).
ACCEPTED_VERSIONS = {1}

EXIT_OK, EXIT_MISSING, EXIT_INVALID = 0, 2, 3

SPEC = "spec"
ONE = "dev"
LOOP = "auto-dev"
TEST = "auto-test"
TECH = "tech-eval"
ROADMAP = "roadmap"
STATUS = "status"
IDEA = "idea"
SKILLS = (SPEC, ONE, LOOP, TEST, TECH, ROADMAP, STATUS, IDEA)

# Dotted path -> (type, skills that require it, one-line meaning).
# `references/profile-schema.md` documents the same paths; a test keeps the two
# in step. Paths required by no skill are known-but-optional.
FIELDS = {
    "profile": (int, SKILLS, "Profile format version."),
    "tracker.kind": (str, SKILLS, "github-project | todo-file."),
    "tracker.issues_repo": (str, SKILLS, "owner/repo that holds the issues."),
    "tracker.code_repo": (str, SKILLS, "owner/repo that holds the code."),
    "tracker.public": (bool, SKILLS, "True if the tracker is readable by the public."),
    "tracker.ready_marker": (str, (SPEC, LOOP), "Label that marks an issue as specced and pickable."),
    "tracker.tool": (str, (ONE, LOOP, TEST, ROADMAP), "'shared' for the plugin's tracker.py, or a command for the repo's own tool meeting references/tracker-contract.md."),
    "tracker.project_owner": (str, (), "Owner of the GitHub project board."),
    "tracker.project_number": (int, (), "Number of the GitHub project board."),
    "tracker.queue": (str, (LOOP,), "Board column the loop works."),
    "tracker.columns.in_progress": (str, (ONE, LOOP), "Column of an issue being worked now."),
    "tracker.columns.needs_human": (str, (), "Column of an issue stopped for a person: an unreviewed fix, "
                                    "a decision or Hard Stop found mid-change, or verification that gave up. "
                                    "Optional; absent means the in_progress column."),
    "environments": (list, SKILLS, "Where code runs: name, roles, and url/serves/reached_by/data/writes."),
    "stages": (list, (ONE, LOOP, TEST), "The path a change takes after it merges: code_is, column, environment."),
    "hard_stops.source": (str, SKILLS, "Where the repo's Hard Stop rules live (file#anchor)."),
    "hard_stops.form": (str, (SPEC, ONE, LOOP), "categories | questions."),
    "hard_stops.items": (list, (SPEC, ONE, LOOP), "Names of the categories or questions, in order."),
    "hard_stops.two_licence": (list, (), "Changes that need a design approval and an apply approval."),
    "design.placement_rule": (str, (), "Where the repo says which layer or folder new code belongs in."),
    "technology.register": (str, (), "Path of the technology decisions register, from the repo root."),
    "roadmap.file": (str, (), "Path of the roadmap document, from the folder holding .agents/; it may sit in another git repo checked out inside this one."),
    "release.major": (int, (), "Hand-set major version. A production release is tagged deploy-<build> and versioned <major>.0.<build>; see references/versioning.md."),
    "lanes": (list, (SPEC, ONE, LOOP), "Test lanes: name, plus run/focused/mutate/tests/env/ci."),
    "verify.agent": (list, (ONE, LOOP), "Environments where the implementing agent checks its work."),
    "verify.human": (str, (SPEC, TEST), "Environment where a person confirms a fix."),
    "verify.rungs": (list, (ONE, LOOP), "Ordered verification steps."),
    "state.read": (str, (), "How to read a safe copy of real state."),
    "state.forbidden": (list, (ONE, LOOP), "What must never be written or run."),
    "report.staleness_source": (str, (), "How to tell which build a report came from."),
    "observability": (str, (), "Error tracker to consult before reading code."),
    "gates.always": (list, (LOOP,), "Checks run before every merge."),
    "gates.when": (dict, (), "Path pattern -> extra checks."),
    "integration.strategy": (str, (LOOP,), "merge-script | run-branch-pr | pr-squash."),
    "integration.base": (str, (LOOP,), "Branch issue branches are cut from."),
    "integration.command": (str, (), "Merge command, for merge-script."),
    "integration.final_target": (str, (), "Branch the run's PR targets, for run-branch-pr."),
    "integration.mode_check": (str, (), "Command that proves unattended mode is on."),
    "integration.ci_before_merge": (bool, (LOOP,), "True if a PR with no CI checks at all must not merge. Checks that exist are always awaited."),
    "integration.workspace": (str, (), "checkout | worktree. Optional; absent means checkout. Where dev and "
                              "auto-dev do an issue's work: in the checkout, or in a git worktree "
                              "../<repo>-wt-<n> beside it. Worktree support is in development."),
    "handback.reporter": (str, (), "trailer | assign | none. Optional; absent means none. trailer: each merge "
                          "writes a Ships-issue trailer naming the reporter, and stage sync assigns them when "
                          "the card enters a stage with a tag."),
    "preflight.extra": (list, (), "Extra checks before a run."),
    "stop.extra": (list, (), "Extra conditions that stop a whole run."),
    "notify": (str, (), "none / telegram. Optional; absent means telegram when this machine has credentials, "
               "else off. Credentials come from TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment, "
               "the repo's git-ignored .claude/gogogo/notify.env, or the per-user notify.env, never the "
               "profile."),
    "review.coverage": (str, (), "precise / broad / exhaustive. Optional; absent means broad. How wide a net "
                        "the first review round casts; correction rounds are always precise."),
    "independence": (str, (), "junior-dev / tech-lead / product-owner. Optional; absent means junior-dev. Which "
                     "decisions Claude asks about and which it takes itself; see docs/independence-mode.md."),
    "auto_test.pass_column": (str, (TEST,), "Column a card moves to on PASS."),
    "auto_test.fail_column": (str, (TEST,), "Column a card moves to on FAIL."),
    "auto_test.fail_label": (str, (TEST,), "Label added on FAIL."),
    "auto_test.human_label": (str, (TEST,), "Label added on NEEDS HUMAN."),
    "auto_test.pass_closes": (bool, (TEST,), "True if PASS closes the issue."),
}

# Body sections (## headings) a skill reads, by skill.
SECTIONS = {
    "Recon traps": (SPEC, ONE),
    "Lane constraints": (SPEC, ONE),
    "superpowers boundary": SKILLS,
    "Test data": (TEST,),
}

# The `### ` headings `## Test data` must have; each may say "None".
TEST_DATA_HEADINGS = ("Running build", "Finding the change", "Sandbox and fixtures",
                      "Optional lanes", "Extra step rules", "Never call")

ROLES = ("pre-merge", "pre-production", "production")

# Settings a profile may still carry that no skill reads any more: each warns.
# Other keys of `tracker.columns` are column roles a repo may add for its own
# tool (references/tracker-contract.md), so they do not warn.
RETIRED = {"tracker.columns.back_to_queue": "retired: no skill reads it since gogogo#26"}


def _in_progress(settings):
    value, present = _lookup(settings, "tracker.columns.in_progress")
    return value if present and isinstance(value, str) and value.strip() else None


# Settings added to the format after repos adopted it: path -> (resolver, issue).
# A resolver returns the value used when the profile lacks the path, or None
# when it cannot tell (the path then stays absent). Each use warns, naming the
# issue, and effective() applies them, so every reader sees the same value.
# A setting whose absence a skill acts on has no entry, since filling it would
# hide that: integration.workspace (absent plus worktree prose stops dev).
DEFAULTS = {
    "tracker.columns.needs_human": (_in_progress, "gogogo#32"),
    "handback.reporter": (lambda settings: "none", "gogogo#9"),
}

# What profile version 1 requires, pinned: a test fails when FIELDS drifts from
# it. A new required setting gets a DEFAULTS entry instead, or a version bump
# with its own REQUIRED_V<n>.
REQUIRED_V1 = frozenset({
    ("profile", SKILLS),
    ("tracker.kind", SKILLS),
    ("tracker.issues_repo", SKILLS),
    ("tracker.code_repo", SKILLS),
    ("tracker.public", SKILLS),
    ("tracker.ready_marker", (SPEC, LOOP)),
    ("tracker.tool", (ONE, LOOP, TEST, ROADMAP)),
    ("tracker.queue", (LOOP,)),
    ("tracker.columns.in_progress", (ONE, LOOP)),
    ("environments", SKILLS),
    ("stages", (ONE, LOOP, TEST)),
    ("hard_stops.source", SKILLS),
    ("hard_stops.form", (SPEC, ONE, LOOP)),
    ("hard_stops.items", (SPEC, ONE, LOOP)),
    ("lanes", (SPEC, ONE, LOOP)),
    ("verify.agent", (ONE, LOOP)),
    ("verify.human", (SPEC, TEST)),
    ("verify.rungs", (ONE, LOOP)),
    ("state.forbidden", (ONE, LOOP)),
    ("gates.always", (LOOP,)),
    ("integration.strategy", (LOOP,)),
    ("integration.base", (LOOP,)),
    ("integration.ci_before_merge", (LOOP,)),
    ("auto_test.pass_column", (TEST,)),
    ("auto_test.fail_column", (TEST,)),
    ("auto_test.fail_label", (TEST,)),
    ("auto_test.human_label", (TEST,)),
    ("auto_test.pass_closes", (TEST,)),
})

# The `tracker.columns` roles the profile format defines, from FIELDS.
COLUMN_ROLES = tuple(p.split(".", 2)[2] for p in FIELDS if p.startswith("tracker.columns."))

# The keys a stage may have (`stages` is a list, so FIELDS cannot name them).
STAGE_KEYS = ("code_is", "environment", "column", "moved_by", "tag")

ENUMS = {
    "tracker.kind": {"github-project", "todo-file"},
    "hard_stops.form": {"categories", "questions"},
    "integration.strategy": {"merge-script", "run-branch-pr", "pr-squash"},
    "integration.workspace": {"checkout", "worktree"},
    "handback.reporter": {"trailer", "assign", "none"},
    "notify": {"none", "telegram"},
    "review.coverage": {"precise", "broad", "exhaustive"},
    "independence": {"junior-dev", "tech-lead", "product-owner"},
}


class ProfileError(Exception):
    """The file exists but cannot be read as a profile."""


def split_profile(text):
    """Return (settings dict, {section title: section text})."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "+++":
        raise ProfileError("settings: the file must start with a +++ line (TOML front matter)")
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "+++")
    except StopIteration:
        raise ProfileError("settings: no closing +++ line") from None
    try:
        settings = tomllib.loads("\n".join(lines[1:end]))
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"settings: not valid TOML ({exc})") from None

    sections, title, buf = {}, None, []
    for line in lines[end + 1:]:
        if line.startswith("## "):
            if title is not None:
                sections[title] = "\n".join(buf).strip()
            title, buf = line[3:].strip(), []
        elif title is not None:
            buf.append(line)
    if title is not None:
        sections[title] = "\n".join(buf).strip()
    return settings, sections


def _lookup(settings, path):
    node = settings
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None, False
        node = node[part]
    return node, True


def effective(settings):
    """A copy of `settings` with each absent DEFAULTS path filled in, where its
    resolver can tell the value and the tables above it are tables."""
    out = copy.deepcopy(settings)
    for path, (resolve, _) in DEFAULTS.items():
        if _lookup(out, path)[1]:
            continue
        value = resolve(out)
        if value is None:
            continue
        node, parts = out, path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                break
        else:
            node[parts[-1]] = value
    return out


def _leaf_paths(node, prefix=""):
    """Dotted paths present in the settings, stopping at known dict/list fields."""
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and path not in FIELDS:
            yield from _leaf_paths(value, path + ".")
        else:
            yield path


def _check_environments(settings):
    """Environments, stages and the verify settings must agree with each other."""
    errors = []
    environments = settings.get("environments")
    if not isinstance(environments, list):
        return errors
    names, roles_seen = [], set()
    for i, env in enumerate(environments):
        if not isinstance(env, dict) or not env.get("name"):
            errors.append(f"environments[{i}]: each environment needs a name")
            continue
        name = env["name"]
        if name in names:
            errors.append(f"environments[{i}] ({name}): the name is used twice")
        names.append(name)
        roles = env.get("roles")
        if not isinstance(roles, list) or not roles:
            errors.append(f"environments[{i}] ({name}): needs roles, a list from {', '.join(ROLES)}")
            continue
        for role in roles:
            if role not in ROLES:
                errors.append(f"environments[{i}] ({name}): '{role}' is not one of {', '.join(ROLES)}")
        roles_seen.update(roles)
    # A repo may have no pre-production environment; it always has the other two.
    for role in ("pre-merge", "production"):
        if names and role not in roles_seen:
            errors.append(f"environments: none has the role {role}")

    verify = settings.get("verify") if isinstance(settings.get("verify"), dict) else {}
    human = verify.get("human")
    if isinstance(human, str) and human and human not in names:
        errors.append(f"verify.human: '{human}' is not in environments")
    agent = verify.get("agent")
    if isinstance(agent, list):
        for name in agent:
            if name not in names:
                errors.append(f"verify.agent: '{name}' is not in environments")
    return errors


def _check_stages(settings):
    """Each stage, and its `tag` (a glob: a card enters the stage when every
    commit linked to it is in a tag matching it). Returns (errors, warnings).

    `_leaf_paths` does not descend into lists, so a typo'd key inside a stage
    is caught here or nowhere.
    """
    errors, warnings = [], []
    stages = settings.get("stages")
    if not isinstance(stages, list):
        return errors, warnings
    environments = settings.get("environments")
    names = ([e["name"] for e in environments if isinstance(e, dict) and e.get("name")]
             if isinstance(environments, list) else None)
    tags = {}
    for i, stage in enumerate(stages):
        if not isinstance(stage, dict) or not stage.get("code_is") or not stage.get("column"):
            errors.append(f"stages[{i}]: each stage needs code_is and column")
            continue
        where = f"stages[{i}] ({stage['column']})"
        env = stage.get("environment")
        if names is not None and env is not None and env not in names:
            errors.append(f"{where}: environment '{env}' is not in environments")
        for key in stage:
            if key not in STAGE_KEYS:
                warnings.append(f"{where}: unknown key '{key}' (typo, or not in this profile version)")
        if "tag" not in stage:
            continue
        tag = stage["tag"]
        if not isinstance(tag, str) or not tag:
            errors.append(f'{where}: tag must be a non-empty glob, such as "deploy-*"')
            continue
        if i == 0:
            errors.append(f"{where}: tag is not allowed on the first stage (a merge puts a card there, not a tag)")
        if env is None:
            errors.append(f"{where}: a stage with a tag needs an environment")
        if "/" in tag:
            # git's tag patterns and fnmatch disagree on '/'.
            errors.append(f"{where}: tag '{tag}' must not contain '/'")
        if tag in tags:
            errors.append(f"{where}: tag '{tag}' is also on stages[{tags[tag]}]")
        else:
            tags[tag] = i

    handback = settings.get("handback") if isinstance(settings.get("handback"), dict) else {}
    if handback.get("reporter") == "trailer" and not tags:
        warnings.append("handback.reporter: 'trailer', but no stage has a tag, so nothing assigns the reporter")
    return errors, warnings


def environment(settings, name):
    """The environment table with this name, or None."""
    for env in settings.get("environments", []):
        if isinstance(env, dict) and env.get("name") == name:
            return env
    return None


def _check_auto_test(settings, sections):
    """auto-test tests on the `verify.human` environment, in the column of its one stage."""
    errors = []
    verify = settings.get("verify") if isinstance(settings.get("verify"), dict) else {}
    name = verify.get("human")
    env = environment(settings, name) if isinstance(name, str) else None
    if env is not None:
        for key in ("url", "writes"):
            if not env.get(key):
                errors.append(f"verify.human: environment '{name}' has no {key}")
        stages = settings.get("stages") if isinstance(settings.get("stages"), list) else []
        held = [s for s in stages if isinstance(s, dict) and s.get("environment") == name]
        if not held:
            errors.append(f"stages: no stage has environment '{name}', so there is no column to test")
        elif len(held) > 1:
            errors.append(f"stages: {len(held)} stages have environment '{name}'; auto-test needs exactly one")
    text = sections.get("Test data")
    if text:
        headings = {line[4:].strip() for line in text.splitlines() if line.startswith("### ")}
        for heading in TEST_DATA_HEADINGS:
            if heading not in headings:
                errors.append(f"section '## Test data': no '### {heading}'")
    return errors


def check(settings, sections, skill=None, root=None):
    """Return (errors, warnings); each entry starts with the field it is about.

    With no skill, every skill's needs are checked, and auto-test's only when the
    settings have an [auto_test] table (a repo that never adopted it must pass).
    `root`: the repo root, for checking that a merge script exists; None skips it.
    """
    errors, warnings = [], []
    if skill:
        wanted = (skill,)
    else:
        wanted = tuple(s for s in SKILLS if s != TEST or "auto_test" in settings)

    raw, settings = settings, effective(settings)
    for path, (_, issue) in DEFAULTS.items():
        value, present = _lookup(settings, path)
        if present and not _lookup(raw, path)[1]:
            warnings.append(f"{path}: missing; using {value!r} (default since {issue}). "
                            "/gogogo:setup adds it to the profile.")

    columns, columns_present = _lookup(settings, "tracker.columns")
    columns_bad = columns_present and not isinstance(columns, dict)
    for path, (kind, required_by, meaning) in FIELDS.items():
        if columns_bad and path.startswith("tracker.columns."):
            continue  # one error for the whole table, below
        value, present = _lookup(settings, path)
        required = any(s in required_by for s in wanted)
        if not present:
            if required:
                errors.append(f"{path}: missing. {meaning}")
            continue
        # bool is an int in Python; keep them apart.
        ok = isinstance(value, kind) and not (kind is int and isinstance(value, bool))
        if not ok:
            errors.append(f"{path}: expected {kind.__name__}, found {type(value).__name__}")
            continue
        if kind in (str, list, dict) and not value and required:
            errors.append(f"{path}: empty. {meaning}")
        if path in ENUMS and value not in ENUMS[path]:
            errors.append(f"{path}: '{value}' is not one of {', '.join(sorted(ENUMS[path]))}")

    version, present = _lookup(settings, "profile")
    if present and isinstance(version, int) and version not in ACCEPTED_VERSIONS:
        errors.append(f"profile: version {version} is not supported (this checker reads {PROFILE_VERSION})")

    strategy, _ = _lookup(settings, "integration.strategy")
    command, _ = _lookup(settings, "integration.command")
    if (root is not None and strategy == "merge-script" and (ONE in wanted or LOOP in wanted)
            and isinstance(command, str) and command.split()):
        # A command, not a path: only a first word with a / in it names a file.
        token = command.split()[0]
        if "/" in token and not (Path(root) / token).exists():
            errors.append(f"integration.command: {token} does not exist in {root}")

    lanes, present = _lookup(settings, "lanes")
    if present and isinstance(lanes, list):
        for i, lane in enumerate(lanes):
            if not isinstance(lane, dict) or not lane.get("name"):
                errors.append(f"lanes[{i}]: each lane needs a name")
            elif not (lane.get("run") or lane.get("env")):
                errors.append(f"lanes[{i}] ({lane['name']}): needs run (a command) or env (where it is checked)")
            elif "mutate" in lane and not (isinstance(lane["mutate"], str) and lane["mutate"].strip()
                                           and "<base>" in lane["mutate"]):
                errors.append(f"lanes[{i}] ({lane['name']}): mutate must be a command containing <base>, "
                              "the branch the change merges into")
            elif "tests" in lane and not (isinstance(lane["tests"], list) and lane["tests"]
                                          and all(isinstance(p, str) and p for p in lane["tests"])):
                errors.append(f'lanes[{i}] ({lane["name"]}): tests must be a list of file patterns, '
                              'for example ["tests/*"]')

    if columns_bad:
        errors.append(f"tracker.columns: expected a table of role = column name, found {type(columns).__name__}")
    elif columns_present:
        for role, name in columns.items():
            if any(e.startswith(f"tracker.columns.{role}:") for e in errors):
                continue  # FIELDS above already named it
            if not isinstance(name, str) or not name.strip():
                errors.append(f"tracker.columns.{role}: expected a column name, found {name!r}")

    errors.extend(_check_environments(settings))
    stage_errors, stage_warnings = _check_stages(settings)
    errors.extend(stage_errors)
    warnings.extend(stage_warnings)
    major, present = _lookup(settings, "release.major")
    if present and isinstance(major, int) and not isinstance(major, bool) and major < 1:
        errors.append("release.major: must be 1 or more")
    if TEST in wanted:
        errors.extend(_check_auto_test(settings, sections))

    for path in _leaf_paths(settings):
        if path in RETIRED:
            warnings.append(f"{path}: unknown setting ({RETIRED[path]}); remove it")
        elif path not in FIELDS and path != "tracker.columns" and not path.startswith("tracker.columns."):
            warnings.append(f"{path}: unknown setting (typo, or not in this profile version)")

    for title, needed_by in SECTIONS.items():
        if any(s in needed_by for s in wanted):
            if title not in sections:
                errors.append(f"section '## {title}': missing")
            elif not sections[title]:
                errors.append(f"section '## {title}': empty")
    return errors, warnings


def find_profile(start=None):
    """The nearest profile at or above `start`, stopping at the repo root.

    One repo can hold one profile at its root, or one per app in a monorepo; a
    skill working in a folder uses the closest one above it.
    """
    here = Path(start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / DEFAULT_PATH
        if candidate.is_file():
            return candidate
        if (folder / ".git").exists():
            break
    return Path(DEFAULT_PATH)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a repo's process profile.")
    parser.add_argument("--for", dest="skill", choices=SKILLS,
                        help="check only what this skill needs (default: every skill, and auto-test "
                             "only when the profile has [auto_test])")
    parser.add_argument("--path", help=f"profile file (default: the nearest {DEFAULT_PATH} at or "
                                       "above this folder, within the repo)")
    parser.add_argument("--show", action="store_true", help="print the settings as JSON on stdout")
    args = parser.parse_args(argv)

    path = Path(args.path) if args.path else find_profile()
    if not path.is_file():
        print(f"profile: no file at {path}. Run /gogogo:setup to adopt gogogo in this repo "
              f"(references/profile-schema.md describes the file).", file=sys.stderr)
        return EXIT_MISSING
    try:
        settings, sections = split_profile(path.read_text(encoding="utf-8"))
    except ProfileError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID

    # The profile sits at <repo>/.agents/dev-process.md.
    errors, warnings = check(settings, sections, args.skill, root=path.resolve().parent.parent)
    for line in warnings:
        print(f"warning: {line}", file=sys.stderr)
    for line in errors:
        print(f"error: {line}", file=sys.stderr)
    if errors:
        return EXIT_INVALID
    if args.show:
        json.dump({"settings": effective(settings), "sections": sorted(sections)}, sys.stdout, indent=2)
        print()
    scope = args.skill or "all skills"
    print(f"profile ok for {scope}: {path}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
