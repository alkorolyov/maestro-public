"""The Claude Code executor guard (global/hooks/guard_executor.py).

The child-side twin of the live-child guard. A delegated subagent shares the parent's
checkout; inside one, a Bash command that discards uncommitted work, moves the tree or
publishes is denied before it runs. Claude Code tells the hook it is inside a subagent by
`agent_id` in the payload and by a `transcript_path` under `<session>/subagents/`.

The last tests are the symmetry claim for this pair: both halves decide "does this
command discard shared work" from ONE list, and the mirror in the .mjs cannot drift.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

HOOK = ROOT / "global" / "hooks" / "guard_executor.py"

from maestro_cli.guards import EXECUTOR_PATTERNS, discards_shared_work  # noqa: E402

SUB_TRANSCRIPT = "/home/u/.claude/projects/-p/sess-1/subagents/agent-a19945eb.jsonl"
TOP_TRANSCRIPT = "/home/u/.claude/projects/-p/sess-1.jsonl"


def _run(command: str, tool: str = "Bash", **extra) -> str:
    payload = {"tool_name": tool, "tool_input": {"command": command}, **extra}
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _reason(stdout: str) -> str:
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_stash_inside_a_subagent_is_denied_and_the_reason_says_why():
    reason = _reason(_run("git stash && git checkout -b epic6-item1", agent_id="agent-1",
                          transcript_path=SUB_TRANSCRIPT))
    assert "delegated child" in reason
    assert "git stash && git checkout -b epic6-item1" in reason


def test_agent_id_alone_marks_a_subagent():
    assert _run("git stash", agent_id="agent-1", transcript_path=TOP_TRANSCRIPT) != ""


def test_a_subagents_transcript_path_alone_marks_a_subagent():
    assert _run("git stash", transcript_path=SUB_TRANSCRIPT) != ""


def test_a_top_level_session_is_never_touched():
    assert _run("git stash", transcript_path=TOP_TRANSCRIPT) == ""
    assert _run("git reset --hard HEAD~1") == ""


@pytest.mark.parametrize("command", [
    "git stash",
    "cd repo/rust && git stash -u 2>/dev/null; cargo clippy; git stash pop",
    "git stash drop",
    "git reset -q MERGE_HEAD",
    "git reset --hard HEAD~1",
    "git clean -fd",
    "git restore --staged CLAUDE.md",
    "git worktree add /tmp/baseline main",
    "git checkout main -- .",
    "git checkout HEAD -- docs/epics/",
    "git checkout -- CLAUDE.md",
    "cd rust && git checkout -- ../docs/epics/epic_06.md",
    "git merge --no-ff feat/x",
    "git rebase main",
    "git push origin feat/x",
    "git branch -D feat/x",
])
def test_every_discarding_command_is_denied_inside_a_subagent(command):
    assert _run(command, agent_id="agent-1") != "", command


@pytest.mark.parametrize("command", [
    "git checkout -b epic6-item1",
    "git checkout main && git checkout -b epic6-item2",
    "git switch -c feat/x main",
    "git add rust/policy_core rust/Cargo.toml && git commit -m 'epic 6 item 1'",
    "git status --short",
    "git diff main...epic6-item8 --name-only",
    "git log --oneline -- docs/",
    "git branch --show-current",
    "git merge-base main HEAD",
    "cargo test -p game_core",
])
def test_branch_cutting_commits_and_reads_pass_inside_a_subagent(command):
    assert _run(command, agent_id="agent-1") == "", command


def test_a_non_bash_tool_is_never_consulted():
    assert _run("git stash", tool="Edit", agent_id="agent-1") == ""


def test_unparseable_stdin_never_blocks():
    out = subprocess.run([sys.executable, str(HOOK)], input="{{{", capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0 and out.stdout == ""




@pytest.mark.parametrize("command, discards", [
    ("git stash", True), ("git checkout main -- .", True), ("git checkout -b feat/x", False),
    ("git checkout main", False), ("git merge feat/x", True), ("git merge-base a b", False),
    ("git branch -d feat/x", True), ("git branch --show-current", False),
])
def test_the_shared_matcher_is_what_both_halves_call(command, discards):
    assert discards_shared_work(command) is discards
