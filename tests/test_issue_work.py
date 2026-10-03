#!/usr/bin/env python3
"""Tests for issue_work.py: the earlier work an issue already has (gogogo#86).

Each test builds a bare `origin` and a clone with a profile, puts a fake `gh`
on PATH that answers from a JSON fixture, and runs the script from the clone,
as tests/test_stranded_work.py does.

    python3 -m unittest tests.test_issue_work
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_stranded_work import ENV, Repos  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "scripts" / "issue_work.py"

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
fixture = json.load(open(os.environ["FAKE_GH"]))
if args[:2] == ["api", "graphql"]:
    answer = fixture.get("graphql", "fail")
elif args[:2] == ["pr", "view"]:
    answer = fixture.get("prview", {}).get(args[2], "fail")
else:
    answer = "fail"
if answer == "fail":
    print("boom", file=sys.stderr)
    sys.exit(1)
print(json.dumps(answer))
"""


def timeline(prs=(), comments=()):
    nodes = [{"source": p} for p in prs]
    return {"data": {"repository": {"issue": {
        "timelineItems": {"nodes": nodes},
        "comments": {"nodes": [{"body": c} for c in comments]}}}}}


def pr(number, branch, head="o/code", base="o/code", state="OPEN"):
    return {"__typename": "PullRequest", "number": number, "state": state, "headRefName": branch,
            "isCrossRepository": head != base,
            "headRepository": {"nameWithOwner": head} if head else None,
            "baseRepository": {"nameWithOwner": base}}


class IssueWork(Repos):
    def setUp(self):
        super().setUp()
        (self.clone / ".agents").mkdir()
        (self.clone / ".agents" / "dev-process.md").write_text(
            '+++\n[tracker]\nissues_repo = "o/code"\ncode_repo = "o/code"\n+++\n')
        bin_dir = self.tmp / "ghbin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(FAKE_GH)
        (bin_dir / "gh").chmod(0o755)
        self.fixture = self.tmp / "gh.json"
        self.log = self.tmp / "gh.log"
        self.log.write_text("")
        self.env = {**ENV, "PATH": f"{bin_dir}{os.pathsep}{ENV['PATH']}", "FAKE_GH": str(self.fixture),
                    "FAKE_GH_LOG": str(self.log)}

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def profile(self, extra=""):
        (self.clone / ".agents" / "dev-process.md").write_text(
            '+++\n[tracker]\nissues_repo = "o/code"\ncode_repo = "o/code"\n' + extra + '+++\n')

    def work(self, number, fixture, base="main"):
        self.fixture.write_text(json.dumps(fixture))
        out = subprocess.run([sys.executable, str(SCRIPT), str(number), *(["--base", base] if base else [])],
                             cwd=self.clone,
                             env=self.env, capture_output=True, text=True)
        self.stderr = out.stderr
        return out.returncode, out.stdout.splitlines()

    def remote_only(self, name, commits):
        self.branch_with(name, commits)
        self.git("push", "-q", "origin", name)
        self.git("branch", "-q", "-D", name)

    def test_no_earlier_work(self):
        self.assertEqual(self.work(89, {"graphql": timeline()}), (0, []))
        self.assertIn("no earlier work for #89", self.stderr)

    def test_an_open_pr_on_an_unnumbered_name_is_found(self):
        self.remote_only("issue-46", 2)
        code, lines = self.work(46, {"graphql": timeline([pr(63, "issue-46")])})
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("candidate: issue-46 (remote), 2 commit(s) ahead of main"), lines[0])
        self.assertIn("PR #63 open", lines[0])

    def test_the_stop_marker_branch_is_one_candidate_local_and_remote(self):
        self.branch_with("fix/57-branch-rules", 1)
        self.git("push", "-q", "origin", "fix/57-branch-rules")
        comment = ("**Needs you:** read the [branch](https://github.com/o/code/tree/fix/57-branch-rules).\n"
                   "<!-- gogogo:stop v=1 reason=review -->")
        code, lines = self.work(57, {"graphql": timeline(comments=["older", comment])})
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("candidate: fix/57-branch-rules (local and remote)", lines[0])
        self.assertIn("stop marker reason=review", lines[0])

    def test_two_branches_are_two_candidates(self):
        self.branch_with("fix/387-a", 1)
        self.branch_with("fix/387-b", 1)
        code, lines = self.work(387, {"graphql": timeline()})
        self.assertEqual(code, 1)
        self.assertEqual(sorted(l.split(" (")[0] for l in lines),
                         ["candidate: fix/387-a", "candidate: fix/387-b"])

    def test_a_fork_pr_cannot_be_continued(self):
        code, lines = self.work(9, {"graphql": timeline([pr(12, "patch-1", head="stranger/code")])})
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["fork PR #12 from stranger/code: cannot be continued"])

    def test_a_failed_lookup_is_not_no_work(self):
        code, lines = self.work(9, {"graphql": "fail"})
        self.assertEqual(code, 2)
        self.assertEqual(lines, [])
        self.assertIn("boom", self.stderr)

    def test_a_branch_not_ahead_is_not_a_candidate(self):
        self.git("branch", "fix/7-done", "main")
        self.assertEqual(self.work(7, {"graphql": timeline()}), (0, []))

    def test_a_local_only_branch_is_a_candidate(self):
        self.branch_with("fix/8-unpushed", 1)
        code, lines = self.work(8, {"graphql": timeline()})
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["candidate: fix/8-unpushed (local), 1 commit(s) ahead of main"])

    def test_a_pr_in_another_base_repo_is_ignored(self):
        code, lines = self.work(9, {"graphql": timeline([pr(3, "x", head="o/other", base="o/other")])})
        self.assertEqual((code, lines), (0, []))

    def test_a_closed_pr_is_not_a_candidate(self):
        self.remote_only("issue-46", 1)
        code, lines = self.work(46, {"graphql": timeline([pr(63, "issue-46", state="CLOSED")])})
        self.assertEqual((code, lines), (0, []))

    def test_a_stop_marker_linking_a_pr_names_its_branch(self):
        self.remote_only("issue-50", 1)
        comment = "**Needs you:** see https://github.com/o/code/pull/70\n<!-- gogogo:stop v=1 reason=ci -->"
        code, lines = self.work(50, {"graphql": timeline(comments=[comment]),
                                     "prview": {"70": {"headRefName": "issue-50"}}})
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["candidate: issue-50 (remote), 1 commit(s) ahead of main, stop marker reason=ci"])

    def test_a_failed_ahead_count_cannot_tell(self):
        self.branch_with("fix/8-unpushed", 1)
        real = shutil.which("git")
        shim = self.tmp / "gitbin"
        shim.mkdir()
        (shim / "git").write_text(f'#!/bin/sh\n[ "$1" = rev-list ] && exit 128\nexec "{real}" "$@"\n')
        (shim / "git").chmod(0o755)
        self.env["PATH"] = f"{shim}{os.pathsep}{self.env['PATH']}"
        code, lines = self.work(8, {"graphql": timeline()})
        self.assertEqual((code, lines), (2, []))

    def test_a_stop_link_to_the_base_is_not_a_candidate(self):
        comment = "**Needs you:** see https://github.com/o/code/tree/main\n<!-- gogogo:stop v=1 reason=spec -->"
        self.assertEqual(self.work(5, {"graphql": timeline(comments=[comment])}), (0, []))

    def test_a_stop_link_to_another_repos_pr_is_not_looked_up(self):
        self.remote_only("fix/5-x", 1)
        comment = ("**Needs you:** blocked on https://github.com/other/lib/pull/70\n"
                   "<!-- gogogo:stop v=1 reason=decision -->")
        code, lines = self.work(5, {"graphql": timeline(comments=[comment]), "prview": {}})
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["candidate: fix/5-x (remote), 1 commit(s) ahead of main"])

    def test_the_graphql_call_names_the_issue_and_reads_the_timeline(self):
        self.work(46, {"graphql": timeline()})
        call = self.calls()[0]
        self.assertEqual(call[:2], ["api", "graphql"])
        pairs = list(zip(call[2::2], call[3::2]))
        self.assertIn(("-f", "owner=o"), pairs)
        self.assertIn(("-f", "name=code"), pairs)
        self.assertIn(("-F", "number=46"), pairs)
        query = next(v for f, v in pairs if f == "-f" and v.startswith("query="))
        self.assertIn("timelineItems", query)

    def test_a_stop_link_pr_is_looked_up_in_the_code_repo(self):
        self.remote_only("issue-50", 1)
        comment = "**Needs you:** see https://github.com/o/code/pull/70\n<!-- gogogo:stop v=1 reason=ci -->"
        self.work(50, {"graphql": timeline(comments=[comment]), "prview": {"70": {"headRefName": "issue-50"}}})
        self.assertIn(["pr", "view", "70", "--repo", "o/code", "--json", "headRefName"], self.calls())

    def test_an_empty_ahead_count_cannot_tell(self):
        self.branch_with("fix/8-unpushed", 1)
        real = shutil.which("git")
        shim = self.tmp / "gitbin"
        shim.mkdir()
        (shim / "git").write_text(f'#!/bin/sh\n[ "$1" = rev-list ] && exit 0\nexec "{real}" "$@"\n')
        (shim / "git").chmod(0o755)
        self.env["PATH"] = f"{shim}{os.pathsep}{self.env['PATH']}"
        self.assertEqual(self.work(8, {"graphql": timeline()}), (2, []))

    def test_a_profile_without_a_code_repo_cannot_tell(self):
        (self.clone / ".agents" / "dev-process.md").write_text('+++\n[tracker]\nissues_repo = "o/code"\n+++\n')
        self.assertEqual(self.work(9, {"graphql": timeline()}), (2, []))
        self.assertIn("code_repo", self.stderr)

    def test_the_base_defaults_to_main_then_integration_base(self):
        self.branch_with("fix/8-unpushed", 1)
        self.assertEqual(self.work(8, {"graphql": timeline()}, base=None),
                         (1, ["candidate: fix/8-unpushed (local), 1 commit(s) ahead of main"]))
        self.git("push", "-q", "origin", "main:trunk")
        self.git("fetch", "-q", "origin")
        self.profile('[integration]\nbase = "trunk"\n')
        self.assertEqual(self.work(8, {"graphql": timeline()}, base=None),
                         (1, ["candidate: fix/8-unpushed (local), 1 commit(s) ahead of trunk"]))

    def test_origin_head_is_neither_a_branch_nor_the_end_of_the_list(self):
        self.remote_only("fix/5-x", 1)
        self.git("remote", "set-head", "origin", "main")
        comment = "**Needs you:** https://github.com/o/code/tree/HEAD\n<!-- gogogo:stop v=1 reason=spec -->"
        code, lines = self.work(5, {"graphql": timeline(comments=[comment])})
        self.assertEqual(lines, ["candidate: fix/5-x (remote), 1 commit(s) ahead of main"])

    def test_the_local_branch_is_counted_when_both_exist(self):
        self.branch_with("fix/6-x", 1)
        self.git("push", "-q", "origin", "fix/6-x")
        self.git("checkout", "-q", "fix/6-x")
        self.commit("unpushed")
        self.git("checkout", "-q", "main")
        code, lines = self.work(6, {"graphql": timeline()})
        self.assertEqual(lines, ["candidate: fix/6-x (local and remote), 2 commit(s) ahead of main"])

    def test_every_timeline_node_is_read(self):
        self.remote_only("issue-46", 1)
        prs = [pr(60, "old", state="CLOSED"), pr(61, "x", head="o/other", base="o/other"),
               pr(62, "patch-1", head="stranger/code"), pr(63, "issue-46")]
        code, lines = self.work(46, {"graphql": timeline(prs)})
        self.assertEqual(lines, ["candidate: issue-46 (remote), 1 commit(s) ahead of main, PR #63 open",
                                 "fork PR #62 from stranger/code: cannot be continued"])

    def test_no_profile_cannot_tell(self):
        (self.clone / ".agents" / "dev-process.md").unlink()
        code, lines = self.work(9, {"graphql": timeline()})
        self.assertEqual((code, lines), (2, []))


if __name__ == "__main__":
    unittest.main()
