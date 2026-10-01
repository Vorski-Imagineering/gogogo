#!/usr/bin/env python3
"""Check a repo's process profile (.agents/dev-process.md).

    profile_check.py [--for SKILL] [--path FILE] [--show]

The profile is a markdown file whose first block is TOML between two `+++`
lines (the settings), followed by `## ` sections (project knowledge the skills
point at). A skill runs this before doing anything else, so a missing setting
is a named error instead of a guess.

Exit codes: 0 ok (warnings allowed), 2 no profile file, 3 profile unreadable or
incomplete. Problems go to stderr, one per line, each naming the field.

Standard library only (tomllib needs Python 3.11+).
"""
import argparse
import json
import sys
import tomllib
from pathlib import Path

DEFAULT_PATH = ".agents/dev-process.md"
PROFILE_VERSION = 1

EXIT_OK, EXIT_MISSING, EXIT_INVALID = 0, 2, 3

SPEC = "spec"
ONE = "dev"
LOOP = "auto-dev"
TEST = "auto-test"
TECH = "tech-eval"
SKILLS = (SPEC, ONE, LOOP, TEST, TECH)

# Dotted path -> (type, skills that require it, one-line meaning).
# `references/profile-schema.md` documents the same paths; a test keeps the two
# in step. Paths required by no skill are known-but-optional.
FIELDS = {
    "profile": (int, SKILLS, "Profile format version."),
    "tracker.kind": (str, SKILLS, "github-project | github-label | todo-file."),
    "tracker.issues_repo": (str, SKILLS, "owner/repo that holds the issues."),
    "tracker.code_repo": (str, SKILLS, "owner/repo that holds the code."),
    "tracker.public": (bool, SKILLS, "True if the tracker is readable by the public."),
    "tracker.ready_marker": (str, (SPEC, LOOP), "Label that marks an issue as specced and pickable."),
    "tracker.tool": (str, (ONE, LOOP), "'shared' for the plugin's tracker.py, or a command for the repo's own tool meeting references/tracker-contract.md."),
    "tracker.project_owner": (str, (), "Owner of the GitHub project board."),
    "tracker.project_number": (int, (), "Number of the GitHub project board."),
    "tracker.queue": (str, (LOOP,), "Column or label the loop works."),
    "tracker.columns": (dict, (ONE, LOOP), "Columns before any code moves: in_progress, back_to_queue."),
    "environments": (list, SKILLS, "Where code runs: name, roles, and url/serves/reached_by/data/writes."),
    "stages": (list, (ONE, LOOP, TEST), "The path a change takes after it merges: code_is, column, environment."),
    "hard_stops.source": (str, SKILLS, "Where the repo's Hard Stop rules live (file#anchor)."),
    "hard_stops.form": (str, (SPEC, ONE, LOOP), "categories | questions."),
    "hard_stops.items": (list, (SPEC, ONE, LOOP), "Names of the categories or questions, in order."),
    "hard_stops.two_licence": (list, (), "Changes that need a design approval and an apply approval."),
    "design.placement_rule": (str, (), "Where the repo says which layer or folder new code belongs in."),
    "technology.register": (str, (), "Path of the technology decisions register, from the repo root."),
    "lanes": (list, (SPEC, ONE, LOOP), "Test lanes: name, plus run/focused/env/ci."),
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
    "integration.base": (str, (), "Branch issue branches are cut from, for merge-script and pr-squash."),
    "integration.command": (str, (), "Merge command, for merge-script."),
    "integration.run_branch": (str, (), "Run branch name with <date> (YYYY-MM-DD), for run-branch-pr."),
    "integration.run_from": (str, (), "Branch the run branch is cut from, for run-branch-pr."),
    "integration.final_target": (str, (), "Branch the run's PR targets, for run-branch-pr."),
    "integration.mode_check": (str, (), "Command that proves unattended mode is on."),
    "integration.ci_before_merge": (bool, (LOOP,), "True if CI must pass on each issue before it merges."),
    "handback.reporter": (str, (ONE, LOOP), "trailer | assign | none."),
    "preflight.extra": (list, (), "Extra checks before a run."),
    "stop.extra": (list, (), "Extra conditions that stop a whole run."),
    "notify": (str, (), "none | telegram."),
}

# Settings auto-dev needs under each integration.strategy. Under run-branch-pr
# issue branches are cut from the run branch, so integration.base is not read.
STRATEGY_FIELDS = {
    "merge-script": ("integration.base",),
    "pr-squash": ("integration.base",),
    "run-branch-pr": ("integration.run_branch", "integration.run_from", "integration.final_target"),
}

# Body sections (## headings) a skill reads, by skill.
SECTIONS = {
    "Recon traps": (SPEC, ONE),
    "Lane constraints": (SPEC, ONE),
    "superpowers boundary": SKILLS,
}

# How auto-dev sends a message; required by auto-dev when notify is not none.
NOTIFICATIONS = "Notifications"

ROLES = ("pre-merge", "pre-production", "production")

ENUMS = {
    "tracker.kind": {"github-project", "github-label", "todo-file"},
    "hard_stops.form": {"categories", "questions"},
    "integration.strategy": {"merge-script", "run-branch-pr", "pr-squash"},
    "handback.reporter": {"trailer", "assign", "none"},
    "notify": {"none", "telegram"},
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

    stages = settings.get("stages")
    if isinstance(stages, list):
        for i, stage in enumerate(stages):
            if not isinstance(stage, dict) or not stage.get("code_is") or not stage.get("column"):
                errors.append(f"stages[{i}]: each stage needs code_is and column")
                continue
            env = stage.get("environment")
            if env is not None and env not in names:
                errors.append(f"stages[{i}] ({stage['column']}): environment '{env}' is not in environments")

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


def environment(settings, name):
    """The environment table with this name, or None."""
    for env in settings.get("environments", []):
        if isinstance(env, dict) and env.get("name") == name:
            return env
    return None


def check(settings, sections, skill=None):
    """Return (errors, warnings); each entry starts with the field it is about."""
    errors, warnings = [], []
    wanted = (skill,) if skill else SKILLS

    for path, (kind, required_by, meaning) in FIELDS.items():
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
    if present and isinstance(version, int) and version != PROFILE_VERSION:
        errors.append(f"profile: version {version} is not supported (this checker reads {PROFILE_VERSION})")

    lanes, present = _lookup(settings, "lanes")
    if present and isinstance(lanes, list):
        for i, lane in enumerate(lanes):
            if not isinstance(lane, dict) or not lane.get("name"):
                errors.append(f"lanes[{i}]: each lane needs a name")
            elif not (lane.get("run") or lane.get("env")):
                errors.append(f"lanes[{i}] ({lane['name']}): needs run (a command) or env (where it is checked)")

    errors.extend(_check_environments(settings))

    if LOOP in wanted:
        _check_strategy(settings, sections, errors, warnings)

    for path in _leaf_paths(settings):
        if path not in FIELDS:
            warnings.append(f"{path}: unknown setting (typo, or not in this profile version)")

    for title, needed_by in SECTIONS.items():
        if any(s in needed_by for s in wanted):
            if title not in sections:
                errors.append(f"section '## {title}': missing")
            elif not sections[title]:
                errors.append(f"section '## {title}': empty")
    return errors, warnings


def _check_strategy(settings, sections, errors, warnings):
    """What auto-dev needs on top of FIELDS: the strategy's settings, and how to notify."""
    strategy, _ = _lookup(settings, "integration.strategy")
    if not isinstance(strategy, str):
        strategy = None
    for path in STRATEGY_FIELDS.get(strategy, ()):
        value, present = _lookup(settings, path)
        meaning = FIELDS[path][2]
        if not present:
            errors.append(f"{path}: missing. {meaning}")
        elif isinstance(value, str) and not value:
            errors.append(f"{path}: empty. {meaning}")
    if strategy == "run-branch-pr":
        name, present = _lookup(settings, "integration.run_branch")
        if present and isinstance(name, str) and name and "<date>" not in name:
            errors.append(f"integration.run_branch: '{name}' has no <date>; each run needs its own branch")
        if _lookup(settings, "integration.base")[1]:
            warnings.append("integration.base: not read under run-branch-pr; issue branches are cut "
                            "from integration.run_branch, which is cut from integration.run_from")

    notify, present = _lookup(settings, "notify")
    if present and isinstance(notify, str) and notify != "none":
        if NOTIFICATIONS not in sections:
            errors.append(f"section '## {NOTIFICATIONS}': missing. notify is '{notify}'; "
                          "say how to send, where the credentials live, and the message formats")
        elif not sections[NOTIFICATIONS]:
            errors.append(f"section '## {NOTIFICATIONS}': empty")


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
                        help="check only what this skill needs (default: every skill)")
    parser.add_argument("--path", help=f"profile file (default: the nearest {DEFAULT_PATH} at or "
                                       "above this folder, within the repo)")
    parser.add_argument("--show", action="store_true", help="print the settings as JSON on stdout")
    args = parser.parse_args(argv)

    path = Path(args.path) if args.path else find_profile()
    if not path.is_file():
        print(f"profile: no file at {path}. This repo has not adopted gogogo; "
              f"see references/profile-schema.md", file=sys.stderr)
        return EXIT_MISSING
    try:
        settings, sections = split_profile(path.read_text(encoding="utf-8"))
    except ProfileError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID

    errors, warnings = check(settings, sections, args.skill)
    for line in warnings:
        print(f"warning: {line}", file=sys.stderr)
    for line in errors:
        print(f"error: {line}", file=sys.stderr)
    if errors:
        return EXIT_INVALID
    if args.show:
        json.dump({"settings": settings, "sections": sorted(sections)}, sys.stdout, indent=2)
        print()
    scope = args.skill or "all skills"
    print(f"profile ok for {scope}: {path}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
