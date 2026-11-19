"""Two git states that are not a breach (tools/maestro_cli/gitstate.py).

MERGE RESOLUTION. During a merge, a record whose CLI-owned surface equals one side's was
taken from that side: the stamp check passes it (S3, a note), and the record guard lets a
write through that leaves it so. A surface that matches neither side is still a hand edit.

A LINKED WORKTREE WITHOUT data/. A cited path that git ignores, missing here but present
in the main checkout, is a warning, not drift. Missing there too, it stays drift; and in
the main checkout itself nothing changes.

Every case drives real git in a throwaway repo, and the CLI as a subprocess with
MAESTRO_ROOT, as the pre-commit hook and the stamp guard would.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from maestro_cli import frontmatter as fm  # noqa: E402
from maestro_cli import gitstate, guards  # noqa: E402

ADR = "docs/adrs/adr_01_x.md"


def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check)


def _cli(cwd: Path, *args) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "tools"), "MAESTRO_ROOT": str(cwd)}
    return subprocess.run([sys.executable, "-m", "maestro_cli.cli", *args], cwd=str(cwd),
                          capture_output=True, text=True, env=env, timeout=60)


def _init(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"],
                ["config", "user.name", "T"], ["config", "core.hooksPath", "/dev/null"]):
        _git(repo, *cmd)


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


# ── merge resolution ─────────────────────────────────────────────────────────

@pytest.fixture
def conflicted(tmp_path):
    """main and `side` both changed ADR 1's decision; `side` committed a HAND-EDITED
    frontmatter (its stamp does not match), so taking that side leaves a mismatch."""
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "docs" / "adrs").mkdir(parents=True)
    fm.write(repo / ADR, {"adr": 1, "title": "x", "status": "accepted", "decision": "base"},
             "\n# ADR 1 — x\n")
    _commit(repo, "base")
    _git(repo, "switch", "-q", "-c", "side")
    p = repo / ADR
    p.write_text(p.read_text().replace("decision: base", "decision: from side by hand"))
    _commit(repo, "side")
    _git(repo, "switch", "-q", "main")
    fm.write(repo / ADR, {"adr": 1, "title": "x", "status": "accepted", "decision": "from main"},
             "\n# ADR 1 — x\n")
    _commit(repo, "main")
    assert _git(repo, "merge", "--no-ff", "side", check=False).returncode != 0   # conflict
    return repo


def _theirs(repo):
    return _git(repo, "show", f"MERGE_HEAD:{ADR}").stdout


def test_a_merge_is_detected(conflicted):
    assert len(gitstate.merge_heads(conflicted / "docs" / "adrs")) == 1


def test_taking_a_side_passes_the_stamp_check(conflicted):
    (conflicted / ADR).write_text(_theirs(conflicted))
    out = _cli(conflicted, "docs", "stamp", "--check")
    assert out.returncode == 0, out.stderr
    assert "merge resolution" in out.stdout


def test_the_same_content_outside_a_merge_is_a_hand_edit(conflicted):
    theirs = _theirs(conflicted)
    _git(conflicted, "merge", "--abort")
    (conflicted / ADR).write_text(theirs)
    assert _cli(conflicted, "docs", "stamp", "--check").returncode == 2


def test_a_hand_edit_during_a_merge_is_still_caught(conflicted):
    (conflicted / ADR).write_text(_theirs(conflicted).replace("from side by hand", "typed now"))
    out = _cli(conflicted, "docs", "stamp", "--check")
    assert out.returncode == 2 and "adr_01_x.md" in out.stderr


def test_the_record_guard_lets_a_write_of_one_side_through(conflicted):
    p = conflicted / ADR
    assert guards.verdict("Write", {"file_path": str(p), "content": _theirs(conflicted)}) is None


def test_the_record_guard_lets_an_edit_that_resolves_to_a_side_through(conflicted):
    p = conflicted / ADR
    current = p.read_text()
    start = current.index("<<<<<<<")
    end = current.index("\n", current.index(">>>>>>>")) + 1
    block = current[start:end]
    theirs = block[block.index("=======\n") + len("=======\n"):block.index(">>>>>>>")]
    assert current[:start] + theirs + current[end:] == _theirs(conflicted)
    assert guards.verdict("Edit", {"file_path": str(p), "old_string": block,
                                   "new_string": theirs}) is None


def test_the_record_guard_still_denies_a_new_frontmatter_during_a_merge(conflicted):
    p = conflicted / ADR
    typed = _theirs(conflicted).replace("from side by hand", "typed now")
    assert "FRONTMATTER" in guards.verdict("Write", {"file_path": str(p), "content": typed})


def test_the_record_guard_denies_the_side_text_outside_a_merge(conflicted):
    theirs = _theirs(conflicted)
    _git(conflicted, "merge", "--abort")
    p = conflicted / ADR
    assert guards.verdict("Write", {"file_path": str(p), "content": theirs}) is not None


# ── the linked worktree ──────────────────────────────────────────────────────

ARTIFACT = "data/experiments/exp_01_x/run_1/metrics.json"


@pytest.fixture
def main_checkout(tmp_path):
    """A project whose exp 1 cites a gitignored artifact that exists in this checkout."""
    repo = tmp_path / "main"
    _init(repo)
    (repo / ".gitignore").write_text("data/\n")
    (repo / "docs").mkdir()
    (repo / ARTIFACT).parent.mkdir(parents=True)
    (repo / ARTIFACT).write_text("{}\n")
    (repo / "data" / "experiments" / "exp_01_x" / "run_1" / "run.log").write_text("ok\n")
    assert _cli(repo, "exp", "new", "--slug=x").returncode == 0
    out = _cli(repo, "exp", "update", "--id=1", "--status=done", "--outcome=confirmed",
               "--takeaway=t", f"--source-artifacts={ARTIFACT}")
    assert out.returncode == 0, out.stderr
    (repo / "CLAUDE.md").write_text(f"# P\n\nThe metric lives in `{ARTIFACT}`.\n")
    _commit(repo, "docs")
    assert _cli(repo, "docs", "check").returncode == 0
    return repo


def _worktree(repo: Path) -> Path:
    wt = repo.parent / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat/x", str(wt))
    return wt


def test_the_main_checkout_is_not_a_linked_worktree(main_checkout):
    assert gitstate.main_checkout(str(main_checkout)) is None


def test_a_missing_ignored_artifact_in_a_worktree_is_a_warning(main_checkout):
    wt = _worktree(main_checkout)
    assert gitstate.main_checkout(str(wt.resolve())) == main_checkout.resolve()
    out = _cli(wt, "docs", "check")
    assert out.returncode == 0, out.stderr
    assert "main checkout" in out.stdout and ARTIFACT in out.stdout


def test_a_cited_doc_path_in_a_worktree_with_a_partial_data_dir_is_a_warning(main_checkout):
    wt = _worktree(main_checkout)
    (wt / "data").mkdir()                      # the top dir exists, so CLAUDE.md is judged
    out = _cli(wt, "docs", "check")
    assert out.returncode == 0, out.stderr
    assert "CLAUDE.md:3" in out.stdout


def test_missing_in_the_main_checkout_too_is_still_drift(main_checkout):
    wt = _worktree(main_checkout)
    (main_checkout / ARTIFACT).unlink()
    out = _cli(wt, "docs", "check")
    assert out.returncode == 2 and ARTIFACT in out.stderr


def test_in_the_main_checkout_a_missing_artifact_is_drift(main_checkout):
    (main_checkout / ARTIFACT).unlink()
    out = _cli(main_checkout, "docs", "check")
    assert out.returncode == 2 and ARTIFACT in out.stderr
