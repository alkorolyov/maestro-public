"""The merge-evidence guard: the shared rule, and the Claude Code half that runs it.

The fourth command guard, and the first that ships INERT. Core rule 1 closes an item with
evidence, but nothing checked that the evidence existed when the merge happened: two
items reached main before any gate run existed for them, and a third cited its PARENT
commit's gate line as its own. The rule was enforced by an
after-the-fact watchdog, which can only alarm once the bad merge already exists.

The rule is `git merge --no-ff <ref>` is denied when the project declares a merge-evidence
log and that log holds no passing line for the TIP COMMIT of <ref>. Nothing about a
particular project's gate lives in maestro: the log's path and what a passing line looks
like are read from the project's own `[tool.maestro]` block, and a project that declares
neither key is never denied anything — the first section below is that claim.

The last section is the symmetry claim for this pair: the .mjs pre-filter cannot drift
from the Python pattern list. The dsh half's own behaviour is tested in
test_dsh_merge_evidence_guard.py, and test_guard_table.py pins that this guard is
shipped UNWIRED on both sides.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

HOOK = ROOT / "global" / "hooks" / "guard_merge_evidence.py"

from maestro_cli.guards import (MERGE_EVIDENCE_PATTERNS, evidence_shas,  # noqa: E402
                                merge_evidence_config, merge_evidence_verdict,
                                merged_ref, merges_no_ff, project_root, vouched_for)

LOG = "docs/archive/gate_runs.log"

# What a project says about its own gate. `merge_evidence_pass` is applied per LINE and its
# first capture group is the commit that line vouches for — here: a clean tree (no `-dirty`
# suffix) and a RESULT=OK verdict. TOML literal strings, so the regex escapes survive.
DECLARED = (
    "[tool.maestro]\n"
    f'merge_evidence_log = "{LOG}"\n'
    """merge_evidence_pass = '\\b([0-9a-f]{7,40})\\b(?!-dirty).*RESULT=OK'\n"""
)

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}


def _git(repo: Path, *args) -> str:
    out = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                         text=True, env={**GIT_ENV, "HOME": str(repo)})
    return out.stdout.strip()


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


class Project:
    """A repo with a trunk, a feature branch, and (optionally) a declared evidence log."""

    def __init__(self, repo: Path, parent: str, tip: str):
        self.repo, self.parent, self.tip = repo, parent, tip

    def log_line(self, sha: str, verdict: str = "RESULT=OK", suffix: str = "") -> str:
        return (f"2026-09-10T21:03:11Z {sha[:8]}{suffix} feat/x cargo=812345 "
                f"typecheck=9100 wasm=41200 {verdict}")

    def write_log(self, *lines: str) -> None:
        path = self.repo / LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")

    def verdict(self, command: str = "git merge --no-ff feat/x") -> str | None:
        return merge_evidence_verdict(command, self.repo)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    repo = tmp_path / "project"
    (repo / "docs" / "archive").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(DECLARED)
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    parent = _commit(repo, "README.md", "base\n")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    tip = _commit(repo, "item.rs", "the item's code\n")
    _git(repo, "checkout", "-q", "main")
    return Project(repo, parent, tip)


# ── inert unless the project asks for it ─────────────────────────────────────
#
# The whole point of the design: `docs/archive/gate_runs.log`, `make gate` and `RESULT=OK`
# are ONE project's concepts. A project that declares nothing must behave exactly as it did
# before this guard existed.

def test_a_project_that_declares_nothing_is_never_denied(project):
    (project.repo / "pyproject.toml").write_text('[project]\nname = "p"\n')
    assert project.verdict() is None


def test_no_pyproject_at_all_is_never_denied(project):
    (project.repo / "pyproject.toml").unlink()
    assert project.verdict() is None


def test_half_a_declaration_is_no_declaration(project):
    (project.repo / "pyproject.toml").write_text(f'[tool.maestro]\nmerge_evidence_log = "{LOG}"\n')
    assert project.verdict() is None


def test_a_pattern_with_no_capture_group_is_refused_as_configuration(project):
    (project.repo / "pyproject.toml").write_text(
        "[tool.maestro]\n" f'merge_evidence_log = "{LOG}"\n'
        "merge_evidence_pass = 'RESULT=OK'\n")
    assert merge_evidence_config(project.repo) is None
    assert project.verdict() is None


def test_a_pattern_that_is_not_a_regex_is_refused_as_configuration(project):
    (project.repo / "pyproject.toml").write_text(
        "[tool.maestro]\n" f'merge_evidence_log = "{LOG}"\n'
        "merge_evidence_pass = '([0-9a-f'\n")
    assert merge_evidence_config(project.repo) is None
    assert project.verdict() is None


def test_an_unparseable_pyproject_is_refused_as_configuration(project):
    (project.repo / "pyproject.toml").write_text("[tool.maestro\n")
    assert project.verdict() is None


def test_what_a_declaration_reads_back_as(project):
    assert merge_evidence_config(project.repo) == (
        LOG, r"\b([0-9a-f]{7,40})\b(?!-dirty).*RESULT=OK")


def test_the_project_root_is_the_nearest_pyproject(project):
    deep = project.repo / "rust" / "engine_core"
    deep.mkdir(parents=True)
    assert project_root(deep) == project.repo.resolve()


# ── the rule itself ──────────────────────────────────────────────────────────

def test_a_passing_line_for_the_tip_allows_the_merge(project):
    project.write_log(project.log_line(project.tip))
    assert project.verdict() is None


def test_no_line_at_all_denies_and_says_so(project):
    project.write_log("")
    reason = project.verdict()
    assert reason is not None
    assert LOG in reason and project.tip[:12] in reason and "feat/x" in reason
    assert "no passing line at all" in reason


def test_a_missing_log_denies(project):
    assert "has no passing line" in project.verdict()


def test_the_parent_commits_line_is_not_this_commits_evidence(project):
    """A line that vouches for HEAD~1, cited as if it vouched for the tip."""
    project.write_log(project.log_line(project.parent))
    reason = project.verdict()
    assert reason is not None
    assert "parent commit's line" in reason
    assert project.parent[:8] in reason          # the newest passing line is named


def test_a_failed_gate_run_is_not_evidence(project):
    project.write_log(project.log_line(project.tip, verdict="RESULT=FAIL"))
    assert project.verdict() is not None


def test_a_dirty_tree_run_is_not_evidence_when_the_project_says_so(project):
    """The `-dirty` exclusion is the PROJECT's clause, not maestro's — it lives in the
    pattern the project declares, and this is what declaring it buys."""
    project.write_log(project.log_line(project.tip, suffix="-dirty"))
    assert project.verdict() is not None


def test_a_full_length_sha_in_the_log_matches_the_tip_too(project):
    project.write_log(f"2026-09-10T21:03:11Z {project.tip} feat/x RESULT=OK")
    assert project.verdict() is None


def test_committing_the_gate_line_onto_the_branch_moves_the_tip_past_it(project):
    """The design's sharp edge, pinned so nobody discovers it in a live session.

    Evidence names the sha the gate ran on. Committing that line onto the branch makes a
    NEW tip, which the line does not name — so a project whose workflow commits its gate
    line on the code branch can never satisfy this guard, and must leave the line
    uncommitted at merge time (or commit it on the trunk, as core rule 9 already has it).
    """
    _git(project.repo, "checkout", "-q", "feat/x")
    project.write_log(project.log_line(project.tip))
    _git(project.repo, "add", "-A")
    _git(project.repo, "commit", "-q", "-m", "gate line")
    new_tip = _git(project.repo, "rev-parse", "HEAD")
    assert new_tip != project.tip
    assert project.verdict() is not None              # the line is one commit behind

    # The supported shape: the same gate line, left in the working tree, naming the tip.
    project.write_log(project.log_line(new_tip))
    assert project.verdict() is None


# ── which commands the rule is about ─────────────────────────────────────────

@pytest.mark.parametrize("command", [
    "git merge feat/x",                       # a fast-forward merge is not this rule
    "git merge-base main feat/x",
    "git merge-tree a b",
    "git log --merges",
    "git status",
])
def test_commands_the_rule_is_not_about_pass(project, command):
    assert merges_no_ff(command) is False
    assert project.verdict(command) is None


def test_a_ref_git_cannot_resolve_allows(project):
    assert project.verdict("git merge --no-ff feat/never-existed") is None


@pytest.mark.parametrize("command, ref", [
    ("git merge --no-ff feat/x", "feat/x"),
    ("cd /p && git merge --no-ff feat/e12-item17 && git branch -d feat/e12-item17", "feat/e12-item17"),
    ('git merge --no-ff -m "merge item 5" feat/y', "feat/y"),
    ("git merge --no-ff --log feat/q", "feat/q"),
    ("git merge --no-ff origin/feat/z", "origin/feat/z"),
    ("git merge --no-ff", None),
    ("git merge feat/x", None),
    ("git merge-base a b", None),
    (None, None),
])
def test_the_ref_is_read_out_of_the_command(command, ref):
    assert merged_ref(command) == ref


# ── the two halves of a sha ──────────────────────────────────────────────────

def test_a_short_sha_vouches_for_the_full_one_and_the_other_way_round():
    assert vouched_for(["0d9e74e5"], "0d9e74e5c1f2a3b4") is True
    assert vouched_for(["0d9e74e5c1f2a3b4"], "0d9e74e5c1f2a3b4") is True
    assert vouched_for(["0d9e74e6"], "0d9e74e5c1f2a3b4") is False


def test_a_token_too_short_to_identify_a_commit_is_ignored():
    assert evidence_shas("2026 0d9e7 feat/x RESULT=OK", r"\b([0-9a-f]{4,40})\b.*RESULT=OK") == []


def test_the_lines_are_returned_in_file_order():
    text = ("2026 aaaaaaa1 x RESULT=OK\n"
            "2026 bbbbbbb2 x RESULT=FAIL\n"
            "2026 ccccccc3 x RESULT=OK\n")
    assert evidence_shas(text, r"\b([0-9a-f]{7,40})\b.*RESULT=OK") == ["aaaaaaa1", "ccccccc3"]


# ── the Claude Code half ─────────────────────────────────────────────────────

def _run(command: str, cwd: Path | None, tool: str = "Bash") -> str:
    payload = {"tool_name": tool, "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _reason(stdout: str) -> str:
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def test_the_hook_denies_a_merge_with_no_evidence(project):
    reason = _reason(_run("git merge --no-ff feat/x", project.repo))
    assert LOG in reason and "feat/x" in reason


def test_the_hook_allows_the_same_merge_once_the_gate_line_is_there(project):
    project.write_log(project.log_line(project.tip))
    assert _run("git merge --no-ff feat/x", project.repo) == ""


def test_the_hook_is_silent_in_a_project_that_declares_nothing(project):
    (project.repo / "pyproject.toml").unlink()
    assert _run("git merge --no-ff feat/x", project.repo) == ""


def test_the_hook_ignores_tools_other_than_bash(project):
    assert _run("git merge --no-ff feat/x", project.repo, tool="Edit") == ""


def test_the_hook_never_blocks_on_unparseable_stdin():
    out = subprocess.run([sys.executable, str(HOOK)], input="{{{", capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0 and out.stdout == ""


