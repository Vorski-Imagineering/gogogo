#!/usr/bin/env python3
"""Check that this repo is set up for the gogogo skills, and say what to fix.

    setup_check.py [--json]

Run from anywhere inside the repo. Prints one line per check:

    PASS  <check>
    FAIL  <check>: <what is wrong> -> <how to fix it>
    WARN  <check>: <what to look at>
    INFO  <check>: <for the record>

Exit 0 when nothing FAILs, 1 otherwise. It only reads: nothing is created,
changed or moved. `/gogogo:setup` uses it and does the fixing, with approval.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402

MARKETPLACE = "vorski-skills"
PLUGIN = "gogogo@vorski-skills"
MARKETPLACE_REPO = "Vorski-Imagineering/gogogo"
# Local skills that the shared plugin replaces. A copy left in .claude/skills
# competes with the shared one for the same requests.
REPLACED_LOCAL_SKILLS = [
    "spec-to-issue", "spec", "dev", "auto-dev", "fix-issue", "fix-reported-issue",
    "gogogo-auto-dev", "auto-issue-gogo", "wrap-up",
]


def run(*cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, check, detail="", fix=""):
        self.rows.append({"level": level, "check": check, "detail": detail, "fix": fix})

    def ok(self, check, detail=""):
        self.add("PASS", check, detail)

    def fail(self, check, detail, fix):
        self.add("FAIL", check, detail, fix)

    def warn(self, check, detail):
        self.add("WARN", check, detail)

    def info(self, check, detail):
        self.add("INFO", check, detail)

    def failed(self):
        return any(r["level"] == "FAIL" for r in self.rows)

    def print(self):
        for r in self.rows:
            line = f"{r['level']:<5} {r['check']}"
            if r["detail"]:
                line += f": {r['detail']}"
            if r["fix"]:
                line += f" -> {r['fix']}"
            print(line)


def check_settings(root, rep):
    path = root / ".claude" / "settings.json"
    if not path.is_file():
        rep.fail("plugin settings", f"no {path.relative_to(root)}",
                 f"run `claude plugin marketplace add {MARKETPLACE_REPO} --scope project`, then "
                 f"`claude plugin install {PLUGIN} --scope project`, and commit .claude/settings.json")
        return
    try:
        settings = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        rep.fail("plugin settings", f".claude/settings.json is not valid JSON ({exc})", "fix the JSON")
        return
    market = (settings.get("extraKnownMarketplaces") or {}).get(MARKETPLACE)
    if not market:
        rep.fail("plugin settings: marketplace", f"no extraKnownMarketplaces.{MARKETPLACE}",
                 f"add it with source github {MARKETPLACE_REPO} (a teammate who trusts the folder then gets it)")
    else:
        rep.ok("plugin settings: marketplace")
        check_marketplace_source(market, rep)
        if not market.get("autoUpdate"):
            rep.warn("plugin settings: auto-update",
                     f"extraKnownMarketplaces.{MARKETPLACE}.autoUpdate is not true; installed copies stay "
                     "at the commit they were installed at")
    if (settings.get("enabledPlugins") or {}).get(PLUGIN) is not True:
        rep.fail("plugin settings: enabled", f"enabledPlugins.{PLUGIN} is not true",
                 f"`claude plugin install {PLUGIN} --scope project`")
    else:
        rep.ok("plugin settings: enabled")
    tracked = run("git", "ls-files", "--error-unmatch", str(path), cwd=root).returncode == 0
    if not tracked:
        rep.warn("plugin settings: committed",
                 ".claude/settings.json is not tracked by git, so teammates do not get the plugin "
                 "(check .gitignore; `git add -f` if .claude/ is ignored)")


def check_hard_stop_source(root, source, rep):
    # "CLAUDE.md § Heading" or "CLAUDE.md#anchor"
    m = re.match(r"\s*([^\s§#]+)\s*(?:§\s*(.+)|#(.+))?$", source or "")
    if not m:
        rep.fail("hard stops: source", f"cannot read hard_stops.source {source!r}",
                 "write it as 'CLAUDE.md § <heading>'")
        return
    file, heading, anchor = m.group(1), m.group(2), m.group(3)
    path = root / file
    if not path.is_file():
        rep.fail("hard stops: source", f"{file} does not exist", "point hard_stops.source at the file with the rules")
        return
    if heading:
        wanted = heading.split(",")[0].split(" and ")[0].strip().lower()
        headings = [line.lstrip("#").strip().lower() for line in path.read_text().splitlines()
                    if line.startswith("#")]
        if not any(wanted in h for h in headings):
            rep.fail("hard stops: source", f"no heading like {heading!r} in {file}",
                     "correct the heading name in hard_stops.source")
            return
    rep.ok("hard stops: source", source)


def check_tracker(root, settings, rep):
    tracker = settings.get("tracker") or {}
    repo = tracker.get("issues_repo")
    if not repo:
        return
    if run("gh", "auth", "status").returncode != 0:
        rep.fail("tracker: gh login", "gh is not logged in", "`gh auth login`, then `gh auth setup-git`")
        return
    view = run("gh", "repo", "view", repo, "--json", "nameWithOwner")
    if view.returncode != 0:
        rep.fail("tracker: issues repo", f"{repo} is not readable with this gh login",
                 "check the name in tracker.issues_repo and your access")
        return
    rep.ok("tracker: issues repo", repo)

    label = tracker.get("ready_marker")
    if label:
        labels = run("gh", "label", "list", "--repo", repo, "--limit", "200", "--json", "name")
        names = {x["name"] for x in json.loads(labels.stdout or "[]")} if labels.returncode == 0 else set()
        if label in names:
            rep.ok("tracker: ready label", label)
        else:
            rep.fail("tracker: ready label", f"{repo} has no label {label!r}",
                     f"`gh label create \"{label}\" --repo {repo} --description \"The spec is in this "
                     "issue's body and needs nothing further from anyone.\"`")

    tool = tracker.get("tool")
    if not tool:
        return
    if tool != "shared":
        rep.info("tracker: tool", f"the repo's own tool: {tool} (must meet references/tracker-contract.md)")
        return
    import tracker as shared  # noqa: E402  (sibling script)
    try:
        shared.configure(str(profile_check.find_profile(root)))
        meta = shared.board_meta()
    except (shared.ProfileMissing, shared.BoardError) as exc:
        rep.fail("tracker: board", str(exc),
                 "check tracker.project_owner and tracker.project_number, and that gh can see the project "
                 "(`gh auth refresh -s project` if the token lacks the project scope)")
        return
    rep.ok("tracker: board", f"{meta['title']} ({shared.ORG} #{shared.PROJECT_NUMBER}), {meta['total']} items")
    missing = shared.missing_columns(meta)
    if missing:
        rep.fail("tracker: columns", "the board lacks " + ", ".join(repr(m) for m in missing),
                 "add them in the board's Status field settings, or correct the profile's stages/columns")
    else:
        rep.ok("tracker: columns", ", ".join(sorted({c.name for c in shared.COLUMNS.values()})))
    try:
        cards, recovered, _ = shared.list_cards(repo=repo)
        expected = ({"future", "⚡ new", "new", "backlog", "done"}
                    | {c.name.replace("\ufe0f", "").strip().lower() for c in shared.COLUMNS.values()})
        check_board_hygiene(cards, recovered, meta["options"], expected, rep)
    except shared.BoardError as exc:
        rep.info("tracker: board hygiene", f"could not read the cards ({exc})")
    try:
        nodes = (shared.graphql(WORKFLOWS_QUERY, org=shared.ORG, number=shared.PROJECT_NUMBER)
                 ["repositoryOwner"]["projectV2"]["workflows"]["nodes"])
    except (shared.BoardError, KeyError, TypeError):
        nodes = None
    check_board_workflows(nodes, rep)


def check_marketplace_source(market, rep):
    """The marketplace must name the repo that is the plugin's home today. A renamed repo
    keeps working through GitHub's redirect only until another repo takes the name."""
    source = market.get("source") if isinstance(market, dict) else None
    repo = source.get("repo") if isinstance(source, dict) else None
    if not isinstance(repo, str):
        return
    if repo.lower() != MARKETPLACE_REPO.lower():
        rep.warn("plugin settings: marketplace source",
                 f"names {repo}; the plugin lives at {MARKETPLACE_REPO}. The old name works only through "
                 f"GitHub's rename redirect and can stop updating; set source.repo to {MARKETPLACE_REPO}")


#: Workflows only the board's web page can turn on (setup SKILL.md), by GitHub's own names.
BOARD_WORKFLOWS = ("Auto-add to project", "Item added to project")

WORKFLOWS_QUERY = """
query($org: String!, $number: Int!) {
  repositoryOwner(login: $org) {
    ... on ProjectV2Owner {
    projectV2(number: $number) { workflows(first: 50) { nodes { name enabled } } }
    }
  }
}
"""


def check_board_workflows(workflows, rep):
    """`workflows` is a list of {name, enabled}, or None when it could not be read."""
    if workflows is None:
        rep.info("tracker: board workflows", "could not be read; check ⋯ → Workflows on the board by hand")
        return
    on = {w.get("name") for w in workflows if w.get("enabled")}
    off = [n for n in BOARD_WORKFLOWS if n not in on]
    if off:
        rep.warn("tracker: board workflows",
                 "not enabled: " + ", ".join(off) + ". Open the board, ⋯ → Workflows, and turn them on "
                 "(Item added to project sets Status to the new-issue column), or new issues never reach it")
    else:
        rep.ok("tracker: board workflows", ", ".join(BOARD_WORKFLOWS))


def _norm(name):
    """Column names compare case-insensitively and without emoji variation selectors."""
    return name.replace("\ufe0f", "").strip().lower()


def check_board_hygiene(cards, recovered, options, expected, rep):
    """`cards`: flattened cards; `recovered`: open issues the board did not list;
    `options`: the live Status column names; `expected`: lower-case names the profile uses."""
    if recovered:
        rep.warn("tracker: issues missing from the board",
                 f"{len(recovered)} open issue(s) have no card: "
                 + ", ".join(f"#{c['number']}" for c in recovered[:10]) + ("..." if len(recovered) > 10 else "")
                 + ". Add them (`gh project item-add`) and turn on Auto-add to project")
    for name in options:
        if _norm(name) in expected:
            continue
        held = sum(1 for c in cards if _norm(c.get("status") or "") == _norm(name))
        rep.warn("tracker: unused column",
                 f"'{name}' is not a column this profile uses and holds {held} card(s). "
                 + ("Move them to the right column, then remove it in the board's Status settings"
                    if held else "Remove it in the board's Status settings"))
    missing = {c.get("number") for c in recovered}
    no_status = [c for c in cards if not c.get("status") and c.get("number")
                 and c["number"] not in missing and c.get("state") in (None, "OPEN")]
    if no_status:
        rep.warn("tracker: cards without a column", f"{len(no_status)} open card(s) have no Status: "
                 + ", ".join(f"#{c['number']}" for c in no_status[:10]))


def check_local_skills(root, rep):
    skills = root / ".claude" / "skills"
    found = [n for n in REPLACED_LOCAL_SKILLS if (skills / n / "SKILL.md").is_file()]
    if found:
        rep.warn("local skills", "still loaded and replaced by the shared plugin: "
                 + ", ".join(found) + ". Move each to .claude/skills-retired/ once its project "
                 "specifics are in the profile, so only one copy answers")
    else:
        rep.ok("local skills", "no local copy competes with the shared skills")


def check_claude_md(root, rep):
    path = root / "CLAUDE.md"
    if not path.is_file():
        rep.warn("CLAUDE.md", "no CLAUDE.md; the Hard Stops and the pointer to the profile usually live there")
        return
    if ".agents/dev-process.md" not in path.read_text():
        rep.warn("CLAUDE.md", "does not mention .agents/dev-process.md; add a short pointer so every "
                 "session knows where this repo's process lives")
    else:
        rep.ok("CLAUDE.md", "points at the profile")


def check_release_shape(settings, rep):
    """Say whether the profile is staged or straight to production, and warn when it
    contradicts itself. Reads the profile only; never FAILs. No evidence, no row."""
    envs = settings.get("environments")
    if not isinstance(envs, list) or not envs or not all(isinstance(e, dict) for e in envs):
        return

    def roles(env):
        r = env.get("roles")
        return r if isinstance(r, list) else []

    by_name = {e["name"]: e for e in envs if isinstance(e.get("name"), str)}
    if not any("production" in roles(e) for e in envs):
        return
    stages = [s for s in (settings.get("stages") or []) if isinstance(s, dict)]
    columns = " -> ".join(str(s.get("column")) for s in stages)
    pre_prod = [e.get("name") for e in envs if "pre-production" in roles(e)]
    stage_envs = [s.get("environment") for s in stages]

    def is_production(name):
        return "production" in roles(by_name.get(name) or {})

    if not pre_prod:
        rep.info("release shape", f"straight to production: a merge to the base branch is the release; "
                                  f"stage column: {columns or 'none'}")
        if len(stages) != 1:
            rep.warn("release shape: stages", f"found {columns or 'none'}; a straight-to-production repo has "
                     "one stage, merged to main, with the production environment")
        elif not is_production(stage_envs[0]):
            rep.warn("release shape: stage environment", f"the stage {columns} names "
                     f"'{stage_envs[0]}', which is not a production environment")
        verify = settings.get("verify")
        verify = verify.get("agent") if isinstance(verify, dict) else None
        named = [n for n in (verify if isinstance(verify, list) else []) if is_production(n)]
        if named:
            rep.warn("release shape: verify.agent", f"names production ({', '.join(named)}); the agent "
                     "verifies before the merge, a person confirms on production")
    else:
        rep.info("release shape", f"staged: pre-production = {', '.join(map(str, pre_prod))}; "
                                  f"stages: {columns or 'none'}")
        if any(n not in stage_envs for n in pre_prod) or not any(is_production(n) for n in stage_envs):
            rep.warn("release shape: stages", f"stages ({columns or 'none'}) do not reach every pre-production "
                     "environment and production")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rep = Report()

    top = run("git", "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        print("FAIL  git repo: not inside a git repository")
        return 1
    root = Path(top.stdout.strip())
    rep.info("repo", str(root))

    check_settings(root, rep)

    path = profile_check.find_profile()
    settings = {}
    if not path.is_file():
        rep.fail("profile", "no .agents/dev-process.md",
                 "create one from plugins/gogogo/references/profile-schema.md (/gogogo:setup drafts it)")
    else:
        try:
            settings, sections = profile_check.split_profile(path.read_text(encoding="utf-8"))
        except profile_check.ProfileError as exc:
            rep.fail("profile", str(exc), "fix the settings block")
            sections = None
        if sections is not None:
            for skill in profile_check.SKILLS:
                errors, warnings = profile_check.check(settings, sections, skill)
                if errors:
                    rep.fail(f"profile for /gogogo:{skill}", "; ".join(errors), "add the missing settings or sections")
                else:
                    rep.ok(f"profile for /gogogo:{skill}")
            for w in profile_check.check(settings, sections)[1]:
                rep.warn("profile", w)
    if settings:
        check_release_shape(settings, rep)
        check_hard_stop_source(root, (settings.get("hard_stops") or {}).get("source"), rep)
        check_tracker(root, settings, rep)
    check_local_skills(root, rep)
    check_claude_md(root, rep)

    if args.json:
        json.dump(rep.rows, sys.stdout, indent=2)
        print()
    else:
        rep.print()
    return 1 if rep.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
