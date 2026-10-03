#!/usr/bin/env python3
"""Tests for notify.py, the sender behind auto-dev's and stage sync's messages.

Telegram is never called: `urlopen` is patched, the credentials file is a temp
file, the environment is cleared of the two keys, and each case writes its own
profile in its own temp folder, which is the repo root the repo file is read from.

    python3 -m unittest tests.test_notify
"""

import io
import json
import os
import stat
import subprocess
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
        path = self.tmp / ".agents" / "dev-process.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"+++\nprofile = 1\n{line}+++\n\n## superpowers boundary\nx\n")
        return str(path)

    def write_creds(self, token=TOKEN, chat=CHAT, extra=""):
        self.creds.parent.mkdir(parents=True, exist_ok=True)
        self.creds.write_text(f"{extra}{notify.TOKEN_KEY}={token}\n{notify.CHAT_KEY}={chat}\n")

    def git_repo(self, ignored=True):
        """Make the temp folder a git repo, with `.claude/gogogo/` ignored or not."""
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        (self.tmp / ".gitignore").write_text(".claude/gogogo/\n" if ignored else "*.pem\n")

    def write_repo(self, text):
        self.repo_file.parent.mkdir(parents=True, exist_ok=True)
        self.repo_file.write_text(text)

    @property
    def repo_file(self):
        return self.tmp / ".claude" / "gogogo" / "notify.env"

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
        for value in ("none",):
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

    def test_6_a_token_with_a_control_character_is_refused_unsent(self):
        self.write_creds(token="12:AB\tCD")
        code, out, err = self.run_main("send", "--profile", self.profile(), "--text", "x")
        self.assertEqual(code, 1)
        self.assertNotIn("AB", out + err)
        self.urlopen.assert_not_called()

    def test_6_a_token_with_other_characters_is_refused_everywhere(self):
        for token in ("123:SECRÉT", "12:ab\\cd", "12:ab # mine", "AAHsecretonly", "12:", "１２:abcd"):
            self.write_creds(token=token)
            for argv in (("send", "--profile", self.profile(), "--text", "x"),
                         ("status", "--profile", self.profile()), ("chat-id",)):
                code, out, err = self.run_main(*argv)
                self.assertEqual(code, 1, (token, argv))
                self.assertNotIn(token[-4:], out + err, (token, argv))
        self.urlopen.assert_not_called()

    def test_6_an_answer_that_is_not_an_object_is_a_failed_send(self):
        self.write_creds()
        self.urlopen.return_value = Answer([])
        code, _, err = self.run_main("send", "--profile", self.profile(), "--text", "x")
        self.assertEqual(code, 1)
        self.assertIn("not a JSON object", err)

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
        self.urlopen.side_effect = [ok({}), ok({"first_name": "Vic"})]
        self.assertEqual(self.run_main("status", "--profile", self.profile())[0], 1)
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

    def test_11_save_follows_a_symlink_and_refuses_an_empty_id(self):
        real = self.tmp / "dotfiles" / "notify.env"
        real.parent.mkdir()
        real.write_text(f"{notify.TOKEN_KEY}={TOKEN}\n{notify.CHAT_KEY}=\n")
        self.creds.parent.mkdir(parents=True, exist_ok=True)
        self.creds.symlink_to(real)
        self.urlopen.return_value = self.updates({"id": 5, "first_name": "Ann"})
        self.assertEqual(self.run_main("chat-id", "--save", "5")[0], 0)
        self.assertTrue(self.creds.is_symlink())
        self.assertIn(f"{notify.CHAT_KEY}=5", real.read_text())
        self.assertEqual(self.run_main("chat-id", "--save", "")[0], 2)

    def test_11_malformed_updates_are_skipped(self):
        self.write_creds(chat="")
        self.urlopen.return_value = ok([1, {"message": {"chat": {"first_name": "no id"}}},
                                        {"message": {"chat": {"id": None}}}, {"message": {"chat": {"id": [1]}}},
                                        {"message": {"chat": {"id": "5\nTELEGRAM_BOT_TOKEN=x"}}},
                                        {"message": {"chat": {"id": " "}}},
                                        {"message": {"chat": {"id": 3, "first_name": "Cy"}}}])
        code, out, _ = self.run_main("chat-id")
        self.assertEqual(code, 0)
        self.assertEqual(out.split()[0], "3")

    def test_11_no_messages_and_no_token(self):
        self.write_creds(chat="")
        self.urlopen.return_value = self.updates()
        code, out, _ = self.run_main("chat-id")
        self.assertEqual(code, 1)
        self.assertIn("no messages yet", out)
        self.creds.unlink()
        self.assertEqual(self.run_main("chat-id")[0], 2)


class ByDefault(Case):
    """An absent `notify` sends when this machine has credentials; "none" opts out."""

    def test_1_absent_with_credentials_is_telegram_by_default(self):
        self.write_creds()
        self.urlopen.side_effect = [ok({"username": "gobot"}), ok({"first_name": "Vic"})]
        state, line, _ = notify.status(self.profile(None))
        self.assertEqual(state, notify.READY)
        self.assertIn("(by default)", line)
        self.urlopen.side_effect = None
        self.urlopen.return_value = ok({})
        code, out, _ = self.run_main("send", "--profile", self.profile(None), "--text", "x")
        self.assertEqual((code, out.strip()), (0, "sent"))
        self.assertEqual(self.urlopen.call_count, 3)
        self.assertTrue(self.posted(self.urlopen.call_args)[0].endswith("/sendMessage"))

    def test_2_absent_without_credentials_is_off(self):
        code, out, _ = self.run_main("status", "--profile", self.profile(None))
        self.assertEqual((code, out.strip()), (0, "notify: off"))
        code, out, _ = self.run_main("send", "--profile", self.profile(None), "--text", "x")
        self.assertEqual((code, out.strip()), (0, "notify: off"))
        self.write_creds(chat="")
        self.assertEqual(self.run_main("status", "--profile", self.profile(None))[1].strip(), "notify: off")
        self.urlopen.assert_not_called()

    def test_3_none_stays_off_with_credentials(self):
        self.write_creds()
        code, out, _ = self.run_main("status", "--profile", self.profile("none"))
        self.assertEqual((code, out.strip()), (0, "notify: off"))
        code, out, _ = self.run_main("send", "--profile", self.profile("none"), "--text", "x")
        self.assertEqual((code, out.strip()), (0, "notify: off"))
        self.urlopen.assert_not_called()

    def test_explicit_telegram_prints_as_before(self):
        self.write_creds()
        self.urlopen.side_effect = [ok({"username": "gobot"}), ok({"first_name": "Vic"})]
        code, out, _ = self.run_main("status", "--profile", self.profile())
        self.assertEqual((code, out.strip()), (0, "notify: telegram: bot @gobot -> Vic"))


class RepoFile(Case):
    """<root>/.claude/gogogo/notify.env: read key by key, only when git-ignored."""

    def test_4_each_key_from_the_first_source_that_has_it(self):
        self.git_repo()
        self.write_creds(chat="111")
        self.write_repo(f"{notify.CHAT_KEY}=222\n")
        self.assertEqual(notify.credentials(self.tmp)[:2], (TOKEN, "222"))
        self.assertEqual(notify.credentials()[:2], (TOKEN, "111"))

    def test_5_the_environment_wins_over_the_repo_file(self):
        self.git_repo()
        self.write_creds(chat="111")
        self.write_repo(f"{notify.CHAT_KEY}=222\n")
        os.environ[notify.CHAT_KEY] = "333"
        self.assertEqual(notify.credentials(self.tmp)[:2], (TOKEN, "333"))

    def test_6_a_file_that_is_not_ignored_is_never_read(self):
        self.git_repo(ignored=False)
        self.write_creds(chat="111")
        self.write_repo(f"{notify.TOKEN_KEY}=999:REPO\n{notify.CHAT_KEY}=222\n")
        self.assertEqual(notify.credentials(self.tmp)[:2], (TOKEN, "111"))
        code, out, _ = self.run_main("status", "--profile", self.profile())
        self.assertEqual(code, 1)
        self.assertIn("not git-ignored", out)
        self.assertIn(".claude/gogogo/", out)
        self.urlopen.assert_not_called()
        self.urlopen.return_value = ok({})
        code, out, err = self.run_main("send", "--profile", self.profile(), "--text", "x")
        self.assertEqual((code, out.strip()), (0, "sent"))
        self.assertIn("not git-ignored", err)
        url, params = self.posted(self.urlopen.call_args)
        self.assertIn(TOKEN, url)
        self.assertEqual(params["chat_id"], "111")

    def test_6_outside_a_git_repo_the_file_is_not_read(self):
        self.write_creds(chat="111")
        self.write_repo(f"{notify.CHAT_KEY}=222\n")
        self.assertEqual(notify.credentials(self.tmp)[:2], (TOKEN, "111"))

    def test_an_app_env_file_is_never_read(self):
        self.git_repo()
        (self.tmp / ".env").write_text(f"{notify.TOKEN_KEY}=999:APP\n{notify.CHAT_KEY}=222\n")
        self.assertEqual(notify.credentials(self.tmp)[:2], ("", ""))

    def test_7_init_repo_refuses_unless_ignored(self):
        self.git_repo(ignored=False)
        code, out, err = self.run_main("--profile", self.profile(), "init", "--repo")
        self.assertEqual(code, 2)
        self.assertIn("not git-ignored", out + err)
        self.assertFalse(self.repo_file.exists())
        self.git_repo()
        code, out, _ = self.run_main("--profile", self.profile(), "init", "--repo")
        self.assertEqual(code, 0)
        self.assertIn(str(self.repo_file), out)
        self.assertEqual(stat.S_IMODE(self.repo_file.stat().st_mode), 0o600)
        self.assertEqual(self.repo_file.read_text(), notify.TEMPLATE)
        self.assertFalse(self.creds.exists())

    def test_7_init_repo_outside_a_git_repo_writes_nothing(self):
        code, _, _ = self.run_main("--profile", self.profile(), "init", "--repo")
        self.assertEqual(code, 2)
        self.assertFalse(self.repo_file.exists())

    def test_8_chat_id_save_repo_writes_only_the_repo_file(self):
        self.git_repo()
        self.write_creds(chat="111")
        before = self.creds.read_bytes()
        self.urlopen.return_value = ok([{"update_id": 1, "message": {"chat": {"id": 5, "first_name": "Ann"}}}])
        code, _, _ = self.run_main("--profile", self.profile(), "chat-id", "--save", "5", "--repo")
        self.assertEqual(code, 0)
        self.assertIn(f"{notify.CHAT_KEY}=5\n", self.repo_file.read_text())
        self.assertEqual(stat.S_IMODE(self.repo_file.stat().st_mode), 0o600)
        self.assertEqual(self.creds.read_bytes(), before)

    def test_8_chat_id_save_repo_refuses_unless_ignored(self):
        self.git_repo(ignored=False)
        self.write_creds(chat="")
        code, out, err = self.run_main("--profile", self.profile(), "chat-id", "--save", "5", "--repo")
        self.assertEqual(code, 2)
        self.assertIn("not git-ignored", out + err)
        self.assertFalse(self.repo_file.exists())
        self.urlopen.assert_not_called()

    def test_9_no_new_line_prints_the_token(self):
        self.git_repo(ignored=False)
        self.write_creds()
        self.write_repo(f"{notify.TOKEN_KEY}={TOKEN}\n")
        self.urlopen.side_effect = urllib.error.URLError(f"cannot reach /bot{TOKEN}/getMe")
        for argv in (("status", "--profile", self.profile(None)),
                     ("send", "--profile", self.profile(None), "--text", "x"),
                     ("--profile", self.profile(), "init", "--repo"),
                     ("--profile", self.profile(), "chat-id", "--save", "5", "--repo")):
            code, out, err = self.run_main(*argv)
            self.assertNotIn(TOKEN, out + err, argv)
        self.git_repo()
        code, out, err = self.run_main("status", "--profile", self.profile(None))
        self.assertEqual(code, 1)
        self.assertIn("(by default)", out)
        self.assertIn("<token>", out)
        self.assertNotIn(TOKEN, out + err)


class RepoFileLines(Case):
    """The exact lines Design 3 and the --repo commands print, and how the ignore test is asked."""

    def unread_line(self):
        path = self.tmp.resolve() / ".claude" / "gogogo" / "notify.env"
        return f"notify: {path} is not git-ignored, so it is not read: add .claude/gogogo/ to .gitignore"

    def test_status_and_init_print_the_not_ignored_line(self):
        self.git_repo(ignored=False)
        self.write_repo(f"{notify.CHAT_KEY}=222\n")
        code, out, _ = self.run_main("status", "--profile", self.profile())
        self.assertEqual((code, out.strip()), (1, self.unread_line()))
        code, out, err = self.run_main("init", "--repo", "--profile", self.profile())
        self.assertEqual((code, out, err.strip()), (2, "", self.unread_line()))

    def test_by_default_lines_name_the_default(self):
        self.git_repo()
        self.write_creds()
        self.urlopen.side_effect = [ok({"username": "gobot"}), ok({"first_name": "Vic"})]
        code, out, _ = self.run_main("status", "--profile", self.profile(None))
        self.assertEqual((code, out.strip()), (0, "notify: telegram (by default): bot @gobot -> Vic"))
        self.urlopen.side_effect = [ok({"username": "gobot"}),
                                    Answer({"ok": False, "description": "Bad Request: chat not found"})]
        code, out, _ = self.run_main("status", "--profile", self.profile(None))
        self.assertEqual((code, out.strip()), (1, "notify: telegram (by default): Bad Request: chat not found"))

    def test_init_repo_names_the_repo_file_and_never_overwrites(self):
        self.git_repo()
        code, out, _ = self.run_main("init", "--repo", "--profile", self.profile())
        self.assertEqual((code, out.strip()), (0, f"created: {self.tmp.resolve() / '.claude/gogogo/notify.env'}"))
        code, out, _ = self.run_main("init", "--repo", "--profile", self.profile())
        self.assertEqual((code, out.strip()),
                         (0, f"already there: {self.tmp.resolve() / '.claude/gogogo/notify.env'}"))

    def test_chat_id_repo_lines_name_the_repo_file(self):
        self.git_repo()
        repo_file = self.tmp.resolve() / ".claude" / "gogogo" / "notify.env"
        code, out, _ = self.run_main("chat-id", "--repo", "--profile", self.profile())
        self.assertEqual((code, out.strip()), (2, f"no bot token: put it after {notify.TOKEN_KEY}= in "
                                                  f"{repo_file} (`notify.py init --repo` creates the file)"))
        code, out, _ = self.run_main("chat-id")
        self.assertEqual((code, out.strip()), (2, f"no bot token: put it after {notify.TOKEN_KEY}= in "
                                                  f"{self.creds} (`notify.py init` creates the file)"))
        self.write_repo(f"{notify.TOKEN_KEY}={TOKEN}\n")
        self.urlopen.return_value = ok([{"update_id": 1, "message": {"chat": {"id": 5, "first_name": "Ann"}}}])
        code, out, _ = self.run_main("chat-id", "--save", "5", "--repo", "--profile", self.profile())
        self.assertEqual((code, out.strip().splitlines()[-1]),
                         (0, f"saved {notify.CHAT_KEY}=5 in {repo_file}"))

    def test_the_ignore_test_is_a_quiet_git_check_ignore(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(notify._ignored(self.tmp))
        run.assert_called_once_with(["git", "-C", str(self.tmp), "check-ignore", "-q",
                                     str(Path(".claude") / "gogogo" / "notify.env")], capture_output=True)
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("git")):
            self.assertFalse(notify._ignored(self.tmp))

    def test_help_names_the_repo_option(self):
        for argv, pattern in ((["--help"], r"init\s+create "),
                              (["init", "--help"], r"--repo\s+the repo's git-ignored <root>/"),
                              (["chat-id", "--help"], r"--repo\s+the repo's git-ignored <root>/")):
            out = io.StringIO()
            with redirect_stdout(out), mock.patch.dict(os.environ, {"COLUMNS": "400"}), \
                    self.assertRaises(SystemExit):
                notify.main(argv)
            self.assertRegex(out.getvalue(), pattern, argv)


if __name__ == "__main__":
    unittest.main()
