#!/usr/bin/env python3
"""Send a run's state changes to a person, by the transport the profile names.

    notify.py [--profile FILE] send [--text TEXT]      (text from stdin when --text is absent)
    notify.py [--profile FILE] status
    notify.py init
    notify.py chat-id [--save [ID]]

The profile's `notify` setting picks the transport: absent or "none" is off,
"telegram" sends through a Telegram bot. Messages are a convenience, never a
reason to stop a run: off, or a machine with no credentials, sends nothing and
exits 0.

Telegram credentials are never in the profile or a repo. `TELEGRAM_BOT_TOKEN`
and `TELEGRAM_CHAT_ID` come from the environment (how CI supplies them, as
secrets), else from ~/.claude/gogogo/notify.env (`KEY=value` lines), which the
person fills in themselves. Every line this script prints has the token
scrubbed out.

Exit codes:
  send     0 sent, off, or no credentials; 1 a send was attempted and failed;
           2 usage (empty text, no profile, an unknown `notify` value)
  status   0 off or ready; 1 failed; 3 no credentials; 2 usage
  init     0 created or already there
  chat-id  0 at least one chat; 1 none, the call failed, or --save named an unlisted chat;
           2 no token, or an empty --save

Standard library only; imports `profile_check` from this folder, so a vendored
copy works when the files sit side by side.
"""
from __future__ import annotations

import argparse
import json
import os
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
TOKEN_KEY, CHAT_KEY = "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"
API = "https://api.telegram.org/bot{token}/{method}"
LIMIT = 4096  # Telegram counts UTF-16 code units
TIMEOUT = 10

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
    """A call to the transport was made and failed."""


def _scrub(text, token):
    text = str(text)
    return text.replace(token, "<token>") if token else text


def _say(text, token, stream=None):
    print(_scrub(text, token), file=stream or sys.stdout)


# --- credentials -----------------------------------------------------------

def _read_file():
    values = {}
    try:
        lines = CREDENTIALS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def credentials():
    """(token, chat id); each from the environment first, else the file; '' when unset."""
    stored = _read_file()
    return tuple((os.environ.get(key) or stored.get(key) or "").strip() for key in (TOKEN_KEY, CHAT_KEY))


# --- transport -------------------------------------------------------------

def _check_token(token):
    """A token with spaces or control characters cannot be sent, and would leak in an error."""
    if any(c.isspace() or not c.isprintable() for c in token):
        raise SendError(f"{TOKEN_KEY} holds spaces or control characters; paste the token alone")


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

    def __init__(self):
        self.token, self.chat = credentials()

    def missing(self):
        return [key for key, value in ((TOKEN_KEY, self.token), (CHAT_KEY, self.chat)) if not value]


    def send(self, text):
        _call(self.token, "sendMessage", {"chat_id": self.chat, "text": text,
                                          "disable_web_page_preview": "true"})

    def describe(self):
        me = _call(self.token, "getMe")
        chat = _call(self.token, "getChat", {"chat_id": self.chat})
        if not isinstance(me, dict) or not me.get("username") or not isinstance(chat, dict):
            raise SendError("Telegram's answer had no bot or chat")
        who = chat.get("title") or chat.get("first_name") or chat.get("username") or self.chat
        return f"bot @{me.get('username')} -> {who}"


TRANSPORTS = {"telegram": Telegram}


def _setting(profile_path):
    path = Path(profile_path) if profile_path else profile_check.find_profile()
    if not path.is_file():
        raise UsageError(f"no profile at {path}")
    try:
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except profile_check.ProfileError as exc:
        raise UsageError(f"profile {path}: {exc}") from None
    value = settings.get("notify") or "none"
    if value != "none" and value not in TRANSPORTS:
        raise UsageError(f"notify: '{value}' has no transport (known: none, {', '.join(sorted(TRANSPORTS))})")
    return value


def status(profile_path=None):
    """(state, line, token) for the profile's transport on this machine. Sends nothing."""
    value = _setting(profile_path)
    if value == "none":
        return OFF, "notify: off", ""
    transport = TRANSPORTS[value]()
    missing = transport.missing()
    if missing:
        return (NO_CREDENTIALS, f"notify: {value}, but no bot credentials on this machine "
                f"({' and '.join(missing)} not set): messages off", transport.token)
    try:
        return READY, f"notify: {value}: {transport.describe()}", transport.token
    except SendError as exc:
        return FAILED, f"notify: {value}: {exc}", transport.token


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
    text = args.text if args.text is not None else sys.stdin.read()
    text = text.strip()
    if not text:
        raise UsageError("nothing to send: empty text")
    text = _fit(text)
    value = _setting(args.profile)
    if value == "none":
        print("notify: off")
        return EXIT_OK
    transport = TRANSPORTS[value]()
    missing = transport.missing()
    if missing:
        print(f"notify: {value}, but no bot credentials on this machine "
              f"({' and '.join(missing)} not set): messages off")
        return EXIT_OK
    try:
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


def cmd_init(_args):
    CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(CREDENTIALS, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"already there: {CREDENTIALS}")
        return EXIT_OK
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(TEMPLATE)
    print(f"created: {CREDENTIALS}")
    return EXIT_OK


def _chats(updates):
    """Each distinct chat once, (id, name), in the order its latest message came."""
    seen = {}
    for update in updates:
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or update.get("channel_post") or {}
        chat = message.get("chat") if isinstance(message, dict) else None
        if not isinstance(chat, dict) or "id" not in chat:
            continue
        name = chat.get("title") or chat.get("first_name") or chat.get("username") or ""
        seen.pop(chat["id"], None)
        seen[chat["id"]] = name
    return list(seen.items())


def _save_chat(chat_id):
    lines = CREDENTIALS.read_text(encoding="utf-8").splitlines() if CREDENTIALS.is_file() else []
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
    target = CREDENTIALS.resolve()
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
    token, _ = credentials()
    if args.save == "":
        print("--save needs a chat id from the list, or nothing for the newest")
        return EXIT_USAGE
    if not token:
        print(f"no bot token: put it after {TOKEN_KEY}= in {CREDENTIALS} (`notify.py init` creates the file)")
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
        _save_chat(chosen)
        print(f"saved {CHAT_KEY}={chosen} in {CREDENTIALS}")
    return EXIT_OK


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md)")
    sub = parser.add_subparsers(dest="command", required=True)
    send = sub.add_parser("send", help="send one message (from --text, else stdin)")
    send.add_argument("--text")
    send.add_argument("--profile", dest="profile_sub", help=argparse.SUPPRESS)
    st = sub.add_parser("status", help="say whether messages would send, without sending")
    st.add_argument("--profile", dest="profile_sub", help=argparse.SUPPRESS)
    sub.add_parser("init", help=f"create {CREDENTIALS} (mode 600), never overwriting it")
    chat = sub.add_parser("chat-id", help="list the chats that messaged the bot")
    chat.add_argument("--save", nargs="?", const=True, metavar="ID",
                      help=f"write a listed chat's id to {CHAT_KEY} (default: the newest)")
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
