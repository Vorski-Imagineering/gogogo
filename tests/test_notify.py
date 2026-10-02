#!/usr/bin/env python3
"""Tests for notify.py, the sender behind auto-dev's and stage sync's messages.

Telegram is never called: `urlopen` is patched, the credentials file is a temp
file, the environment is cleared of the two keys, and each case writes its own
profile.

    python3 -m unittest tests.test_notify
"""

import io
import json
import os
import stat
import sys
import tempfile
import unittest
import http.client
import urllib.error
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "gogogo" / "scripts"))

import notify  # noqa: E402

TOKEN = "123456:SECRET-token-ABC"
CHAT = "4242"


class Answer:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok(result=True):
    return Answer({"ok": True, "result": result})


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.creds = self.tmp / "gogogo" / "notify.env"
        patches = [
            mock.patch.object(notify, "CREDENTIALS", self.creds),
            mock.patch.dict(os.environ, {}, clear=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        for key in (notify.TOKEN_KEY, notify.CHAT_KEY):
            os.environ.pop(key, None)
        self.urlopen = mock.patch("urllib.request.urlopen").start()
        self.addCleanup(mock.patch.stopall)

    def profile(self, notify_value="telegram"):
        line = f'notify = "{notify_value}"\n' if notify_value is not None else ""
        path = self.tmp / "dev-process.md"
        path.write_text(f"+++\nprofile = 1\n{line}+++\n\n## superpowers boundary\nx\n")
        return str(path)

    def write_creds(self, token=TOKEN, chat=CHAT, extra=""):
        self.creds.parent.mkdir(parents=True, exist_ok=True)
        self.creds.write_text(f"{extra}{notify.TOKEN_KEY}={token}\n{notify.CHAT_KEY}={chat}\n")

    def run_main(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch("sys.stdin", io.StringIO(stdin or "")):
            code = notify.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def posted(self, call):
        request = call.args[0]
        return request.full_url, dict(urllib.parse.parse_qsl(request.data.decode()))


class Send(Case):
    def test_1_sends_once_with_chat_and_text_and_no_parse_mode(self):
        self.write_creds()
        self.urlopen.return_value = ok({"message_id": 1})
        code, out, _ = self.run_main("send", "--profile", self.profile(), "--text", "hello")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "sent")
        self.assertEqual(self.urlopen.call_count, 1)
        url, params = self.posted(self.urlopen.call_args)
        self.assertTrue(url.endswith(f"/bot{TOKEN}/sendMessage"), url)
        self.assertEqual(params["chat_id"], CHAT)
        self.assertEqual(params["text"], "hello")
        self.assertNotIn("parse_mode", params)

    def test_2_off_sends_nothing(self):
        self.write_creds()
        for value in ("none", None):
            code, out, _ = self.run_main("send", "--profile", self.profile(value), "--text", "x")
            self.assertEqual((code, out.strip()), (0, "notify: off"), value)
        self.urlopen.assert_not_called()

    def test_3_no_credentials_is_off_not_a_failure(self):
        code, out, _ = self.run_main("send", "--profile", self.profile(), "--text", "x")
        self.assertEqual(code, 0)
        self.assertIn("no bot credentials", out)
        self.assertIn(notify.TOKEN_KEY, out)
        self.write_creds(chat="")
        code, out, _ = self.run_main("send", "--profile", self.profile(), "--text", "x")
        self.assertEqual(code, 0)
        self.assertIn(notify.CHAT_KEY, out)
        self.assertNotIn(notify.TOKEN_KEY, out)
        self.urlopen.assert_not_called()

    def test_4_file_used_and_environment_wins(self):
        self.write_creds()
        self.urlopen.return_value = ok({})
        self.run_main("send", "--profile", self.profile(), "--text", "x")
        url, params = self.posted(self.urlopen.call_args)
        self.assertIn(TOKEN, url)
        self.assertEqual(params["chat_id"], CHAT)
        os.environ[notify.TOKEN_KEY] = "999:ENV"
        os.environ[notify.CHAT_KEY] = "77"
        self.run_main("send", "--profile", self.profile(), "--text", "x")
        url, params = self.posted(self.urlopen.call_args)
        self.assertIn("999:ENV", url)
        self.assertEqual(params["chat_id"], "77")

    def test_5_telegram_refusal_is_a_failed_send(self):
        self.write_creds()
        self.urlopen.return_value = Answer({"ok": False, "description": "Bad Request: chat not found"})
        code, _, err = self.run_main("send", "--profile", self.profile(), "--text", "x")
        self.assertEqual(code, 1)
        self.assertIn("chat not found", err)

    def test_6_the_token_never_leaks_through_an_error(self):
        self.write_creds()
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        errors = [
            urllib.error.HTTPError(url, 502, f"Bad Gateway at {url}", {}, io.BytesIO(b"<html>")),
            urllib.error.URLError(f"cannot reach {url}"),
            http.client.InvalidURL(f"URL can't contain control characters. '/bot{TOKEN}/sendMessage'"),
        ]
        for error in errors:
            self.urlopen.side_effect = error
            code, out, err = self.run_main("send", "--profile", self.profile(), "--text", "x")
            self.assertEqual(code, 1, error)
            self.assertNotIn(TOKEN, out + err, error)
            self.assertIn("<token>", out + err, error)

    def test_7_long_text_is_cut_to_the_limit(self):
        self.write_creds()
        self.urlopen.return_value = ok({})
        self.run_main("send", "--profile", self.profile(), "--text", "a" * 5000)
        _, params = self.posted(self.urlopen.call_args)
        self.assertEqual(len(params["text"]), 4096)
        self.assertTrue(params["text"].endswith("…"))

    def test_7_the_limit_is_in_utf16_units(self):
        self.write_creds()
        self.urlopen.return_value = ok({})
        self.run_main("send", "--profile", self.profile(), "--text", "😀" * 3000)
        _, params = self.posted(self.urlopen.call_args)
        self.assertLessEqual(len(params["text"].encode("utf-16-le")) // 2, 4096)
        self.assertTrue(params["text"].endswith("…"))

    def test_8_usage_errors_make_no_call(self):
        self.write_creds()
        code, _, _ = self.run_main("send", "--profile", self.profile(), "--text", "  ")
        self.assertEqual(code, 2)
        code, _, err = self.run_main("send", "--profile", self.profile("slack"), "--text", "x")
        self.assertEqual(code, 2)
        self.assertIn("slack", err)
        self.urlopen.assert_not_called()

    def test_text_from_stdin(self):
        self.write_creds()
        self.urlopen.return_value = ok({})
        code, _, _ = self.run_main("send", "--profile", self.profile(), stdin="from stdin\n")
        self.assertEqual(code, 0)
        self.assertEqual(self.posted(self.urlopen.call_args)[1]["text"], "from stdin")


class Status(Case):
    def methods(self):
        return [self.posted(c)[0].rsplit("/", 1)[1] for c in self.urlopen.call_args_list]

    def test_9_each_state_and_never_sends(self):
        code, out, _ = self.run_main("status", "--profile", self.profile("none"))
        self.assertEqual((code, out.strip()), (0, "notify: off"))
        code, out, _ = self.run_main("status", "--profile", self.profile())
        self.assertEqual(code, 3)
        self.assertIn("no bot credentials", out)
        self.write_creds()
        self.urlopen.side_effect = [ok({"username": "gobot"}), ok({"first_name": "Vic"})]
        code, out, _ = self.run_main("status", "--profile", self.profile())
        self.assertEqual(code, 0)
        self.assertIn("@gobot", out)
        self.assertIn("Vic", out)
        self.urlopen.side_effect = [ok({"username": "gobot"}),
                                    Answer({"ok": False, "description": "Bad Request: chat not found"})]
        code, out, _ = self.run_main("status", "--profile", self.profile())
        self.assertEqual(code, 1)
        self.assertIn("chat not found", out)
        self.assertNotIn("sendMessage", self.methods())


class Init(Case):
    def test_10_creates_private_file_and_never_overwrites(self):
        code, out, _ = self.run_main("init")
        self.assertEqual(code, 0)
        self.assertEqual(stat.S_IMODE(self.creds.stat().st_mode), 0o600)
        text = self.creds.read_text()
        self.assertIn(f"{notify.TOKEN_KEY}=\n", text)
        self.assertIn(f"{notify.CHAT_KEY}=\n", text)
        self.write_creds()
        before = self.creds.read_bytes()
        code, _, _ = self.run_main("init")
        self.assertEqual(code, 0)
        self.assertEqual(self.creds.read_bytes(), before)


class ChatId(Case):
    def updates(self, *chats):
        return ok([{"update_id": i, "message": {"chat": chat}} for i, chat in enumerate(chats)])

    def test_11_lists_each_chat_once_and_saves_the_newest(self):
        self.write_creds(chat="", extra="# my comment\n")
        os.chmod(self.creds, 0o600)
        a, b = {"id": 1, "first_name": "Ann"}, {"id": 2, "title": "Team"}
        self.urlopen.return_value = self.updates(a, a, b)
        code, out, _ = self.run_main("chat-id")
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[0] for line in out.strip().splitlines()], ["1", "2"])
        self.urlopen.return_value = self.updates(a, b)
        code, _, _ = self.run_main("chat-id", "--save")
        self.assertEqual(code, 0)
        text = self.creds.read_text()
        self.assertIn(f"{notify.CHAT_KEY}=2", text)
        self.assertIn(f"{notify.TOKEN_KEY}={TOKEN}", text)
        self.assertIn("# my comment", text)
        self.assertEqual(stat.S_IMODE(self.creds.stat().st_mode), 0o600)

    def test_11_save_a_chosen_chat_and_refuse_an_unlisted_one(self):
        self.write_creds(chat="")
        a, b = {"id": 1, "first_name": "Ann"}, {"id": 2, "title": "Team"}
        self.urlopen.return_value = self.updates(a, b)
        self.assertEqual(self.run_main("chat-id", "--save", "1")[0], 0)
        self.assertIn(f"{notify.CHAT_KEY}=1\n", self.creds.read_text())
        self.urlopen.return_value = self.updates(a, b)
        self.assertEqual(self.run_main("chat-id", "--save", "9")[0], 1)
        self.assertIn(f"{notify.CHAT_KEY}=1\n", self.creds.read_text())

    def test_11_no_messages_and_no_token(self):
        self.write_creds(chat="")
        self.urlopen.return_value = self.updates()
        code, out, _ = self.run_main("chat-id")
        self.assertEqual(code, 1)
        self.assertIn("no messages yet", out)
        self.creds.unlink()
        self.assertEqual(self.run_main("chat-id")[0], 2)


if __name__ == "__main__":
    unittest.main()
