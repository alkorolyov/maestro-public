"""The root-writes-code rule (maestro_cli.guards) — the Python half of the dsh-only
root-code guard.

The rule is DSH-ONLY: a Claude Code session is the
high-judgment top-level session that edits code itself, while a dsh planner routes
well-scoped items to local workers — it is the planner that has to stay out of the code
lane. There is no Claude Code hook for it, and `test_guard_table.py` does not ask
for one. The rule stays in Python because the plugin mirrors it and these tests are what
pin the two together.

Core rule 9 splits the lanes — the orchestrator plans, writes docs/ and merges; an
executor writes the code. A planner that writes code breaks that split, so the guard
refuses it.

What is pinned here: a root session is refused a write to TRACKED code; docs/, the
instruction files, .claude/, untracked paths and every delegated session pass; the shell
half fires on commands that write and not on commands that read; and the .mjs mirror of
the pattern list cannot drift from the Python one.

The "written paths" section at the bottom is a REGRESSION suite. A refusal once named
every tracked file in the checkout: the command text carried the repo root, which
resolved to `.`, and `git ls-files -- .` answers with everything. A candidate now has to come back from
git as that exact FILE, and the echo names five paths at most.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


from maestro_cli.guards import (ECHO_PATHS, EXECUTOR_PRESETS, ROOT_CODE_WRITE_PATTERNS,  # noqa: E402
                                root_code_write_reason, tracked_code_paths, writes_a_file,
                                written_paths)

def _git(repo: Path, *args) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(repo), "PATH": "/usr/bin:/bin"})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed maestro project: tracked code, tracked docs, one untracked file."""
    (tmp_path / "docs" / "epics").mkdir(parents=True)
    (tmp_path / "rust" / "engine_core").mkdir(parents=True)
    (tmp_path / ".claude").mkdir()
    (tmp_path / "docs" / "epics" / "epic_06_x.md").write_text("---\nepic: 6\n---\n")
    (tmp_path / "docs" / "progress.md").write_text("## Current\n")
    (tmp_path / "rust" / "engine_core" / "lib.rs").write_text("fn main() {}\n")
    (tmp_path / "CLAUDE.md").write_text("# project\n")
    (tmp_path / "README.md").write_text("# readme\n")
    (tmp_path / ".claude" / "settings.json").write_text("{}\n")
    (tmp_path / "maestro.toml").write_text("[items]\nmax_files = 40\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "scratch.log").write_text("not tracked\n")
    return tmp_path


def verdict(repo: Path, tool: str, tool_input: dict, depth: int = 0, env: dict | None = None):
    return root_code_write_reason(tool, tool_input, depth, repo, env={} if env is None else env)


# ── the shared rule ──────────────────────────────────────────────────────────

def test_a_root_edit_of_tracked_code_is_denied_and_names_the_file(repo):
    reason = verdict(repo, "Edit", {"file_path": "rust/engine_core/lib.rs", "old_string": "fn"})
    assert reason and "rust/engine_core/lib.rs" in reason
    assert "ROOT session" in reason and "rule 9" in reason
    assert "Files: <the list>" in reason and "root_writes_code = true" in reason


def test_an_absolute_path_inside_the_checkout_is_the_same_write(repo):
    assert verdict(repo, "Edit", {"file_path": str(repo / "rust" / "engine_core" / "lib.rs")})


def test_a_delegated_session_writes_code_freely(repo):
    assert verdict(repo, "Edit", {"file_path": "rust/engine_core/lib.rs"}, depth=1) is None
    assert verdict(repo, "Bash", {"command": "sed -i 's/a/b/' rust/engine_core/lib.rs"},
                   depth=2) is None


@pytest.mark.parametrize("path", [
    "docs/progress.md", "docs/epics/epic_06_x.md", "CLAUDE.md", "README.md",
    ".claude/settings.json", "scratch.log", "rust/engine_core/new_file.rs",
])
def test_the_orchestrators_own_surface_and_untracked_paths_pass(repo, path):
    assert verdict(repo, "Write", {"file_path": path, "content": "x"}) is None


def test_a_read_shaped_call_is_never_a_write(repo):
    assert verdict(repo, "str_replace_editor",
                   {"path": "rust/engine_core/lib.rs", "command": "view"}) is None


def test_a_path_outside_the_checkout_is_not_this_rules_business(repo):
    assert verdict(repo, "Write", {"file_path": "/tmp/somewhere/else.rs"}) is None


def test_a_checkout_that_is_not_a_maestro_project_is_never_guarded(tmp_path):
    (tmp_path / "rust").mkdir()
    (tmp_path / "rust" / "lib.rs").write_text("fn main() {}\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    assert root_code_write_reason("Edit", {"file_path": "rust/lib.rs"}, 0, tmp_path) is None


def test_the_opt_out_is_honoured(repo):
    assert verdict(repo, "Edit", {"file_path": "rust/engine_core/lib.rs"})
    (repo / "maestro.toml").write_text("[agents.dsh]\nroot_writes_code = true\n")
    assert verdict(repo, "Edit", {"file_path": "rust/engine_core/lib.rs"}) is None
    # …and the agent cannot write itself the opt-out: maestro.toml is tracked code too.
    (repo / "maestro.toml").write_text("[items]\nmax_files = 40\n")
    assert "maestro.toml" in verdict(repo, "Edit", {"file_path": "maestro.toml"})


def test_git_that_cannot_answer_allows(repo):
    assert tracked_code_paths(["rust/engine_core/lib.rs"], repo,
                              run=lambda argv, cwd: (128, "")) == []
    assert root_code_write_reason("Edit", {"file_path": "rust/engine_core/lib.rs"}, 0, repo,
                                  run=lambda argv, cwd: (128, "")) is None


# ── the shell half ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", [
    "sed -i 's/a/b/' rust/engine_core/lib.rs",
    "sed -i.bak 's/a/b/' rust/engine_core/lib.rs",
    "cat > rust/engine_core/lib.rs <<'EOF'\nfn main() {}\nEOF",
    "echo 'fn x() {}' >> rust/engine_core/lib.rs",
    "cat patch.txt | tee rust/engine_core/lib.rs",
    "cp /tmp/new.rs rust/engine_core/lib.rs",
    "mv /tmp/new.rs rust/engine_core/lib.rs",
    "patch -p1 rust/engine_core/lib.rs < /tmp/x.diff",
    "git apply --3way /tmp/x.diff rust/engine_core/lib.rs",
    "python3 - <<'PY'\nopen('rust/engine_core/lib.rs','w').write('x')\nPY",
    "python3 -c \"from pathlib import Path; Path('rust/engine_core/lib.rs').write_text('x')\"",
])
def test_every_file_writing_shell_shape_is_denied_for_the_root(repo, command):
    assert verdict(repo, "Bash", {"command": command}), command


@pytest.mark.parametrize("command", [
    "sed -n '5,9p' rust/engine_core/lib.rs",
    "cat rust/engine_core/lib.rs",
    "grep -rn todo rust/engine_core/lib.rs",
    "cargo nextest run -p engine_core",
    "git diff --stat main...HEAD -- rust/engine_core/lib.rs",
    # a READ of code whose output lands outside the checkout: the redirect narrows to its
    # own target, so the files on the reading side are not what is judged
    "grep -rn todo rust/engine_core/lib.rs > /tmp/hits.txt",
    "cargo test 2>&1 | tee /tmp/run.log",
    # the orchestrator's own lane, through the shell
    "echo '- 2026-09-12 — merged' >> docs/progress.md",
    "sed -i 's/x/y/' docs/progress.md",
])
def test_reads_and_docs_writes_pass_for_the_root(repo, command):
    assert verdict(repo, "Bash", {"command": command}) is None, command


def test_written_paths_narrows_a_redirect_to_its_target():
    assert written_paths("grep -rn x rust/lib.rs > /tmp/hits.txt") == ["/tmp/hits.txt"]
    assert "rust/lib.rs" in written_paths("sed -i 's/x/y/' rust/lib.rs")


def test_writes_a_file_is_the_shared_matcher():
    assert writes_a_file("sed -i s/a/b/ f.rs") and writes_a_file("echo x > f.rs")
    assert not writes_a_file("sed -n 1p f.rs") and not writes_a_file("cargo build")




def _unescape(literal: str) -> str:
    """The value of a JS single-quoted string literal — `\\b` is a backslash and a b,
    `\\'` is a quote. The executor guard's pin only ever had to undo the first."""
    out, i = [], 0
    while i < len(literal):
        if literal[i] == "\\" and i + 1 < len(literal) and literal[i + 1] in "\\'\"":
            out.append(literal[i + 1])
            i += 2
        else:
            out.append(literal[i])
            i += 1
    return "".join(out)


# ── written paths: exactly the files, never a directory prefix ───────────────

def commit_files(repo: Path, *rel: str) -> None:
    for r in rel:
        path = repo / r
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fn main() {}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "more code")


def test_the_repo_root_in_the_command_no_longer_drags_in_every_tracked_file(repo):
    """The root resolves to `.`, `git ls-files -- .` answers with the whole checkout, and
    the refusal named every file instead of the one."""
    commit_files(repo, "rust/other.rs", "Makefile")
    command = f"cd {repo} && sed -i s/a/b/ rust/engine_core/lib.rs"
    reason = verdict(repo, "Bash", {"command": command})
    assert reason
    # only the PATH LIST is judged here: the remedy sentence names maestro.toml too
    listed = reason.split(" is tracked code")[0]
    assert "rust/engine_core/lib.rs" in listed
    for elsewhere in ("Makefile", "rust/other.rs", "maestro.toml", "more)"):
        assert elsewhere not in listed


@pytest.mark.parametrize("token", ["rust", "rust/", ".", "./"])
def test_a_directory_is_a_prefix_not_a_write(repo, token):
    assert verdict(repo, "Bash", {"command": f"sed -i s/a/b/ {token}"}) is None
    assert tracked_code_paths([token], repo) == []


def test_the_checkout_itself_is_not_a_file(repo):
    assert tracked_code_paths([str(repo)], repo) == []


def test_a_tracked_file_still_comes_back_exactly(repo):
    assert tracked_code_paths(["rust/engine_core/lib.rs", "rust/nope.rs"], repo) == \
        ["rust/engine_core/lib.rs"]


def test_a_glob_is_matched_against_what_git_returns(repo):
    commit_files(repo, "rust/engine_core/mod.rs")
    hits = tracked_code_paths(["rust/engine_core/*.rs"], repo)
    assert sorted(hits) == ["rust/engine_core/lib.rs", "rust/engine_core/mod.rs"]


def test_prose_punctuation_is_not_a_glob(repo):
    """`.**` is markdown, not a pathspec.

    A root-session docs-only rewrite carried `.**` in its payload — a sentence-ending
    period run against markdown bold. The token holds a `*`, so it was matched against
    git and hit every tracked dot-prefixed file; the refusal named
    `.github/workflows/ci.yml` and `.gitignore`, and the planner asked for
    `root_writes_code` to route around a docs write it was entitled to make.
    """
    commit_files(repo, ".gitignore", ".github/workflows/ci.yml")
    assert tracked_code_paths([".**"], repo) == []
    assert tracked_code_paths(["**"], repo) == []
    assert tracked_code_paths(["?"], repo) == []
    # A real glob is untouched: an alphanumeric survives stripping `*` and `?`.
    assert tracked_code_paths([".gitignore"], repo) == [".gitignore"]
    assert tracked_code_paths([".git*"], repo) == [".github/workflows/ci.yml", ".gitignore"]




def test_the_echo_names_five_paths_and_counts_the_rest(repo):
    more = [f"rust/engine_core/f{i}.rs" for i in range(1, 8)]
    commit_files(repo, *more)
    reason = verdict(repo, "Bash", {"command": "sed -i s/a/b/ " + " ".join(more)})
    assert reason.count("rust/engine_core/f") == ECHO_PATHS
    assert f"(+{7 - ECHO_PATHS} more)" in reason


@pytest.mark.parametrize("command", [
    # the write pattern matches only because a quoted string MENTIONS it, and the path
    # that is named is the orchestrator's own
    "grep -n 'sed -i' docs/progress.md",
    # a code path quoted as search TEXT, in a command that writes nothing
    "grep -rn \"rust/engine_core/lib.rs\" docs/progress.md",
])
def test_a_code_path_that_is_not_the_target_of_a_write_passes(repo, command):
    assert verdict(repo, "Bash", {"command": command}) is None, command


# ── the executor presets: depth 0 but the session IS the executor ────────────

@pytest.mark.parametrize("preset", ["item-solo", "item-solo-ctx200k"])
def test_an_item_solo_session_writes_code(repo, preset):
    edit = {"file_path": "rust/engine_core/lib.rs"}
    assert verdict(repo, "Edit", edit, env={"DSH_TUI_PRESET": preset}) is None


@pytest.mark.parametrize("env", [{"DSH_TUI_PRESET": "epic-local"},
                                 {"DSH_TUI_PRESET": "epic-local-3-ctx100k"},
                                 {"DSH_TUI_PRESET": "item-soloist"},
                                 {}])
def test_a_planner_preset_or_none_is_still_refused(repo, env):
    assert verdict(repo, "Edit", {"file_path": "rust/engine_core/lib.rs"}, env=env)


