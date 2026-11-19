#!/usr/bin/env python3
"""Maestro executor guard — a Claude Code PreToolUse hook.

Its dsh twin (a plugin) was removed. A delegated child shares its
parent's checkout, and that tree may hold the parent's uncommitted knowledge-base
writes — see `maestro_cli.guards.EXECUTOR_PATTERNS` for the reason this exists (an
executor's `git stash` or `git checkout main -- .` can wipe the orchestrator's uncommitted
board edits, even after a brief that forbids it).
Inside a subagent, a Bash command that stashes, resets, cleans, restores, adds a
worktree, checks out paths, merges, rebases, pushes or deletes a branch is denied before
it runs. Cutting a branch, committing explicit paths, and every read pass. A top-level
session is never touched.

The two harnesses answer "am I a delegated child?" differently, and that is the whole
of the difference between the halves:

    dsh           the session header — `delegationDepth >= 1` (or `origin: subagent`)
    Claude Code   the hook payload — `agent_id` is present only inside a subagent, and
                  its `transcript_path` sits under `<session>/subagents/agent-<id>.jsonl`

Either Claude Code signal is enough; neither present means top-level, and the hook exits
silently. It fails OPEN in every uncertainty — unparseable stdin, a payload shape that
stopped matching — because a guard that cannot tell where it runs must not stop the work.

Wire-up (in ~/.claude/settings.json, alongside any existing PreToolUse entries):

    {"hooks": {"PreToolUse": [
      {"matcher": "Bash",
       "hooks": [{"type": "command",
                  "command": "python3 <maestro>/global/hooks/guard_executor.py",
                  "timeout": 5}]}
    ]}}

`maestro init --harness` writes that row for you.

Contract: reads the hook payload as JSON on stdin; emits a PreToolUse
`permissionDecision: "deny"` to stdout when this is a subagent and the command would
discard or move shared work; exits 0 silently otherwise.
"""
import json
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
try:
    from maestro_cli.guards import discards_shared_work, executor_reason
except ImportError:  # pragma: no cover - a checkout without tools/ on disk
    discards_shared_work = None


def is_delegated(payload: dict) -> bool:
    """True when this hook fired inside a subagent."""
    if payload.get("agent_id"):
        return True
    transcript = payload.get("transcript_path")
    return isinstance(transcript, str) and "subagents" in PurePosixPath(transcript).parts


def main() -> int:
    if discards_shared_work is None:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    if (payload.get("tool_name") or "") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not discards_shared_work(command):
        return 0
    if not is_delegated(payload):
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": executor_reason(command),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
