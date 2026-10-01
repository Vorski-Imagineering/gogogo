#!/usr/bin/env python3
"""Tests for record_outcome.py, the one place /gogogo:auto-test writes to a tracker.

Every `gh` and tracker call goes through `record_outcome.run`, which these tests
replace with a fake that keeps each issue's labels, state, column and comments.
End-state assertions read the fake's store, never the script's own word: a
script that trusted its writes is exactly what the read-back guards against.

    python3 -m unittest tests.test_record_outcome
"""

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gogogo"
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_check as pc  # noqa: E402
import record_outcome as ro  # noqa: E402
from test_profile_check import COMPLETE  # noqa: E402

COLUMN = "In Production"  # the stage whose environment is verify.human in COMPLETE
RUN = "20261001-1200-abcd"


class FakeWorld:
    """`gh` and the tracker, over a dict. Records every call as (verb, cmd)."""

    def __init__(self, labels=(), column=COLUMN, comments=()):
        self.issue = {"labels": set(labels), "state": "OPEN", "column": column, "comments": list(comments)}
        self.calls = []
        self.fail = {}      # verb -> exit code
        self.inert = set()  # verbs that exit 0 and change nothing

    def verbs(self):
        return [v for v, _ in self.calls]

    def __call__(self, cmd):
        cmd = [str(c) for c in cmd]
        verb, effect = self.parse(cmd)
        self.calls.append((verb, cmd))
        if self.fail.get(verb):
            return subprocess.CompletedProcess(cmd, self.fail[verb], "", f"fake {verb} failed")
        out = "" if verb in self.inert else effect()
        if isinstance(out, int):
            return subprocess.CompletedProcess(cmd, out, "", "")
        return subprocess.CompletedProcess(cmd, 0, out or "", "")

    def parse(self, cmd):
        issue = self.issue
        if cmd[0] == "git":
            return "git", lambda: 128
        if cmd[0] != "gh":  # the tracker tool
            sub = next(c for c in cmd if c in ("show", "move", "list", "fields"))
            rest = cmd[cmd.index(sub) + 1:]
            if sub == "show":
                expect = rest[rest.index("--expect") + 1]
                return "show", lambda: 0 if issue["column"] == expect else 3
            if sub == "move":
                return "move", lambda: issue.update(column=rest[rest.index("--to") + 1])
            return sub, lambda: ""
        action = cmd[2]
        if action == "comment":
            body = Path(cmd[cmd.index("--body-file") + 1]).read_text()
            return "comment", lambda: issue["comments"].append({"body": body})
        if action == "edit" and "--add-label" in cmd:
            label = cmd[cmd.index("--add-label") + 1]
            return "label+", lambda: issue["labels"].add(label)
        if action == "edit" and "--remove-label" in cmd:
            label = cmd[cmd.index("--remove-label") + 1]
            return "label-", lambda: issue["labels"].discard(label)
        if action == "close":
            return "close", lambda: issue.update(state="CLOSED")
        if action == "view" and "comments" in cmd[cmd.index("--json") + 1]:
            return "comments", lambda: json.dumps({"comments": issue["comments"]})
        if action == "view":
            return "view", lambda: json.dumps({"state": issue["state"],
                                               "labels": [{"name": n} for n in sorted(issue["labels"])]})
        raise AssertionError(f"unexpected command {cmd}")


def profile(tmp, text=COMPLETE, **auto_test):
    for key, value in auto_test.items():
        old = next(line for line in text.splitlines() if line.startswith(f"{key} = "))
        text = text.replace(old, f"{key} = {json.dumps(value)}")
    path = Path(tmp) / "dev-process.md"
    path.write_text(text)
    return path


def run_dir(tmp):
    d = Path(tmp) / RUN
    d.mkdir(exist_ok=True)
    return d


def marker_comment(d, n, verdict):
    (d / f"comment-{n}.md").write_text(
        f"<!-- auto-test v1 run={RUN} verdict={verdict} build=deploy-2 skill=c-000000000000 -->\n## Auto-test\n")


def call(world, *argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(ro, "run", world), mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
            redirect_stdout(out), redirect_stderr(err):
        code = ro.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


SPEC = {
    "n": 7, "verdict": "PASS", "kind": "behaviour", "summary": "The band shows on the board.",
    "role": "staff", "commits": ["`abc1234` Show the band (#7) - in `deploy-2`"],
    "checks": [["band shows", "body", "`/<slug>/board/` · open", "the band", "the band", "✅"]],
}


class Apply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dir = run_dir(self.tmp)

    def apply(self, world, verdict, marker=None, **auto_test):
        path = profile(self.tmp, **auto_test)
        marker_comment(self.dir, 7, marker or verdict)
        return call(world, "--profile", path, "apply", self.dir, 7, verdict)

    def run_md(self):
        path = self.dir / "run.md"
        return path.read_text() if path.exists() else ""

    def test_pass_that_closes(self):
        world = FakeWorld(labels={"test fail", "test needs human", "bug"})
        code, _, err = self.apply(world, "PASS")
        self.assertEqual(code, 0, err)
        self.assertEqual(world.verbs(), ["show", "comment", "label-", "label-", "close", "move", "view"])
        self.assertEqual(world.issue["state"], "CLOSED")
        self.assertEqual(world.issue["labels"], {"bug"})
        self.assertEqual(world.issue["column"], "Done")
        self.assertEqual(len(world.issue["comments"]), 1)
        self.assertIn("| #7 | PASS |", self.run_md())

    def test_pass_that_does_not_close(self):
        world = FakeWorld()
        code, _, err = self.apply(world, "PASS", pass_closes=False)
        self.assertEqual(code, 0, err)
        self.assertNotIn("close", world.verbs())
        self.assertEqual(world.issue["state"], "OPEN")
        self.assertEqual(world.issue["column"], "Done")

    def test_fail_and_needs_human(self):
        world = FakeWorld(labels={"test needs human"})
        code, _, err = self.apply(world, "FAIL")
        self.assertEqual(code, 0, err)
        self.assertEqual(world.issue["labels"], {"test fail"})
        self.assertEqual((world.issue["column"], world.issue["state"]), ("New", "OPEN"))

        world = FakeWorld(labels={"test fail"})
        code, _, err = self.apply(world, "NEEDS_HUMAN")
        self.assertEqual(code, 0, err)
        self.assertEqual(world.issue["labels"], {"test needs human"})
        self.assertNotIn("move", world.verbs())
        self.assertNotIn("close", world.verbs())
        self.assertEqual((world.issue["column"], world.issue["state"]), (COLUMN, "OPEN"))

    def test_a_card_no_longer_in_the_column_gets_nothing_written(self):
        for rc in (3, 1):
            world = FakeWorld()
            world.fail["show"] = rc
            code, _, _ = self.apply(world, "PASS")
            self.assertEqual(code, 0, rc)
            self.assertEqual(world.verbs(), ["show"], rc)
            self.assertIn("nothing written", self.run_md())
        world = FakeWorld()
        world.fail["show"] = 2
        code, _, _ = self.apply(world, "PASS")
        self.assertEqual(code, 2)
        self.assertEqual(world.verbs(), ["show"])
        self.assertEqual(world.issue["comments"], [])

    def test_comment_first(self):
        world = FakeWorld()
        world.fail["comment"] = 1
        code, _, _ = self.apply(world, "FAIL")
        self.assertEqual(code, 2)
        self.assertEqual(world.verbs(), ["show", "comment"])
        self.assertEqual(world.issue["labels"], set())

    def test_the_read_back_is_the_confirmation(self):
        world = FakeWorld()
        world.inert.add("label+")
        code, _, err = self.apply(world, "FAIL")
        self.assertEqual(code, 2)
        self.assertEqual(world.verbs()[-1], "view")
        self.assertNotIn("| #7 | FAIL |", self.run_md())

    def test_a_failed_move_after_closing_stops(self):
        world = FakeWorld()
        world.fail["move"] = 2
        code, _, err = self.apply(world, "PASS")
        self.assertEqual(code, 2)
        self.assertIn("close", world.verbs())
        self.assertIn("disagree", err)

    def test_the_comment_must_carry_the_same_verdict(self):
        world = FakeWorld()
        code, _, err = self.apply(world, "PASS", marker="FAIL")
        self.assertEqual(code, 2)
        self.assertEqual(world.calls, [])

    def test_the_repos_own_tool_and_the_card_repo(self):
        path = profile(self.tmp)
        marker_comment(self.dir, 7, "NEEDS_HUMAN")
        world = FakeWorld()
        self.assertEqual(call(world, "--profile", path, "apply", self.dir, 7, "NEEDS_HUMAN")[0], 0)
        show = world.calls[0][1]
        self.assertEqual(show[:2], ["python3", "tools/board.py"])
        self.assertNotIn("--repo", show)
        self.assertTrue(all(cmd[cmd.index("--repo") + 1] == "acme/issues" for v, cmd in world.calls if v != "show"))

        world = FakeWorld()
        self.assertEqual(call(world, "--profile", path, "apply", self.dir, 7, "NEEDS_HUMAN",
                              "--repo", "acme/code")[0], 0)
        show = world.calls[0][1]
        self.assertEqual(show[show.index("--repo") + 1], "acme/code")
        self.assertTrue(all(cmd[cmd.index("--repo") + 1] == "acme/code" for _, cmd in world.calls))

    def test_the_shared_tool_is_this_folders_tracker(self):
        path = profile(self.tmp, COMPLETE.replace('tool = "python3 tools/board.py"', 'tool = "shared"'))
        marker_comment(self.dir, 7, "NEEDS_HUMAN")
        world = FakeWorld()
        self.assertEqual(call(world, "--profile", path, "apply", self.dir, 7, "NEEDS_HUMAN")[0], 0)
        show = world.calls[0][1]
        self.assertEqual(show[:4], [sys.executable, str(PLUGIN / "scripts" / "tracker.py"), "--profile", str(path.resolve())])


class EmptyColumn(unittest.TestCase):
    """trap 2: `show --expect ""` checks nothing, so no column means no command at all."""

    def test_every_subcommand_stops_before_any_call(self):
        broken = {
            "empty": COMPLETE.replace('column = "In Production"', 'column = ""'),
            "blank": COMPLETE.replace('column = "In Production"', 'column = " "'),
            "no stage": COMPLETE.replace('environment = "production"\ncolumn', 'column'),
        }
        for name, text in broken.items():
            with tempfile.TemporaryDirectory() as tmp:
                path = profile(tmp, text)
                d = run_dir(tmp)
                marker_comment(d, 7, "PASS")
                for argv in (["column"], ["version"], ["last", 7],
                             ["render", d, "--build", "b", "--model", "m"], ["apply", d, 7, "PASS"]):
                    world = FakeWorld()
                    code, _, _ = call(world, "--profile", path, *argv, stdin=json.dumps(SPEC))
                    self.assertEqual(code, 2, (name, argv))
                    self.assertEqual(world.calls, [], (name, argv))

    def test_column_itself_refuses_an_empty_name(self):
        for value in ("", " "):
            settings = {"verify": {"human": "p"}, "stages": [{"code_is": "x", "environment": "p", "column": value}]}
            with self.assertRaises(ro.Stop):
                ro.column(settings)


class Render(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dir = run_dir(self.tmp)

    def render(self, spec, **kw):
        path = profile(self.tmp, **kw)
        return call(FakeWorld(), "--profile", path, "render", self.dir, "--build", "deploy-2",
                    "--model", "claude-test", stdin=json.dumps(spec))

    def written(self):
        return (self.dir / "comment-7.md").exists()

    def test_a_rendered_comment(self):
        code, _, err = self.render(SPEC)
        self.assertEqual(code, 0, err)
        lines = (self.dir / "comment-7.md").read_text().splitlines()
        self.assertRegex(lines[0], rf"^<!-- auto-test v1 run={RUN} verdict=PASS build=deploy-2 skill=c-[0-9a-f]{{12}} -->$")
        self.assertIn("app.example.org", "\n".join(lines))

    def test_no_evidence_is_a_failure(self):
        self.assertEqual(self.render({**SPEC, "checks": []})[0], 2)
        self.assertFalse(self.written())
        bad = [[*SPEC["checks"][0][:5], "✅"], ["second", "body", "s", "e", "o", "❌"]]
        self.assertEqual(self.render({**SPEC, "checks": bad})[0], 2)
        self.assertFalse(self.written())

    def test_a_missing_role_is_never_guessed(self):
        spec = {k: v for k, v in SPEC.items() if k != "role"}
        code, _, err = self.render(spec)
        self.assertEqual(code, 2)
        self.assertIn("role", err)
        self.assertFalse(self.written())

    def test_a_public_comment_carries_no_secrets(self):
        for value in ("https://x.example/a?token=abc", "https://u:p@x.example/", "seen at 10.0.0.1"):
            check = [*SPEC["checks"][0][:4], value, "✅"]
            code, _, err = self.render({**SPEC, "checks": [check]})
            self.assertEqual(code, 2, value)
            self.assertIn("checks[0][4]", err)
            self.assertFalse(self.written())
        check = [*SPEC["checks"][0][:4], "https://x.example/a?token=abc", "✅"]
        text = COMPLETE.replace("public = true", "public = false")
        code, _, err = self.render({**SPEC, "checks": [check]}, text=text)
        self.assertEqual(code, 0, err)


class Last(unittest.TestCase):
    """trap 7 (the old marker prefix) and trap 11 (what render writes, last reads)."""

    OLD = "<!-- gogogo-auto-test v1 run=old verdict=FAIL build=deploy-1 skill=0123abcd -->\n## Auto-test"

    def last(self, world, tmp):
        return call(world, "--profile", profile(tmp), "last", 7)

    def test_newest_marker_either_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = run_dir(tmp)
            code, _, err = call(FakeWorld(), "--profile", profile(tmp), "render", d, "--build", "deploy-2",
                                "--model", "m", stdin=json.dumps(SPEC))
            self.assertEqual(code, 0, err)
            rendered = (d / "comment-7.md").read_text()
            stamp = rendered.split("skill=")[1].split()[0]

            world = FakeWorld(comments=[{"body": self.OLD}, {"body": "thanks!"}, {"body": rendered}])
            code, out, _ = self.last(world, tmp)
            self.assertEqual((code, out.strip()), (0, f"verdict=PASS build=deploy-2 skill={stamp} run={RUN}"))

            world = FakeWorld(comments=[{"body": self.OLD}, {"body": "thanks!"}])
            code, out, _ = self.last(world, tmp)
            self.assertEqual((code, out.strip()), (0, "verdict=FAIL build=deploy-1 skill=0123abcd run=old"))

            code, out, _ = self.last(FakeWorld(comments=[{"body": "thanks!"}]), tmp)
            self.assertEqual((code, out.strip()), (0, "none"))

            world = FakeWorld()
            world.fail["comments"] = 1
            self.assertEqual(self.last(world, tmp)[0], 2)


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Version(unittest.TestCase):
    """trap 3: an installed plugin is not a git repo, so the stamp hashes content only."""

    def plugin_copy(self, root):
        (root / "skills" / "auto-test").mkdir(parents=True)
        (root / "scripts").mkdir()
        shutil.copy(PLUGIN / "skills" / "auto-test" / "SKILL.md", root / "skills" / "auto-test" / "SKILL.md")
        shutil.copy(PLUGIN / "scripts" / "record_outcome.py", root / "scripts" / "record_outcome.py")
        return root

    def test_the_same_content_gives_the_same_stamp_anywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            installed = self.plugin_copy(tmp / "0123456789ab")
            clone = tmp / "clone"
            clone.mkdir()
            git("init", "-q", cwd=clone)
            plugin = self.plugin_copy(clone / "plugins" / "gogogo")
            git("add", ".", cwd=clone)
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c", cwd=clone)
            sha = git("rev-parse", "--short", "HEAD", cwd=clone)

            data = "### Running build\nThe footer.\n"
            self.assertEqual(ro.stamp(installed, data), ro.stamp(plugin, data))
            self.assertRegex(ro.stamp(installed, data), r"^c-[0-9a-f]{12}$")
            self.assertEqual(ro.source(installed), "installed 0123456789ab")
            self.assertEqual(ro.source(plugin), f"git {sha}")

            before = ro.stamp(plugin, data)
            self.assertNotEqual(ro.stamp(plugin, data + "x"), before)
            skill = plugin / "skills" / "auto-test" / "SKILL.md"
            skill.write_bytes(skill.read_bytes() + b" ")
            self.assertNotEqual(ro.stamp(plugin, data), before)
            self.assertEqual(ro.source(plugin), f"git {sha}-dirty")

    def test_cli_prints_the_stamp_and_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = profile(tmp)
            code, out, err = call(subprocess_run, "--profile", path, "version")
        settings, sections = pc.split_profile(COMPLETE)
        self.assertEqual((code, out.strip()), (0, ro.stamp(PLUGIN, sections["Test data"])))
        self.assertTrue(err.strip().startswith(("git ", "installed ", "unknown")), err)


def subprocess_run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
