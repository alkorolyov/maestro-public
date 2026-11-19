#!/usr/bin/env python3
"""Maestro record-guard — a Claude Code PreToolUse hook.

The Claude Code adapter over `maestro_cli.guards.verdict`. It carries no rule of its
own: it translates a PreToolUse payload into the shared call shape, and translates a
deny reason back into a PreToolUse decision. Its dsh twin (removed),
is the same adapter for `tools/pre-execute` and reaches the same rule through
`maestro docs guard`. Both harnesses therefore refuse exactly the same writes.

What the rule guards, and why a hook rather than a written rule: "never hand-author
records" was documented everywhere and enforced nowhere, so ~125 hand-edit violations
accumulated across adopting projects. See tools/maestro_cli/guards.py for the surface
it draws (frontmatter and an epic's `## Log` are CLI-owned; body prose is not) and the
reasoning behind each line.

It does NOT block the maestro CLI: that writes records through its own file I/O as a
Bash subprocess, so it never appears as a Write/Edit tool call. findings.md,
progress.md, the docs/data.md catalog and docs/kb/** are hand-edited by design and are
never guarded.

Wire-up (in ~/.claude/settings.json, alongside any existing PreToolUse entries):

    {"hooks": {"PreToolUse": [
      {"matcher": "Write|Edit|MultiEdit",
       "hooks": [{"type": "command",
                  "command": "python3 <maestro>/global/hooks/guard_records.py",
                  "timeout": 5}]}
    ]}}

`maestro init --harness` writes that row for you.

Contract: reads the hook payload as JSON on stdin; emits a PreToolUse
`permissionDecision: "deny"` (with a reason the model sees and self-corrects on) to
stdout for guarded paths; exits 0 silently for everything else.

Under `MAESTRO_GATES=warn` (maestro_cli/gates.py) a guarded write is NOT denied: the
hook sets no permission decision, so the normal permission flow runs, and hands the same
reason to the model as `additionalContext` (and to the human as a `systemMessage`).
"""
import json
import sys
from pathlib import Path

# The rule lives in the CLI package beside this checkout — imported, not shelled out to,
# because a PreToolUse hook sits in front of every Write and Edit and a subprocess per
# call is a tax on the whole session. A checkout without the package still loads: the
# guard then has no opinion rather than blocking every write.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
try:
    from maestro_cli.gates import warning, warns
    from maestro_cli.guards import verdict
except ImportError:  # pragma: no cover - a checkout without tools/ on disk
    verdict = None


def main() -> int:
    if verdict is None:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # no parseable payload → no opinion, let normal flow proceed

    tool_input = payload.get("tool_input") or {}
    reason = verdict(payload.get("tool_name") or "", tool_input)
    if reason is None:
        return 0  # not a guarded surface → allow

    if warns():
        text = warning("record-guard", reason)
        json.dump({"systemMessage": text,
                   "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "additionalContext": text}}, sys.stdout)
        return 0

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
