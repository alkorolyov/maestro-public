"""The gate mode (tools/maestro_cli/gates.py): MAESTRO_GATES=warn|block.

Block is the default and every other test file runs under it (tests/conftest.py). What is
pinned here is both modes of each gate the switch touches:

    gate                     block (default)            warn
    record guard (hook)      deny                       no decision + additionalContext
    stamp guard (hook)       decision: block            additionalContext, once per report
    pre-commit guards 1, 2   commit refused             WARNING on stderr, commit made
    pre-commit guard 3       refused                    refused (not a record gate)

and that the dsh plugins drop the variable, so a dsh lane never inherits warn mode.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from maestro_cli import frontmatter as fm  # noqa: E402
from maestro_cli import gates  # noqa: E402

RECORD_HOOK = ROOT / "global" / "hooks" / "guard_records.py"
STAMP_HOOK = ROOT / "global" / "hooks" / "guard_stamps.py"
PRE_COMMIT = ROOT / "templates" / "pre-commit"

_spec = importlib.util.spec_from_file_location("guard_stamps_gates", STAMP_HOOK)
stamp_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp_guard)


# ── the switch ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    (None, "block"), ("", "block"), ("block", "block"), ("warn", "warn"), (" WARN ", "warn"),
    ("warning", "block"), ("off", "block"), ("0", "block"),
])
def test_only_an_explicit_warn_weakens_a_gate(value, expected):
    env = {} if value is None else {gates.ENV: value}
    assert gates.mode(env) == expected


def test_the_default_reads_the_process_environment(monkeypatch):
    assert gates.mode() == "block"
    monkeypatch.setenv("MAESTRO_GATES", "warn")
    assert gates.warns()


# ── the record guard ─────────────────────────────────────────────────────────

def _adr(tmp_path: Path) -> Path:
    d = tmp_path / "docs" / "adrs"
    d.mkdir(parents=True)
    p = d / "adr_07_t.md"
    p.write_text("---\nadr: 7\ntitle: t\nstatus: accepted\n---\n\n# ADR 7 — t\n")
    return p


def _record_hook(payload, **env) -> dict:
    out = subprocess.run([sys.executable, str(RECORD_HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30,
                         env={**os.environ, **env})
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def _frontmatter_edit(p):
    return {"tool_name": "Edit", "tool_input": {
        "file_path": str(p), "old_string": "status: accepted", "new_string": "status: superseded"}}


def test_record_guard_denies_in_block_mode(tmp_path):
    out = _record_hook(_frontmatter_edit(_adr(tmp_path)))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_record_guard_warns_and_decides_nothing_in_warn_mode(tmp_path):
    out = _record_hook(_frontmatter_edit(_adr(tmp_path)), MAESTRO_GATES="warn")
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in spec            # the normal permission flow runs
    assert "WARNING" in spec["additionalContext"] and "FRONTMATTER" in spec["additionalContext"]
    assert "maestro adr update" in spec["additionalContext"]
    assert out["systemMessage"] == spec["additionalContext"]


def test_record_guard_stays_silent_on_an_allowed_write_in_warn_mode(tmp_path):
    p = _adr(tmp_path)
    assert _record_hook({"tool_name": "Edit", "tool_input": {
        "file_path": str(p), "old_string": "# ADR 7 — t", "new_string": "# ADR 7 — t\n\nprose"}},
        MAESTRO_GATES="warn") == {}


# ── the stamp guard ──────────────────────────────────────────────────────────

def _epic_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    epics = root / "docs" / "epics"
    epics.mkdir(parents=True)
    fm.write(epics / "epic_01_x.md", {"epic": 1, "title": "x", "status": "todo", "items": []},
             "\n# Epic 1\n\n## Log\n\n- 2026-09-01 — opened.\n")
    return root


def _break(root: Path):
    p = root / "docs" / "epics" / "epic_01_x.md"
    p.write_text(p.read_text().replace("status: todo", "status: done"))


def _stamp_hook(monkeypatch, capsys, root: Path, tmp_path: Path) -> str:
    monkeypatch.setattr(stamp_guard.shutil, "which", lambda _: None)   # the checkout's CLI
    monkeypatch.setattr(stamp_guard.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash", "cwd": str(root)})))
    assert stamp_guard.main() == 0
    return capsys.readouterr().out


def test_stamp_guard_blocks_in_block_mode(tmp_path, monkeypatch, capsys):
    root = _epic_project(tmp_path)
    _break(root)
    assert json.loads(_stamp_hook(monkeypatch, capsys, root, tmp_path))["decision"] == "block"


def test_stamp_guard_warns_once_per_report_in_warn_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAESTRO_GATES", "warn")
    root = _epic_project(tmp_path)
    _break(root)
    first = json.loads(_stamp_hook(monkeypatch, capsys, root, tmp_path))
    assert "decision" not in first
    ctx = first["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PostToolUse"
    assert "WARNING" in ctx["additionalContext"] and "epic_01_x.md" in ctx["additionalContext"]
    # the same breach on the next tool call is not repeated
    assert _stamp_hook(monkeypatch, capsys, root, tmp_path) == ""


def test_stamp_guard_warns_again_after_the_breach_was_cleared(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAESTRO_GATES", "warn")
    root = _epic_project(tmp_path)
    p = root / "docs" / "epics" / "epic_01_x.md"
    clean = p.read_text()
    _break(root)
    assert _stamp_hook(monkeypatch, capsys, root, tmp_path)
    p.write_text(clean)
    assert _stamp_hook(monkeypatch, capsys, root, tmp_path) == ""      # clean: state cleared
    _break(root)
    assert "additionalContext" in _stamp_hook(monkeypatch, capsys, root, tmp_path)


# ── the pre-commit hook ──────────────────────────────────────────────────────

DRIFTY = "# Progress\n\n## Current\n\nThe table is 274 CONFORMANT / 0 OPEN.\n"


def _git(repo, *args, **kw):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, **kw)


@pytest.fixture
def hooked(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs" / "epics").mkdir(parents=True)
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"],
                ["config", "user.name", "T"]):
        _git(repo, *cmd, check=True)
    fm.write(repo / "docs" / "epics" / "epic_01_x.md",
             {"epic": 1, "title": "x", "status": "todo", "items": []}, "\n# Epic 1\n")
    (repo / "docs" / "findings.md").write_text("# Findings\n")
    _git(repo, "add", "-A", check=True)
    _git(repo, "commit", "-q", "-m", "docs: seed", check=True)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(PRE_COMMIT.read_text())
    hook.chmod(0o755)
    return repo


def _commit(repo, mode=None):
    _git(repo, "add", "-A", check=True)
    env = {k: v for k, v in os.environ.items() if k != "MAESTRO_GATES"}
    env["MAESTRO_CLI"] = str(ROOT / "tools")
    if mode is not None:
        env["MAESTRO_GATES"] = mode
    return _git(repo, "commit", "-m", "change", env=env)


def _hand_edit_record(repo):
    p = repo / "docs" / "epics" / "epic_01_x.md"
    p.write_text(p.read_text().replace("status: todo", "status: done"))


def test_pre_commit_stamp_guard_blocks_by_default(hooked):
    _hand_edit_record(hooked)
    out = _commit(hooked)
    assert out.returncode != 0 and "hand-edited maestro record" in out.stderr


def test_pre_commit_stamp_guard_warns_in_warn_mode(hooked):
    _hand_edit_record(hooked)
    out = _commit(hooked, "warn")
    assert out.returncode == 0, out.stderr
    assert "WARNING (MAESTRO_GATES=warn" in out.stderr and "epic_01_x.md" in out.stderr


def test_pre_commit_drift_guard_warns_in_warn_mode(hooked):
    (hooked / "docs" / "progress.md").write_text(DRIFTY)
    out = _commit(hooked, "warn")
    assert out.returncode == 0, out.stderr
    assert "WARNING" in out.stderr and "CONFORMANT" in out.stderr


def test_pre_commit_drift_guard_blocks_in_block_mode(hooked):
    (hooked / "docs" / "progress.md").write_text(DRIFTY)
    out = _commit(hooked, "block")
    assert out.returncode != 0 and "staged docs carry drift" in out.stderr


def test_pre_commit_trunk_guard_blocks_only_in_block_mode(hooked):
    """Guard 3 is the strict lane's git rule: a high-judgment session
    under warn organises its own git work and may commit code on main."""
    (hooked / "src").mkdir()
    (hooked / "src" / "m.py").write_text("x = 1\n")
    out = _commit(hooked, "block")
    assert out.returncode != 0 and "only docs/ may be committed directly" in out.stderr
    out = _commit(hooked, "warn")
    assert out.returncode == 0, out.stderr
    assert "only docs/ may be committed directly" not in out.stderr


