"""The Claude Code spawn guard (global/hooks/guard_spawn.py).

Before an Agent/Task child is spawned into a maestro project, docs/ must hold no
uncommitted knowledge-base writes. That is this half's WHOLE rule: the brief check
(`Files:` / `Done:`) lives in the dsh plugin only — the harnesses diverge by design,
and `test_this_half_does_not_judge_the_brief` pins it. A child shares the checkout, and
one `git stash` from it wipes uncommitted docs. The hook asks git in the payload's cwd;
the shared rule (`guards.dirty_docs`, `guards.spawn_reason`) is what both halves run.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

HOOK = ROOT / "global" / "hooks" / "guard_spawn.py"

from maestro_cli import guards  # noqa: E402
from maestro_cli.guards import (brief_refusal, current_branch, dirty_docs,  # noqa: E402
                                foreign_writer, spawn_reason)


def _git(repo: Path, *args) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(repo), "PATH": "/usr/bin:/bin"})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed maestro project: docs/epics/epic_06.md, docs/progress.md, src/lib.rs."""
    (tmp_path / "docs" / "epics").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "docs" / "epics" / "epic_06_x.md").write_text("---\nepic: 6\n---\n# Epic 6\n")
    (tmp_path / "docs" / "progress.md").write_text("## Current\n")
    (tmp_path / "src" / "lib.rs").write_text("fn main() {}\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _run(cwd: Path, tool: str = "Agent", **tool_input) -> str:
    payload = {"tool_name": tool,
               "tool_input": {"description": "item 1", "prompt": "do it", **tool_input},
               "cwd": str(cwd)}
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _reason(stdout: str) -> str:
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_clean_tree_spawns(repo):
    assert _run(repo) == ""


# ── the brief rule is NOT here ──────────────────────────────────────────────

def test_this_half_does_not_judge_the_brief(repo):
    """The dsh half refuses a spawn whose brief names no files and no done-command
    (`guards.brief_refusal`, driven in test_dsh_spawn_guard.py). This one does not: a
    Claude Code session is the high-judgment top-level session that writes code itself,
    and it is the dsh PLANNER routing work to local workers whose briefs have to be
    scoped. The harnesses are not mirrors, and this test is what says so."""
    assert brief_refusal("port the read sites, you will find them") is not None
    assert _run(repo, prompt="port the read sites, you will find them") == ""
    assert _run(repo, prompt="", description="") == ""


def test_a_modified_record_denies_and_names_the_path(repo):
    (repo / "docs" / "epics" / "epic_06_x.md").write_text("---\nepic: 6\nstatus: in_progress\n---\n")
    reason = _reason(_run(repo))
    assert "docs/epics/epic_06_x.md" in reason
    assert "git add" in reason and "commit" in reason


def test_a_new_untracked_record_denies_too(repo):
    (repo / "docs" / "epics" / "epic_07_y.md").write_text("---\nepic: 7\n---\n")
    assert "docs/epics/epic_07_y.md" in _reason(_run(repo))


def test_a_staged_but_uncommitted_write_denies(repo):
    (repo / "docs" / "progress.md").write_text("## Current\nepic 6\n")
    _git(repo, "add", "docs/progress.md")
    assert "docs/progress.md" in _reason(_run(repo))


def test_dirty_code_alone_does_not_block_a_spawn(repo):
    (repo / "src" / "lib.rs").write_text("fn main() { todo!() }\n")
    assert _run(repo) == ""


@pytest.mark.parametrize("isolation", ["remote", "worktree"])
def test_a_child_with_its_own_tree_is_exempt(repo, isolation):
    (repo / "docs" / "progress.md").write_text("dirty\n")
    assert _run(repo, isolation=isolation) == ""


def test_the_task_spelling_counts_too(repo):
    (repo / "docs" / "progress.md").write_text("dirty\n")
    assert _run(repo, tool="Task") != ""


def test_other_tools_are_never_consulted(repo):
    (repo / "docs" / "progress.md").write_text("dirty\n")
    assert _run(repo, tool="Bash") == ""


def test_a_project_without_records_is_not_guarded(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.md").write_text("x\n")
    assert _run(tmp_path) == ""


def test_a_maestro_layout_outside_git_allows(tmp_path):
    (tmp_path / "docs" / "adrs").mkdir(parents=True)
    (tmp_path / "docs" / "adrs" / "adr_1.md").write_text("x\n")
    assert _run(tmp_path) == ""


def test_unparseable_stdin_never_blocks():
    out = subprocess.run([sys.executable, str(HOOK)], input="{{{", capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0 and out.stdout == ""


# ── the shared rule ──────────────────────────────────────────────────────────

def test_dirty_docs_lists_only_docs_paths(repo):
    (repo / "src" / "lib.rs").write_text("changed\n")
    (repo / "docs" / "progress.md").write_text("changed\n")
    assert dirty_docs(repo) == ["docs/progress.md"]


def test_dirty_docs_is_none_when_git_cannot_answer(tmp_path):
    assert dirty_docs(tmp_path) is None


def test_the_reason_caps_the_path_list():
    paths = [f"docs/kb/n{i}.md" for i in range(11)]
    reason = spawn_reason(paths)
    assert "(+3 more)" in reason and "docs/kb/n10.md" not in reason


def test_the_reason_says_so_when_the_checkout_is_off_the_trunk():
    on_branch = spawn_reason(["docs/progress.md"], "feat/e9-item2-preset")
    assert "You are on `feat/e9-item2-preset`" in on_branch and "switch to main" in on_branch
    for trunk in ("main", "master", None):
        assert "switch to main" not in spawn_reason(["docs/progress.md"], trunk)


def test_current_branch_reads_git_or_says_nothing(tmp_path):
    assert current_branch(tmp_path, run=lambda argv, cwd: (0, "feat/x\n")) == "feat/x"
    assert current_branch(tmp_path, run=lambda argv, cwd: (0, "\n")) is None      # detached
    assert current_branch(tmp_path, run=lambda argv, cwd: (128, "")) is None


# ── the foreign-writer exemption ─────────────────────────────────────────────

def _fake_pid(proc: Path, pid: str, comm: str, argv: list[str], cwd: Path) -> None:
    """One /proc/<pid>/ entry: comm, a NUL-separated cmdline, and a cwd symlink."""
    d = proc / pid
    d.mkdir(parents=True)
    (d / "comm").write_text(comm + "\n")
    (d / "cmdline").write_text("\0".join(argv) + "\0")
    (d / "cwd").symlink_to(cwd)


def test_foreign_writer_finds_a_dsh_running_in_the_checkout(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    project, other = tmp_path / "project", tmp_path / "other"
    project.mkdir()
    other.mkdir()
    # A node-wrapped dsh in the project, and a node process of another kind beside it.
    _fake_pid(proc, "4242", "node", ["node", "/home/u/.nvm/bin/dsh", "--profile", "headless"],
              project)
    _fake_pid(proc, "17", "node", ["node", "/home/u/bin/vite", "dev"], project)
    _fake_pid(proc, "notapid", "x", ["x"], project)
    (proc / "8").mkdir()          # a process that exited mid-scan: no comm, no cmdline
    monkeypatch.setattr(guards, "PROC", proc)
    assert foreign_writer(project) == 4242
    assert foreign_writer(other) is None


def test_foreign_writer_ignores_a_dsh_in_another_checkout(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    project, elsewhere = tmp_path / "project", tmp_path / "elsewhere"
    project.mkdir()
    elsewhere.mkdir()
    _fake_pid(proc, "99", "dsh-headless-local", ["dsh-headless-local"], elsewhere)
    monkeypatch.setattr(guards, "PROC", proc)
    assert foreign_writer(project) is None
    assert foreign_writer(elsewhere) == 99
