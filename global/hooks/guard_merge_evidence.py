#!/usr/bin/env python3
"""Maestro merge-evidence guard — a Claude Code PreToolUse hook.

Its dsh twin (a plugin) was removed. A `git merge --no-ff <ref>`
is denied when the project declares a merge-evidence log and that log holds no passing
line for the TIP COMMIT of <ref>. The rule, the configuration keys and what the design
costs are in `maestro_cli.guards.merge_evidence_verdict`; nothing project-specific lives
here or there — the log's path and what a passing line looks like are read from the
project's own pyproject.toml:

    [tool.maestro]
    merge_evidence_log = "docs/archive/gate_runs.log"
    merge_evidence_pass = '\\b([0-9a-f]{7,40})\\b(?!-dirty).*RESULT=OK'

A project that declares neither key is never denied anything, which is why this guard can
ship without being wired: it is inert by construction.

Why a guard and not a check: merges reached main before any gate run existed for them,
and one cited its PARENT commit's gate line as its own. A check enforced after the fact
can only alarm once the bad merge already exists.

It fails OPEN in every uncertainty — nothing declared, no pyproject.toml, a ref git cannot
resolve, git unavailable — because a guard that cannot see the evidence must not stop the
work.

NOT WIRED. `maestro init --harness` does not write a row for this hook and
`harness.DSH_PLUGINS` carries none for its twin; arming it is a deliberate act. The row,
when someone wants it, is:

    {"hooks": {"PreToolUse": [
      {"matcher": "Bash",
       "hooks": [{"type": "command",
                  "command": "python3 <maestro>/global/hooks/guard_merge_evidence.py",
                  "timeout": 10}]}
    ]}}

Contract: reads the hook payload as JSON on stdin; emits a PreToolUse
`permissionDecision: "deny"` to stdout when the merge has no evidence; exits 0 silently
otherwise.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
try:
    from maestro_cli.guards import merge_evidence_verdict
except ImportError:  # pragma: no cover - a checkout without tools/ on disk
    merge_evidence_verdict = None


def main() -> int:
    if merge_evidence_verdict is None:
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
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    reason = merge_evidence_verdict(command, cwd)
    if not reason:
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
