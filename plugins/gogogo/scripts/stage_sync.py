#!/usr/bin/env python3
"""Link merged commits to issues, and move cards to a stage when a tag ships them.

    stage_sync.py [--profile FILE] trailer (--issue ISSUE ... | --branch NAME) [--verify] [--co-authors-from RANGE]
    stage_sync.py [--profile FILE] sync --tag TAG [--main-ref REF] [--dry-run]
    stage_sync.py [--profile FILE] shipped --tag TAG [--titles]
    stage_sync.py [--profile FILE] reverts [--main-ref REF] [--apply]

`trailer` prints the `Ships-issue` lines a squash commit carries; `sync` moves
every card whose linked commits are all in a tag to the stage whose `tag` glob
matches it; `shipped` lists what a tag ships since the previous matching tag;
`reverts` names each open card in a stage column whose shipped commit was
reverted on the base (a `This reverts commit <sha>` line, as `git revert` and
GitHub's Revert button write it), and with `--apply` comments on the issue
with a stop marker and moves its card to `tracker.columns.needs_human`.

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
assigned), (`reverts`) a shipped fix was reverted; 2 nothing trustworthy to act on, or a comment or move failed (a
failed comment leaves that card unmoved and the others still move);
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
        """Repo name (lower case) -> owner/name for the legacy short form, issues repo first."""
        known: dict[str, str] = {}
        for repo in (self.issues_repo, self.tracker.get("code_repo") or ""):
            if "/" in repo:
                known.setdefault(repo.split("/", 1)[1].lower(), repo)
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
        """What a link and a card meet on. GitHub names are case-insensitive."""
        return link_key(self.repo, self.number)

    def ref(self) -> str:
        return f"{self.repo}#{self.number}"

    def short(self) -> str:
        return f"{self.repo.split('/', 1)[-1]}#{self.number}"


def link_key(repo: str, number: int) -> tuple[str, int]:
    return (repo.lower(), number)


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
        return known.get(match["name"].lower())
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


def card_repo(card: dict, issues_repo: str) -> str:
    return card.get("repo") or issues_repo


def plan(card: dict, links: dict[tuple[str, int], Linked], is_shipped, issues_repo: str) -> Decision:
    """MOVE when every linked commit is in the tag, STAY when one is not.

    Every, not any: one issue can have several commits, and a refix after a
    failed check adds one. A card whose newest fix has not shipped is not done
    at that stage, whatever the older commits say.
    """
    key = (card_repo(card, issues_repo), card["number"])
    linked = links.get(link_key(*key))
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


def marker(tag: str, decision: Decision, stage: str) -> str:
    """`stage` is the column the card is being moved into."""
    return f"<!-- stage-sync stage={stage} tag={tag} {_marker_tail(decision)}"


#: The markers an earlier sync may have left. `board-sync` is the older name of
#: this script's marker, still on issues it announced.
MARKER_PREFIXES = ("<!-- stage-sync ", "<!-- board-sync ")
# A column may hold spaces, so the stage runs up to " tag=".
_MARKER = re.compile(r"<!-- (?:stage|board)-sync (?:stage=(?P<stage>.+?) )?tag=(?P<tag>\S+) ")


def already_announced(repo: str, number: str, decision: Decision, glob: str, stage: str) -> bool:
    """Whether an earlier sync already posted this stage's comment for these commits.

    A sync that commented and then failed to move leaves the card where it was,
    and the next tag plans it again; without this it would comment again on
    every tag. A marker counts when its shas are these commits **and** it was
    written for this stage: its `stage=` is the column being moved into
    (case-insensitive). A marker without `stage=` (the older forms) counts when
    its tag matches this stage's glob. So the same fix is announced once per
    stage, and a comment for another stage never stands in for this one, even
    when one tag matches both globs. A failed read answers False — a duplicate
    comment beats a missing one.
    """
    tail = _marker_tail(decision)
    proc = subprocess.run(
        ["gh", "issue", "view", number, "--repo", repo, "--json", "comments",
         "-q", ".comments[].body"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return False
    for line in proc.stdout.splitlines():
        line = line.rstrip()
        match = _MARKER.search(line)
        if not match or not line.endswith(tail):
            continue
        if match["stage"] is not None:
            if match["stage"].lower() == stage.lower():
                return True
        elif fnmatch.fnmatchcase(match["tag"], glob):
            return True
    return False


def live_comment(tag: str, decision: Decision, where: str, mention: bool, stage: str) -> str:
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
    lines.append(marker(tag, decision, stage))
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
    the comment already mentions them), "comment-failed" (nothing assigned or
    moved: a card must never reach its new column without its comment) or
    "skipped" (a person moved the card first). Neither a failed comment nor a
    failed assignment stops the other cards. A failed move raises.
    """
    repo, number = decision.key[0], str(decision.key[1])
    ref = decision.ref()

    code = run(tracker_cmd(move.profile, "show", number, "--repo", repo, "--expect", move.source))
    if code == 3:
        return "skipped"
    if code != 0:
        raise SyncError(f"{ref}: could not confirm the card is in {move.source} (exit {code})")

    if not already_announced(repo, number, decision, move.glob, move.target):
        mention = move.profile.reporter_mode == "trailer"
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as body:
            body.write(live_comment(move.tag, decision, move.where, mention, move.target))
        try:
            if run(["gh", "issue", "comment", number, "--repo", repo, "--body-file", body.name]):
                print(f"{ref}: comment failed; card not moved", file=sys.stderr)
                return "comment-failed"
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


def report_unlinked(move: Move, decisions: list) -> int:
    unlinked = [d.ref() for d, _ in decisions if d.kind == UNLINKED]
    if unlinked:
        print(f"{len(unlinked)} card(s) in {move.source} have no linked commit; "
              f"move them by hand: {', '.join(unlinked)}", file=sys.stderr)
    return len(unlinked)


def report_comment_failed(refs: list[str]) -> None:
    if refs:
        print(f"{len(refs)} card(s) not moved, their comment failed: {', '.join(refs)}", file=sys.stderr)


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
    # One read of the board, and every matched stage planned from it: a card
    # moved into one stage in this run is not a source for the next one.
    cards, _recovered, _total = tracker.list_cards(
        open_only=True, issues_only=True, repo=tracker.DEFAULT_REPO
    )
    plans = []
    for move in moves:
        source = tracker.column(move.source).lower()  # as list_cards resolves a status
        in_source = [c for c in cards if (c.get("status") or "").lower() == source]
        decisions = [(plan(c, links, lambda s: is_ancestor(s, tag), profile.issues_repo), c)
                     for c in in_source]
        plans.append((move, decisions))

        print(f"stage {move.target} (tag {move.glob}): cards in {move.source}")
        for decision, _card in decisions:
            shas = ",".join(s[:8] for s in decision.shas) or "-"
            note = (f"  (not in tag: {','.join(s[:8] for s in decision.missing)})"
                    if decision.missing else "")
            print(f"{decision.kind:<8}  {decision.ref()}  {shas}{note}")

    me, me_read = None, False
    unassigned, comment_failed, unlinked_total = [], [], 0
    if dry_run:
        print("dry run: nothing written")
    for stage_index, (move, decisions) in enumerate(plans):
        for card_index, (decision, card) in enumerate(decisions):
            if dry_run or decision.kind != MOVE:
                continue
            if not me_read:
                me, me_read = authenticated_login(), True
                if me is None:
                    print("warning: could not read the login gh is authenticated as; "
                          "nobody is unassigned", file=sys.stderr)
            try:
                outcome = apply_move(move, decision, card, me)
            except SyncError:
                # The run stops, but first says everything it already knows.
                report_comment_failed(comment_failed)
                for later_move, later in plans[stage_index:]:
                    report_unlinked(later_move, later)
                not_attempted = [d.ref() for d, _ in decisions[card_index + 1:] if d.kind == MOVE]
                not_attempted += [d.ref() for _, later in plans[stage_index + 1:]
                                  for d, _ in later if d.kind == MOVE]
                if not_attempted:
                    print(f"{len(not_attempted)} card(s) not attempted: {', '.join(not_attempted)}",
                          file=sys.stderr)
                raise
            ref = decision.ref()
            if outcome == "skipped":
                print(f"{ref}: no longer in {move.source} (moved by a person) - nothing written")
                continue
            if outcome == "comment-failed":
                comment_failed.append(ref)
                continue
            print(f"{ref}: {move.source} -> {move.target}")
            if outcome == "moved-unassigned":
                unassigned.append(ref)
                print(f"{ref}: could not assign {', '.join(decision.reporters)}; "
                      "the comment mentions them: assign by hand", file=sys.stderr)

        unlinked_total += report_unlinked(move, decisions)

    if comment_failed:
        report_comment_failed(comment_failed)
        return 2
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


def shipped(tag: str, prev: str, known: dict[str, str], issues_repo: str = "") -> Shipped:
    """The issues whose commits are in `prev..tag`, first-merged first.

    A commit links to an issue by its `Ships-issue` trailer or, given
    `issues_repo`, by `Refs #<n>` / `Refs <owner>/<repo>#<n>` in its subject,
    read as `reverts` reads them; an issue named both ways counts once.
    Commits with no link are counted, not dropped: a short list that silently
    omits unlinked work reads as the whole release.
    """
    rev_range = f"{prev}..{tag}"
    refs: dict[str, list[IssueLink]] = {}
    if issues_repo:
        for sha, subject, _ in log_records(rev_range):
            for match in _REFS.finditer(subject):
                repo = f"{match['owner']}/{match['name']}" if match["owner"] else issues_repo
                refs.setdefault(sha, []).append(IssueLink(repo, int(match["number"])))
    seen: dict[tuple[str, int], IssueLink] = {}
    unlinked = 0
    for commit in commits_with_trailers(rev_range, known):
        links = commit.links + refs.get(commit.sha, [])
        if not links:
            unlinked += 1
        for link in links:
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
    result = shipped(args.tag, prev, profile.known, profile.issues_repo)
    titles = fetch_titles(result.links) if args.titles else None
    sys.stdout.write(render_shipped(args.tag, environment, result, titles))
    return 0


# --------------------------------------------------------------------------
# reverts — a shipped fix taken back out of the base
# --------------------------------------------------------------------------

#: `Refs #12` or `Refs owner/repo#12` in a subject: how every skill-made commit
#: names its issue (dev § Name the issue without closing it).
_REFS = re.compile(rf"\bRefs (?:(?P<owner>{_LOGIN})/(?P<name>{_NAME}))?#(?P<number>{_NUMBER})\b")
#: A shorter sha is too likely to match a different commit.
_REVERTS = re.compile(r"This reverts commit ([0-9a-fA-F]{7,40})\b")


@dataclass(frozen=True)
class Revert:
    key: tuple[str, int]
    shipped: str  # the reverted commit, full sha
    sha: str  # the revert, full sha
    subject: str

    def line(self, issues_repo: str) -> str:
        repo, number = self.key
        ref = f"#{number}" if repo == issues_repo.lower() else f"{repo}#{number}"
        return f"{ref}: shipped by {self.shipped[:7]}, reverted by {self.sha[:7]} ({self.subject})"


def log_records(main_ref: str) -> list[tuple[str, str, str]]:
    """(sha, subject, body) for every commit on `main_ref`, newest first."""
    out = git("log", "--format=%H%x00%s%x00%B%x1e", main_ref)
    records = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if record:
            sha, subject, body = record.split("\x00", 2)
            records.append((sha, subject, body))
    return records


def subject_links(records: list[tuple[str, str, str]], issues_repo: str) -> dict[tuple[str, int], list[str]]:
    """{(owner/repo, number): shas} from the `Refs` in each subject; a bare `#n` is the issues repo."""
    links: dict[tuple[str, int], list[str]] = {}
    for sha, subject, _ in records:
        for match in _REFS.finditer(subject):
            repo = f"{match['owner']}/{match['name']}" if match["owner"] else issues_repo
            links.setdefault(link_key(repo, int(match["number"])), []).append(sha)
    return links


def find_reverts(cards: list[dict], profile: Profile, main_ref: str) -> list[Revert]:
    """Each card's linked commits that a commit on `main_ref` says it reverts."""
    records = log_records(main_ref)
    reverted = [(prefix.lower(), sha, subject)
                for sha, subject, body in records for prefix in _REVERTS.findall(body)]
    if not reverted:
        return []
    links = {key: list(linked.shas) for key, linked in trailer_links(main_ref, profile.known).items()}
    for key, shas in subject_links(records, profile.issues_repo).items():
        links.setdefault(key, []).extend(s for s in shas if s not in links[key])
    hits = []
    for card in cards:
        key = link_key(card_repo(card, profile.issues_repo), card["number"])
        for shipped_sha in links.get(key, []):
            for prefix, sha, subject in reverted:
                if shipped_sha.startswith(prefix):
                    hits.append(Revert(key, shipped_sha, sha, subject))
    return hits


def revert_comment(hit: Revert, base: str) -> str:
    return (f"The fix for this issue was reverted by {hit.sha[:7]} on {base}: {hit.subject}.\n\n"
            "**Needs you:** decide whether to fix again or close\n"
            "<!-- gogogo:stop v=1 reason=reverted -->\n")


def apply_revert(profile: Profile, hit: Revert, base: str) -> str:
    """Comment, then move to needs_human. Returns "moved", "already" (the newest
    comment already names this revert), "comment-failed" or "move-failed"."""
    repo, number = hit.key[0], str(hit.key[1])
    try:
        if hit.sha[:7] in tracker.newest_comment(hit.key[1], repo):
            return "already"
    except tracker.BoardError:
        pass  # a duplicate comment beats a card left in a column it no longer belongs in
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as body:
        body.write(revert_comment(hit, base))
    try:
        if run(["gh", "issue", "comment", number, "--repo", repo, "--body-file", body.name]):
            return "comment-failed"
    finally:
        Path(body.name).unlink(missing_ok=True)
    if run(tracker_cmd(profile, "move", number, "--repo", repo, "--to", "needs_human")):
        return "move-failed"
    return "moved"


def reverts(profile: Profile, main_ref: str | None, apply: bool) -> int:
    if profile.tracker.get("kind") != "github-project":
        raise SyncError(f"tracker.kind is {profile.tracker.get('kind')!r}; "
                        "reverts reads cards on a github-project board only")
    base = (profile.settings.get("integration") or {}).get("base") or "main"
    main_ref = main_ref or f"origin/{base}"
    git("rev-parse", "--verify", "--quiet", f"{main_ref}^{{commit}}")
    tracker.configure(str(profile.path))
    if apply:
        if not (profile.tracker.get("columns") or {}).get("needs_human"):
            raise SyncError("tracker.columns.needs_human: missing; --apply moves a reverted card there")
        tracker.require_columns(tracker.board_meta(), ["needs_human"])
    columns = {tracker.column(s["column"]).lower() for s in profile.stages if s.get("column")}
    cards, _recovered, _total = tracker.list_cards(open_only=True, issues_only=True, repo=tracker.DEFAULT_REPO)
    cards = [c for c in cards if c.get("kind") == "Issue" and c.get("state") == "OPEN"
             and (c.get("status") or "").lower() in columns]
    hits = find_reverts(cards, profile, main_ref)
    if not hits:
        print("no shipped fix has been reverted")
        return 0
    for hit in hits:
        print(hit.line(profile.issues_repo))
    if not apply:
        return 1

    failed = []
    done: set[tuple[str, int]] = set()
    for hit in hits:  # newest revert first; one comment and one move per issue
        if hit.key in done:
            continue
        done.add(hit.key)
        ref = f"{hit.key[0]}#{hit.key[1]}"
        outcome = apply_revert(profile, hit, main_ref.removeprefix("origin/"))
        if outcome == "already":
            print(f"{ref}: its newest comment already names {hit.sha[:7]} - nothing written")
        elif outcome == "comment-failed":
            print(f"{ref}: comment failed; card not moved", file=sys.stderr)
            failed.append(ref)
        elif outcome == "move-failed":
            print(f"{ref}: commented, but the move to needs_human did not verify", file=sys.stderr)
            failed.append(ref)
        else:
            print(f"{ref}: -> {tracker.column('needs_human')}")
    return 2 if failed else 1


def cmd_reverts(args: argparse.Namespace, profile: Profile) -> int:
    return reverts(profile, args.main_ref, args.apply)


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

    rev = sub.add_parser("reverts", help="name, and with --apply hand back, cards whose shipped fix was reverted")
    rev.add_argument("--main-ref", default=None,
                     help="the branch to read reverts on (default origin/<integration.base>)")
    rev.add_argument("--apply", action="store_true",
                     help="comment on each issue with a stop marker, then move its card to needs_human")
    rev.set_defaults(func=cmd_reverts)

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
