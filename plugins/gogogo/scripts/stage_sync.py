#!/usr/bin/env python3
"""Link merged commits to issues, and move cards to a stage when a tag ships them.

    stage_sync.py [--profile FILE] trailer (--issue ISSUE ... | --branch NAME) [--verify] [--co-authors-from RANGE]
    stage_sync.py [--profile FILE] sync --tag TAG [--main-ref REF] [--dry-run]
    stage_sync.py [--profile FILE] shipped --tag TAG [--titles]

`trailer` prints the `Ships-issue` lines a squash commit carries; `sync` moves
every card whose linked commits are all in a tag to the stage whose `tag` glob
matches it; `shipped` lists what a tag ships since the previous matching tag.

Which issue a commit fixes lives in git, as a `Ships-issue` trailer on the
squash commit, not on the board: a CI runner or a deploy box with no `gh` can
then read it, and there is no second store to disagree with the history. This
script is the only writer and the only reader of that format. See
`references/stage-sync.md`.

The board, the issues repo, the stages and their tags all come from the profile
(`--profile`, default the nearest `.agents/dev-process.md`). Every board read
and move goes through `tracker.py`, given that same profile.

Exit codes: 0 ok; 1 (`sync`) every possible move was made and something needs
a look (a card with no linked commit, or a reporter that could not be
assigned); 2 nothing trustworthy to act on, or a comment or move failed;
3 (`trailer --verify`) every issue exists but a reporter cannot be assigned.
An unexpected crash exits 2, never 1.

Standard library only; imports `profile_check` and `tracker` from this folder,
so a vendored copy works when the three files sit side by side.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile_check  # noqa: E402
import tracker  # noqa: E402

TRAILER_KEY = "Ships-issue"
CO_AUTHOR_KEY = "Co-Authored-By"

#: A chat message has a size limit (4096 characters is common), and a release
#: after a long gap can ship dozens of issues.
SHIPPED_LIMIT = 25
TITLE_MAX = 120


class SyncError(Exception):
    """Nothing trustworthy to act on, or a write that did not happen."""


# --------------------------------------------------------------------------
# the profile
# --------------------------------------------------------------------------


@dataclass
class Profile:
    path: Path
    settings: dict

    @property
    def tracker(self) -> dict:
        return self.settings.get("tracker") or {}

    @property
    def issues_repo(self) -> str:
        return self.tracker.get("issues_repo") or ""

    @property
    def known(self) -> dict[str, str]:
        """Repo name -> owner/name for the legacy short form, issues repo first."""
        known: dict[str, str] = {}
        for repo in (self.issues_repo, self.tracker.get("code_repo") or ""):
            if "/" in repo:
                known.setdefault(repo.split("/", 1)[1], repo)
        return known

    @property
    def reporter_mode(self) -> str:
        return (self.settings.get("handback") or {}).get("reporter") or "none"

    @property
    def stages(self) -> list[dict]:
        stages = self.settings.get("stages")
        return [s for s in stages if isinstance(s, dict)] if isinstance(stages, list) else []

    def tagged_stages(self) -> list[tuple[int, dict]]:
        return [(i, s) for i, s in enumerate(self.stages) if isinstance(s.get("tag"), str) and s["tag"]]

    def environment(self, stage: dict) -> tuple[str, str]:
        """(name, where): the stage's environment name, and its url or else its name."""
        name = stage.get("environment") or stage.get("column") or ""
        env = profile_check.environment(self.settings, name) or {}
        return name, env.get("url") or name


def load_profile(path: str | None) -> Profile:
    profile_path = Path(path) if path else profile_check.find_profile()
    if not profile_path.is_file():
        raise SyncError(f"no profile at {profile_path}")
    try:
        settings, _ = profile_check.split_profile(profile_path.read_text(encoding="utf-8"))
    except (OSError, profile_check.ProfileError) as exc:
        raise SyncError(f"{profile_path}: {exc}") from None
    profile = Profile(profile_path, settings)
    if "/" not in profile.issues_repo:
        raise SyncError(f"tracker.issues_repo: missing or not owner/name in {profile_path}")
    return profile


# --------------------------------------------------------------------------
# The link format — one writer, one reader
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IssueLink:
    repo: str  # always owner/name
    number: int
    reporter: str | None = None  # GitHub login, or None

    @property
    def key(self) -> tuple[str, int]:
        return (self.repo, self.number)

    def ref(self) -> str:
        return f"{self.repo}#{self.number}"

    def short(self) -> str:
        return f"{self.repo.split('/', 1)[-1]}#{self.number}"


_LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_NAME = r"[A-Za-z0-9._-]+"
_NUMBER = r"[1-9]\d*"
_TRAILER_VALUE = re.compile(
    rf"^(?:(?P<owner>{_LOGIN})/)?(?P<name>{_NAME})#(?P<number>{_NUMBER})"
    rf"(?: reporter=(?P<reporter>{_LOGIN}))?$"
)
_ISSUE_ARG = re.compile(
    rf"^(?:(?:(?P<owner>{_LOGIN})/)?(?P<name>{_NAME})#)?(?P<number>{_NUMBER})"
    rf"(?:=(?P<reporter>{_LOGIN}))?$"
)
_FIX_BRANCH = re.compile(r"^fix/([1-9]\d*)-")


def _repo(match: re.Match, known: dict[str, str], default: str | None) -> str | None:
    """owner/name for a parsed reference; a bare name only when it is known."""
    if match["owner"]:
        return f"{match['owner']}/{match['name']}"
    if match["name"]:
        return known.get(match["name"])
    return default


def format_trailer(link: IssueLink) -> str:
    """`Ships-issue: owner/repo#450`, or with ` reporter=<login>` appended.

    `Ships-issue`, not `Fixes`/`Closes`: those are GitHub closing keywords and
    would close the issue at merge, before anyone has seen the fix live.
    """
    value = link.ref()
    if link.reporter:
        value += f" reporter={link.reporter}"
    return f"{TRAILER_KEY}: {value}"


def parse_trailer(value: str, known: dict[str, str]) -> IssueLink:
    """The trailer's value (after `Ships-issue:`) back into a link.

    Reads the full form for any owner/name, and the legacy short form
    `<name>#<n>` only for a name in `known` (the issues and code repos).
    """
    match = _TRAILER_VALUE.match(value.strip())
    repo = _repo(match, known, None) if match else None
    if not repo:
        raise ValueError(f"not a {TRAILER_KEY} value: {value!r}")
    return IssueLink(repo, int(match["number"]), match["reporter"])


def parse_issue_arg(arg: str, known: dict[str, str]) -> IssueLink:
    """`450`, `450=jdoe`, `owner/repo#12[=jdoe]`, `repo#12[=jdoe]`; a bare
    number is the issues repo (the first of `known`)."""
    match = _ISSUE_ARG.match(arg.strip())
    repo = _repo(match, known, next(iter(known.values()), None)) if match else None
    if not repo:
        raise ValueError(
            f"not an issue: {arg!r} (expected <n>, <n>=<login>, <owner/repo>#<n>[=<login>]"
            f" or one of {', '.join(f'{name}#<n>' for name in known)})"
        )
    return IssueLink(repo, int(match["number"]), match["reporter"])


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SyncError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def resolve_tag(tag: str) -> str:
    """The commit a tag names. An unresolvable tag is an error, never "nothing to move"."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SyncError(f"no such tag: {tag}")
    return proc.stdout.strip()


def is_ancestor(sha: str, tag: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, tag], capture_output=True, text=True
    )
    # 128: the sha is unknown here. Treat as "not shipped", never as shipped.
    return proc.returncode == 0


@dataclass
class Commit:
    sha: str
    links: list[IssueLink]


def commits_with_trailers(rev_range: str, known: dict[str, str]) -> list[Commit]:
    """Every commit in the range, oldest first, with its `Ships-issue` links.

    Git only parses the final paragraph of a message as trailers, and only
    if the whole paragraph is trailers — so a body laid out wrongly yields no
    link here, which is what the round-trip tests pin.
    """
    out = git(
        "log", "--reverse",
        f"--format=%H%x00%(trailers:key={TRAILER_KEY},valueonly,separator=%x1f)%x1e",
        rev_range,
    )
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, values = record.partition("\x00")
        links = []
        for value in filter(None, (v.strip() for v in values.split("\x1f"))):
            try:
                links.append(parse_trailer(value, known))
            except ValueError:
                print(f"warning: {sha[:8]} has an unreadable {TRAILER_KEY}: {value!r}",
                      file=sys.stderr)
        commits.append(Commit(sha, links))
    return commits


@dataclass
class Linked:
    shas: list[str] = field(default_factory=list)
    reporters: list[str] = field(default_factory=list)


def trailer_links(main_ref: str, known: dict[str, str]) -> dict[tuple[str, int], Linked]:
    """`{(owner/repo, number): Linked(shas, reporters)}` over the whole of `main_ref`."""
    links: dict[tuple[str, int], Linked] = {}
    for commit in commits_with_trailers(main_ref, known):
        for link in commit.links:
            entry = links.setdefault(link.key, Linked())
            if commit.sha not in entry.shas:
                entry.shas.append(commit.sha)
            if link.reporter and link.reporter not in entry.reporters:
                entry.reporters.append(link.reporter)
    return links


def co_author_lines(rev_range: str) -> list[str]:
    """The `Co-Authored-By` trailers of every commit in the range, de-duplicated
    case-insensitively, first spelling kept, in first-seen order."""
    out = git("log", f"--format=%(trailers:key={CO_AUTHOR_KEY},valueonly=false)", rev_range)
    seen: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if line:
            seen.setdefault(line.lower(), line)
    return list(seen.values())


# --------------------------------------------------------------------------
# trailer
# --------------------------------------------------------------------------


def verify_links(links: list[IssueLink]) -> tuple[list[str], list[str]]:
    """(issues that do not exist, reporters that cannot be assigned), as messages.

    A trailer is permanent once on the base branch, so a number that does not
    exist, or a login that cannot be assigned, can no longer be corrected after
    the merge. This catches a number that does not exist, not a wrong-but-real
    one: nothing here knows which issue was meant.
    """
    missing, unassignable = [], []
    for link in links:
        if subprocess.run(["gh", "issue", "view", str(link.number), "--repo", link.repo,
                           "--json", "number"], capture_output=True).returncode:
            missing.append(f"{link.ref()} does not exist (or cannot be read): "
                           "check the --issue number.")
        if link.reporter and subprocess.run(
            ["gh", "api", f"repos/{link.repo}/assignees/{link.reporter}", "--silent"],
            capture_output=True,
        ).returncode:
            unassignable.append(f"'{link.reporter}' cannot be assigned issues in {link.repo}: "
                                "check the reporter login.")
    return missing, unassignable


def cmd_trailer(args: argparse.Namespace, profile: Profile) -> int:
    known = profile.known
    if args.issue:
        try:
            links = [parse_issue_arg(a, known) for a in args.issue]
        except ValueError as exc:
            print(f"stage_sync.py: {exc}", file=sys.stderr)
            return 2
    elif args.branch:
        match = _FIX_BRANCH.match(args.branch)
        if not match:
            print(f"stage_sync.py: the branch '{args.branch}' names no issue; "
                  "pass --issue <n>[=<reporter-login>]", file=sys.stderr)
            return 2
        links = [IssueLink(profile.issues_repo, int(match[1]))]
    else:
        print("stage_sync.py: no issue; pass --issue <n>[=<reporter-login>] or --branch <name>",
              file=sys.stderr)
        return 2

    if args.verify:
        missing, unassignable = verify_links(links)
        for problem in missing + unassignable:
            print(f"stage_sync.py: {problem}", file=sys.stderr)
        if missing:
            return 2
        if unassignable:
            return 3

    lines = [format_trailer(link) for link in links]
    if args.co_authors_from:
        lines += co_author_lines(args.co_authors_from)
    # Nothing reaches stdout until every check has passed.
    print("\n".join(lines))
    return 0


# --------------------------------------------------------------------------
# sync — the decision is pure; the writes come after, in a fixed order
# --------------------------------------------------------------------------

MOVE, STAY, UNLINKED = "MOVE", "STAY", "UNLINKED"


@dataclass(frozen=True)
class Decision:
    kind: str
    key: tuple[str, int]
    shas: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()  # the shas not in the tag, for STAY
    reporters: tuple[str, ...] = ()

    def ref(self) -> str:
        return f"{self.key[0]}#{self.key[1]}"


def card_key(card: dict, issues_repo: str) -> tuple[str, int]:
    return (card.get("repo") or issues_repo, card["number"])


def plan(card: dict, links: dict[tuple[str, int], Linked], is_shipped, issues_repo: str) -> Decision:
    """MOVE when every linked commit is in the tag, STAY when one is not.

    Every, not any: one issue can have several commits, and a refix after a
    failed check adds one. A card whose newest fix has not shipped is not done
    at that stage, whatever the older commits say.
    """
    key = card_key(card, issues_repo)
    linked = links.get(key)
    if not linked or not linked.shas:
        return Decision(UNLINKED, key)
    missing = tuple(s for s in linked.shas if not is_shipped(s))
    kind = STAY if missing else MOVE
    return Decision(kind, key, tuple(linked.shas), missing, tuple(linked.reporters))


def run(cmd: list[str]) -> int:
    """Every external write goes through here, so the order is observable."""
    return subprocess.run(cmd).returncode


def tracker_cmd(profile: Profile, *args: str) -> list[str]:
    """tracker.py from this folder, always given this run's profile: a CI run
    must never read whatever profile its working directory happens to find."""
    return [sys.executable, str(HERE / "tracker.py"), "--profile", str(profile.path), *args]


def authenticated_login() -> str | None:
    """The login `gh` is authenticated as, or None when it cannot be read."""
    try:
        proc = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _marker_tail(decision: Decision) -> str:
    """The marker's tail — what `already_announced` matches on. One builder, so
    the writer and the reader cannot drift apart."""
    return f"shas={','.join(s[:8] for s in decision.shas)} -->"


def marker(tag: str, decision: Decision) -> str:
    return f"<!-- stage-sync tag={tag} {_marker_tail(decision)}"


#: The markers an earlier sync may have left. `board-sync` is the older name of
#: this script's marker, still on issues it announced.
MARKER_PREFIXES = ("<!-- stage-sync ", "<!-- board-sync ")


def already_announced(repo: str, number: str, decision: Decision) -> bool:
    """Whether an earlier sync already posted the comment for these commits.

    A sync that commented and then failed to move leaves the card where it was,
    and the next tag plans it again; without this it would comment again on
    every tag. Keyed on the shas, not the tag: the same fix is announced once.
    A failed read answers False — a duplicate comment beats a missing one.
    """
    tail = _marker_tail(decision)
    proc = subprocess.run(
        ["gh", "issue", "view", number, "--repo", repo, "--json", "comments",
         "-q", ".comments[].body"],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and any(
        any(p in line for p in MARKER_PREFIXES) and line.rstrip().endswith(tail)
        for line in proc.stdout.splitlines()
    )


def live_comment(tag: str, decision: Decision, where: str, mention: bool) -> str:
    """A public tracker publishes this: the tag, the environment's url from the
    profile, and logins already on the issue. Nothing else."""
    lines = [f"**Now live on {where}** in `{tag}`.", ""]
    if mention and decision.reporters:
        mentions = " ".join(f"@{r}" for r in decision.reporters)
        lines += [
            f"{mentions} — please check it there, and close this issue if it is "
            "fixed or say what is still wrong.",
            "",
        ]
    lines.append(marker(tag, decision))
    return "\n".join(lines) + "\n"


@dataclass
class Move:
    """One stage's move: the tag, the columns, and how to talk about it."""
    profile: Profile
    tag: str
    glob: str
    source: str
    target: str
    where: str


def apply_move(move: Move, decision: Decision, card: dict, me: str | None) -> str:
    """Check, comment, assign, move — in that order.

    Returns "moved", "moved-unassigned" (the reporter could not be assigned;
    the comment already mentions them) or "skipped" (a person moved the card
    first). Raises on a failed comment or move: a card must never reach its new
    column without its comment. A failed assignment does not raise — it would
    fail again on every tag and block every card behind this one.
    """
    repo, number = decision.key[0], str(decision.key[1])
    ref = decision.ref()

    code = run(tracker_cmd(move.profile, "show", number, "--repo", repo, "--expect", move.source))
    if code == 3:
        return "skipped"
    if code != 0:
        raise SyncError(f"{ref}: could not confirm the card is in {move.source} (exit {code})")

    if not already_announced(repo, number, decision):
        mention = move.profile.reporter_mode == "trailer"
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as body:
            body.write(live_comment(move.tag, decision, move.where, mention))
        try:
            if run(["gh", "issue", "comment", number, "--repo", repo, "--body-file", body.name]):
                raise SyncError(f"{ref}: comment failed; card not moved")
        finally:
            Path(body.name).unlink(missing_ok=True)

    outcome = "moved"
    if move.profile.reporter_mode == "trailer" and decision.reporters:
        cmd = ["gh", "issue", "edit", number, "--repo", repo,
               "--add-assignee", ",".join(decision.reporters)]
        if me and me in card.get("assignees", []) and me not in decision.reporters:
            cmd += ["--remove-assignee", me]
        if run(cmd):
            outcome = "moved-unassigned"

    if run(tracker_cmd(move.profile, "move", number, "--repo", repo, "--to", move.target)):
        raise SyncError(f"{ref}: commented, but the move did not verify")
    return outcome


def matching_stages(profile: Profile, tag: str) -> list[tuple[int, dict]]:
    """The stages whose `tag` glob matches `tag`, in stage order."""
    return [(i, s) for i, s in profile.tagged_stages() if fnmatch.fnmatchcase(tag, s["tag"])]


def no_stage_matches(profile: Profile, tag: str) -> SyncError:
    tagged = ", ".join(f"{s.get('column')} ({s['tag']})" for _, s in profile.tagged_stages())
    return SyncError(f"no stage's tag matches {tag}; stages with a tag: {tagged or 'none'}")


def sync(profile: Profile, tag: str, main_ref: str, dry_run: bool) -> int:
    if profile.tracker.get("kind") != "github-project":
        raise SyncError(f"tracker.kind is {profile.tracker.get('kind')!r}; "
                        "sync moves cards on a github-project board only")
    resolve_tag(tag)  # before any read of the board, and before any write

    matched = matching_stages(profile, tag)
    if not matched:
        raise no_stage_matches(profile, tag)
    moves = []
    for i, stage in matched:
        if i == 0:
            raise SyncError(f"stages[0] ({stage.get('column')}) has a tag; a merge puts a card "
                            "in the first stage, not a tag")
        _, where = profile.environment(stage)
        moves.append(Move(profile, tag, stage["tag"], profile.stages[i - 1]["column"],
                          stage["column"], where))

    # Every column this sync reads and writes, before anything is read or
    # written: a card must not get its public comment and then fail to move.
    tracker.configure(str(profile.path))
    meta = tracker.board_meta()
    for move in moves:
        tracker.require_columns(meta, [move.source, move.target])

    links = trailer_links(main_ref, profile.known)
    me, me_read = None, False
    unassigned, unlinked_total = [], 0

    for move in moves:
        cards, _recovered, _total = tracker.list_cards(
            status=move.source, open_only=True, issues_only=True, repo=tracker.DEFAULT_REPO
        )
        decisions = [(plan(c, links, lambda s: is_ancestor(s, tag), profile.issues_repo), c)
                     for c in cards]

        print(f"stage {move.target} (tag {move.glob}): cards in {move.source}")
        for decision, _card in decisions:
            shas = ",".join(s[:8] for s in decision.shas) or "-"
            note = (f"  (not in tag: {','.join(s[:8] for s in decision.missing)})"
                    if decision.missing else "")
            print(f"{decision.kind:<8}  {decision.ref()}  {shas}{note}")

        if dry_run:
            print("dry run: nothing written")
        else:
            for decision, card in decisions:
                if decision.kind != MOVE:
                    continue
                if not me_read:
                    me, me_read = authenticated_login(), True
                    if me is None:
                        print("warning: could not read the login gh is authenticated as; "
                              "nobody is unassigned", file=sys.stderr)
                outcome = apply_move(move, decision, card, me)
                ref = decision.ref()
                if outcome == "skipped":
                    print(f"{ref}: no longer in {move.source} (moved by a person) - nothing written")
                    continue
                print(f"{ref}: {move.source} -> {move.target}")
                if outcome == "moved-unassigned":
                    unassigned.append(ref)
                    print(f"{ref}: could not assign {', '.join(decision.reporters)}; "
                          "the comment mentions them: assign by hand", file=sys.stderr)

        unlinked = [d.ref() for d, _ in decisions if d.kind == UNLINKED]
        if unlinked:
            unlinked_total += len(unlinked)
            print(f"{len(unlinked)} card(s) in {move.source} have no linked commit; "
                  f"move them by hand: {', '.join(unlinked)}", file=sys.stderr)

    return 1 if unlinked_total or unassigned else 0


# --------------------------------------------------------------------------
# shipped — what one tag ships, for a notification
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Shipped:
    links: list[IssueLink]
    unlinked_commits: int


def previous_tag(tag: str, glob: str) -> str | None:
    """The matching tag before `tag`, or None for the first one.

    A second tag on the same commit is answered by the tag already on it, so
    it ships nothing rather than re-announcing the first one's list.
    """
    sha = resolve_tag(tag)
    same_commit = git("tag", "--points-at", sha, "--list", glob, "--sort=creatordate").split()
    if tag in same_commit and same_commit.index(tag) > 0:
        return same_commit[same_commit.index(tag) - 1]
    proc = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", glob, f"{sha}^"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def shipped(tag: str, prev: str, known: dict[str, str]) -> Shipped:
    """The issues whose commits are in `prev..tag`, first-merged first.

    Commits with no link are counted, not dropped: a short list that silently
    omits unlinked work reads as the whole release.
    """
    seen: dict[tuple[str, int], IssueLink] = {}
    unlinked = 0
    for commit in commits_with_trailers(f"{prev}..{tag}", known):
        if not commit.links:
            unlinked += 1
        for link in commit.links:
            seen.setdefault(link.key, link)
    return Shipped(list(seen.values()), unlinked)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def render_shipped(
    tag: str,
    environment: str,
    s: Shipped,
    titles: dict[tuple[str, int], str] | None,
    limit: int = SHIPPED_LIMIT,
) -> str:
    """Plain text, no markup: titles are user-written and must not be parsed."""
    lines = [f"Deployed {tag} to {environment}", ""]
    if not s.links:
        lines.append(f"Ships no linked issues ({_plural(s.unlinked_commits, 'commit')})")
        return "\n".join(lines) + "\n"

    lines.append(f"Ships {_plural(len(s.links), 'issue')}:")
    for link in s.links[:limit]:
        title = (titles or {}).get(link.key)
        if title and len(title) > TITLE_MAX:
            title = title[: TITLE_MAX - 1].rstrip() + "…"
        lines.append(f"• {link.short()} {title}" if title else f"• {link.short()}")
    if len(s.links) > limit:
        lines.append(f"… and {len(s.links) - limit} more")
    if s.unlinked_commits:
        lines.append(f"+ {_plural(s.unlinked_commits, 'commit')} with no linked issue")
    return "\n".join(lines) + "\n"


def fetch_titles(links: list[IssueLink]) -> dict[tuple[str, int], str]:
    """Titles where `gh` can read them; a failed lookup just leaves the reference."""
    titles = {}
    for link in links[:SHIPPED_LIMIT]:
        try:
            proc = subprocess.run(
                ["gh", "issue", "view", str(link.number), "--repo", link.repo,
                 "--json", "title", "-q", ".title"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            titles[link.key] = proc.stdout.strip()
    return titles


def cmd_shipped(args: argparse.Namespace, profile: Profile) -> int:
    matched = matching_stages(profile, args.tag)
    if not matched:
        raise no_stage_matches(profile, args.tag)
    stage = matched[0][1]
    environment, _ = profile.environment(stage)
    resolve_tag(args.tag)
    prev = previous_tag(args.tag, stage["tag"])
    if prev is None:
        print(f"Deployed {args.tag} to {environment}\n\n"
              f"first tag matching {stage['tag']}; nothing to compare with")
        return 0
    result = shipped(args.tag, prev, profile.known)
    titles = fetch_titles(result.links) if args.titles else None
    sys.stdout.write(render_shipped(args.tag, environment, result, titles))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def cmd_sync(args: argparse.Namespace, profile: Profile) -> int:
    return sync(profile, args.tag, args.main_ref, args.dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--profile",
                        help="profile file (default: the nearest .agents/dev-process.md above this folder)")
    sub = parser.add_subparsers(dest="command", required=True)

    trailer = sub.add_parser("trailer", help="print Ships-issue trailer lines")
    trailer.add_argument("--issue", action="append", default=[],
                         help="<n>, <n>=<login>, <owner/repo>#<n>[=<login>] (repeatable)")
    trailer.add_argument("--branch", help="a fix/<n>-<slug> branch names issue <n>; ignored with --issue")
    trailer.add_argument("--verify", action="store_true",
                         help="also check on GitHub that each issue exists and each reporter is assignable")
    trailer.add_argument("--co-authors-from", metavar="RANGE",
                         help="append the Co-Authored-By trailers of the commits in this range")
    trailer.set_defaults(func=cmd_trailer)

    syncer = sub.add_parser("sync", help="move the cards a tag ships to the stage its glob names")
    syncer.add_argument("--tag", required=True)
    syncer.add_argument("--main-ref", default="origin/main",
                        help="the branch the tags are cut from (default origin/main)")
    syncer.add_argument("--dry-run", action="store_true")
    syncer.set_defaults(func=cmd_sync)

    ship = sub.add_parser("shipped", help="list what a tag ships since the previous matching tag")
    ship.add_argument("--tag", required=True)
    ship.add_argument("--titles", action="store_true", help="look titles up with gh")
    ship.set_defaults(func=cmd_shipped)

    args = parser.parse_args(argv)
    try:
        profile = load_profile(args.profile)
        return args.func(args, profile)
    except (SyncError, tracker.BoardError, tracker.ProfileMissing) as exc:
        print(f"stage_sync.py: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Exit 1 means "every possible move made, something needs a look"; an
        # uncaught traceback would say that too, mid-loop. A crash is a 2.
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
