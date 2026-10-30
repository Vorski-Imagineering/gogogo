#!/usr/bin/env python3
"""Structure of /gogogo:auto-dev's queue selection (gogogo#60).

The selection reads each card's labels and lints the label-less ones. These
pin the setting, script and output names the step depends on, never its
sentences (CLAUDE.md § Tests); whether it behaves is a scenario run.

    python3 -m unittest tests.test_auto_dev_skill
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "plugins" / "gogogo" / "skills" / "auto-dev" / "SKILL.md"
BRANCH = SKILL.parent / "references" / "branch.md"
REVIEW_WAIT = SKILL.parent / "references" / "review-wait.md"
sys.path.insert(0, str(SKILL.parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_stats  # noqa: E402
from test_dev_skill import moved  # noqa: E402


def section(text, heading):
    return text.split(f"\n## {heading}")[1].split("\n## ")[0]


class QueueSelection(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")

    def test_select_reads_labels_and_lints_the_rest(self):
        select = section(self.text, "1. Select the queue")
        for name in ("tracker.ready_marker", "spec_lint.py", "--json"):
            self.assertIn(name, select)

    def test_the_lint_verdict_is_named(self):
        self.assertIn("label: apply", self.text)

    def test_branching_looks_for_earlier_work(self):
        self.assertIn("issue_work.py", moved(BRANCH))
        dev = (SKILL.parents[1] / "dev" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("issue_work.py", section(dev, "4. Change"))

    def test_the_skip_marker_matches_the_parser(self):
        triage = section(self.text, "2. Triage each issue before touching it")
        markers = re.findall(r"<!-- gogogo:skip (.*?) -->", triage)
        self.assertEqual(len(markers), 1, markers)
        found = re.fullmatch(r"v=1 reason=<([^>]*)> session=<id\|unknown>", markers[0])
        self.assertIsNotNone(found, markers[0])
        self.assertEqual(tuple(found.group(1).split("|")), review_stats.SKIPS)

    def test_a_skip_is_handed_back(self):
        triage = section(self.text, "2. Triage each issue before touching it")
        for name in ("tracker.columns.needs_human", "tracker.ready_marker", "gh issue comment", "--remove-label"):
            self.assertIn(name, triage)

    def test_the_skip_names_its_session_source(self):
        self.assertIn("CLAUDE_CODE_SESSION_ID", self.text.split("\n## Claude-specific")[1])

    def test_triage_only_still_posts_nothing(self):
        triage_only = section(self.text, "Triage-only mode")
        for words in ("post nothing", "move no card"):
            self.assertIn(words, triage_only)

    def test_triage_only_names_the_ready_label(self):
        self.assertIn("ready label", section(self.text, "Triage-only mode"))

    def test_triage_folds_in_comments(self):
        """gogogo#108: an answer in a comment is folded in, not skipped; a preview folds nothing."""
        triage = section(self.text, "2. Triage each issue before touching it")
        self.assertIn("Fold in comments", triage)
        self.assertIn("folds nothing", section(self.text, "Triage-only mode"))


class NeverWaits(unittest.TestCase):
    """The loop never waits on chat or on a turn's end (gogogo#96)."""

    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")

    def test_the_chat_section_comes_before_selection(self):
        chat = self.text.find("\n## The loop never waits on chat\n")
        self.assertNotEqual(chat, -1)
        self.assertLess(chat, self.text.index("\n## 1. Select the queue"))

    def test_no_run_ends_a_turn_for_background_work(self):
        step = section(self.text, "4. Change, test, review, verify")
        self.assertIn("Never end a turn to wait for background work", step)
        both = [ln for ln in step.splitlines() if "headless" in ln.lower() and "never end a turn" in ln.lower()]
        self.assertFalse(both, both)

    def test_claude_specific_names_the_poll_and_the_banned_tool(self):
        claude = self.text.split("\n## Claude-specific")[1]
        for name in ("timeout 540", "AskUserQuestion"):
            self.assertIn(name, claude)

    def test_launch_command_starts_a_goal(self):
        claude = self.text.split("\n## Claude-specific")[1]
        lines = self.launch_line_in(claude)
        self.assertEqual(len(lines), 1, lines)
        for name in ('"/goal ', "/gogogo:auto-dev", "--permission-mode bypassPermissions"):
            self.assertIn(name, lines[0])

    def launch_line_in(self, text):
        return [ln.strip() for ln in text.splitlines() if ln.strip().startswith("claude -n")]

    def test_readme_launch_matches_skill(self):
        claude = self.text.split("\n## Claude-specific")[1]
        skill = self.launch_line_in(claude)
        readme = self.launch_line_in((SKILL.parents[4] / "README.md").read_text(encoding="utf-8"))
        self.assertEqual(len(skill), 1, skill)
        self.assertEqual(readme[:1], skill)

    def test_review_wait_notice_is_the_only_turn_end(self):
        step = section(self.text, "4. Change, test, review, verify")
        self.assertIn("Waiting on the review (started <HH:MM>); the run resumes when it reports.", step)
        claude = self.text.split("\n## Claude-specific")[1]
        self.assertIn("30 minutes", " ".join(claude.split()))
        self.assertIn("reader=self", claude)

    def test_reader_wait_uses_a_done_marker_not_a_line_count(self):
        claude = self.text.split("\n## Claude-specific")[1]
        wait = claude.split("**Waiting for the spec check's reader**")[1].split("\n- ")[0]
        self.assertIn(".done", wait)
        self.assertIn("rm -f", wait)
        self.assertNotIn("grep -c", wait)
        dev = (SKILL.parents[1] / "dev" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(".done", dev.split("\n## Claude-specific")[1])

    def test_review_turn_end_needs_an_active_goal_and_a_background_review(self):
        step = section(self.text, "4. Change, test, review, verify")
        rule = step.split("**The review is the one place")[1].split("\n- ")[0]
        self.assertIn("/goal", rule)
        self.assertIn("background", rule)
        self.assertIn("foreground", rule)


class ReviewWait(unittest.TestCase):
    """gogogo#253: with no goal, a run waits on the forked review's own files."""

    def setUp(self):
        self.text = REVIEW_WAIT.read_text(encoding="utf-8")
        self.blocks = re.findall(r"^```bash\n(.*?)^```$", self.text, re.M | re.S)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def bash(self, script, **env):
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30,
                              env={**os.environ, **env}).stdout.strip()

    def test_the_rule_names_the_reference(self):
        rule = section(SKILL.read_text(encoding="utf-8"), "4. Change, test, review, verify")
        rule = rule.split("**The review is the one place")[1].split("\n- ")[0]
        self.assertIn("references/review-wait.md", rule)
        self.assertIn("foreground", rule)

    def test_the_reference_names_what_it_reads(self):
        for name in ("forked-skill.json", ".meta.json", "finished", "CLAUDE_CODE_SESSION_ID", "silent"):
            self.assertIn(name, self.text)

    def test_the_find_command_picks_this_rounds_review(self):
        folder = self.tmp / ".claude" / "projects" / "slug" / "sid" / "subagents"
        folder.mkdir(parents=True)
        older = folder / "agent-old.forked-skill.json"
        older.write_text("{}")
        os.utime(older, (1000, 1000))
        start = self.tmp / "review-start"
        start.write_text("")
        os.utime(start, (2000, 2000))
        script = self.blocks[0].replace("<scratch>", str(self.tmp))
        self.assertEqual(self.bash(script, HOME=str(self.tmp), CLAUDE_CODE_SESSION_ID="sid"), "")
        newer = folder / "agent-new.forked-skill.json"
        newer.write_text("{}")
        os.utime(newer, (3000, 3000))
        self.assertEqual(self.bash(script, HOME=str(self.tmp), CLAUDE_CODE_SESSION_ID="sid"),
                         str(folder / "agent-new"))

    def test_the_wait_command_sees_finished(self):
        agent = self.tmp / "agent-a"
        state = agent.with_name("agent-a.meta.json")
        state.write_text('{"agentType":"x","finished":true}')
        self.assertEqual(self.bash(self.blocks[1].replace("<agent>", str(agent))), "finished")
        pattern = re.search(r"grep -Eq '([^']+)'", self.blocks[1]).group(1)
        state.write_text('{"agentType":"x"}')
        self.assertEqual(subprocess.run(["grep", "-Eq", pattern, str(state)]).returncode, 1)

    def test_the_commands_read_a_home_with_a_space(self):
        folder = self.tmp / "first last"
        folder.mkdir()
        agent = folder / "agent-a"
        agent.with_name("agent-a.meta.json").write_text('{"finished":true}')
        agent.with_name("agent-a.jsonl").write_text(
            json.dumps({"message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}) + "\n")
        self.assertEqual(self.bash(self.blocks[1].replace("<agent>", str(agent))), "finished")
        self.assertEqual(self.bash(self.blocks[2].replace("<agent>", str(agent))), "ok")

    def test_the_stop_reason_is_one_the_tracker_accepts(self):
        import tracker
        reasons = re.findall(r"with reason `([a-z-]+)`", self.text)
        self.assertTrue(reasons)
        for reason in reasons:
            self.assertIn(reason, tracker.STOP_REASONS)

    def test_the_reader_prints_the_last_assistant_text(self):
        def line(role, content):
            return json.dumps({"message": {"role": role, "content": content}})
        agent = self.tmp / "agent-a"
        transcript = agent.with_name("agent-a.jsonl")
        script = self.blocks[2].replace("<agent>", str(agent))
        transcript.write_text("\n".join([
            line("user", [{"type": "tool_result", "content": "x"}]),
            line("assistant", [{"type": "text", "text": "the findings"}]),
            line("user", [{"type": "text", "text": "not the findings"}]),
        ]) + "\n")
        self.assertEqual(self.bash(script), "the findings")
        transcript.write_text(line("assistant", [{"type": "tool_use", "name": "Bash"}]) + "\n")
        self.assertEqual(self.bash(script), "")


class Independence(unittest.TestCase):
    """dev and auto-dev read the repo's `independence` level (gogogo#90)."""

    def test_dev_and_auto_dev_read_independence(self):
        for skill in (SKILL, SKILL.parents[1] / "dev" / "SKILL.md"):
            text = skill.read_text(encoding="utf-8")
            for name in ("independence", "Decided without asking"):
                self.assertIn(name, text, f"{skill.parent.name}: {name}")


class TakeWithFrom(unittest.TestCase):
    """§3 takes the card with `move --from` before it branches (gogogo#101)."""

    def setUp(self):
        self.step = moved(BRANCH)

    def test_the_move_carries_from_and_comes_before_the_branch(self):
        lines = self.step.splitlines()
        moves = [i for i, ln in enumerate(lines) if " move <n>" in ln and "--to in_progress" in ln]
        branch = next(i for i, ln in enumerate(lines) if "git switch -c" in ln)
        self.assertEqual(len(moves), 1, moves)
        self.assertIn("--from", lines[moves[0]])
        self.assertLess(moves[0], branch)

    def test_the_look_for_earlier_work_comes_before_the_move(self):
        lines = self.step.splitlines()
        look = next(i for i, ln in enumerate(lines) if "issue_work.py" in ln)
        move = next(i for i, ln in enumerate(lines) if " move <n>" in ln and "--to in_progress" in ln)
        self.assertLess(look, move)

    def test_a_failed_branch_moves_the_card_back_from_in_progress(self):
        self.assertIn("--from in_progress", self.step)


class WorktreeSweep(unittest.TestCase):
    """dev and auto-dev remove finished worktrees; status and wrap-up only list them (gogogo#92)."""

    RUN = re.compile(r'scripts/worktree_sweep\.py"( --apply)?')

    def runs(self, skill):
        folder = SKILL.parents[1] / skill
        # A step's rules may sit in the skill's references/ (gogogo#130).
        text = "\n".join(p.read_text(encoding="utf-8")
                          for p in [folder / "SKILL.md", *sorted(folder.glob("references/*.md"))])
        return [m.group(1) is not None for m in self.RUN.finditer(text)]

    def test_dev_and_auto_dev_run_the_sweep_with_apply(self):
        for skill in ("dev", "auto-dev"):
            self.assertTrue(self.runs(skill), skill)
            self.assertTrue(all(self.runs(skill)), skill)

    def test_status_and_wrap_up_run_the_sweep_without_apply(self):
        for skill in ("status", "wrap-up"):
            self.assertTrue(self.runs(skill), skill)
            self.assertFalse(any(self.runs(skill)), skill)


class Workspace(unittest.TestCase):
    """Where an issue's work goes is the profile's `integration.workspace`, asked by setup (gogogo#94)."""

    def test_dev_and_auto_dev_branch_by_the_setting(self):
        dev = (SKILL.parents[1] / "dev" / "SKILL.md").read_text(encoding="utf-8")
        for name, text in (("dev §4", section(dev, "4. Change")), ("auto-dev §3", moved(BRANCH))):
            for word in ("integration.workspace", "git worktree add"):
                self.assertIn(word, text, name)

    def test_auto_dev_preflight_reads_the_setting(self):
        preflight = section(SKILL.read_text(encoding="utf-8"), "Before anything: preflight")
        self.assertIn("integration.workspace", preflight)

    def test_a_profile_placeholder_says_where_it_comes_from(self):
        # Guards gogogo#192: a preflight step ran `--profile <profile>` without saying which file.
        preflight = section(SKILL.read_text(encoding="utf-8"), "Before anything: preflight")
        items = re.split(r"^\d+\. ", preflight, flags=re.M)[1:]
        self.assertTrue(any("<profile>" in item for item in items))
        for item in items:
            if "<profile>" in item:
                self.assertIn("profile_check.py", item, item.split("\n")[0])

    def test_setup_asks_with_both_options(self):
        setup = (SKILL.parents[1] / "setup" / "SKILL.md").read_text(encoding="utf-8")
        for word in ("integration.workspace", "The checkout", "A worktree per issue"):
            self.assertIn(word, setup)


MERGE = SKILL.parent / "references" / "merge.md"
LATE = "Cards a late-merged run PR carried"


def numbered_items(text):
    return [int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", text, re.M)]


class LateRunPr(unittest.TestCase):
    """Cards a run PR carried, merged after its run ended (gogogo#59)."""

    def test_preflight_ends_with_the_late_run_pr_item(self):
        preflight = section(SKILL.read_text(encoding="utf-8"), "Before anything: preflight")
        nums = numbered_items(preflight)
        self.assertEqual(nums, list(range(1, len(nums) + 1)))
        last = " ".join(re.split(r"^\d+\. ", preflight, flags=re.M)[-1].split())
        for word in ("run-branch-pr", LATE, "--triage-only"):
            self.assertIn(word, last)

    def test_late_merge_subsection_names_its_checks(self):
        text = MERGE.read_text(encoding="utf-8")
        contents = text.split("## Contents")[1].split("\n\n")[1]
        self.assertIn(LATE, contents)
        sub = text.split(f"### {LATE}")[1].split("\n### ")[0]
        for word in ("Ships-issue", "--parents", "verify_merged.py", "--open", "move", "--from",
                     "--state open", "mergeCommit.oid"):
            self.assertIn(word, sub)
        step5 = sub.split("\n5. ")[1].split("\n6. ")[0]
        for word in ("gh pr view", "--json commits", "messageBody", "Ships-issue"):
            self.assertIn(word, step5)
        self.assertNotIn("as in step 4", step5)

    def test_final_pr_description_lists_after_merging(self):
        bullet = moved(MERGE).split("- **`run-branch-pr`**")[1].split("\n- **")[0]
        self.assertIn("After merging", bullet)
        after = bullet.split("After merging")[1]
        for word in ("no `tag`", "stage sync", "merge commit", "Ships-issue"):
            self.assertIn(word, after)
        close = section(SKILL.read_text(encoding="utf-8"), "9. Close the run")
        self.assertIn("After merging", close)



class Authorisation(unittest.TestCase):
    def test_obeys_the_authorisation(self):
        four = SKILL.read_text(encoding="utf-8").split("\n## 4. ")[1].split("\n## ")[0]
        self.assertIn("authoris", four)
        self.assertIn("/gogogo:dev` §1", four)



class ShipWait(unittest.TestCase):
    """gogogo#238: a row whose spec waits on a blocker until shipped is passed over."""

    def test_blocked_reference_waits_until_shipped(self):
        text = (SKILL.parent / "references" / "blocked.md").read_text(encoding="utf-8")
        for words in ("until shipped", "`shipped`", "no blocked-by link"):
            self.assertIn(words, text)


class CloseReport(unittest.TestCase):
    """gogogo#239: the close report ends with the RELATED block, from one read."""

    def test_lists_related_repos(self):
        close = section(SKILL.read_text(encoding="utf-8"), "9. Close the run")
        for words in ("related_repos", "list --issues-only --open-only --json", "RELATED  unreadable:", "/gogogo:status"):
            self.assertIn(words, close)


if __name__ == "__main__":
    unittest.main()
