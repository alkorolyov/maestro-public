#!/usr/bin/env python3
"""Maestro spawn guard — a Claude Code PreToolUse hook.

Its dsh twin (a plugin) was removed. Before an Agent (or Task) child is
spawned, the checkout's docs/ tree must carry no uncommitted knowledge-base writes —
modified, staged or untracked. A child shares this checkout, and one `git stash` or
`git checkout` from it wipes whatever the parent had not committed. Board edits that
exist only in the working tree are lost this way, because board writes are committed at
merge time. The rule is: commit them, then spawn. The reason names the paths and the command.

The dsh half ALSO judges the brief (`Files:` / `Done:` markers — `guards.brief_refusal`).
That rule is deliberately not here: a Claude Code session is the high-judgment top-level
session that writes code itself, while a dsh planner routes well-scoped items to local
workers, and it is the routing that needs the brief enforced.
The two harnesses are not mirrors.

Exempt: a child that shares no filesystem — `isolation: "remote"` or `"worktree"` on the
Agent tool — since nothing of the parent's can be reached from it; and a checkout whose
docs/ is dirty because another agent harness (a dsh session) is working in it, which owns
those writes rather than this session. Silent when the cwd is
not a maestro project (no docs/ with records), not a git repository, or git cannot
answer: a guard that cannot see the tree must not stop the work.

Wire-up (in ~/.claude/settings.json, alongside any existing PreToolUse entries):

    {"hooks": {"PreToolUse": [
      {"matcher": "Agent|Task",
       "hooks": [{"type": "command",
                  "command": "python3 <maestro>/global/hooks/guard_spawn.py",
                  "timeout": 10}]}
    ]}}

`maestro init --harness` writes that row for you.

Contract: reads the hook payload as JSON on stdin; emits a PreToolUse
`permissionDecision: "deny"` to stdout when docs/ is dirty and the child would share the
tree; exits 0 silently otherwise.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
try:
    from maestro_cli.guards import (current_branch, dirty_docs, foreign_writer,
                                    is_maestro_project, shares_the_tree, spawn_reason)
except ImportError:  # pragma: no cover - a checkout without tools/ on disk
    dirty_docs = None

# Both spellings of the spawn tool are accepted: it has been called Task and Agent
# across versions, and a guard that fails open must not also fail open on a rename.
_CHILD_TOOLS = {"Agent", "Task"}


def main() -> int:
    if dirty_docs is None:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    if (payload.get("tool_name") or "") not in _CHILD_TOOLS:
        return 0
    tool_input = payload.get("tool_input") or {}
    if not shares_the_tree(tool_input):
        return 0

    root = Path(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not is_maestro_project(root):
        return 0
    paths = dirty_docs(root)
    if not paths:
        return 0
    # A foreign agent harness working in this checkout owns the dirty docs/: those are
    # its writes, left uncommitted for as long as it runs, and this session has nothing
    # of its own to lose. Its children are expected to be read-only, so fall open.
    if foreign_writer(root) is not None:
        return 0

    return deny(spawn_reason(paths, current_branch(root)))


def deny(reason: str) -> int:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
