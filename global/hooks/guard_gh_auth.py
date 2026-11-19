#!/usr/bin/env python3
"""Maestro gh-auth guard — a Claude Code PreToolUse hook.

gh is used with a per-project token only (`source .env` puts GITHUB_TOKEN in the env;
see modules/repo_setup.md). A global gh login would give every folder one account, and
`gh auth setup-git` adds gh as a GLOBAL git credential helper that git asks before a
repo's own store — both silently cross the per-org identity split. `gh auth token`
prints the credential itself. So any Bash command that runs

    gh auth login | setup-git | switch | refresh | token

is denied, in every session (top-level and subagent). The match is over the whole
command text, so `bash -c "gh auth login"`, `x && /usr/bin/gh auth ...` are caught too.
Read-only `gh auth status` passes. The person can still run it themselves via `! ...`.

Claude Code only — dsh and plain shells are not covered.

Wire-up (in ~/.claude/settings.json, PreToolUse, matcher "Bash"):

    {"type": "command",
     "command": "python3 <maestro>/global/hooks/guard_gh_auth.py",
     "timeout": 5}

Contract: reads the hook payload as JSON on stdin; emits `permissionDecision: "deny"`
on a match; exits 0 silently otherwise, and fails OPEN on an unreadable payload.
"""
import json
import re
import sys

GH_AUTH_WRITE = re.compile(r"\bgh\s+auth\s+(login|setup-git|switch|refresh|token)\b")

REASON = (
    "gh-auth guard: `gh auth {sub}` is blocked. gh must use the project's own token "
    "(`source .env && gh ...` — gh reads GITHUB_TOKEN), never a global login or a "
    "global git credential helper (maestro modules/repo_setup.md). If a login is truly "
    "needed, ask the person to run it themselves."
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    m = GH_AUTH_WRITE.search(command)
    if not m:
        return 0
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": REASON.format(sub=m.group(1)),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
