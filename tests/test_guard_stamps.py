"""The stamp guard hook (global/hooks/guard_stamps.py): after any tool call, block when a
record's CLI-owned surface was edited by hand — whatever tool or shell did it.

The hook shells out to `maestro docs stamp --check`; these tests force the module fallback
(the checkout's own package) so they do not depend on an installed `maestro`.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from maestro_cli import frontmatter as fm  # noqa: E402

_HOOK = Path(__file__).resolve().parent.parent / "global" / "hooks" / "guard_stamps.py"
_spec = importlib.util.spec_from_file_location("guard_stamps", _HOOK)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

BODY = "\n# Epic 1\n\n## Log\n\n- 2026-09-01 — opened.\n"


def _run(monkeypatch, capsys, cwd: Path) -> tuple[int, str]:
    monkeypatch.setattr(guard.shutil, "which", lambda _: None)      # force the module fallback
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash", "cwd": str(cwd)})))
    code = guard.main()
    return code, capsys.readouterr().out


def _project(tmp_path: Path) -> Path:
    epics = tmp_path / "docs" / "epics"
    epics.mkdir(parents=True)
    fm.write(epics / "epic_01_x.md", {"epic": 1, "title": "x", "status": "todo", "items": []}, BODY)
    return tmp_path


def test_silent_outside_a_maestro_project(tmp_path, monkeypatch, capsys):
    (tmp_path / "src").mkdir()
    assert _run(monkeypatch, capsys, tmp_path) == (0, "")


def test_silent_when_every_stamp_matches(tmp_path, monkeypatch, capsys):
    assert _run(monkeypatch, capsys, _project(tmp_path)) == (0, "")


def test_silent_after_a_body_edit(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path)
    p = root / "docs" / "epics" / "epic_01_x.md"
    p.write_text(p.read_text().replace("# Epic 1", "# Epic 1\n\nhand-written prose is fine"))
    assert _run(monkeypatch, capsys, root) == (0, "")


@pytest.mark.parametrize("edit", [
    ("status: todo", "status: done"),                              # frontmatter, any tool
    ("- 2026-09-01 — opened.\n", "- 2026-09-01 — opened.\n- 2026-09-02 — all merged.\n"),  # cat >>
])
def test_blocks_a_hand_edit_and_names_the_file(tmp_path, monkeypatch, capsys, edit):
    root = _project(tmp_path)
    p = root / "docs" / "epics" / "epic_01_x.md"
    p.write_text(p.read_text().replace(*edit))
    code, out = _run(monkeypatch, capsys, root)
    assert code == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "epic_01_x.md" in decision["reason"] and "maestro" in decision["reason"]


def test_silent_when_no_cli_can_be_found(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path)
    monkeypatch.setattr(guard, "maestro_command", lambda: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(root)})))
    assert guard.main() == 0 and capsys.readouterr().out == ""
