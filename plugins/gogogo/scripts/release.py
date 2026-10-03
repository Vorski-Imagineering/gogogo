#!/usr/bin/env python3
"""Number, tag and describe a production release: deploy-<build>, <major>.0.<build>.

    release.py [--profile FILE] build [--ref REF]
    release.py [--profile FILE] version [--ref REF]
    release.py [--profile FILE] tag [--ref REF] [--push REMOTE] [--dry-run]
    release.py [--profile FILE] notes --tag TAG [--titles]

`build` prints the commit count of REF, the number people say; `version` prints
`<release.major>.0.<build>`; `tag` cuts the annotated `deploy-<build>` tag with
generated notes, after the deploy has succeeded; `notes` prints those notes for
an existing tag. The standard is references/versioning.md.

The build needs full history and the base branch: a shallow clone counts only
what it has, and a commit on another branch can share a count with one on the
base. Both are refused. A re-run on an already tagged commit creates nothing;
with --push it pushes the existing tag again, so a retry after a failed push
still reaches the remote, and a remote that already has it is left as it is.

Exit codes: 0 ok (including "already tagged"); 2 profile or usage error;
3 refused; 4 the tag exists here but not on the remote.

Standard library only; the notes come from stage_sync.py's readers, imported.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile_check  # noqa: E402
import stage_sync  # noqa: E402

EXIT_OK, EXIT_PROFILE, EXIT_REFUSED, EXIT_NOT_PUSHED = 0, 2, 3, 4
GLOB = "deploy-*"
FIRST = f"first {GLOB} release; nothing to compare with"


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
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_PROFILE

    handler = {"build": cmd_build, "version": cmd_version, "tag": cmd_tag, "notes": cmd_notes}[args.command]
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
