"""The Claude Code live-child guard (global/hooks/guard_live_child.py).

The half that did not exist: the dsh harness guarded its sessions against merging
while a child was live, and the identical mistake in Claude Code — merging while a
subagent keeps editing — was guarded by nothing. dsh asks its subagents service which children are
live; Claude Code has none, so this reads the session transcript, where an Agent
tool_use with no tool_result yet IS a running child.

The last test is the symmetry claim for this pair: the two halves decide "does this
command move the branch" from ONE list, and the mirror in the .mjs cannot drift.
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

HOOK = ROOT / "global" / "hooks" / "guard_live_child.py"

from maestro_cli.guards import (ECHO_WIDTH, LIVE_CHILD_PATTERNS,  # noqa: E402
                                blocked_excerpt, live_child_reason, moves_the_branch)

# A realistic long command: 1396 characters, an innocent `maestro epic item` in front,
# ~1200 characters of --note= prose in the middle, and the `git checkout` that actually
# fires the guard at the very TAIL. Under the old `command[:200]` echo the refusal quoted
# the prose and nothing else, so the model could not see which verb it had been refused for.
_HEAD = ("cd /home/u/proj && maestro epic item --id=12 --item=33 "
         '--status=done --note="')
_TAIL = '" && git checkout main -q 2>/dev/null || true'
_NOTE = "the field-and-all-readers commit; the tree compiles at this commit. "
LONG_ITEM_COMMAND = _HEAD + (_NOTE * 30)[:1396 - len(_HEAD) - len(_TAIL)] + _TAIL
assert len(LONG_ITEM_COMMAND) == 1396


def _transcript(tmp_path: Path, *events) -> Path:
    p = tmp_path / "transcript.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in events))
    return p


def _spawn(tool_id: str, description: str, name: str = "Agent") -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tool_id, "name": name, "input": {"description": description}}]}}


def _result(tool_id: str) -> dict:
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": "done"}]}}


def _run(command: str, transcript: Path | None, tool: str = "Bash") -> str:
    payload = {"tool_name": tool, "tool_input": {"command": command}}
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _reason(stdout: str) -> str:
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_merge_while_a_child_runs_is_denied(tmp_path):
    t = _transcript(tmp_path, _spawn("t1", "Trace the decision path"))
    reason = _reason(_run("git merge --no-ff feat/x", t))
    assert "Trace the decision path" in reason
    assert "git merge --no-ff feat/x" in reason


def test_a_finished_child_blocks_nothing(tmp_path):
    t = _transcript(tmp_path, _spawn("t1", "child"), _result("t1"))
    assert _run("git merge --no-ff feat/x", t) == ""


def test_only_the_unfinished_child_is_named(tmp_path):
    t = _transcript(tmp_path, _spawn("t1", "done one"), _result("t1"), _spawn("t2", "still going"))
    reason = _reason(_run("git switch main", t))
    assert "still going" in reason and "done one" not in reason


def test_the_task_spelling_counts_too(tmp_path):
    t = _transcript(tmp_path, _spawn("t1", "legacy name", name="Task"))
    assert _run("git rebase main", t) != ""


@pytest.mark.parametrize("command", [
    "git merge --no-ff feat/x",
    "git switch main",
    "git checkout -b feat/y",
    "git branch -D feat/x",
    "git branch --delete feat/x",
    "git reset --hard HEAD~1",
    "git rebase main",
    "git stash",
    "cd repo && git merge feat/x",
])
def test_every_branch_moving_command_is_denied(tmp_path, command):
    t = _transcript(tmp_path, _spawn("t1", "child"))
    assert _run(command, t) != "", command


@pytest.mark.parametrize("command", [
    "git status", "git log --merges", "git diff", "git branch --show-current",
    "git merge-base main feat/x", "git merge-tree a b", "ls", "cargo test",
])
def test_reads_pass_even_with_a_live_child(tmp_path, command):
    t = _transcript(tmp_path, _spawn("t1", "child"))
    assert _run(command, t) == "", command


def test_a_non_bash_tool_is_never_consulted(tmp_path):
    t = _transcript(tmp_path, _spawn("t1", "child"))
    assert _run("git merge feat/x", t, tool="Edit") == ""


# ── failing open ─────────────────────────────────────────────────────────────

def test_no_transcript_path_allows(tmp_path):
    assert _run("git merge feat/x", None) == ""


def test_a_missing_transcript_allows(tmp_path):
    assert _run("git merge feat/x", tmp_path / "nope.jsonl") == ""


def test_a_transcript_of_junk_allows(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("not json\n{}\n{\"message\": 3}\n")
    assert _run("git merge feat/x", p) == ""


def test_unparseable_stdin_never_blocks():
    out = subprocess.run([sys.executable, str(HOOK)], input="{{{", capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0 and out.stdout == ""


# ── the blocked-command echo shows the offence, not the head ─────────────────

def test_the_echo_quotes_a_short_command_whole():
    assert blocked_excerpt("git merge --no-ff feat/x", ()) == \
        "Blocked command: git merge --no-ff feat/x"


def test_a_long_command_is_cut_around_the_match_and_the_match_is_named():
    echo = blocked_excerpt(LONG_ITEM_COMMAND, [re.compile(p) for p in LIVE_CHILD_PATTERNS])
    assert "git checkout main -q 2>/dev/null || true" in echo   # the offence is visible
    assert "`git checkout` at char 1356" in echo                # and it is named
    assert "1396 chars" in echo
    assert "--id=12" not in echo                                # the head is what got cut


def test_the_echo_stays_readable():
    """A window, not the whole command: the cap is what makes the refusal readable."""
    echo = blocked_excerpt(LONG_ITEM_COMMAND, [re.compile(p) for p in LIVE_CHILD_PATTERNS])
    assert len(echo) < ECHO_WIDTH + 120


def test_a_long_command_that_matched_nothing_still_gets_the_old_head_echo():
    echo = blocked_excerpt("echo " + "x" * 400, ())
    assert echo.startswith("Blocked command: echo xxx") and echo.endswith("…")


def test_the_hook_shows_the_tail_verb_of_the_real_1396_char_command(tmp_path):
    t = _transcript(tmp_path, _spawn("t1", "child"))
    reason = _reason(_run(LONG_ITEM_COMMAND, t))
    assert "git checkout main -q" in reason


# ── the refusal says what waiting looks like ─────────────────────────────────
#
# It said "wait for the child's finished event" and stopped there. The model then ran
# `sleep 120` inside a bash call — killed at 60 s with no output — and tried `job_output`
# on the subagent id, which is not a job.

def test_the_refusal_says_to_end_the_step_and_not_to_poll():
    reason = live_child_reason("git merge --no-ff feat/x", ["child-7f3a"])
    assert "ENDING YOUR STEP" in reason
    assert "sleep" in reason and "not a job id" in reason
    assert "send_message" in reason and "interrupt_agent" in reason




@pytest.mark.parametrize("command, moves", [
    ("git merge feat/x", True), ("git merge-base a b", False),
    ("git branch -d feat/x", True), ("git branch --show-current", False),
])
def test_the_shared_matcher_is_what_both_halves_call(command, moves):
    assert moves_the_branch(command) is moves
