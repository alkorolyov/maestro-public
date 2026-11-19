#!/usr/bin/env python3
"""Maestro live-child guard — a Claude Code PreToolUse hook.

Its dsh twin (a plugin) was removed. A parent agent and its
background children share ONE git checkout, and a child's report is PROGRESS, not
completion — see `maestro_cli.guards.live_child_reason` for why this exists. While a child of this
session is still running, a Bash command that merges, switches or checks out, deletes a branch,
resets, rebases or stashes is denied before it runs. Reads pass, and nothing is blocked when no
child is running.

The two harnesses answer "which children are live?" differently, and that is the whole
of the difference between the halves:

    dsh           the subagents service, queried live (SubagentRuntime.continuations)
    Claude Code   the session transcript — an Agent tool_use with no tool_result yet

Claude Code has no service to ask, but it writes every tool call to the transcript the
hook is handed (`transcript_path`), and a subagent's tool_result is written only when
it finishes. So an unmatched Agent tool_use IS a running child. Background Bash is
deliberately not counted: it returns its result immediately, so pairing says nothing
about it, and a background shell is not a child agent editing the tree.

It fails OPEN in every uncertainty — no transcript, unreadable, a schema that stopped
matching — because a guard that cannot see the children must not stop the work. The
cost of a miss is a child's work landing on the wrong branch; the cost of a false block is every
merge in every session, which is how a guard gets uninstalled.

Wire-up (in ~/.claude/settings.json, alongside any existing PreToolUse entries):

    {"hooks": {"PreToolUse": [
      {"matcher": "Bash",
       "hooks": [{"type": "command",
                  "command": "python3 <maestro>/global/hooks/guard_live_child.py",
                  "timeout": 5}]}
    ]}}

`maestro init --harness` writes that row for you.

Contract: reads the hook payload as JSON on stdin; emits a PreToolUse
`permissionDecision: "deny"` to stdout when a child is live and the command would move
the branch; exits 0 silently otherwise.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
try:
    from maestro_cli.guards import live_child_reason, moves_the_branch
except ImportError:  # pragma: no cover - a checkout without tools/ on disk
    moves_the_branch = None

# The tool names a subagent is spawned under. Both spellings are accepted: the tool has
# been called Task and Agent across versions, and a guard that fails open must not also
# fail open on a rename.
_CHILD_TOOLS = {"Agent", "Task"}


def running_children(transcript_path: str) -> list[str]:
    """Ids of subagents spawned in this session that have not reported a result yet.

    An empty list means "none live", which is also what an unreadable or unfamiliar
    transcript yields — the fail-open direction.
    """
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    spawned: dict[str, str] = {}   # tool_use id → a short label for the message
    finished: set[str] = set()
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        # Every shape is checked rather than assumed: a transcript line is written by
        # the harness, not by this guard, and one odd line must not raise — a hook that
        # crashes is a hook that gets removed.
        message = event.get("message") if isinstance(event, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") in _CHILD_TOOLS:
                label = (block.get("input") or {}).get("description") or block.get("name")
                spawned[str(block.get("id"))] = str(label)
            elif block.get("type") == "tool_result":
                finished.add(str(block.get("tool_use_id")))
    return [label for tool_id, label in spawned.items() if tool_id not in finished]


def main() -> int:
    if moves_the_branch is None:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if (payload.get("tool_name") or "") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not moves_the_branch(command):
        return 0

    transcript = payload.get("transcript_path")
    if not transcript:
        return 0  # nothing to read → no way to know → allow
    live = running_children(str(transcript))
    if not live:
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": live_child_reason(command, live),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
