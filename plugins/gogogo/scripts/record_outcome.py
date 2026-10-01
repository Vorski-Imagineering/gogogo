#!/usr/bin/env python3
"""Render and record one /gogogo:auto-test outcome, in the order the skill requires.

    record_outcome.py [--profile FILE] column
    record_outcome.py [--profile FILE] version
    record_outcome.py [--profile FILE] last <issue> [--repo owner/name]
    record_outcome.py [--profile FILE] render <run-dir> <issue> --build <ref> --model <id> < spec.json
    record_outcome.py [--profile FILE] apply <run-dir> <issue> <PASS|FAIL|NEEDS_HUMAN> [--repo owner/name]

`column` prints the column under test: the `column` of the one stage whose
`environment` is `verify.human`. `version` prints the stamp a verdict carries
(a hash of the skill, this script and the profile's `## Test data`), and on
stderr where the plugin came from. `last` prints the newest verdict marker on
an issue. `render` writes `<run-dir>/comment-<n>.md` from a JSON spec. `apply`
checks (with the shared tracker) that the board has the column this verdict
moves the card to, that the card is still in the column under test and the
issue still open, then posts that comment, labels,
closes and moves the card as the profile's `[auto_test]` says, and reads the
issue back.

Why a script rather than steps in the skill: recording an outcome is several
writes for one change, and retyping them per issue is how they went wrong.

  * The comment goes first, so a failure part way always leaves the
    explanation on the issue.
  * The column comes from the profile here, never from an argument: the
    tracker reads an empty `--expect` as "no check" and an empty `--status`
    as "the whole board".
  * The read-back of the issue is the only success signal; a write that
    exited 0 and changed nothing is a failure.

The stamp hashes content, not a git sha: an installed plugin is a cache folder
with no `.git`, and the same skill must stamp the same there and in a clone.

Every subcommand checks the profile for auto-test first. Exit codes: 0 ok, 2
stop the run (the reason is on stderr). Standard library only.
"""
import argparse
import datetime
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile_check  # noqa: E402
import tracker as shared_tracker  # noqa: E402

EXIT_OK, EXIT_STOP = 0, 2
VERDICTS = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "NEEDS_HUMAN": "🧑 NEEDS HUMAN"}
# The shared marker, and the one a repo-local copy of this skill wrote before it.
MARKERS = ("<!-- auto-test ", "<!-- gogogo-auto-test ")
REQUIRED = ("n", "verdict", "kind", "summary", "role", "commits", "checks")
BY_VERDICT = {"FAIL": ("repro",), "NEEDS_HUMAN": ("human", "blocked")}

# What a published comment may not hold (tracker.public): a URL with a query
# string, a URL with a user:password part, a bare IPv4 address.
SECRETS = (
    (re.compile(r"[a-z][a-z0-9+.-]*://[^\s?#]*\?\S", re.I), "a URL with a query string"),
    (re.compile(r"[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]*@", re.I), "a URL with a user:password part"),
    (re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"), "an IP address"),
)


class Stop(Exception):
    """Stop the run; the message says why."""


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Every external command goes through here (the tests replace it)."""
    return subprocess.run(cmd, capture_output=True, text=True)


def load(path):
    path = Path(path) if path else profile_check.find_profile()
    if not path.is_file():
        raise Stop(f"profile: no file at {path}")
    try:
        settings, sections = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except profile_check.ProfileError as exc:
        raise Stop(str(exc)) from None
    errors, _ = profile_check.check(settings, sections, profile_check.TEST)
    if errors:
        raise Stop("\n".join(errors))
    return path.resolve(), settings, sections


def column(settings):
    """The column under test: that of the one stage on the `verify.human` environment."""
    human = (settings.get("verify") or {}).get("human")
    held = [s for s in settings.get("stages") or [] if isinstance(s, dict) and s.get("environment") == human]
    if len(held) != 1:
        raise Stop(f"stages: {len(held)} stages have environment '{human}'; auto-test needs exactly one")
    name = held[0].get("column")
    if not isinstance(name, str) or not name.strip():
        raise Stop(f"stages: the stage on '{human}' has no column name")
    return name


def stamp(plugin_root, test_data):
    """`c-` and 12 hex of sha256 over the skill, this script and the `## Test data` text."""
    root = Path(plugin_root)
    digest = hashlib.sha256()
    digest.update((root / "skills" / "auto-test" / "SKILL.md").read_bytes())
    digest.update((root / "scripts" / "record_outcome.py").read_bytes())
    digest.update(test_data.encode("utf-8"))
    return "c-" + digest.hexdigest()[:12]


def source(plugin_root):
    """Where the plugin came from, for people to read. Never compared."""
    root = str(plugin_root)
    inside = run(["git", "-C", root, "rev-parse", "--is-inside-work-tree"])
    if inside.returncode == 0 and inside.stdout.strip() == "true":
        sha = run(["git", "-C", root, "rev-parse", "--short", "HEAD"]).stdout.strip() or "no-commit"
        dirty = run(["git", "-C", root, "status", "--porcelain", "--", "."]).stdout.strip()
        return f"git {sha}" + ("-dirty" if dirty else "")
    if re.fullmatch(r"[0-9a-f]{12}", Path(plugin_root).name):
        return f"installed {Path(plugin_root).name}"
    return "unknown"


def parse_marker(line):
    """The fields of a verdict marker line, or None when the line is not one."""
    if not line.startswith(MARKERS):
        return None
    return dict(re.findall(r"(\w+)=(\S+)", line.removesuffix("-->")))


def tracker_cmd(settings, profile_path):
    tool = settings["tracker"]["tool"]
    if tool == "shared":
        return [sys.executable, str(HERE / "tracker.py"), "--profile", str(profile_path)]
    return shlex.split(tool)


def cell(value, code=False):
    """A value made safe for one markdown table cell; `code` when it sits in backticks."""
    text = str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "\n")
    return text.replace("\n", " " if code else "<br>")


def board_has(profile_path, name):
    """Whether the shared tracker's `move --to <name>` finds a column, by move's own rule."""
    try:
        shared_tracker.configure(str(profile_path))
        meta = shared_tracker.board_meta()
    except (shared_tracker.ProfileMissing, shared_tracker.BoardError) as exc:
        raise Stop(f"could not read the board's columns: {exc}") from None
    try:
        shared_tracker.resolve_option(meta, shared_tracker.column(name))
    except shared_tracker.BoardError:
        return False
    return True


def issue_number(n):
    """The spec's `n` as an int: 7, "7" or "#7"; anything else is refused."""
    if isinstance(n, int) and not isinstance(n, bool):
        return n
    if isinstance(n, str) and re.fullmatch(r"#?\d+", n.strip()):
        return int(n.strip().lstrip("#"))
    raise Stop(f"spec: n must be the issue number (7, \"7\" or \"#7\"), found {n!r}")


def _check_spec(spec, public, issue, host=None):
    if not isinstance(spec, dict):
        raise Stop("spec: expected a JSON object")
    verdict = spec.get("verdict")
    if verdict not in VERDICTS:
        raise Stop(f"spec: verdict must be one of {', '.join(VERDICTS)}, found {verdict!r}")
    for key in REQUIRED + BY_VERDICT.get(verdict, ()):
        if spec.get(key) in (None, ""):
            raise Stop(f"spec: {key} is missing" + (" (record the role preflight saw; never guess it)"
                                                    if key == "role" else ""))
    if issue_number(spec["n"]) != issue:
        raise Stop(f"spec: n is {spec['n']!r}, but this is issue {issue}")
    if spec.get("mention") and verdict != "PASS":
        raise Stop(f"spec: mention is for a PASS only, and this is {verdict}")
    if not isinstance(spec["commits"], list):
        raise Stop("spec: commits must be a list (one entry per commit)")
    checks = spec["checks"]
    if not isinstance(checks, list) or any(not isinstance(c, list) or len(c) != 6 for c in checks):
        raise Stop("spec: checks must be a list of [criterion, source, steps, expected, observed, mark]")
    if verdict == "PASS":
        if not checks:
            raise Stop("spec: PASS with no checks; no evidence is a failure")
        marks = [str(c[5]).strip() for c in checks]
        if any(m != "✅" for m in marks):
            raise Stop(f"spec: PASS with a check not marked ✅ ({', '.join(marks)})")
    if verdict == "FAIL" and not any(str(c[5]).strip() == "❌" for c in checks):
        raise Stop("spec: FAIL with no check marked ❌; say which criterion failed")
    if verdict == "NEEDS_HUMAN" and not checks:
        raise Stop("spec: NEEDS_HUMAN with no checks; list what ran and what could not")
    if public:
        for key, value in _strings(spec):
            if host and host.lower() in value.lower():
                raise Stop(f"spec: {key} holds the environment's host {host}, and this tracker is public")
            for pattern, what in SECRETS:
                if pattern.search(value):
                    raise Stop(f"spec: {key} holds {what}, and this tracker is public")


def _strings(node, key=""):
    if isinstance(node, str):
        yield key, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(v, f"{key}.{k}" if key else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, f"{key}[{i}]")


def render(settings, sections, run_dir, issue, build, model, spec, plugin_root):
    public = settings["tracker"]["public"] is True
    env = profile_check.environment(settings, settings["verify"]["human"])
    host = urlparse(env["url"]).hostname or env["url"]
    _check_spec(spec, public, issue, host)
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise Stop(f"run folder {run_dir} does not exist")
    auto = settings["auto_test"]
    run_id, n, verdict = run_dir.name, issue, spec["verdict"]
    skill = stamp(plugin_root, sections.get("Test data", ""))
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")

    out = [f"<!-- auto-test v1 run={run_id} issue={n} verdict={verdict} build={build} skill={skill} -->",
           f"## Auto-test: {VERDICTS[verdict]}", "", spec["summary"]]
    if spec.get("mention"):
        out.append(f"@{spec['mention'].lstrip('@')}: this passed an automated check on {env['name']}; "
                   "reopen if it still isn't what you reported.")
    out += ["", "### Build tested", "| | |", "|---|---|",
            # A public comment names the environment only: its host may be internal.
            f"| Environment | {cell(env['name'])} |" if public else f"| Environment | {cell(env['name'])}: `{cell(host, code=True)}` |",
            f"| Running build | `{cell(build, code=True)}` |"]
    out += [f"| Change under test | {cell(c)} |" for c in spec["commits"] or ["none found"]]
    out += [f"| Kind | {cell(spec['kind'])} |", "",
            "### How it was tested", "| | |", "|---|---|",
            f"| Tester | `auto-test` @ `{skill}` ({source(plugin_root)}) · {cell(model)} |",
            f"| Account role | {cell(spec['role'])} |",
            "| Method | Browser, hard reload per page; console and failed requests captured per step |",
            f"| When | finished {now} UTC · run `{run_id}` |", "",
            "### Checks",
            "| # | Criterion | Source | Steps (route · action) | Expected | Observed | |",
            "|---|---|---|---|---|---|---|"]
    out += [f"| {i} | " + " | ".join(cell(v) for v in c) + " |" for i, c in enumerate(spec["checks"], 1)]
    out += ["", f"Signals: {spec.get('signals', 'no console errors, no 4xx/5xx')}", "",
            "### Test data", spec.get("data", "None created. No fixtures used."), "",
            "### Not tested", spec.get("not_tested", "Nothing.")]
    if verdict == "FAIL":
        out += ["", "### Reproduce", spec["repro"], "",
                f"Card moved to `{auto['fail_column']}` and labelled `{auto['fail_label']}`."]
    if verdict == "NEEDS_HUMAN":
        out += ["", "### For the human tester", spec["human"], "",
                f"Blocked because: {spec['blocked']} Remove `{auto['human_label']}` and close when done."]
    path = run_dir / f"comment-{n}.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def last(settings, issue, repo):
    view = run(["gh", "issue", "view", str(issue), "--repo", repo, "--json", "comments"])
    if view.returncode != 0:
        raise Stop(f"#{issue}: could not read the comments: {view.stderr.strip()}")
    try:
        comments = json.loads(view.stdout).get("comments") or []
    except (json.JSONDecodeError, AttributeError):
        raise Stop(f"#{issue}: gh returned comments that are not JSON") from None
    newest = None
    for comment in comments:
        fields = parse_marker(((comment.get("body") or "").splitlines() or [""])[0])
        if fields is not None:
            newest = fields
    if newest is None:
        return "none"
    return " ".join(f"{k}={newest.get(k, '')}" for k in ("verdict", "build", "skill", "run"))


def _append(run_dir, row):
    with open(Path(run_dir) / "run.md", "a", encoding="utf-8") as f:
        f.write(row + "\n")


def apply(settings, profile_path, run_dir, issue, verdict, repo):
    auto = settings["auto_test"]
    issues_repo = settings["tracker"]["issues_repo"]
    col = column(settings)
    comment = Path(run_dir) / f"comment-{issue}.md"
    if not comment.is_file():
        raise Stop(f"#{issue}: no {comment}; render it first")
    first = (comment.read_text(encoding="utf-8").splitlines() or [""])[0]
    fields = parse_marker(first)
    if fields is None or fields.get("verdict") != verdict or fields.get("issue") != str(issue):
        raise Stop(f"#{issue}: {comment.name} does not start with a marker saying issue={issue} verdict={verdict}")

    tool = tracker_cmd(settings, profile_path)
    card_repo = ["--repo", repo] if repo != issues_repo else []
    gh = ["--repo", repo]
    n = str(issue)

    # Only the shared tool can be asked in-process, by the rule its move uses; a repo's
    # own tool is covered by preflight's `fields --check`.
    to = {"PASS": auto["pass_column"], "FAIL": auto["fail_column"]}.get(verdict)
    if to and settings["tracker"]["tool"] == "shared" and not board_has(profile_path, to):
        raise Stop(f"#{issue}: the board has no column {to!r}: nothing written")

    shown = run([*tool, "show", n, "--expect", col, *card_repo])
    # 3 is the contract's "in a different column"; the shared tool also exits 1 for "not on the board".
    moved = (3, 1) if settings["tracker"]["tool"] == "shared" else (3,)
    if shown.returncode in moved:
        print(f"#{issue} is no longer in {col}: nothing written")
        _append(run_dir, f"| #{issue} | no longer in {col}: nothing written |")
        return
    if shown.returncode != 0:
        raise Stop(f"#{issue}: could not read the card (tracker exit {shown.returncode}): {shown.stderr.strip()}")

    state = run(["gh", "issue", "view", n, *gh, "--json", "state"])
    try:
        current = json.loads(state.stdout).get("state") if state.returncode == 0 else None
    except (json.JSONDecodeError, AttributeError):
        current = None
    if current is None:
        raise Stop(f"#{issue}: could not read the issue's state: {state.stderr.strip()}")
    if current != "OPEN":
        print(f"#{issue} is {current.lower()}: nothing written")
        _append(run_dir, f"| #{issue} | closed: nothing written |")
        return

    def must(cmd, what):
        result = run(cmd)
        if result.returncode != 0:
            raise Stop(f"#{issue}: {what} failed (exit {result.returncode}): {result.stderr.strip()}")

    def remove(label):
        run(["gh", "issue", "edit", n, *gh, "--remove-label", label])  # may be absent: ignored

    must(["gh", "issue", "comment", n, *gh, "--body-file", str(comment)], "the comment")
    if verdict == "PASS":
        remove(auto["fail_label"])
        remove(auto["human_label"])
        if auto["pass_closes"]:
            must(["gh", "issue", "close", n, *gh, "--reason", "completed"], "closing")
        want_labels, absent, state, to = set(), {auto["fail_label"], auto["human_label"]}, \
            ("CLOSED" if auto["pass_closes"] else "OPEN"), auto["pass_column"]
    elif verdict == "FAIL":
        must(["gh", "issue", "edit", n, *gh, "--add-label", auto["fail_label"]], "adding the label")
        remove(auto["human_label"])
        want_labels, absent, state, to = {auto["fail_label"]}, {auto["human_label"]}, "OPEN", auto["fail_column"]
    else:
        must(["gh", "issue", "edit", n, *gh, "--add-label", auto["human_label"]], "adding the label")
        remove(auto["fail_label"])
        want_labels, absent, state, to = {auto["human_label"]}, {auto["fail_label"]}, "OPEN", None
    if to is not None:
        moved = run([*tool, "move", n, "--to", to, *card_repo])
        if moved.returncode != 0:
            raise Stop(f"#{issue}: the move to {to} failed (exit {moved.returncode}); "
                       f"the board and the issue now disagree: {moved.stderr.strip()}")

    view = run(["gh", "issue", "view", n, *gh, "--json", "state,labels"])
    if view.returncode != 0:
        raise Stop(f"#{issue}: could not read the issue back: {view.stderr.strip()}")
    try:
        data = json.loads(view.stdout)
        labels = {label["name"] for label in data.get("labels") or []}
        found = data.get("state")
    except (json.JSONDecodeError, AttributeError, KeyError, TypeError):
        raise Stop(f"#{issue}: the read-back is not the JSON expected") from None
    problems = [f"state {found}, expected {state}"] if found != state else []
    problems += [f"label {label!r} missing" for label in sorted(want_labels - labels)]
    problems += [f"label {label!r} still present" for label in sorted(absent & labels)]
    if problems:
        raise Stop(f"#{issue}: the read-back disagrees with {verdict}: " + "; ".join(problems))
    print(f"#{issue}: {verdict} recorded ({found}, labels: {', '.join(sorted(labels)) or 'none'}"
          + (f", card -> {to})" if to else ")"))
    _append(run_dir, f"| #{issue} | {verdict} |")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render and record one /gogogo:auto-test outcome.")
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("column", help="the column under test")
    sub.add_parser("version", help="the stamp; the plugin's source on stderr")
    p = sub.add_parser("last", help="the newest verdict marker on an issue")
    p.add_argument("issue", type=int)
    p.add_argument("--repo")
    p = sub.add_parser("render", help="write <run-dir>/comment-<n>.md from a JSON spec on stdin")
    p.add_argument("run_dir")
    p.add_argument("issue", type=int)
    p.add_argument("--build", required=True)
    p.add_argument("--model", required=True)
    p = sub.add_parser("apply", help="comment, then labels, close and card, then read the issue back")
    p.add_argument("run_dir")
    p.add_argument("issue", type=int)
    p.add_argument("verdict", choices=sorted(VERDICTS))
    p.add_argument("--repo")
    args = parser.parse_args(argv)
    plugin_root = HERE.parent

    try:
        path, settings, sections = load(args.profile)
        col = column(settings)
        repo = getattr(args, "repo", None) or settings["tracker"]["issues_repo"]
        if args.command == "column":
            print(col)
        elif args.command == "version":
            print(stamp(plugin_root, sections.get("Test data", "")))
            print(source(plugin_root), file=sys.stderr)
        elif args.command == "last":
            print(last(settings, args.issue, repo))
        elif args.command == "render":
            try:
                spec = json.load(sys.stdin)
            except json.JSONDecodeError as exc:
                raise Stop(f"spec: not valid JSON ({exc})") from None
            print(render(settings, sections, args.run_dir, args.issue, args.build, args.model, spec, plugin_root))
        elif args.command == "apply":
            apply(settings, path, args.run_dir, args.issue, args.verdict, repo)
    except Stop as exc:
        for line in str(exc).splitlines():
            print(f"error: {line}", file=sys.stderr)
        return EXIT_STOP
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
