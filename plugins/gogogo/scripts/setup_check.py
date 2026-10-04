#!/usr/bin/env python3
"""Check that this repo is set up for the gogogo skills, and say what to fix.

    setup_check.py [--json]
    setup_check.py --branch-rules [--json]
    setup_check.py --ruleset BRANCH

Run from anywhere inside the repo. Prints one line per check:

    PASS  <check>
    FAIL  <check>: <what is wrong> -> <how to fix it>
    WARN  <check>: <what to look at>
    INFO  <check>: <for the record>

Exit 0 when nothing FAILs, 1 otherwise. It only reads: nothing is created,
changed or moved. `/gogogo:setup` uses it and does the fixing, with approval.

`--branch-rules` runs only the branch-rules rows (what GitHub enforces on the
branches the profile merges into, and on the default branch), for
`/gogogo:auto-dev`'s preflight. `--ruleset BRANCH` prints the ruleset body the
branch-rules fix sends to GitHub, and exits 2 for a branch the profile does not
give.
"""
import argparse
import fnmatch
import json
import re
from collections import Counter
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_check  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = "vorski-skills"
PLUGIN = "gogogo@vorski-skills"
MARKETPLACE_REPO = "Vorski-Imagineering/gogogo"
# The ready label looks the same in every repo; gh writes colours without '#'.
READY_LABEL_COLOUR = "0E8A16"
READY_LABEL_DESCRIPTION = "The spec is in this issue's body and needs nothing further from anyone."
READY_LABEL_COLOUR_CHECK = "tracker: ready label colour"
DELETE_BRANCH_CHECK = "code repo: delete merged branches"
BRANCH_RULES_CHECK = "code repo: branch rules"
# Local skills that the shared plugin replaces. A copy left in .claude/skills
# competes with the shared one for the same requests.
REPLACED_LOCAL_SKILLS = [
    "spec-to-issue", "spec", "dev", "auto-dev", "fix-issue", "fix-reported-issue",
    "gogogo-auto-dev", "auto-issue-gogo", "wrap-up", "gogogo-auto-test",
    "auto-test", "roadmap", "update-milestone-doc",
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

    def warn(self, check, detail, fix=""):
        self.add("WARN", check, detail, fix)

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


def check_git_state(root, rep):
    """Setup commits to the default branch, so it starts there: nothing uncommitted and
    level with origin. `git ls-remote` asks origin without fetching, so this still only reads."""
    head = run("git", "symbolic-ref", "--quiet", "--short", "HEAD", cwd=root).stdout.strip()
    problems, default, remote_sha = [], None, None
    if run("git", "remote", "get-url", "origin", cwd=root).returncode != 0:
        rep.info("git: origin", "no origin remote; cannot compare with it")
    else:
        sym = run("git", "ls-remote", "--symref", "origin", "HEAD", cwd=root)
        m = re.search(r"^ref: refs/heads/(\S+)\s+HEAD", sym.stdout, re.M)
        if m:
            default = m.group(1)
            line = run("git", "ls-remote", "origin", f"refs/heads/{default}", cwd=root).stdout.split()
            remote_sha = line[0] if line else None
        else:
            rep.info("git: origin", "could not read origin's default branch")
    if not head:
        problems.append("HEAD is detached")
    elif default and head != default:
        problems.append(f"on {head!r}, not {default!r}")
    status = run("git", "status", "--porcelain", cwd=root).stdout.splitlines()
    tracked = [s for s in status if not s.startswith("??")]
    untracked = [s[3:] for s in status if s.startswith("??")]
    if tracked:
        problems.append(f"{len(tracked)} uncommitted change(s)")
    if remote_sha and head and head == default:
        local = run("git", "rev-parse", "HEAD", cwd=root).stdout.strip()
        if local != remote_sha:
            known = run("git", "cat-file", "-e", f"{remote_sha}^{{commit}}", cwd=root).returncode == 0
            ahead = known and run("git", "merge-base", "--is-ancestor", remote_sha, "HEAD",
                                  cwd=root).returncode == 0
            problems.append(f"has commits origin/{default} lacks" if ahead
                            else f"is not level with origin/{default}")
    if untracked:
        rep.warn("git: untracked files", ", ".join(untracked[:10]) + ("..." if len(untracked) > 10 else "")
                 + ". Setup commits only the files it writes; these stay as they are")
    branch = default or head or "the default branch"
    if problems:
        rep.fail("git: clean main", "; ".join(problems),
                 f"commit, push or set aside that work yourself, then `git switch {branch} && "
                 "git pull --ff-only`; setup starts from a clean, current default branch")
    else:
        rep.ok("git: clean main", f"on {branch}, clean" + (", level with origin" if remote_sha else ""))


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


def check_ready_label(repo, label, listing, rep):
    """`listing`: parsed `gh label list --json name,color,description`, or None when gh failed."""
    # GitHub label names are case-insensitive: "Dev Ready" is the profile's "dev ready".
    want = str(label).lower()
    found = next((x for x in listing or [] if str(x.get("name") or "").lower() == want), None)
    if found is None:
        rep.fail("tracker: ready label", f"{repo} has no label {label!r}",
                 f"`gh label create \"{label}\" --repo {repo} --color {READY_LABEL_COLOUR} "
                 f"--description \"{READY_LABEL_DESCRIPTION}\"`")
        return
    rep.ok("tracker: ready label", label)
    colour = found.get("color") or ""
    if colour.lower() != READY_LABEL_COLOUR.lower():
        rep.warn(READY_LABEL_COLOUR_CHECK,
                 f"{label!r} is #{colour} in {repo}; the standard is #{READY_LABEL_COLOUR} so the label looks "
                 f"the same in every repo. Fix: gh label edit \"{label}\" --repo {repo} --color {READY_LABEL_COLOUR}")


def check_delete_branch(repo, setting, error, rep):
    """`setting`: the repo's `delete_branch_on_merge` (True/False/None); `error`: gh's message when the read failed."""
    if error:
        rep.warn(DELETE_BRANCH_CHECK, f"could not read {repo}'s settings: {error}")
    elif setting is True:
        rep.ok(DELETE_BRANCH_CHECK, repo)
    elif setting is False:
        rep.fail(DELETE_BRANCH_CHECK, f"{repo} keeps a pull request's branch after it merges",
                 f"`gh api -X PATCH repos/{repo} -F delete_branch_on_merge=true` (undo: the same with =false)")
    else:
        # GitHub shows the field only to a login that can read the repo's settings.
        rep.warn(DELETE_BRANCH_CHECK, f"{repo} does not show this setting to this gh login; it needs admin access "
                                      "to read")


def ruleset_body(branch, checks, wants_check):
    """The ruleset `--ruleset` prints: no deletion, no force push, and the checks
    that must pass, with nobody able to bypass them (issue #57)."""
    rules = [{"type": "deletion"}, {"type": "non_fast_forward"}]
    if wants_check and checks:
        rules.append({"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": False,
            "required_status_checks": [{"context": name} for name in checks]}})
    return {"name": f"gogogo: {branch}", "target": "branch", "enforcement": "active", "bypass_actors": [],
            "conditions": {"ref_name": {"include": [f"refs/heads/{branch}"], "exclude": []}}, "rules": rules}


def _ruleset_fix(repo, branch, existing):
    script = Path(__file__).resolve()
    if existing is None:
        return (f"`python3 \"{script}\" --ruleset {branch} | gh api -X POST repos/{repo}/rulesets --input -` "
                f"(undo: `gh api -X DELETE repos/{repo}/rulesets/<id from the POST's output>`)")
    saved = f'"$(git rev-parse --git-dir)/gogogo-ruleset-{existing}-before.json"'
    return (f"first save the existing ruleset: `gh api repos/{repo}/rulesets/{existing} "
            f"--jq '{{name,target,enforcement,bypass_actors,conditions,rules}}' > {saved}`, then "
            f"`python3 \"{script}\" --ruleset {branch} | gh api -X PUT repos/{repo}/rulesets/{existing} --input -` "
            f"(undo: `gh api -X PUT repos/{repo}/rulesets/{existing} --input {saved}`; undo before applying "
            f"this fix a second time, or the save holds the state after the first PUT)")


def check_branch_rules(repo, branch, rules, classic, checks, wants_check, needs_ci, rep, *, target=True,
                       existing=None):
    """rules: list from rules/branches/<branch>, each rule carrying its ruleset's
    `bypass_actors`, or an error string (also when a ruleset could not be read).
    classic: dict from branches/<branch>/protection, {} when GitHub says
    'Branch not protected', or an error string.
    checks: names that passed on the latest PR merged into <branch>, [] when
    none, or an error string.
    wants_check: False for merge-script's integration.base only.
    target: False for a default branch that is not the merge target.
    existing: the id of a ruleset already named `gogogo: <branch>`, or None."""
    check = f"{BRANCH_RULES_CHECK} ({branch})"
    if isinstance(rules, str):
        rep.warn(check, f"could not read the rules on {repo} {branch}: {rules}")
        return
    types = {r.get("type") for r in rules}
    old = classic if isinstance(classic, dict) else {}
    required = old.get("required_status_checks") or {}
    by_rules = {"no force push": "non_fast_forward" in types, "no deletion": "deletion" in types,
                "a required check": "required_status_checks" in types}
    by_classic = {"no force push": (old.get("allow_force_pushes") or {}).get("enabled") is False,
                  "no deletion": (old.get("allow_deletions") or {}).get("enabled") is False,
                  "a required check": bool(required.get("contexts") or required.get("checks"))}
    present = {name: by_rules[name] or by_classic[name] for name in by_rules}
    # Classic protection with enforce admins off binds nobody who has an admin's
    # login, and the agents use one. A check held only there counts as missing.
    admins_bypass = (old.get("enforce_admins") or {}).get("enabled") is not True
    if admins_bypass and not by_rules["a required check"]:
        present["a required check"] = False
    fix = _ruleset_fix(repo, branch, existing)
    basic = [name for name in ("no force push", "no deletion") if not present[name]]
    if basic and isinstance(classic, str):
        rep.warn(check, f"{repo} {branch} has no ruleset for {', '.join(basic)}; it may be set in classic branch "
                        f"protection, which needs admin to read ({classic})", fix)
        return
    if basic:
        missing = basic + (["a required check"] if wants_check and not present["a required check"] else [])
        rep.fail(check, f"{repo} {branch} is missing: {', '.join(missing)}", fix)
        return
    actors = [a for r in rules for a in r.get("bypass_actors") or []]
    if actors:
        named = ", ".join(sorted({f"{a.get('actor_type')} {a.get('actor_id')}" for a in actors}))
        bypassing = {r.get("ruleset_id") for r in rules if r.get("bypass_actors")}
        rep.fail(check, f"{repo} {branch} can be bypassed by: {named}",
                 fix if bypassing == {existing} else
                 f"empty the bypass list of ruleset {', '.join(sorted(map(str, bypassing)))} in the repo's "
                 "Settings > Rules")
        return
    classic_only = [name for name in ("no force push", "no deletion") if by_classic[name] and not by_rules[name]]
    if classic_only and admins_bypass:
        rep.fail(check, f"{repo} {branch} has {', '.join(classic_only)} only in classic branch protection, which "
                        "admins can bypass (enforce admins is off), and agents use an admin's login", fix)
        return
    if present["a required check"]:
        rep.ok(check, f"{repo} {branch}")
        return
    if not wants_check:
        rep.info(check, f"a required check is not offered: the merge script pushes to {branch} directly")
        return
    if isinstance(classic, str):
        rep.warn(check, f"{repo} {branch} has no ruleset requiring a check; one may be required in classic branch "
                        f"protection, which needs admin to read ({classic})", fix)
        return
    no_names = not checks or isinstance(checks, str)
    if no_names and not target:
        rep.warn(check, f"no check name can be derived: no PR with a passing check has been merged into {branch}")
        return
    if by_classic["a required check"]:
        names = ", ".join(required.get("contexts") or [c.get("context", "?") for c in required.get("checks") or []])
        detail = (f"{repo} {branch} requires {names} only in classic branch protection, which admins can bypass "
                  "(enforce admins is off)")
        if isinstance(checks, str):
            detail += f" ({checks})"
            level_fix = "re-run once the latest merged PR's checks can be read, to get the ruleset command"
        else:
            level_fix = fix if not no_names else (f"merge a PR into `{branch}` whose checks pass, then re-run to "
                                                  "get the ruleset command")
    elif no_names:
        detail = f"{repo} {branch} requires no check, and no check passed on the latest PR merged into {branch}"
        if isinstance(checks, str):
            detail += f" ({checks})"
        level_fix = (f"add a CI workflow that runs on every pull request to `{branch}`, merge one PR, re-run")
    else:
        detail = f"{repo} {branch} requires no check (the latest merged PR passed: {', '.join(checks)})"
        level_fix = fix
    if needs_ci:
        rep.fail(check, detail, level_fix)
    else:
        rep.warn(check, detail, level_fix)


def _gh_json(*args, json_on_failure=False):
    """(parsed stdout, None) or (None, gh's error line). A failed call is an
    error even when GitHub printed its error as JSON, except where the caller
    says a non-zero exit can carry real output (`gh pr checks` exits non-zero
    when a check failed)."""
    out = run("gh", *args)
    try:
        value = json.loads(out.stdout) if out.stdout.strip() else None
    except json.JSONDecodeError:
        value = None
    if out.returncode != 0 and (value is None or not json_on_failure):
        return None, (out.stderr.strip().splitlines() or [f"gh exited {out.returncode}"])[0]
    if value is None:
        return None, "gh printed nothing readable"
    return value, None


def check_names(repo, branch):
    """The checks that passed on the latest PR merged into `branch`: [] when none, or an error string."""
    prs, error = _gh_json("pr", "list", "--repo", repo, "--base", branch, "--state", "merged", "--limit", "1",
                          "--json", "number")
    if error:
        return error
    if not prs:
        return []
    checks, error = _gh_json("pr", "checks", str(prs[0]["number"]), "--repo", repo, "--json", "name,bucket",
                             json_on_failure=True)
    if error:
        return error
    return [c["name"] for c in checks if c.get("bucket") == "pass"]


def branch_plan(settings, default_branch):
    """[(branch, wants_check, target)] to check, and a reason when there is nothing to check."""
    integration = settings.get("integration") or {}
    strategy = integration.get("strategy")
    plan, note = [], None
    if strategy == "run-branch-pr":
        if integration.get("final_target"):
            plan.append((integration["final_target"], True, True))
        else:
            note = "integration.final_target is not set; nothing to check"
    else:
        base = integration.get("base") or default_branch
        if base:
            plan.append((base, strategy != "merge-script", True))
    if default_branch and default_branch not in [b for b, _, _ in plan]:
        plan.append((default_branch, True, False))
    return plan, note


def _rules_with_bypass(repo, branch):
    rules, error = _gh_json("api", f"repos/{repo}/rules/branches/{branch}")
    if error:
        return error
    if not isinstance(rules, list):
        return "gh printed something that is not a list"
    bypass = {}
    for ruleset in {r.get("ruleset_id") for r in rules}:
        body, error = _gh_json("api", f"repos/{repo}/rulesets/{ruleset}")
        if error or not isinstance(body, dict):
            return f"ruleset {ruleset}: {error or 'gh printed something that is not a JSON object'}"
        if "bypass_actors" not in body:
            return f"ruleset {ruleset}: its bypass list is not shown to this gh login"
        bypass[ruleset] = body.get("bypass_actors", [])
    return [dict(r, bypass_actors=bypass[r.get("ruleset_id")]) for r in rules]


def _classic(repo, branch):
    out = run("gh", "api", f"repos/{repo}/branches/{branch}/protection")
    if out.returncode != 0:
        if "Branch not protected" in out.stderr:
            return {}
        return (out.stderr.strip().splitlines() or [f"gh exited {out.returncode}"])[0]
    try:
        value = json.loads(out.stdout)
    except json.JSONDecodeError:
        return "gh printed something that is not JSON"
    return value if isinstance(value, dict) else "gh printed something that is not a JSON object"


def check_branches(code_repo, settings, default_branch, rep):
    """The branch-rules rows for every branch Design 4 of issue #57 names; returns the plan."""
    plan, note = branch_plan(settings, default_branch)
    if note:
        rep.warn(BRANCH_RULES_CHECK, note)
    if not plan:
        if not note:
            rep.warn(BRANCH_RULES_CHECK, "no branch to check: integration.base is not set and the default branch "
                                         "could not be read")
        return plan
    needs_ci = bool((settings.get("integration") or {}).get("ci_before_merge"))
    rulesets, _ = _gh_json("api", f"repos/{code_repo}/rulesets")
    named = {r.get("name"): r.get("id") for r in rulesets or [] if isinstance(r, dict)}
    for branch, wants_check, target in plan:
        check_branch_rules(code_repo, branch, _rules_with_bypass(code_repo, branch), _classic(code_repo, branch),
                           check_names(code_repo, branch) if wants_check else [], wants_check, needs_ci, rep,
                           target=target, existing=named.get(f"gogogo: {branch}"))
    return plan


def print_ruleset(settings, default_branch, branch):
    plan, _ = branch_plan(settings, default_branch)
    wanted = {b: w for b, w, _ in plan}
    if branch not in wanted:
        print(f"{branch} is not a branch the profile merges into or the default branch "
              f"({', '.join(wanted) or 'none'})", file=sys.stderr)
        return 2
    code_repo = (settings.get("tracker") or {}).get("code_repo")
    checks = check_names(code_repo, branch) if wanted[branch] else []
    if isinstance(checks, str):
        # A new ruleset still gets no force push and no deletion; replacing an
        # existing one without its check could drop a check it already requires.
        rulesets, error = _gh_json("api", f"repos/{code_repo}/rulesets")
        if error or any(isinstance(r, dict) and r.get("name") == f"gogogo: {branch}" for r in rulesets or []):
            print(f"could not read the checks to require on {branch}: {checks}", file=sys.stderr)
            return 2
        checks = []
    print(json.dumps(ruleset_body(branch, checks if isinstance(checks, list) else [], wanted[branch]), indent=2))
    return 0


def check_tracker(root, settings, rep):
    tracker = settings.get("tracker") or {}
    repo = tracker.get("issues_repo")
    if not repo:
        return
    own_repos = tuple({r.lower(): r for r in (repo, tracker.get("code_repo")) if r}.values())
    if run("gh", "auth", "status").returncode != 0:
        rep.fail("tracker: gh login", "gh is not logged in", "`gh auth login`, then `gh auth setup-git`")
        return
    view = run("gh", "repo", "view", repo, "--json", "nameWithOwner")
    if view.returncode != 0:
        rep.fail("tracker: issues repo", f"{repo} is not readable with this gh login",
                 "check the name in tracker.issues_repo and your access")
        return
    rep.ok("tracker: issues repo", repo)

    code_repo = tracker.get("code_repo")
    if code_repo:
        api = run("gh", "api", f"repos/{code_repo}")
        setting, error, default_branch = None, None, None
        if api.returncode != 0:
            error = (api.stderr.strip().splitlines() or [f"gh exited {api.returncode}"])[0]
        else:
            try:
                body = json.loads(api.stdout)
                setting, default_branch = body.get("delete_branch_on_merge"), body.get("default_branch")
            except (json.JSONDecodeError, AttributeError):
                error = "gh printed something that is not a JSON object"
        check_delete_branch(code_repo, setting, error, rep)
        check_branches(code_repo, settings, default_branch, rep)

    label = tracker.get("ready_marker")
    if label:
        labels = run("gh", "label", "list", "--repo", repo, "--limit", "200", "--json", "name,color,description")
        check_ready_label(repo, label, json.loads(labels.stdout or "[]") if labels.returncode == 0 else None, rep)

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
        check_board_origin(cards, own_repos, tracker.get("queue"), rep)
    except shared.BoardError as exc:
        rep.info("tracker: board hygiene", f"could not read the cards ({exc})")
    try:
        nodes = (shared.graphql(WORKFLOWS_QUERY, org=shared.ORG, number=shared.PROJECT_NUMBER)
                 ["repositoryOwner"]["projectV2"]["workflows"]["nodes"])
    except (shared.BoardError, KeyError, TypeError):
        nodes = None
    check_board_workflows(nodes, rep, own_repos)
    try:
        views = _views(shared.graphql(VIEWS_QUERY, org=shared.ORG, number=shared.PROJECT_NUMBER)
                       ["repositoryOwner"]["projectV2"]["views"]["nodes"])
    except (shared.BoardError, KeyError, TypeError):
        views = None
    stages = [s.get("column") for s in settings.get("stages") or [] if isinstance(s, dict) and s.get("column")]
    check_board_views(views, tracker.get("ready_marker"), stages, rep)
    check_board_tidiness(shared, repo, rep)


def check_notify(profile, rep):
    """How run messages reach a person on this machine. Never sends, never FAILs."""
    import notify  # noqa: E402  (sibling script)
    try:
        state, line, _ = notify.status(str(profile))
    except notify.UsageError as exc:
        rep.warn("notify", str(exc))
        return
    detail = line.split(": ", 1)[1] if line.startswith("notify: ") else line
    if state == notify.OFF:
        rep.info("notify", "off (no messages); /gogogo:setup can set up Telegram")
    elif state == notify.READY:
        rep.ok("notify", detail)
    elif state == notify.NO_CREDENTIALS:
        rep.warn("notify", "telegram, but no bot credentials on this machine: messages are off here "
                 "-> /gogogo:setup walks you through it")
    else:
        rep.warn("notify", detail)


def numbers(items, limit=10):
    shown = ", ".join(f"#{i['number']}" for i in items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def check_board_tidiness(shared, repo, rep):
    """The board stays current: views hide closed issues, and no card is left behind. Only warns."""
    tool = '"${CLAUDE_PLUGIN_ROOT}/scripts/tracker.py"'
    try:
        showing = shared.views_showing_closed(shared.board_views())
        closed, off_board = shared.untidy(repo)
    except (shared.BoardError, KeyError, TypeError, AttributeError) as exc:
        rep.info("tracker: views and cards", f"could not be read ({exc!r})")
        return

    if showing:
        rep.warn("tracker: views", "show closed issues: " + ", ".join(repr(v["name"]) for v in showing)
                 + f". Run `python3 {tool} views --hide-closed`")
    else:
        rep.ok("tracker: views", "every working view hides closed issues")

    if closed or off_board:
        detail = []
        if closed:
            detail.append(f"closed but not in {shared.DONE_COLUMN}: {numbers(closed)}")
        if off_board:
            detail.append(f"open but not on the board: {numbers(off_board)}")
        rep.warn("tracker: cards", "; ".join(detail) + f". Run `python3 {tool} tidy`, then `tidy --apply`")
    else:
        rep.ok("tracker: cards", f"closed issues are in {shared.DONE_COLUMN}; every open issue is on the board")


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


def check_board_workflows(workflows, rep, repos=()):
    """`workflows` is a list of {name, enabled}, or None when it could not be read.
    `repos`: the repos the board is for, named in the Auto-add row."""
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
    if "Auto-add to project" in on:
        rep.info("tracker: Auto-add repository",
                 "the API does not say which repo Auto-add to project watches; open the board, "
                 f"⋯ → Workflows → Auto-add to project, and check it is {' and '.join(repos) or 'this repo'} "
                 "with the filter `is:issue is:open`. "
                 "Cards from another repo (above) are the sign it is wrong")


VIEWS_QUERY = """
query($org: String!, $number: Int!) {
  repositoryOwner(login: $org) {
    ... on ProjectV2Owner {
    projectV2(number: $number) { views(first: 50) { nodes {
      name layout filter
      fields(first: 50) { nodes { ... on ProjectV2FieldCommon { name } } }
      sortByFields(first: 5) { nodes { direction field { ... on ProjectV2FieldCommon { name } } } }
    } } }
    }
  }
}
"""


def _status_list(names):
    return ",".join(f'"{n}"' if " " in n else n for n in names)


def _shows_label(filt, label):
    filt = filt or ""
    return f'label:"{label}"' in filt or (" " not in label and re.search(rf"label:{re.escape(label)}\b", filt))


def check_board_views(views, ready, stage_columns, rep):
    """The two kanban views setup creates (SKILL.md): Backlog, and the queue filtered on the
    ready label. `views`: [{name, layout, filter, fields, sort: [(field, direction)]}], or None."""
    if views is None:
        rep.info("tracker: board views", "could not be read; check the board's views by hand")
        return
    boards = [v for v in views if v.get("layout") == "BOARD_LAYOUT"]
    queue = [v for v in boards if ready and _shows_label(v.get("filter"), ready)]
    backlog = [v for v in boards if "label:" not in (v.get("filter") or "")]
    problems = []
    if not backlog:
        problems.append("no Backlog kanban: add a board-layout view 'Backlog' filtered "
                        "`is:open -status:Done,Future`, sorted by Created, newest first")
    elif not any(("Created", "DESC") in [tuple(x) for x in v.get("sort") or []] for v in backlog):
        problems.append(f"'{backlog[0]['name']}' is not sorted newest first (View → Sort by → Created, descending)")
    if ready and not queue:
        problems.append(f"no {ready!r} kanban: add a board-layout view filtered "
                        f"`is:open -status:{_status_list(['Done', 'Future', *stage_columns])} label:\"{ready}\"`")
    if problems:
        rep.warn("tracker: board views", "; ".join(problems))
    unlabelled = [v["name"] for v in boards if "Labels" not in (v.get("fields") or [])]
    if unlabelled:
        rep.warn("tracker: labels in board views",
                 "without Labels: " + ", ".join(f"'{n}'" for n in unlabelled) + ". A card carrying the "
                 "ready label looks unlabelled there; View → Fields → Labels, then Save view")
    if not problems and not unlabelled:
        rep.ok("tracker: board views", ", ".join(v["name"] for v in backlog[:1] + queue[:1]))


def _views(nodes):
    return [{"name": n.get("name"), "layout": n.get("layout"), "filter": n.get("filter"),
             "fields": [f.get("name") for f in (n.get("fields") or {}).get("nodes") or [] if f],
             "sort": [((s.get("field") or {}).get("name"), s.get("direction"))
                      for s in (n.get("sortByFields") or {}).get("nodes") or []]}
            for n in nodes]


def _norm(name):
    """Column names compare case-insensitively and without emoji variation selectors."""
    return name.replace("\ufe0f", "").strip().lower()


def check_board_hygiene(cards, recovered, options, expected, rep):
    """`cards`: flattened cards; `recovered`: open issues the board did not list;
    `options`: the live Status column names; `expected`: lower-case names the profile uses."""
    if recovered:
        rep.warn("tracker: cards the board's index missed",
                 f"{len(recovered)} open issue(s) have a card the board's own listing omitted: "
                 + ", ".join(f"#{c['number']}" for c in recovered[:10]) + ("..." if len(recovered) > 10 else "")
                 + "; tracker.py reads them from the issue side, so nothing to fix unless it persists")
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


def _counted(names):
    """'a ×2, b ×1': most common first, then by name."""
    return ", ".join(f"{n} ×{k}" for n, k in sorted(Counter(names).items(), key=lambda kv: (-kv[1], kv[0])))


def check_board_origin(cards, own_repos, queue, rep):
    """Where the board's cards come from, which the workflow check cannot say, and pull requests
    from the board's own repos, which Auto-add should not add. `cards`: flattened cards;
    `own_repos`: issues_repo and code_repo; `queue`: the queue column, or empty."""
    own = {r.lower() for r in own_repos}
    owned = " and ".join(own_repos)
    # Content this login cannot read comes back null, so flatten takes the kind from the item's
    # type (ISSUE, PULL_REQUEST, REDACTED) and has no repo. Only a draft has no repo by design.
    unreadable = [c for c in cards if not c.get("repo") and c.get("kind") not in ("DraftIssue", "DRAFT_ISSUE")]
    if unreadable:
        rep.info("tracker: card origin", f"{len(unreadable)} card(s) have no content this login can read "
                 "(deleted, or in a repo it cannot see), so their repo is unknown")
    # Drafts and unreadable cards have no repo (tracker.flatten), so they are never foreign.
    foreign = [c for c in cards if c.get("repo") and c["repo"].lower() not in own]
    if foreign:
        rep.warn("tracker: cards from another repo",
                 f"{len(foreign)} of {len(cards)} card(s) belong to a repo other than {owned}: "
                 f"{_counted(c['repo'] for c in foreign)}; in columns "
                 f"{_counted(c.get('status') or 'no status' for c in foreign)}. Archive them on the board "
                 f"(card ⋯ → Archive; restorable), then check that Auto-add to project watches {owned}")
    prs = [c for c in cards if c.get("kind") == "PullRequest"
           and (c.get("repo") or "").lower() in own]
    if prs:
        rep.warn("tracker: pull requests on the board",
                 f"{len(prs)} pull request(s) are cards on the board, in columns "
                 f"{_counted(c.get('status') or 'no status' for c in prs)}: "
                 + ", ".join(f"#{c['number']}" for c in prs[:10]) + (", ..." if len(prs) > 10 else "") + ". "
                 "Set Auto-add to project's filter to `is:issue is:open`; /gogogo:setup offers to archive them "
                 "(restorable)")
    if queue:
        closed = [c for c in cards if _norm(c.get("status") or "") == _norm(queue)
                  and c.get("state") not in (None, "OPEN")]
        if closed:
            names = [f"{c.get('repo') or '?'}#{c.get('number')}" for c in closed]
            rep.warn("tracker: closed cards in the queue",
                     f"{len(closed)} closed or merged card(s) sit in '{queue}', where auto-dev reads them "
                     f"as queue rows: {', '.join(names[:10])}{', ...' if len(names) > 10 else ''}. "
                     "Move them out of the queue or archive them")


def check_profile_skills(settings, sections, rep):
    """One row per skill. auto-test is opt-in: a profile without [auto_test] is INFO."""
    for skill in profile_check.SKILLS:
        if skill == profile_check.TEST and "auto_test" not in settings:
            rep.info(f"profile for /gogogo:{skill}", "not set up: add [auto_test] and ## Test data to use it "
                     "(references/profile-schema.md § Auto-test)")
            continue
        errors, warnings = profile_check.check(settings, sections, skill)
        if errors:
            rep.fail(f"profile for /gogogo:{skill}", "; ".join(errors), "add the missing settings or sections")
        else:
            rep.ok(f"profile for /gogogo:{skill}")
    for w in profile_check.check(settings, sections)[1]:
        rep.warn("profile", w)


def main_worktree(root):
    """The repo's main worktree (the first entry of `git worktree list --porcelain`), which is
    what live sessions and hooks run from; `root` when git cannot say."""
    listing = run("git", "worktree", "list", "--porcelain", cwd=root)
    first = (listing.stdout.splitlines() or [""])[0] if listing.returncode == 0 else ""
    return Path(first[len("worktree "):]) if first.startswith("worktree ") else Path(root)


def live_checkout(root, home):
    """What runs straight from this checkout, so that an issue's branch here would change it
    under other sessions: one reason per finding. Names only the path inside the repo and the
    hook's event, never the rest of a hook's command (it can carry a token)."""
    root = Path(root).resolve()
    reasons = []
    if (root / ".claude-plugin").is_dir():
        reasons.append("this repo is a Claude Code plugin; sessions may load it from here with --plugin-dir")
    try:
        data = json.loads((Path(home) / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return reasons
    home_text = str(Path(home).resolve())
    # A path ends where shell syntax or an argument's own punctuation starts.
    inside = re.compile(re.escape(str(root)) + r"(/[^\s'\";|&)<>,=:]*)?(?![^\s'\";|&)<>,=:])")
    for event, entries in _table(_table(data).get("hooks")).items():
        for entry in _list(entries):
            for hook in _list(_table(entry).get("hooks")):
                command = _table(hook).get("command")
                if not isinstance(command, str):
                    continue
                command = re.sub(r"(?<![\w/])~(?=/|$|\s)", home_text, command)
                command = re.sub(r"\$\{?HOME\}?(?!\w)", home_text, command)
                for found in inside.finditer(command):
                    reason = f"your Claude Code settings run {(found.group(1) or '/.')[1:]} on {event}"
                    if reason not in reasons:
                        reasons.append(reason)
    return reasons


def check_workspace(root, settings, sections, rep, home):
    """Where dev and auto-dev do an issue's work (`integration.workspace`): WARN until the
    profile says, INFO once it does, with what runs from this checkout either way."""
    value = _table(settings.get("integration")).get("workspace")
    if value is None:
        level, detail = rep.warn, "not decided: dev and auto-dev work in the checkout"
        if "worktree" in str(_table(sections).get("Lane constraints", "")).lower():
            detail += "; ## Lane constraints mention a worktree, so dev and auto-dev stop until it is set"
    else:
        level, detail = rep.info, str(value)
    live = live_checkout(root, home)
    if live:
        detail += "; live checkout: " + "; ".join(live)
    level("workspace", detail)


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


def check_session_hook(plugin_root, rep):
    """The plugin ships its own SessionStart hook (hooks/hooks.json); setup only reports it."""
    try:
        hooks = json.loads((Path(plugin_root) / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        if any("session_status.py" in str(h.get("command"))
               for e in hooks["hooks"]["SessionStart"] for h in e.get("hooks") or []):
            rep.info("session-status", "shown at session start (plugin hook)")
            return
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    rep.warn("session-status", "the plugin's session-status hook is missing")


def check_release(settings, rep, shallow=None):
    """Whether the repo follows references/versioning.md. Never FAILs. `shallow`: whether this
    clone is shallow, or None to ask git."""
    release = settings.get("release")
    if not isinstance(release, dict):
        rep.info("release", "not adopted: production deploys are not tagged deploy-<build> "
                 "(references/versioning.md)")
        return
    rep.info("release", f"tags deploy-<build>, version {release.get('major', '<major>')}.0.<build>")
    if "major" not in release:
        rep.warn("release: major", "[release] has no major, so release.py cannot version or tag a deploy; "
                 "set major = 1 (references/versioning.md)")
    production = {e.get("name") for e in settings.get("environments") or []
                  if isinstance(e, dict) and "production" in (e.get("roles") or [])}
    # Only production is tagged deploy-<build>; another stage may follow tags of its own.
    for stage in settings.get("stages") or []:
        if not isinstance(stage, dict) or stage.get("environment") not in production:
            continue
        glob = stage.get("tag")
        if isinstance(glob, str) and glob and not fnmatch.fnmatchcase("deploy-1", glob):
            rep.warn("release: stage sync",
                     f"{stage.get('column')} moves on tags matching {glob}, which deploy-<build> tags never match")
    if shallow is None:
        shallow = run("git", "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    if shallow:
        rep.warn("release: build number", "this clone is shallow; the build number needs full history")


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
        # A stage with a tag is reached by a tag, not a merge: only the others count here.
        merged = [s for s in stages if not (isinstance(s.get("tag"), str) and s["tag"])]
        if len(merged) != 1:
            rep.warn("release shape: stages", f"found {columns or 'none'}; a straight-to-production repo has "
                     "one stage, merged to main, with the production environment")
        elif not is_production(merged[0].get("environment")):
            rep.warn("release shape: stage environment", f"the stage {merged[0].get('column')} names "
                     f"'{merged[0].get('environment')}', which is not a production environment")
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

    for i, stage in enumerate(stages):
        if not (isinstance(stage.get("tag"), str) and stage["tag"]):
            continue
        if i == 0:
            rep.warn("release shape: stage sync", f"{stage.get('column')} has tag {stage['tag']}, but a merge "
                     "puts a card in the first stage, not a tag")
            continue
        env = stage.get("environment")
        if not {"pre-production", "production"} & set(roles(by_name.get(env) or {})):
            rep.warn("release shape: stage sync", f"{stage.get('column')} moves on tags, but its environment "
                     f"'{env}' is not a pre-production or production environment")
        rep.info("release shape: stage sync",
                 f"{stage.get('column')} moves on tags matching {stage['tag']}, from {stages[i - 1].get('column')}; "
                 "the repo's CI runs stage_sync.py sync on each such tag (references/stage-sync.md)")


def _joined(values, sep=", "):
    if isinstance(values, (str, int, float)):  # a scalar where a list belongs (bool is an int)
        values = [values]
    return sep.join(str(v) for v in values or []) or "missing"


def _list(value):
    return value if isinstance(value, list) else []


def _table(value):
    """A profile table, or {} when the profile has something else there (profile_check reports it)."""
    return value if isinstance(value, dict) else {}


def config_header(root, settings, rep, profile=None):
    """The repo's setup as written, for the top of the output. Only reads, never judges:
    the checks below it do that. `profile`: the parsed profile's path, or None."""
    tracker = _table(settings.get("tracker"))
    if not settings or not tracker.get("tool"):
        board = "missing"
    elif tracker.get("tool") != "shared":
        board = f"not shown: the repo's own tool {tracker.get('tool') or 'missing'}"
    elif not (tracker.get("project_number") and tracker.get("project_owner")):
        board = "missing"
    else:
        view = run("gh", "project", "view", str(tracker["project_number"]), "--owner",
                   str(tracker["project_owner"]), "--format", "json", "-q", ".url")
        board = (view.stdout.strip() if view.returncode == 0
                 else f"unreadable ({(view.stderr.strip().splitlines() or ['gh failed'])[0]})")
    rep.info("config: board", board)

    def val(v):
        return v if v not in (None, "", [], {}) else "missing"

    if settings:
        columns = _table(tracker.get("columns"))
        rep.info("config: tracker",
                 f"issues {val(tracker.get('issues_repo'))}, code {val(tracker.get('code_repo'))}, "
                 f"ready label \"{val(tracker.get('ready_marker'))}\", queue \"{val(tracker.get('queue'))}\", "
                 f"in progress \"{val(columns.get('in_progress'))}\", needs human \"{val(columns.get('needs_human'))}\", "
                 f"tool {val(tracker.get('tool'))}")
        envs = [e for e in _list(settings.get("environments")) if isinstance(e, dict)]
        stages = [x for x in _list(settings.get("stages")) if isinstance(x, dict)]
        verify = _table(settings.get("verify"))
        integration = _table(settings.get("integration"))
        rep.info("config: release",
                 "environments " + _joined(f"{e.get('name')} ({_joined(e.get('roles'))})" for e in envs)
                 + "; stages " + _joined(f"{x.get('code_is')} -> {x.get('environment')} / {x.get('column')}"
                                         for x in stages)
                 + f"; verify agent {_joined(verify.get('agent'))}, human {val(verify.get('human'))}"
                 + f"; integration {val(integration.get('strategy'))} into {val(integration.get('base'))}"
                 + f", work in {val(integration.get('workspace'))}")
        stops = _table(settings.get("hard_stops"))
        rep.info("config: hard stops", f"{val(stops.get('source'))}: {_joined(stops.get('items'))}")
        lanes = [x for x in _list(settings.get("lanes")) if isinstance(x, dict)]
        rep.info("config: lanes",
                 _joined(f"{x.get('name')}: {x.get('run') or x.get('env') or 'missing'}" for x in lanes)
                 + "; always: " + _joined(_table(settings.get("gates")).get("always"), "; "))
    else:
        for name in ("tracker", "release", "hard stops", "lanes"):
            rep.info(f"config: {name}", "missing")

    path = root / ".claude" / "settings.json"
    if not path.is_file():
        install = "settings file absent"
    else:
        try:
            data = _table(json.loads(path.read_text(encoding="utf-8")))
            market = _table(_table(data.get("extraKnownMarketplaces")).get(MARKETPLACE))
            enabled = _table(data.get("enabledPlugins")).get(PLUGIN) is True
            install = (f"settings file present, plugin enabled {'yes' if enabled else 'no'}, "
                       f"auto-update {'on' if market.get('autoUpdate') else 'off'}")
        except (ValueError, OSError):
            install = "settings file unreadable"
    rep.info("config: install", install)

    if settings and profile:
        try:
            shown = str(Path(profile).resolve().relative_to(Path(root).resolve()))
        except ValueError:
            shown = str(profile)
    else:
        shown = "missing"
    rep.info("config: profile", shown)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--branch-rules", action="store_true", help="only the branch-rules rows")
    parser.add_argument("--ruleset", metavar="BRANCH", help="print the ruleset body for BRANCH")
    args = parser.parse_args(argv)
    rep = Report()

    if args.branch_rules or args.ruleset:
        path = profile_check.find_profile()
        try:
            settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
        except (OSError, profile_check.ProfileError) as exc:
            print(f"profile: {exc}", file=sys.stderr)
            return 2
        code_repo = (settings.get("tracker") or {}).get("code_repo")
        if not code_repo:
            print("profile: tracker.code_repo is not set", file=sys.stderr)
            return 2
        body, error = _gh_json("api", f"repos/{code_repo}")
        default_branch = body.get("default_branch") if isinstance(body, dict) else None
        if args.ruleset:
            return print_ruleset(settings, default_branch, args.ruleset)
        if error:
            rep.warn(BRANCH_RULES_CHECK, f"could not read {code_repo}: {error}")
        check_branches(code_repo, settings, default_branch, rep)
        if args.json:
            json.dump(rep.rows, sys.stdout, indent=2)
            print()
        else:
            rep.print()
        return 1 if rep.failed() else 0

    top = run("git", "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        print("FAIL  git repo: not inside a git repository")
        return 1
    root = Path(top.stdout.strip())
    rep.info("repo", str(root))
    check_git_state(root, rep)

    check_settings(root, rep)

    path = profile_check.find_profile()
    settings, sections = {}, None
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
            check_profile_skills(settings, sections, rep)
            check_workspace(main_worktree(root), settings, sections, rep, Path.home())
        # From here on, the values the skills use: the format's defaults filled in.
        settings = profile_check.effective(settings)
    if sections is None and live_checkout(main_worktree(root), Path.home()):
        # No profile to read yet: setup asks the question while drafting one, so name what runs here.
        check_workspace(main_worktree(root), {}, {}, rep, Path.home())
    if settings:
        check_release_shape(settings, rep)
        check_release(settings, rep)
        check_hard_stop_source(root, (settings.get("hard_stops") or {}).get("source"), rep)
        check_tracker(root, settings, rep)
        check_notify(path, rep)
    check_local_skills(root, rep)
    check_claude_md(root, rep)
    check_session_hook(PLUGIN_ROOT, rep)

    header = Report()
    config_header(root, settings, header, path if settings else None)
    rep.rows = header.rows + rep.rows

    if args.json:
        json.dump(rep.rows, sys.stdout, indent=2)
        print()
    else:
        rep.print()
    return 1 if rep.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
