#!/usr/bin/env python3
"""Number, tag and describe a production release: deploy-<build>, <major>.0.<build>.

    release.py [--profile FILE] build [--ref REF]
    release.py [--profile FILE] version [--ref REF]
    release.py [--profile FILE] tag [--ref REF] [--push REMOTE] [--dry-run]
    release.py [--profile FILE] notes --tag TAG [--titles]
    release.py [--profile FILE] announce --tag TAG [--main-ref REF] [--only release|sync|notify] [--dry-run]

`build` prints the commit count of REF, the number people say; `version` prints
`<release.major>.0.<build>`; `tag` cuts the annotated `deploy-<build>` tag with
generated notes, after the deploy has succeeded; `notes` prints those notes for
an existing tag. `announce` is the deploy's one announcement for a tag, in
three jobs: the GitHub Release (created when missing), the cards the tag ships
(moved as `stage_sync.py sync` moves them), and one `deployed` message, sent
once: the Release's notes are marked when it went. Each job says one line; a
failed one prints the command that retries it alone, and the next still runs.
The standard is references/versioning.md.

The build needs full history and the base branch: a shallow clone counts only
what it has, and a commit on another branch can share a count with one on the
base. Both are refused. A re-run on an already tagged commit creates nothing;
with --push it pushes the existing tag again, so a retry after a failed push
still reaches the remote, and a remote that already has it is left as it is.

Exit codes: 0 ok (including "already tagged", and `announce` whatever its jobs
did: it never fails the deploy); 2 profile or usage error, or `announce` for a
tag this clone does not have; 3 refused; 4 the tag exists here but not on the
remote.

Standard library only; the notes come from stage_sync.py's readers, imported.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import notify  # noqa: E402
import profile_check  # noqa: E402
import stage_sync  # noqa: E402

EXIT_OK, EXIT_PROFILE, EXIT_REFUSED, EXIT_NOT_PUSHED = 0, 2, 3, 4
GLOB = "deploy-*"
FIRST = f"first {GLOB} release; nothing to compare with"
ANNOUNCED = "<!-- gogogo:announced -->"
JOBS = ("release", "sync", "notify")


class Refused(Exception):
    """A release that must not be cut: exit 3."""


class ProfileProblem(Exception):
    """A setting the command needs is missing or wrong: exit 2."""


def git(*args: str) -> str:
    try:
        return stage_sync.git(*args).strip()
    except stage_sync.SyncError as exc:
        raise Refused(str(exc)) from None


def build(ref: str) -> int:
    if git("rev-parse", "--is-shallow-repository") == "true":
        raise Refused("shallow clone: the build number needs full history (fetch with depth 0)")
    return int(git("rev-list", "--count", ref))


def load(path: str | None) -> stage_sync.Profile:
    try:
        return stage_sync.load_profile(path)
    except stage_sync.SyncError as exc:
        raise ProfileProblem(str(exc)) from None


def major(profile: stage_sync.Profile) -> int:
    value, present = profile_check._lookup(profile.settings, "release.major")
    if not present:
        raise ProfileProblem(f"release.major: missing. {profile_check.FIELDS['release.major'][2]}")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProfileProblem("release.major: must be a whole number, 1 or more")
    return value


def version(profile: stage_sync.Profile, build_number: int) -> str:
    # minor: fixed at 0 until Vorski-Imagineering/gogogo#14 decides how it is derived
    return f"{major(profile)}.0.{build_number}"


def production(profile: stage_sync.Profile) -> str:
    for env in profile.settings.get("environments") or []:
        if isinstance(env, dict) and "production" in (env.get("roles") or []):
            return env.get("name") or ""
    raise ProfileProblem("environments: no environment has the role production")


def previous(name: str, sha: str) -> str | None:
    """The deploy-* tag before `name`. A deploy-* tag already on the same commit (an old
    date-named one, before `name` exists) is that release, so nothing is listed twice."""
    if not subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{name}"],
                          capture_output=True).returncode:
        return stage_sync.previous_tag(name, GLOB)
    on_commit = git("tag", "--points-at", sha, "--list", GLOB, "--sort=creatordate").split()
    return on_commit[-1] if on_commit else stage_sync.previous_tag(sha, GLOB)


def body(name: str, sha: str, profile: stage_sync.Profile, titles: bool) -> str:
    """The notes for `name` at `sha`: what it ships since the previous deploy-* tag."""
    prev = previous(name, sha)
    if prev is None:
        return FIRST + "\n"
    result = stage_sync.shipped(sha, prev, profile.known, profile.issues_repo)
    names = stage_sync.fetch_titles(result.links) if titles else None
    return stage_sync.render_shipped(name, production(profile), result, names)


def cmd_build(args, _profile_path) -> int:
    print(build(args.ref))
    return EXIT_OK


def cmd_version(args, profile_path) -> int:
    profile = load(profile_path)
    print(version(profile, build(args.ref)))
    return EXIT_OK


def cmd_tag(args, profile_path) -> int:
    profile = load(profile_path)
    number = build(args.ref)
    name = f"deploy-{number}"
    sha = git("rev-parse", f"{args.ref}^{{commit}}")
    release = version(profile, number)
    environment = production(profile)
    base = (profile.settings.get("integration") or {}).get("base")
    if not base:
        raise ProfileProblem("integration.base: missing; a build number is counted on the base branch")

    if not stage_sync.is_ancestor(sha, f"origin/{base}"):
        raise Refused(f"{sha[:7]} is not on origin/{base}; a build number only identifies a commit "
                      "on the base branch (fetch first if it is)")
    existing = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{commit}}"],
                              capture_output=True, text=True).stdout.strip()
    if existing and existing != sha:
        raise Refused(f"{name} already names {existing[:7]}; history was rewritten")
    if existing:
        print(f"already tagged: {name}")
    else:
        if args.dry_run:
            print(f"{name}\n\n{message(name, sha, release, environment, profile)}", end="")
            return EXIT_OK
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(message(name, sha, release, environment, profile))
        try:
            git("tag", "-a", name, "-F", fh.name, sha)
        finally:
            Path(fh.name).unlink(missing_ok=True)
        print(f"tagged {name} ({release})")

    # Pushed again when already tagged: a retry after a failed push must still reach the
    # remote, and a push of a tag the remote already has changes nothing there.
    if args.push and not args.dry_run:
        pushed = subprocess.run(["git", "push", args.push, f"refs/tags/{name}"], capture_output=True, text=True)
        if pushed.returncode != 0 and remote_commit(args.push, name) == sha:
            # The remote has a tag of that name on this commit (another machine cut it): released.
            print(f"{name} is already on {args.push}")
            return EXIT_OK
        if pushed.returncode != 0:
            print(f"error: tagged {name} locally but the push failed; retry: "
                  f"git push {args.push} refs/tags/{name}\n{pushed.stderr.strip()}", file=sys.stderr)
            return EXIT_NOT_PUSHED
        print(f"pushed {name} to {args.push}")
    return EXIT_OK


def remote_commit(remote: str, name: str) -> str | None:
    """The commit `name` names on `remote`, or None when it has no such tag or cannot be read."""
    proc = subprocess.run(["git", "ls-remote", remote, f"refs/tags/{name}^{{}}", f"refs/tags/{name}"],
                          capture_output=True, text=True)
    refs = dict(reversed(line.split("\t")) for line in proc.stdout.splitlines() if "\t" in line)
    return refs.get(f"refs/tags/{name}^{{}}") or refs.get(f"refs/tags/{name}") if proc.returncode == 0 else None


def message(name: str, sha: str, release: str, environment: str, profile: stage_sync.Profile) -> str:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return (f"Release {release} · {sha[:7]}\nDeployed {when} UTC to {environment}\n\n"
            + body(name, sha, profile, titles=False))


def cmd_notes(args, profile_path) -> int:
    profile = load(profile_path)
    try:
        sha = stage_sync.resolve_tag(args.tag)
    except stage_sync.SyncError as exc:
        raise Refused(str(exc)) from None
    sys.stdout.write(body(args.tag, sha, profile, args.titles))
    return EXIT_OK


def gh(*args: str) -> subprocess.CompletedProcess:
    """Every `gh` call `announce` makes (the tests replace it)."""
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def release_notes(tag: str) -> str | None:
    """The Release's notes, or None when there is no Release for `tag`. Any other
    failure to read it raises, so a Release that exists is never taken as missing."""
    view = gh("release", "view", tag, "--json", "body", "-q", ".body")
    if view.returncode == 0:
        return view.stdout
    if "release not found" in view.stderr:
        return None
    raise RuntimeError(view.stderr.strip() or f"gh release view exited {view.returncode}")


def readable_notes(tag: str) -> str | None:
    """For a dry run, which writes nothing: an unreadable Release reads as no Release."""
    try:
        return release_notes(tag)
    except RuntimeError:
        return None


def write_notes(text: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
    return fh.name


def job_release(tag: str, sha: str, profile: stage_sync.Profile, dry_run: bool) -> tuple[str, str]:
    if dry_run:
        return ("exists", "release: exists") if readable_notes(tag) is not None \
            else ("would create", "release: would create")
    if release_notes(tag) is not None:
        return "exists", "release: exists"
    path = write_notes(body(tag, sha, profile, titles=True))
    try:
        made = gh("release", "create", tag, "--verify-tag", "--title", tag, "--notes-file", path)
    finally:
        Path(path).unlink(missing_ok=True)
    if made.returncode != 0:
        raise RuntimeError(made.stderr.strip() or f"gh release create exited {made.returncode}")
    return "created", "release: created"


def job_sync(tag: str, profile: stage_sync.Profile, main_ref: str, dry_run: bool) -> tuple[str, str]:
    if not stage_sync.matching_stages(profile, tag):
        return "skipped", f"sync: no stage takes {tag}; skipped"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = stage_sync.sync(profile, tag, main_ref, dry_run)
    if code == 2:
        raise RuntimeError("a card's comment failed, so it was not moved")
    lines = out.getvalue().splitlines()
    if dry_run:
        n = sum(1 for line in lines if line.split(" ", 1)[0] == stage_sync.MOVE)
        return f"would move {n}", f"sync: would move {n} card(s)"
    n = sum(1 for line in lines if " -> " in line and ": " in line)
    return f"moved {n}", f"sync: {n} card(s) moved"


def deployed_event(tag: str, sha: str, profile: stage_sync.Profile) -> dict:
    """The `deployed` event `stage_sync.py shipped --json` builds: the matching stage's
    environment and glob, else production's and deploy-*. When it cannot be built, the
    event the stage-sync workflow sends then: the issue list unavailable."""
    try:
        matched = stage_sync.matching_stages(profile, tag)
        if matched:
            environment, glob = profile.environment(matched[0][1])[0], matched[0][1]["tag"]
            prev = stage_sync.previous_tag(tag, glob)
        else:
            environment, prev = production(profile), previous(tag, sha)
        if prev is None:
            return {"event": "deployed", "tag": tag, "environment": environment, "first": True}
        result = stage_sync.shipped(sha, prev, profile.known, profile.issues_repo)
        return stage_sync.shipped_event(tag, environment, result, stage_sync.fetch_titles(result.links))
    except ProfileProblem:
        raise
    except Exception:  # noqa: BLE001 - the message still goes, without its list
        return {"event": "deployed", "tag": tag, "unavailable": True}


def send(profile: stage_sync.Profile, event: dict) -> tuple[int, str]:
    """`notify.py send --event`, in this process: its exit code and what it printed."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), _stdin(json.dumps(event)):
        code = notify.main(["--profile", str(profile.path), "send", "--event"])
    return code, out.getvalue().strip()


@contextlib.contextmanager
def _stdin(text: str):
    saved, sys.stdin = sys.stdin, io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = saved


def job_notify(tag: str, sha: str, profile: stage_sync.Profile, dry_run: bool) -> tuple[str, str]:
    if dry_run:
        notes = readable_notes(tag)
        return ("already sent", "notify: already sent") if notes is not None and ANNOUNCED in notes \
            else ("would send", "notify: would send")
    notes = release_notes(tag)  # unreadable: it may be marked, so nothing is sent (Approvals row 1)
    if notes is not None and ANNOUNCED in notes:
        return "already sent", "notify: already sent"
    code, said = send(profile, deployed_event(tag, sha, profile))
    if code != 0:
        raise RuntimeError(said or f"notify.py exited {code}")
    if said != "sent":
        return "off", "notify: off; not marked"
    try:
        notes = release_notes(tag)
    except RuntimeError as exc:
        return "sent", f"notify: sent; not marked ({exc})"
    if notes is None:
        return "sent", "notify: sent; not marked (no Release)"
    path = write_notes(notes.rstrip("\n") + f"\n\n{ANNOUNCED}\n")
    try:
        edited = gh("release", "edit", tag, "--notes-file", path)
    finally:
        Path(path).unlink(missing_ok=True)
    if edited.returncode != 0:
        return "sent", f"notify: sent; not marked ({edited.stderr.strip() or 'gh release edit failed'})"
    return "sent", "notify: sent"


def cmd_announce(args, profile_path) -> int:
    found = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{args.tag}^{{commit}}"],
                           capture_output=True, text=True)
    if found.returncode != 0:
        print(f"error: no tag {args.tag} in this clone; nothing announced", file=sys.stderr)
        return EXIT_PROFILE
    sha = found.stdout.strip()
    try:
        profile, problem = load(profile_path), None
    except ProfileProblem as exc:  # the tag exists, so each job fails and the deploy does not
        profile, problem = None, exc
    run = {
        "release": lambda: job_release(args.tag, sha, profile, args.dry_run),
        "sync": lambda: job_sync(args.tag, profile, args.main_ref, args.dry_run),
        "notify": lambda: job_notify(args.tag, sha, profile, args.dry_run),
    }
    summary = []
    for job in JOBS:
        if args.only and job != args.only:
            continue
        try:
            if problem is not None:
                raise problem
            value, line = run[job]()
        except Exception as exc:  # noqa: BLE001 - a failed job never fails the deploy
            value, line = "failed", (f"{job}: failed: {exc}; retry: python3 {Path(__file__).resolve()} "
                                     f"announce --tag {args.tag} --only {job}")
        print(line, flush=True)
        summary.append(f"{job}={value}")
    print(f"announce: {args.tag} {' '.join(summary)}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--profile",
                        help="profile file (default: the nearest .agents/dev-process.md above this folder)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, helptext in (("build", "print the build number"), ("version", "print <major>.0.<build>")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--ref", default="HEAD")
    tag = sub.add_parser("tag", help="cut the annotated deploy-<build> tag, after a successful deploy")
    tag.add_argument("--ref", default="HEAD")
    tag.add_argument("--push", metavar="REMOTE", help="push the tag to REMOTE")
    tag.add_argument("--dry-run", action="store_true", help="print the tag and its message; create nothing")
    notes = sub.add_parser("notes", help="print the notes for an existing tag")
    notes.add_argument("--tag", required=True)
    notes.add_argument("--titles", action="store_true", help="add issue titles (needs gh)")
    announce = sub.add_parser("announce", help="the Release, the cards and one message for a deploy tag")
    announce.add_argument("--tag", required=True)
    announce.add_argument("--main-ref", default="origin/main", help="where the merged trailers are read")
    announce.add_argument("--only", choices=JOBS, help="run this job alone (a retry)")
    announce.add_argument("--dry-run", action="store_true", help="say what each job would do; write nothing")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_PROFILE

    handler = {"build": cmd_build, "version": cmd_version, "tag": cmd_tag, "notes": cmd_notes,
               "announce": cmd_announce}[args.command]
    try:
        return handler(args, args.profile)
    except ProfileProblem as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROFILE
    except (Refused, stage_sync.SyncError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
