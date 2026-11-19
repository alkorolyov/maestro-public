"""The Claude Code adapter (global/hooks/guard_records.py).

The RULE it enforces is tested in test_guards.py, against both tool dialects. What is
left here is the adapter's own job: read a PreToolUse payload, emit a PreToolUse
decision, and never turn an odd payload into a blocked session. Its dsh twin
(test_dsh_record_guard.py) pins the same three properties on the other side, which is
how "both harnesses refuse the same writes" stays true rather than merely intended.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "global" / "hooks" / "guard_records.py"

_FM = "---\nadr: 7\ntitle: t\nstatus: accepted\n---\n"
_BODY = "\n# ADR 7 — t\n\n**Decision**: body text.\n"


def _run(payload) -> str:
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr   # a hook must never fail; it decides in stdout
    return out.stdout


def _adr(tmp_path: Path) -> Path:
    d = tmp_path / "docs" / "adrs"
    d.mkdir(parents=True)
    p = d / "adr_07_t.md"
    p.write_text(_FM + _BODY)
    return p


def test_a_guarded_write_becomes_a_deny_decision(tmp_path):
    p = _adr(tmp_path)
    decision = json.loads(_run({"tool_name": "Edit", "tool_input": {
        "file_path": str(p), "old_string": "status: accepted", "new_string": "status: superseded"}}))
    out = decision["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert "FRONTMATTER" in out["permissionDecisionReason"]
    assert "maestro adr update" in out["permissionDecisionReason"]


def test_an_allowed_write_emits_nothing(tmp_path):
    p = _adr(tmp_path)
    assert _run({"tool_name": "Edit", "tool_input": {
        "file_path": str(p), "old_string": "body text.", "new_string": "new text."}}) == ""


def test_the_epic_board_is_denied_too(tmp_path):
    """The gap this adapter shipped with: docs/epics/INDEX.md was generated like the
    other three indexes and guarded like none of them."""
    idx = tmp_path / "docs" / "epics" / "INDEX.md"
    idx.parent.mkdir(parents=True)
    idx.write_text("| epic | title |\n")
    decision = json.loads(_run({"tool_name": "Edit", "tool_input": {
        "file_path": str(idx), "old_string": "| epic | title |", "new_string": "x"}}))
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_payload_with_no_tool_input_is_allowed():
    assert _run({"tool_name": "Edit"}) == ""


def test_unparseable_stdin_never_blocks():
    out = subprocess.run([sys.executable, str(HOOK)], input="not json at all",
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stdout == ""
