"""The guard TABLE for Claude Code: which hook files exist and which are wired.

dsh runs with no maestro guards (its plugins were removed); only the Claude Code hooks in
global/hooks/ remain. GUARDS are installed by `maestro init --harness`, CLAUDE_ONLY are
installed and have no twin, SHIPPED_UNWIRED ship tested but are installed by nothing —
arming one means moving it into GUARDS on purpose. A hook file added without a row here
fails this file.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from maestro_cli import init as init_mod  # noqa: E402

GUARDS = {
    "record-guard": "guard_records.py",
    "stamp-guard": "guard_stamps.py",
    "kb-index-regen": "regen_kb_index.py",
}

# Hook files that ship and are tested but that no `init --harness` row installs.
SHIPPED_UNWIRED = {
    "live-child-guard": "guard_live_child.py",
    "executor-guard": "guard_executor.py",
    "spawn-guard": "guard_spawn.py",
    "merge-evidence-guard": "guard_merge_evidence.py",
}

# gh uses a per-project token, never a global login (modules/repo_setup.md).
CLAUDE_ONLY = {
    "gh-auth-guard": "guard_gh_auth.py",
}


@pytest.fixture
def harness_rows(tmp_path):
    """The (event, matcher, command, timeout, label) rows `init --harness` would write."""
    captured = []
    original = init_mod.wire_hooks

    def spy(settings, specs, plan):
        captured.extend(specs)
        return original(settings, specs, plan)

    init_mod.wire_hooks = spy
    try:
        init_mod.init_harness(repo=ROOT, home=tmp_path, dry_run=True)
    finally:
        init_mod.wire_hooks = original
    return captured


@pytest.mark.parametrize("hook", [*GUARDS.values(), *SHIPPED_UNWIRED.values(), *CLAUDE_ONLY.values()])
def test_every_hook_is_on_disk(hook):
    assert (ROOT / "global" / "hooks" / hook).is_file()


@pytest.mark.parametrize("guard_id", GUARDS)
def test_every_guard_is_installed_on_the_claude_code_side(guard_id, harness_rows):
    assert guard_id in {row[4] for row in harness_rows}, \
        f"{guard_id} has a hook file but no row in `maestro init --harness`"


def test_no_claude_code_hook_file_is_left_unwired():
    on_disk = {p.name for p in (ROOT / "global" / "hooks").glob("*.py")}
    assert on_disk == set(GUARDS.values()) | set(SHIPPED_UNWIRED.values()) | set(CLAUDE_ONLY.values())


@pytest.mark.parametrize("guard_id", CLAUDE_ONLY)
def test_a_claude_only_guard_is_installed_on_the_claude_code_side(guard_id, harness_rows):
    rows = {row[4]: row for row in harness_rows}
    assert guard_id in rows, f"{guard_id} has a hook file but no row in `maestro init --harness`"
    assert rows[guard_id][2].endswith(CLAUDE_ONLY[guard_id])


@pytest.mark.parametrize("guard_id, hook", SHIPPED_UNWIRED.items())
def test_an_unwired_guard_is_installed_by_nothing(guard_id, hook, harness_rows):
    """Moving the guard into GUARDS is how it is armed on purpose, not by accident."""
    assert guard_id not in {row[4] for row in harness_rows}
    assert not any(row[2].endswith(hook) for row in harness_rows)


def test_the_claude_code_rows_point_at_files_that_exist(harness_rows):
    for _event, _matcher, command, _timeout, label in harness_rows:
        path = Path(command.split(" ", 1)[1])
        assert path.is_file(), f"{label}: row runs {path}, which does not exist"
