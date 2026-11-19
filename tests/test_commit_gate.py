"""The commit gate: `docs check --staged` and the pre-commit hook that runs it.

Guard 2 of templates/pre-commit exists because of a measured miss. An agent session
wrote its records correctly through the CLI, then committed a progress.md that asserted
`274 CONFORMANT / 0 OPEN` — a metric and a status word, against rules 10 and 2. Nothing
stopped it: the stamp check that pre-commit v1 ran answers "did the CLI write this
record", which is a different question.

--staged is the shape that makes the gate installable. A project adopting maestro has
pre-existing drift (11 unmarked status words in a domain doc); a whole-project
gate would block every unrelated commit until that backlog was cleared, which is how a
gate gets deleted instead of obeyed. Scoped to the staged files it blocks only what THIS
commit adds.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from maestro_cli import checks  # noqa: E402

HOOK = ROOT / "templates" / "pre-commit"

DRIFTY = "# Progress\n\n## Current\n\nThe table is 274 CONFORMANT / 0 OPEN.\n"
CLEAN = "# Progress\n\n## Current\n\nSee `docs/epics/epic_04_x.md` for the table.\n"


def _cli(cwd: Path, *args) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "tools"), "MAESTRO_ROOT": str(cwd)}
    return subprocess.run([sys.executable, "-m", "maestro_cli.cli", *args],
                          cwd=str(cwd), capture_output=True, text=True, env=env, timeout=60)


def _repo(tmp_path: Path) -> Path:
    """A git repo WITH a first commit. The history matters: ADR 9's status-word finding
    only blocks for files git can say were touched, so a repo with no HEAD downgrades
    every one of them to an advisory and the gate under test never fires."""
    (tmp_path / "docs").mkdir()
    for cmd in (["init", "-b", "main"], ["config", "user.email", "t@example.com"],
                ["config", "user.name", "T"]):
        subprocess.run(["git", "-C", str(tmp_path), *cmd], check=True, capture_output=True)
    (tmp_path / "docs" / "findings.md").write_text("# Findings\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "docs: seed"],
                   check=True, capture_output=True)
    return tmp_path


def _commit_all(repo: Path, message: str) -> subprocess.CompletedProcess:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    return subprocess.run(["git", "-C", str(repo), "commit", "-m", message],
                          capture_output=True, text=True,
                          env={**os.environ, "MAESTRO_CLI": str(ROOT / "tools"), "PATH": os.environ["PATH"]})


# ── scope_to: the filter itself ──────────────────────────────────────────────

def test_scope_to_keeps_findings_about_staged_files():
    findings = ["docs/progress.md:9: a status word", "docs/epics/backlog.md:144: another"]
    assert checks.scope_to(findings, {"docs/progress.md"}) == [findings[0]]


def test_scope_to_drops_a_finding_that_names_no_staged_path():
    assert checks.scope_to(["docs/epics/backlog.md:1: old drift"], {"docs/progress.md"}) == []


def test_scope_to_with_nothing_staged_keeps_nothing():
    assert checks.scope_to(["docs/progress.md:9: x"], set()) == []


def test_staged_paths_reads_the_index(tmp_path):
    repo = _repo(tmp_path)
    (repo / "docs" / "progress.md").write_text(CLEAN)
    subprocess.run(["git", "-C", str(repo), "add", "docs/progress.md"], check=True, capture_output=True)
    assert checks.staged_paths(repo) == {"docs/progress.md"}


def test_staged_paths_outside_a_repo_is_empty(tmp_path):
    assert checks.staged_paths(tmp_path) == set()


# ── docs check --staged ──────────────────────────────────────────────────────

def test_unstaged_drift_does_not_fail_the_staged_check(tmp_path):
    repo = _repo(tmp_path)
    (repo / "docs" / "progress.md").write_text(DRIFTY)
    assert _cli(repo, "docs", "check").returncode == 2          # the project IS drifting
    assert _cli(repo, "docs", "check", "--staged").returncode == 0   # but not in this commit


def test_staged_drift_fails_the_staged_check(tmp_path):
    repo = _repo(tmp_path)
    (repo / "docs" / "progress.md").write_text(DRIFTY)
    subprocess.run(["git", "-C", str(repo), "add", "docs/progress.md"], check=True, capture_output=True)
    out = _cli(repo, "docs", "check", "--staged")
    assert out.returncode == 2
    assert "docs/progress.md" in out.stderr and "CONFORMANT" in out.stderr


def test_a_staged_clean_file_beside_unstaged_drift_passes(tmp_path):
    repo = _repo(tmp_path)
    (repo / "docs" / "findings.md").write_text("# Findings\n\nan unrelated line.\n")
    (repo / "docs" / "progress.md").write_text(DRIFTY)
    subprocess.run(["git", "-C", str(repo), "add", "docs/findings.md"], check=True, capture_output=True)
    assert _cli(repo, "docs", "check", "--staged").returncode == 0


# ── the hook, end to end in a real repo ──────────────────────────────────────

@pytest.fixture
def hooked(tmp_path):
    repo = _repo(tmp_path)
    target = repo / ".git" / "hooks" / "pre-commit"
    target.write_text(HOOK.read_text())
    target.chmod(0o755)
    return repo


def test_the_template_declares_v4(tmp_path):
    """The version marker is how `maestro init` knows to replace an older hook in place."""
    assert "# maestro pre-commit v4" in HOOK.read_text()


def test_a_clean_docs_commit_passes(hooked):
    (hooked / "docs" / "progress.md").write_text(CLEAN)
    out = _commit_all(hooked, "docs: clean")
    assert out.returncode == 0, out.stderr


def test_a_commit_that_adds_drift_is_blocked(hooked):
    (hooked / "docs" / "progress.md").write_text(DRIFTY)
    out = _commit_all(hooked, "docs: drifting")
    assert out.returncode != 0
    assert "staged docs carry drift" in out.stderr
    assert "CONFORMANT" in out.stderr


def test_the_blocked_commit_wrote_nothing(hooked):
    """A blocked hook must leave the history where it was — a gate that half-commits is
    worse than none."""
    before = subprocess.run(["git", "-C", str(hooked), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout
    (hooked / "docs" / "progress.md").write_text(DRIFTY)
    _commit_all(hooked, "docs: drifting")
    after = subprocess.run(["git", "-C", str(hooked), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout
    assert after == before


def test_the_override_is_explicit_and_works(hooked):
    (hooked / "docs" / "progress.md").write_text(DRIFTY)
    subprocess.run(["git", "-C", str(hooked), "add", "-A"], check=True, capture_output=True)
    out = subprocess.run(["git", "-C", str(hooked), "commit", "-m", "docs: knowingly"],
                         capture_output=True, text=True,
                         env={**os.environ, "MAESTRO_CLI": str(ROOT / "tools"),
                              "MAESTRO_SKIP_DOCS_CHECK": "1"})
    assert out.returncode == 0, out.stderr


def test_pre_existing_drift_never_blocks_an_unrelated_commit(hooked):
    """The property --staged exists for: adopt maestro on a project with a drifting
    backlog and the very next docs commit must still go through."""
    (hooked / "docs" / "progress.md").write_text(DRIFTY)
    subprocess.run(["git", "-C", str(hooked), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(hooked), "-c", "core.hooksPath=/dev/null",
                    "commit", "-m", "adopt"], check=True, capture_output=True)
    (hooked / "docs" / "findings.md").write_text("# Findings\n\nunrelated work.\n")
    out = _commit_all(hooked, "docs: unrelated")
    assert out.returncode == 0, out.stderr


def test_code_on_main_is_still_blocked_by_guard_3(hooked):
    (hooked / "src").mkdir()
    (hooked / "src" / "m.py").write_text("x = 1\n")
    out = _commit_all(hooked, "code on main")
    assert out.returncode != 0 and "only docs/ may be committed directly" in out.stderr


def test_without_the_cli_the_hook_stays_quiet(hooked):
    """A machine with no maestro must not fail every commit — guards 1 and 2 stand down,
    guard 3 (pure git) still runs."""
    (hooked / "docs" / "progress.md").write_text(DRIFTY)
    subprocess.run(["git", "-C", str(hooked), "add", "-A"], check=True, capture_output=True)
    env = {k: v for k, v in os.environ.items() if k != "MAESTRO_CLI"}
    env["PATH"] = "/nonexistent"
    out = subprocess.run(["/usr/bin/git", "-C", str(hooked), "commit", "-m", "docs: no cli"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
