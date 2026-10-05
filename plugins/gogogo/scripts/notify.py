#!/usr/bin/env python3
"""Send a run's state changes to a person, by the transport the profile names.

    notify.py [--profile FILE] send [--text TEXT]      (text from stdin when --text is absent)
    notify.py [--profile FILE] send --event            (one JSON event on stdin, formatted here)
    notify.py [--profile FILE] status
    notify.py [--profile FILE] init [--repo]
    notify.py [--profile FILE] chat-id [--save [ID]] [--repo]

The profile's `notify` setting picks the transport: "none" is off, "telegram"
sends through a Telegram bot, and absent is "telegram" when this machine has
both credentials (status says `telegram (by default)`), else off. Messages are
a convenience, never a reason to stop a run: off, or a machine with no
credentials, sends nothing and exits 0.

Telegram credentials are never in the profile. `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` are each taken from the first of these that has it:
  1. the environment (how CI supplies them, as secrets);
  2. the repo's own <root>/.claude/gogogo/notify.env, where <root> is the
     folder holding the profile's `.agents/`, read only when
     `git -C <root> check-ignore` says it is ignored; never a repo's `.env`;
  3. the per-user ~/.claude/gogogo/notify.env.
Both files are `KEY=value` lines the person fills in themselves. A repo file
that is not git-ignored is never read: `status` fails on it, and `send` goes on
with the other sources and says so on stderr. Every line this script prints
has the token scrubbed out.

`send --event` takes one JSON object on stdin, `{"event": "<name>", …}`, and builds the
message itself: the sender says what happened, this script says how it looks. The
events are run_started, issue_skipped, issue_started, issue_merged, needs_you,
run_closed, deployed and connected (the fields of each are in `EVENTS` below). A
message starts with a status mark (the roadmap's), the repo in bold, and each issue
number links to the issue; run_started and run_closed open with a line counting the
board's queue, in progress and need-you columns, read once with tracker.py. It is
sent as Telegram HTML, with every value from the event escaped. When Telegram
refuses the HTML it is sent once as plain text, and `notify: sent as plain text:
<why>` goes to stderr; a message too long for Telegram goes as its plain text, cut.
A bad event (not JSON, an unknown name, a missing or mistyped field) is exit 2 and
sends nothing, whatever the `notify` setting. `send --text` and plain stdin send the
text as it is, with no markup.

`init` and `chat-id --save` write the per-user file; with `--repo` they write
the repo file instead, and refuse (exit 2, writing nothing) unless it is
git-ignored in a git repo.

Exit codes:
  send     0 sent, off, or no credentials; 1 the send failed, or the token cannot be sent;
           2 usage (empty text, no profile, an unknown `notify` value, a bad event)
  status   0 off or ready; 1 failed (a call, a token that cannot be sent, or a repo file that is
           not git-ignored); 3 no credentials; 2 usage
  init     0 created or already there; 2 --repo and the repo file is not git-ignored
  chat-id  0 at least one chat; 1 none, the call failed or could not be made, or --save named
           an unlisted chat;
           2 no token, an empty --save, or --repo and the repo file is not git-ignored

Standard library only; imports `profile_check` from this folder, so a vendored
copy works when the files sit side by side.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile_check  # noqa: E402

CREDENTIALS = Path.home() / ".claude" / "gogogo" / "notify.env"
REPO_FILE = Path(".claude") / "gogogo" / "notify.env"  # under the repo root
TOKEN_KEY, CHAT_KEY = "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"
API = "https://api.telegram.org/bot{token}/{method}"
LIMIT = 4096  # Telegram counts UTF-16 code units
TIMEOUT = 10
TRACKER = HERE / "tracker.py"

OFF, READY, NO_CREDENTIALS, FAILED = "off", "ready", "no-credentials", "failed"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NO_CREDENTIALS = 0, 1, 2, 3

TEMPLATE = f"""\
# gogogo notifications: read by plugins/gogogo/scripts/notify.py.
# Paste your bot's token from @BotFather after {TOKEN_KEY}=.
# {CHAT_KEY} is filled in by `notify.py chat-id --save`.
{TOKEN_KEY}=
{CHAT_KEY}=
"""


class UsageError(Exception):
    """Exit 2: the call cannot be made as asked."""


class SendError(Exception):
    """A call to the transport failed, or could not be made (a token that cannot be sent)."""


def _scrub(text, token):
    text = str(text)
    return text.replace(token, "<token>") if token else text


def _say(text, token, stream=None):
    print(_scrub(text, token), file=stream or sys.stdout)


# --- credentials -----------------------------------------------------------

def _read_file(path):
    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _ignored(root):
    """True only when git says the repo file under `root` is ignored (not ignored, or no repo: False)."""
    try:
        return subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(REPO_FILE)],
                              capture_output=True).returncode == 0
    except OSError:
        return False


def _not_ignored(root):
    return (f"notify: {Path(root) / REPO_FILE} is not git-ignored, so it is not read: "
            f"add {REPO_FILE.parent.as_posix()}/ to .gitignore")


def credentials(root=None):
    """(token, chat id, unread); each key from the environment, else the repo file under `root`
    (when it is git-ignored), else the per-user file; '' when unset. `unread` is the line saying
    the repo file exists but is not ignored, so was skipped; '' otherwise."""
    sources, unread = [os.environ], ""
    if root is not None and (Path(root) / REPO_FILE).is_file():
        if _ignored(root):
            sources.append(_read_file(Path(root) / REPO_FILE))
        else:
            unread = _not_ignored(root)
    sources.append(_read_file(CREDENTIALS))
    token, chat = (next((s[key].strip() for s in sources if (s.get(key) or "").strip()), "")
                   for key in (TOKEN_KEY, CHAT_KEY))
    return token, chat, unread


# --- transport -------------------------------------------------------------

TOKEN_SHAPE = re.compile(r"[0-9]+:[A-Za-z0-9_-]+")


def _check_token(token):
    """Only a bot token's shape reaches a URL; anything else would fail there and could leak."""
    if not TOKEN_SHAPE.fullmatch(token):
        raise SendError(f"{TOKEN_KEY} is not shaped like a bot token (<digits>:<letters, digits, _ or ->), "
                        "or holds something else (a space, a comment, an accent); paste the token alone")


def _call(token, method, params=None):
    """POST to the Bot API; the decoded answer when `ok`, else SendError (token scrubbed)."""
    _check_token(token)
    data = urllib.parse.urlencode(params or {}).encode()
    request = urllib.request.Request(API.format(token=token, method=method), data=data)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - any unreadable body: report the HTTP error itself
            raise SendError(_scrub(exc, token)) from None
    except Exception as exc:  # noqa: BLE001 - any failure is a failed call, its text scrubbed
        raise SendError(_scrub(exc, token)) from None
    if not isinstance(body, dict):
        raise SendError("Telegram's answer was not a JSON object")
    if not body.get("ok"):
        raise SendError(_scrub(body.get("description") or "Telegram refused the call", token))
    return body.get("result")


class Telegram:
    name = "telegram"

    def __init__(self, root=None):
        self.token, self.chat, self.unread = credentials(root)

    def missing(self):
        return [key for key, value in ((TOKEN_KEY, self.token), (CHAT_KEY, self.chat)) if not value]


    def send(self, text, markup=False):
        """Send `text`; as Telegram HTML when `markup`, else exactly as it is."""
        params = {"chat_id": self.chat, "text": text, "disable_web_page_preview": "true"}
        if markup:
            params["parse_mode"] = "HTML"
        _call(self.token, "sendMessage", params)

    def describe(self):
        me = _call(self.token, "getMe")
        if not isinstance(me, dict) or not me.get("username"):
            raise SendError("Telegram's getMe answer named no bot")
        chat = _call(self.token, "getChat", {"chat_id": self.chat})
        if not isinstance(chat, dict):
            raise SendError("Telegram's getChat answer named no chat")
        who = chat.get("title") or chat.get("first_name") or chat.get("username") or self.chat
        return f"bot @{me.get('username')} -> {who}"


TRANSPORTS = {"telegram": Telegram}


def _profile(profile_path):
    return Path(profile_path) if profile_path else profile_check.find_profile()


def _root(profile_path):
    """The repo root the profile belongs to: the folder holding its `.agents/`."""
    return _profile(profile_path).resolve().parent.parent


def _setting(profile_path):
    """(value, by_default, root). An absent `notify` is "telegram" by default when both keys
    resolve, else "none"."""
    path = _profile(profile_path)
    if not path.is_file():
        raise UsageError(f"no profile at {path}")
    try:
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except profile_check.ProfileError as exc:
        raise UsageError(f"profile {path}: {exc}") from None
    root = _root(profile_path)
    value = settings.get("notify")
    if not value:
        token, chat, _ = credentials(root)
        by_default = bool(token and chat)
        return ("telegram" if by_default else "none"), by_default, root
    if value != "none" and value not in TRANSPORTS:
        raise UsageError(f"notify: '{value}' has no transport (known: none, {', '.join(sorted(TRANSPORTS))})")
    return value, False, root


def status(profile_path=None):
    """(state, line, token) for the profile's transport on this machine. Sends nothing."""
    value, by_default, root = _setting(profile_path)
    token, _, unread = credentials(root)
    if unread:
        return FAILED, unread, token
    if value == "none":
        return OFF, "notify: off", ""
    transport = TRANSPORTS[value](root)
    label = f"{value} (by default)" if by_default else value
    missing = transport.missing()
    if missing:
        return (NO_CREDENTIALS, f"notify: {value}, but no bot credentials on this machine "
                f"({' and '.join(missing)} not set): messages off", transport.token)
    try:
        return READY, f"notify: {label}: {transport.describe()}", transport.token
    except SendError as exc:
        return FAILED, f"notify: {label}: {exc}", transport.token


def machine_bot(profile_path=None):
    """Does this machine already have a bot? None when either credential is missing,
    (True, "bot @<name> -> <chat>") when both resolve and Telegram answers, and
    (False, reason) when they fail. Reads only (getMe, getChat); sends nothing."""
    transport = Telegram(_root(profile_path))
    if transport.missing():
        return None
    try:
        return True, transport.describe()
    except SendError as exc:
        return False, str(exc)


# --- events ----------------------------------------------------------------

# Event name -> {field: type}; a field in OPTIONAL may be left out. `deployed` is checked apart.
EVENTS = {
    "run_started": {"host": str, "count": int, "queue": str},
    "issue_skipped": {"issue": int, "reason": str, "title": str, "column": str},
    "issue_started": {"issue": int, "title": str},
    "issue_merged": {"issue": int, "title": str, "sha": str, "column": str},
    "needs_you": {"issue": int, "title": str, "reason": str, "column": str},
    "run_closed": {"merged": int, "need_you": int, "skipped": int},
    "deployed": {"tag": str},
    "connected": {"host": str, "scope": str},
}
OPTIONAL = {"issue_skipped": {"title", "column"}}
DEPLOYED_FULL = {"environment": str, "issues": list, "more": int, "unlinked_commits": int}

# The roadmap legend's marks, by the column an issue is in.
MARK_QUEUE, MARK_IN_PROGRESS, MARK_NEEDS_HUMAN, MARK_RELEASED, MARK_OTHER = "🔵", "🟡", "🆘", "🟢", "⛔"


def _typed(value, kind):
    return isinstance(value, kind) and not (kind is int and isinstance(value, bool))


def parse_event(text):
    """The event dict from the JSON on stdin; UsageError, saying what is wrong, when it is not one."""
    try:
        event = json.loads(text)
    except ValueError as exc:
        raise UsageError(f"the event is not JSON: {exc}") from None
    if not isinstance(event, dict):
        raise UsageError("the event must be a JSON object")
    name = event.get("event")
    if name not in EVENTS:
        raise UsageError(f"unknown event {name!r} (known: {', '.join(EVENTS)})")
    fields = dict(EVENTS[name])
    if name == "deployed":
        if event.get("unavailable") is True:
            pass
        elif event.get("first") is True:
            fields["environment"] = str
        else:
            fields.update(DEPLOYED_FULL)
    for field, kind in fields.items():
        if field not in event:
            if field in OPTIONAL.get(name, ()):
                continue
            raise UsageError(f"{name}: missing {field}")
        if not _typed(event[field], kind):
            raise UsageError(f"{name}: {field} must be {kind.__name__}")
    if name == "deployed" and "issues" in fields:
        for item in event["issues"]:
            if not (isinstance(item, dict) and _typed(item.get("repo"), str) and _typed(item.get("issue"), int)
                    and (item.get("title") is None or _typed(item["title"], str))):
                raise UsageError("deployed: each issue needs repo, issue and a title or null")
    return event


def _mark(column, tracker):
    columns = tracker.get("columns") or {}
    if column == tracker.get("queue"):
        return MARK_QUEUE
    if column == columns.get("in_progress"):
        return MARK_IN_PROGRESS
    if column == columns.get("needs_human"):
        return MARK_NEEDS_HUMAN
    return MARK_OTHER


def render(event, profile, summary):
    """(html, plain) for one validated event. `profile` is the settings dict, `summary` the board line
    (run_started and run_closed) or None. Every value from the event is escaped in the HTML."""
    tracker = profile.get("tracker") or {}
    issues_repo, repo = tracker.get("issues_repo") or "", (tracker.get("code_repo") or "").split("/")[-1]
    stage_columns = {s.get("column") for s in profile.get("stages") or [] if isinstance(s, dict)}

    def esc(value):
        return html.escape(str(value), quote=False)

    def link(repo_name, number):
        text = f"#{number}" if repo_name.lower() == issues_repo.lower() else f"{repo_name}#{number}"
        return f'<a href="https://github.com/{repo_name}/issues/{number}">{esc(text)}</a>', text

    def mark(column):
        return MARK_RELEASED if column in stage_columns else _mark(column, tracker)

    name = event["event"]
    bold, bare = f"<b>{esc(repo)}</b>", repo
    pieces = []  # (html, plain) per line

    def line(h, p):
        pieces.append((h, p))

    def with_number(prefix, rest, number):
        a, text = link(issues_repo, number)
        line(f"{prefix} {bold} {a} {rest[0]}", f"{prefix} {bare} {text} {rest[1]}")

    if name in ("run_started", "run_closed") and summary:
        line(esc(summary), summary)
    if name == "run_started":
        tail = f'auto-dev: run started on {{host}}, {event["count"]} issues in "{{queue}}"'
        line(f"▶️ {bold} " + tail.format(host=esc(event["host"]), queue=esc(event["queue"])),
             f"▶️ {bare} " + tail.format(host=event["host"], queue=event["queue"]))
    elif name == "run_closed":
        tail = f'auto-dev: run closed: {event["merged"]} merged, {event["need_you"]} need you, {event["skipped"]} skipped'
        line(f"🏁 {bold} {tail}", f"🏁 {bare} {tail}")
    elif name == "issue_skipped":
        column = event.get("column")
        arrow_h = f" → {esc(column)}" if column else ""
        arrow_p = f" → {column}" if column else ""
        with_number(mark(column) if column else MARK_OTHER,
                    (f"skipped{arrow_h}: {esc(event['reason'])}", f"skipped{arrow_p}: {event['reason']}"), event["issue"])
        if event.get("title"):
            line(esc(event["title"]), event["title"])
    elif name == "issue_started":
        with_number(MARK_IN_PROGRESS, ("started", "started"), event["issue"])
        line(esc(event["title"]), event["title"])
    elif name == "issue_merged":
        with_number(mark(event["column"]), (f"merged ({esc(event['sha'])}) → {esc(event['column'])}",
                                            f"merged ({event['sha']}) → {event['column']}"), event["issue"])
        line(esc(event["title"]), event["title"])
    elif name == "needs_you":
        with_number(mark(event["column"]), (f"needs you → {esc(event['column'])}: {esc(event['reason'])}",
                                            f"needs you → {event['column']}: {event['reason']}"), event["issue"])
        line(esc(event["title"]), event["title"])
    elif name == "deployed":
        tag = event["tag"]
        if event.get("unavailable") is True:
            line(f"🚀 {bold} deployed {esc(tag)} (issue list unavailable)", f"🚀 {bare} deployed {tag} (issue list unavailable)")
        else:
            env = event["environment"]
            line(f"🚀 {bold} deployed {esc(tag)} to {esc(env)}", f"🚀 {bare} deployed {tag} to {env}")
            if event.get("first") is True:
                line("… nothing to compare with", "… nothing to compare with")
            else:
                for item in event["issues"]:
                    a, text = link(item["repo"], item["issue"])
                    title = item.get("title")
                    line(f"• {a}" + (f" {esc(title)}" if title else ""), f"• {text}" + (f" {title}" if title else ""))
                if event["more"] > 0:
                    line(f"… and {event['more']} more", f"… and {event['more']} more")
                if event["unlinked_commits"] > 0:
                    text = f"+ {event['unlinked_commits']} commit(s) with no linked issue"
                    line(text, text)
    elif name == "connected":
        tail = ("auto-dev runs there will report here: when a run starts and ends, and when each issue "
                "starts, is skipped, merges or needs you.")
        line(f"✅ {bold} is connected on {esc(event['host'])} for {esc(event['scope'])}. {tail}",
             f"✅ {bare} is connected on {event['host']} for {event['scope']}. {tail}")
    return "\n".join(h for h, _ in pieces), "\n".join(p for _, p in pieces)


def count_line(profile, statuses):
    """`🔵 <a> ready · 🟡 <b> in progress · 🆘 <c> need you` for the columns the profile names."""
    tracker = profile.get("tracker") or {}
    columns = tracker.get("columns") or {}
    parts = []
    for mark, column, word in ((MARK_QUEUE, tracker.get("queue"), "ready"),
                               (MARK_IN_PROGRESS, columns.get("in_progress"), "in progress"),
                               (MARK_NEEDS_HUMAN, columns.get("needs_human"), "need you")):
        if column:
            parts.append(f"{mark} {sum(1 for s in statuses if s == column)} {word}")
    return " · ".join(parts)


def board_summary(profile_path, profile):
    """The summary line, read from the board once; `board: could not be read` when it cannot be."""
    try:
        out = subprocess.run([sys.executable, str(TRACKER), "--profile", str(profile_path), "list",
                              "--open-only", "--issues-only", "--json"],
                             capture_output=True, text=True, timeout=120, cwd=HERE)
        if out.returncode != 0:
            return "board: could not be read"
        cards = json.loads(out.stdout)
        return count_line(profile, [c.get("status") for c in cards]) or "board: could not be read"
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return "board: could not be read"


def _settings(profile_path):
    path = _profile(profile_path)
    try:
        return path, profile_check.split_profile(path.read_text(encoding="utf-8"))[0]
    except (OSError, profile_check.ProfileError) as exc:
        raise UsageError(f"profile {path}: {exc}") from None


# --- commands --------------------------------------------------------------

def _units(text):
    return len(text.encode("utf-16-le")) // 2


def _fit(text):
    """`text`, cut so it is at most LIMIT UTF-16 units, ending in … when cut."""
    if _units(text) <= LIMIT:
        return text
    out, used = [], 1  # room for the …
    for char in text:
        used += _units(char)
        if used > LIMIT:
            break
        out.append(char)
    return "".join(out) + "…"


def cmd_send(args):
    markup = None
    if args.event:
        if args.text is not None:
            raise UsageError("--event reads the event from stdin; it takes no --text")
        event = parse_event(sys.stdin.read())
        _setting(args.profile)  # a missing profile or an unknown `notify` is a usage error first
        path, settings = _settings(args.profile)
        if not (settings.get("tracker") or {}).get("code_repo"):
            raise UsageError(f"profile {path}: no tracker.code_repo to name the repo with")
        summary = board_summary(path, settings) if event["event"] in ("run_started", "run_closed") else None
        markup, text = render(event, settings, summary)
        if _units(markup) > LIMIT:
            markup = None
    else:
        text = args.text if args.text is not None else sys.stdin.read()
    text = text.strip()
    if not text:
        raise UsageError("nothing to send: empty text")
    text = _fit(text)
    value, _, root = _setting(args.profile)
    token, _, unread = credentials(root)
    if unread:
        _say(unread, token, sys.stderr)
    if value == "none":
        print("notify: off")
        return EXIT_OK
    transport = TRANSPORTS[value](root)
    missing = transport.missing()
    if missing:
        print(f"notify: {value}, but no bot credentials on this machine "
              f"({' and '.join(missing)} not set): messages off")
        return EXIT_OK
    try:
        try:
            transport.send(markup if markup is not None else text, markup=markup is not None)
        except SendError as exc:
            if markup is None:
                raise
            _say(f"notify: sent as plain text: {exc}", transport.token, sys.stderr)
            transport.send(text)
    except SendError as exc:
        _say(f"notify failed: {exc}", transport.token, sys.stderr)
        return EXIT_FAILED
    print("sent")
    return EXIT_OK


def cmd_status(args):
    state, line, token = status(args.profile)
    _say(line, token)
    return {OFF: EXIT_OK, READY: EXIT_OK, FAILED: EXIT_FAILED, NO_CREDENTIALS: EXIT_NO_CREDENTIALS}[state]


def _target(args):
    """The file `init` and `chat-id --save` write: the repo file with --repo, else the per-user one.
    UsageError when --repo and the repo file is not git-ignored."""
    if not args.repo:
        return CREDENTIALS
    root = _root(args.profile)
    if not _ignored(root):
        raise UsageError(_scrub(_not_ignored(root).removeprefix("notify: "), credentials(root)[0]))
    return root / REPO_FILE


def cmd_init(args):
    target = _target(args)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"already there: {target}")
        return EXIT_OK
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(TEMPLATE)
    print(f"created: {target}")
    return EXIT_OK


def _chats(updates):
    """Each distinct chat once, (id, name), in the order its latest message came."""
    seen = {}
    for update in updates:
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or update.get("channel_post") or {}
        chat = message.get("chat") if isinstance(message, dict) else None
        if not isinstance(chat, dict) or type(chat.get("id")) is not int:  # Telegram's ids are integers
            continue
        name = chat.get("title") or chat.get("first_name") or chat.get("username") or ""
        seen.pop(chat["id"], None)
        seen[chat["id"]] = name
    return list(seen.items())


def _save_chat(chat_id, path):
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out, done = [], False
    for line in lines:
        if line.strip().startswith(f"{CHAT_KEY}="):
            out.append(f"{CHAT_KEY}={chat_id}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{CHAT_KEY}={chat_id}")
    # Write a new file beside it and swap it in, so a failed write never loses
    # the token the person pasted. A symlinked file is updated where it points.
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".notify.env.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(out) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cmd_chat_id(args):
    if args.save == "":
        print("--save needs a chat id from the list, or nothing for the newest")
        return EXIT_USAGE
    target = _target(args)
    token, _, _ = credentials(_root(args.profile) if args.repo else None)
    if not token:
        init = "init --repo" if args.repo else "init"
        print(f"no bot token: put it after {TOKEN_KEY}= in {target} (`notify.py {init}` creates the file)")
        return EXIT_USAGE
    try:
        updates = _call(token, "getUpdates")
        chats = _chats(updates if isinstance(updates, list) else [])
    except SendError as exc:
        _say(f"chat-id failed: {exc}", token, sys.stderr)
        return EXIT_FAILED
    if not chats:
        print("no messages yet: send your bot a message "
              "(if the Telegram channel plugin is running, it reads them first)")
        return EXIT_FAILED
    for chat_id, name in chats:
        _say(f"{chat_id}  {name}", token)
    if args.save:
        chosen = args.save if args.save is not True else str(chats[-1][0])
        if chosen not in {str(chat_id) for chat_id, _ in chats}:
            print(f"{chosen} is not one of the chats above; nothing saved")
            return EXIT_FAILED
        _save_chat(chosen, target)
        print(f"saved {CHAT_KEY}={chosen} in {target}")
    return EXIT_OK


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md)")
    sub = parser.add_subparsers(dest="command", required=True)
    send = sub.add_parser("send", help="send one message (from --text, else stdin)")
    send.add_argument("--text")
    send.add_argument("--event", action="store_true", help="one JSON event on stdin, formatted by this script")
    send.add_argument("--profile", dest="profile_sub", help=argparse.SUPPRESS)
    st = sub.add_parser("status", help="say whether messages would send, without sending")
    st.add_argument("--profile", dest="profile_sub", help=argparse.SUPPRESS)
    repo_help = f"the repo's git-ignored <root>/{REPO_FILE} instead of {CREDENTIALS}"
    init = sub.add_parser("init", help=f"create {CREDENTIALS} (mode 600), never overwriting it")
    init.add_argument("--repo", action="store_true", help=repo_help)
    init.add_argument("--profile", dest="profile_sub", help=argparse.SUPPRESS)
    chat = sub.add_parser("chat-id", help="list the chats that messaged the bot")
    chat.add_argument("--save", nargs="?", const=True, metavar="ID",
                      help=f"write a listed chat's id to {CHAT_KEY} (default: the newest)")
    chat.add_argument("--repo", action="store_true", help=repo_help)
    chat.add_argument("--profile", dest="profile_sub", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.profile = getattr(args, "profile_sub", None) or args.profile
    handlers = {"send": cmd_send, "status": cmd_status, "init": cmd_init, "chat-id": cmd_chat_id}
    try:
        return handlers[args.command](args)
    except UsageError as exc:
        print(f"notify: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
