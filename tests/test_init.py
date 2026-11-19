"""Tests for `maestro init` — the adoption command that replaced install.sh (ADR 10).

What is pinned here is what the ADR would be contradicted by, and what a bash heredoc
could never be tested for in the first place:

  * running it twice changes nothing the second time (no duplicated hook, no duplicated
    line in .git/info/exclude);
  * `--dry-run` writes NOTHING — the whole point of moving the JSON surgery into Python
    is that you can read the diff before it happens;
  * a settings.json that is not valid JSON is left byte-identical, with the hook printed
    for the reader to add by hand;
  * the hook command is the installed console script, never a path into a copied tree;
  * tool copies left by the old install model are found and deleted.

Every test runs against throwaway directories under tmp_path, including a fake maestro
checkout — nothing here reads or writes the real ~/.claude/ or this repository.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import init as init_mod  # noqa: E402
from maestro_cli.cli import main  # noqa: E402

# The real templates/pre-commit, not a stand-in: the fake checkout below carries it so
# the hook tests exercise the file adopters actually get.
CHECKOUT = Path(__file__).resolve().parent.parent
REAL_PRE_COMMIT = CHECKOUT / "templates" / init_mod.PRE_COMMIT_TEMPLATE
TEMPLATE_VERSION = init_mod.hook_version(REAL_PRE_COMMIT.read_text())


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def repo(tmp_path):
    """A fake maestro checkout: the trees init reads from, and nothing else."""
    root = tmp_path / "maestro"
    (root / "templates").mkdir(parents=True)
    (root / "core.md").write_text("# core\n")
    for name, _dest in init_mod.SEED_FILES:
        (root / "templates" / name).write_text(f"# {name} template\n")
    shutil.copyfile(REAL_PRE_COMMIT, root / "templates" / init_mod.PRE_COMMIT_TEMPLATE)
    (root / "global" / "hooks").mkdir(parents=True)
    for hook in ("guard_records.py", "regen_kb_index.py"):
        (root / "global" / "hooks" / hook).write_text("# hook\n")
    return root


@pytest.fixture
def project(tmp_path):
    """A throwaway project with a real .git directory, so excludes are exercised."""
    path = tmp_path / "proj"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def snapshot(root: Path):
    """Every path under `root` plus its bytes — what 'wrote nothing' is checked against."""
    out = {}
    for p in sorted(root.rglob("*")):
        out[str(p.relative_to(root))] = p.read_bytes() if p.is_file() else None
    return out


def settings_of(project: Path):
    return json.loads((project / ".claude" / "settings.json").read_text())


def commands_in(data, event):
    return [h["command"] for entry in data["hooks"][event] for h in entry["hooks"]]


# ── project mode ─────────────────────────────────────────────────────────────

def test_fresh_project_is_scaffolded_and_wired(project, repo, capsys):
    plan = init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()

    for rel in init_mod.SCAFFOLD_DIRS:
        assert (project / rel).is_dir(), rel
    for _name, rel in init_mod.SEED_FILES:
        assert (project / rel).is_file(), rel
    assert not (project / ".claude" / "settings.json").exists()   # no hook is wired
    excluded = (project / ".git" / "info" / "exclude").read_text().splitlines()
    assert set(init_mod.EXCLUDE_PATHS) <= set(excluded)
    assert plan.changes > 0


def test_init_renders_the_indexes_a_cold_session_is_told_to_read(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()
    # The four record kinds only. docs/kb/literature/ is opt-in — the fetch skills
    # create it — so init scaffolds no index there and CLAUDE.md cites none.
    for rel in ("docs/experiments/INDEX.md", "docs/adrs/INDEX.md", "docs/epics/INDEX.md",
                "docs/data/INDEX.md"):
        assert (project / rel).exists(), f"{rel} not rendered"
    assert not (project / "docs" / "kb" / "literature").exists()
    # Empty, not absent: CLAUDE.md points a cold session at these first, and an empty
    # table answers "nothing recorded yet" where a missing file answers nothing at all.
    assert "Experiment Index" in (project / "docs" / "experiments" / "INDEX.md").read_text()


def test_a_fresh_project_cites_no_path_it_does_not_have(project, capsys):
    """The REAL templates, checked by the REAL dead-path rule.

    A brand-new project must pass `maestro docs check`: the shipped
    CLAUDE.md cited docs/setup.md, docs/data.md and two INDEX files that the same init
    never wrote. A framework whose own check goes red on a brand-new project teaches
    people to switch the check off, so the invariant is pinned here rather than left to
    whoever next edits the template.
    """
    from maestro_cli import checks  # noqa: PLC0415 — the real rule, not a copy of it

    real_repo = Path(__file__).resolve().parent.parent
    init_mod.init_project(path=project, repo=real_repo)
    capsys.readouterr()

    issues, _ = checks.dead_path_findings(project)
    assert issues == [], "a freshly initialised project cites a path it does not have"


# ── the tracking library reaches the project that turned tracking on ──────────

def test_dep_spec_pins_the_version_and_accepts_a_local_checkout(tmp_path):
    from maestro_cli import __version__

    assert init_mod.maestro_dep_spec() == (
        f"maestro[tracking] @ git+{init_mod.MAESTRO_REPO_URL}@v{__version__}")
    # A URL is taken as given; a path becomes file:// because PEP 508 has no bare-path
    # form. Neither shape puts an absolute local path in a committed pyproject unless
    # the caller asked for one.
    assert init_mod.maestro_dep_spec(source="git+https://example.invalid/m@v1") == (
        "maestro[tracking] @ git+https://example.invalid/m@v1")
    assert init_mod.maestro_dep_spec(source=tmp_path).endswith(tmp_path.as_uri())


def test_tracker_none_installs_nothing(project, repo, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(init_mod, "_uv_add", lambda *a: calls.append(a) or (True, ""))
    (project / "pyproject.toml").write_text('[project]\nname = "p"\ndependencies = []\n')
    (project / "uv.lock").write_text("")           # a uv project, so uv add is possible
    init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()
    # The default is tracker = "none", and per design.md's audit that is every project
    # there has ever been. None of them should acquire a tracker client.
    assert calls == []
    assert "maestro[tracking]" not in (project / "pyproject.toml").read_text()


def test_turning_a_tracker_on_uv_adds_the_extra(project, repo, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(init_mod, "_uv_add", lambda *a: calls.append(a) or (True, ""))
    (project / "pyproject.toml").write_text('[project]\nname = "p"\ndependencies = []\n')
    (project / "uv.lock").write_text("")
    plan = init_mod.init_project(path=project, repo=repo, tracker="wandb")
    capsys.readouterr()
    assert len(calls) == 1 and calls[0][1].startswith("maestro[tracking] @ ")
    assert any("uv add" in text for _mark, text in plan.lines)


def test_a_failing_uv_add_warns_and_does_not_break_init(project, repo, capsys, monkeypatch):
    monkeypatch.setattr(init_mod, "_uv_add", lambda *a: (False, "repository not found"))
    (project / "pyproject.toml").write_text('[project]\nname = "p"\ndependencies = []\n')
    (project / "uv.lock").write_text("")
    plan = init_mod.init_project(path=project, repo=repo, tracker="wandb")
    capsys.readouterr()
    # A private repo or an unpushed tag is the owner's to clear; init still adopts the
    # project and says what to run once it is.
    warned = [text for mark, text in plan.lines if mark == "!"]
    assert any("repository not found" in w and "uv add" in w for w in warned)


def test_a_non_uv_project_is_told_the_requirement_not_uv_added(project, repo, capsys,
                                                               monkeypatch):
    calls = []
    monkeypatch.setattr(init_mod, "_uv_add", lambda *a: calls.append(a) or (True, ""))
    (project / "pyproject.toml").write_text('[project]\nname = "p"\ndependencies = []\n')
    plan = init_mod.init_project(path=project, repo=repo, tracker="mlflow")
    capsys.readouterr()
    # conda projects are first-class (modules/python_env.md) and have no uv add.
    assert calls == []
    assert any("not a uv project" in text for _mark, text in plan.lines)


def test_dry_run_does_not_uv_add(project, repo, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(init_mod, "_uv_add", lambda *a: calls.append(a) or (True, ""))
    (project / "pyproject.toml").write_text('[project]\nname = "p"\ndependencies = []\n')
    (project / "uv.lock").write_text("")
    init_mod.init_project(path=project, repo=repo, tracker="wandb", dry_run=True)
    capsys.readouterr()
    assert calls == []


def test_a_retired_drift_check_stop_hook_is_removed(project, repo, capsys):
    """A retired Stop hook exited 2 on any drift and Claude Code reads that as 'block',
    so it blocked every turn-end of every real project. A settings file that held nothing
    but that row is deleted, not left as `{}`."""
    (project / ".claude").mkdir()
    settings = project / ".claude" / "settings.json"
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "maestro docs check", "timeout": 30}]}]}}))
    plan = init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out
    assert "remove the retired maestro docs check Stop hook" in out
    assert not settings.exists()
    assert plan.changes > 0


def test_second_run_changes_nothing(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()
    before = snapshot(project)

    plan = init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out

    assert plan.changes == 0
    assert snapshot(project) == before
    assert "no changes" in out


def test_init_never_creates_a_settings_file(project, repo, capsys):
    for _ in range(3):
        init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()
    assert not (project / ".claude").exists()


def test_exclude_line_is_not_duplicated(project, repo, capsys):
    for _ in range(3):
        init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()
    lines = (project / ".git" / "info" / "exclude").read_text().split()
    for path in init_mod.EXCLUDE_PATHS:
        assert lines.count(path) == 1, path


def test_existing_hooks_in_settings_are_preserved(project, repo, capsys):
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(json.dumps({
        "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "make lint"}]}]},
    }))
    init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()
    data = settings_of(project)
    assert data["model"] == "opus"
    assert commands_in(data, "Stop") == ["make lint"]


# ── dry run ──────────────────────────────────────────────────────────────────

def test_dry_run_writes_nothing(project, repo, capsys):
    before = snapshot(project)
    plan = init_mod.init_project(path=project, repo=repo, dry_run=True)
    out = capsys.readouterr().out

    assert snapshot(project) == before
    assert plan.changes > 0
    assert "Dry run — nothing written" in out
    # and it names each thing it would do, so the change is reviewable before it happens
    assert "would create docs/experiments/" in out
    assert "would add docs/ to .git/info/exclude" in out


def test_dry_run_reports_the_stale_copies_without_deleting(project, repo, capsys):
    (project / "tools").mkdir()
    (project / "tools" / "rec.py").write_text("# stale\n")
    init_mod.init_project(path=project, repo=repo, dry_run=True)
    out = capsys.readouterr().out
    assert "would remove copied tools/rec.py" in out
    assert (project / "tools" / "rec.py").is_file()


# ── never clobber ────────────────────────────────────────────────────────────

def test_malformed_settings_is_left_untouched(project, repo, capsys):
    settings = project / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text("{ not json at all,,, ")
    before = settings.read_bytes()

    plan = init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out

    assert settings.read_bytes() == before
    assert "not valid JSON" in out
    # the rest of the run still happened
    assert (project / "docs" / "experiments").is_dir()
    assert plan.changes > 0


def test_seed_files_are_kept_and_force_overwrites(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo)
    mine = "# my own CLAUDE.md\n"
    (project / "CLAUDE.md").write_text(mine)
    capsys.readouterr()

    init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out
    assert (project / "CLAUDE.md").read_text() == mine
    assert "CLAUDE.md exists — kept" in out

    plan = init_mod.init_project(path=project, repo=repo, force=True)
    out = capsys.readouterr().out
    assert (project / "CLAUDE.md").read_text() == "# CLAUDE.md template\n"
    assert "overwrite CLAUDE.md" in out
    assert plan.changes > 0


def test_force_dry_run_still_writes_nothing(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo)
    (project / "CLAUDE.md").write_text("# mine\n")
    capsys.readouterr()
    before = snapshot(project)

    init_mod.init_project(path=project, repo=repo, force=True, dry_run=True)
    capsys.readouterr()
    assert snapshot(project) == before


# ── the migration off copied tools ───────────────────────────────────────────

def test_stale_copied_tools_are_removed_and_reported(project, repo, capsys):
    tools = project / "tools"
    (tools / "maestro_cli").mkdir(parents=True)
    (tools / "maestro_cli" / "cli.py").write_text("# a frozen copy\n")
    for name in ("rec.py", "render_index.py", "check_drift.py", "index_kb.py", "dataset_hash.py"):
        (tools / name).write_text("# a frozen copy\n")
    (tools / "keep_me.py").write_text("# the project's own script\n")
    hook = project / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# maestro post-checkout git hook\n")

    init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out

    assert not (tools / "maestro_cli").exists()
    for name in ("rec.py", "render_index.py", "check_drift.py", "index_kb.py", "dataset_hash.py"):
        assert not (tools / name).exists(), name
        assert f"remove copied tools/{name}" in out
    assert "remove copied tools/maestro_cli/" in out
    assert not hook.exists()
    assert (tools / "keep_me.py").is_file()     # only maestro's own copies are touched


def test_no_stale_copies_reports_clean(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo)
    assert "no copied tools left behind" in capsys.readouterr().out


# ── the commit-time guard ────────────────────────────────────────────────────

def hook_of(project: Path) -> Path:
    return project / ".git" / "hooks" / init_mod.PRE_COMMIT_HOOK


def test_the_hook_is_installed_executable_and_marked(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out
    hook = hook_of(project)

    assert hook.is_file()
    assert hook.stat().st_mode & 0o111, "the hook git runs has to be executable"
    assert init_mod.hook_version(hook.read_text()) == TEMPLATE_VERSION
    assert hook.read_bytes() == REAL_PRE_COMMIT.read_bytes()
    assert f"install the pre-commit hook (v{TEMPLATE_VERSION})" in out


def test_a_second_run_leaves_the_hook_alone(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()
    before = hook_of(project).read_bytes()

    plan = init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out
    assert hook_of(project).read_bytes() == before
    assert f"pre-commit hook: installed (v{TEMPLATE_VERSION})" in out
    assert plan.changes == 0


def test_a_foreign_pre_commit_hook_is_never_overwritten(project, repo, capsys):
    hook = hook_of(project)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexec ./run-the-projects-own-checks\n")
    before = hook.read_bytes()

    init_mod.init_project(path=project, repo=repo, force=True)   # not even --force
    out = capsys.readouterr().out

    assert hook.read_bytes() == before
    assert "foreign hook present" in out
    assert "by hand" in out


def test_an_older_maestro_hook_is_replaced(project, repo, capsys):
    hook = hook_of(project)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# maestro pre-commit v0\nexit 0\n")

    init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out

    assert hook.read_bytes() == REAL_PRE_COMMIT.read_bytes()
    assert f"outdated (v0 < v{TEMPLATE_VERSION})" in out


def test_a_newer_hook_is_left_in_place(project, repo, capsys):
    """A checkout older than the project's hook must not downgrade it."""
    hook = hook_of(project)
    hook.parent.mkdir(parents=True, exist_ok=True)
    newer = f"#!/bin/sh\n# maestro pre-commit v{TEMPLATE_VERSION + 1}\nexit 0\n"
    hook.write_text(newer)

    init_mod.init_project(path=project, repo=repo)
    assert hook.read_text() == newer
    assert f"installed (v{TEMPLATE_VERSION + 1})" in capsys.readouterr().out


def test_a_project_without_git_gets_no_hook(tmp_path, repo, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    init_mod.init_project(path=plain, repo=repo)
    out = capsys.readouterr().out
    assert "pre-commit hook: not a git repo — skipped" in out
    assert not (plain / ".git").exists()


def test_a_hooks_path_naming_the_default_dir_is_not_an_override(project, repo, capsys):
    default = project / ".git" / "hooks"
    subprocess.run(["git", "-C", str(project), "config", "core.hooksPath", str(default)],
                   check=True)

    init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out

    assert "core.hooksPath" not in out
    assert hook_of(project).exists()


def test_a_custom_hooks_path_is_reported_not_written_into(project, repo, capsys):
    elsewhere = project / "githooks"
    elsewhere.mkdir()
    subprocess.run(["git", "-C", str(project), "config", "core.hooksPath", str(elsewhere)],
                   check=True)

    init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out

    assert "core.hooksPath" in out
    assert not hook_of(project).exists()
    assert list(elsewhere.iterdir()) == []


def test_dry_run_installs_no_hook(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo, dry_run=True)
    out = capsys.readouterr().out
    assert "would install the pre-commit hook" in out
    assert not hook_of(project).exists()


def test_the_hook_never_advertises_an_override():
    """A guard that names its own bypass is a suggestion, not a guard."""
    text = REAL_PRE_COMMIT.read_text()
    assert "no-verify" not in text
    assert "`" not in text, "backticks: POSIX sh command substitution is $( ), and the "\
                            "header prose must not carry them either"
    assert text.startswith("#!/bin/sh\n")


# ── the guard's behaviour, run by git ────────────────────────────────────────

def git(project, *args, env=None):
    """A git command in `project` with a PATH that has no `maestro` on it.

    The stamp guard is then a no-op by design (a machine without the CLI cannot check a
    stamp and must not fail every commit), which leaves these tests measuring exactly
    one thing: the trunk guard.
    """
    environ = dict(os.environ)
    environ.pop("MAESTRO_CLI", None)
    environ.update({"PATH": "/usr/bin:/bin", "GIT_AUTHOR_NAME": "T",
                    "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "T",
                    "GIT_COMMITTER_EMAIL": "t@example.com"})
    environ.update(env or {})
    return subprocess.run(["git", "-C", str(project), *args],
                          capture_output=True, text=True, env=environ)


@pytest.fixture
def guarded(project, repo, capsys):
    """An adopted repo sitting on `main`, with one docs-only commit behind it."""
    init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()
    subprocess.run(["git", "-C", str(project), "symbolic-ref", "HEAD", "refs/heads/main"],
                   check=True)
    # -f: init excludes docs/ from git, and this repo is one where docs/ IS the content.
    assert git(project, "add", "-f", "docs/progress.md").returncode == 0
    done = git(project, "commit", "-m", "docs: seed")
    assert done.returncode == 0, done.stderr
    return project


def test_docs_only_commits_on_main_pass(guarded):
    (guarded / "docs" / "findings.md").write_text("# findings\nsomething measured\n")
    assert git(guarded, "add", "-f", "docs/findings.md").returncode == 0
    done = git(guarded, "commit", "-m", "docs: a finding")
    assert done.returncode == 0, done.stderr


def test_code_staged_on_main_is_blocked(guarded):
    (guarded / "src").mkdir()
    (guarded / "src" / "thing.py").write_text("x = 1\n")
    assert git(guarded, "add", "src/thing.py").returncode == 0

    done = git(guarded, "commit", "-m", "feat: a thing")
    assert done.returncode == 1
    assert "BLOCKED" in done.stderr
    assert "src/thing.py" in done.stderr
    assert "git merge --no-ff" in done.stderr
    # ...and nothing was committed.
    assert git(guarded, "log", "--oneline").stdout.count("\n") == 1


def test_the_same_code_passes_on_a_feature_branch_and_merges_back(guarded):
    (guarded / "src").mkdir()
    (guarded / "src" / "thing.py").write_text("x = 1\n")

    assert git(guarded, "switch", "-c", "feat/thing").returncode == 0
    assert git(guarded, "add", "src/thing.py").returncode == 0
    done = git(guarded, "commit", "-m", "feat: a thing")
    assert done.returncode == 0, done.stderr

    assert git(guarded, "switch", "main").returncode == 0
    merged = git(guarded, "merge", "--no-ff", "-m", "merge: the thing", "feat/thing")
    assert merged.returncode == 0, merged.stderr
    assert (guarded / "src" / "thing.py").is_file()
    assert "merge: the thing" in git(guarded, "log", "--oneline").stdout


# ── project without git ──────────────────────────────────────────────────────

def test_project_without_git_is_scaffolded_anyway(tmp_path, repo, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    init_mod.init_project(path=plain, repo=repo)
    out = capsys.readouterr().out
    assert (plain / "docs" / "adrs").is_dir()
    assert "no .git directory" in out
    assert not (plain / ".git").exists()


def test_missing_project_path_is_an_error(tmp_path, repo):
    with pytest.raises(init_mod.InitError):
        init_mod.init_project(path=tmp_path / "nope", repo=repo)


def test_bad_repo_flag_is_an_error(project, tmp_path):
    with pytest.raises(init_mod.InitError):
        init_mod.init_project(path=project, repo=tmp_path / "not-a-checkout")


def test_missing_templates_are_skipped_not_invented(project, tmp_path, monkeypatch, capsys):
    """With no checkout to copy from, the layout is still scaffolded and the hook still
    wired — init never writes starter text it made up."""
    monkeypatch.delenv("MAESTRO_REPO", raising=False)
    monkeypatch.setattr(init_mod, "repo_dir", lambda explicit=None: None)
    init_mod.init_project(path=project)
    out = capsys.readouterr().out
    assert not (project / "CLAUDE.md").exists()
    assert "no maestro checkout found" in out
    assert (project / "docs" / "experiments").is_dir()
    assert not (project / ".claude" / "settings.json").exists()


# ── harness mode ─────────────────────────────────────────────────────────────

def test_harness_mode_is_idempotent(tmp_path, repo, capsys):
    home = tmp_path / "home"
    home.mkdir()
    init_mod.init_harness(repo=repo, home=home)
    capsys.readouterr()
    before = snapshot(home)

    plan = init_mod.init_harness(repo=repo, home=home)
    out = capsys.readouterr().out
    assert plan.changes == 0
    assert snapshot(home) == before
    assert "no changes" in out


def test_harness_dry_run_writes_nothing(tmp_path, repo, capsys):
    home = tmp_path / "home"
    home.mkdir()
    before = snapshot(home)
    init_mod.init_harness(repo=repo, home=home, dry_run=True)
    out = capsys.readouterr().out
    assert snapshot(home) == before
    assert "guard_records.py" in out


def test_harness_mode_wires_no_root_code_row(tmp_path, repo, capsys):
    """The root-code rule is dsh-only: `init --harness` installs the Claude Code
    guard set, and the root-code guard is not in it."""
    home = tmp_path / "home"
    home.mkdir()
    init_mod.init_harness(repo=repo, home=home)
    capsys.readouterr()
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    commands = [h["command"] for entries in settings["hooks"].values()
                for entry in entries for h in entry["hooks"]]
    assert not any("guard_root_code.py" in c for c in commands)
    assert any("guard_records.py" in c for c in commands)    # the record guards stay
    # the shared-checkout guards run under dsh only
    assert not any(h in c for c in commands
                   for h in ("guard_spawn.py", "guard_executor.py", "guard_live_child.py"))


def test_harness_mode_removes_a_retired_row_from_an_existing_settings_file(tmp_path, repo,
                                                                           capsys):
    """An installed row outlives the file it names. A machine that ran an older
    `init --harness` carries a `guard_root_code.py` row, and that script is gone —
    left in place it would shell out to a missing file on every Bash/Write/Edit call."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    settings = home / ".claude" / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash|Write|Edit|MultiEdit", "hooks": [
            {"type": "command", "command": "python3 /old/checkout/global/hooks/guard_root_code.py",
             "timeout": 10}]},
        {"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 /mine/own_hook.py", "timeout": 5}]},
    ]}}))

    init_mod.init_harness(repo=repo, home=home)
    out = capsys.readouterr().out
    assert "remove the retired guard_root_code.py PreToolUse hook" in out

    data = json.loads(settings.read_text())
    commands = [h["command"] for entries in data["hooks"].values()
                for entry in entries for h in entry["hooks"]]
    assert not any("guard_root_code.py" in c for c in commands)
    assert "python3 /mine/own_hook.py" in commands            # nobody else's row is touched
    # the entry the retired row left empty is gone, not left as a matcher with no hooks
    assert all(entry["hooks"] for entry in data["hooks"]["PreToolUse"])


def test_a_dry_run_removes_no_retired_row(tmp_path, repo, capsys):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    settings = home / ".claude" / "settings.json"
    before = json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 /old/global/hooks/guard_root_code.py",
             "timeout": 10}]}]}})
    settings.write_text(before)
    init_mod.init_harness(repo=repo, home=home, dry_run=True)
    assert "remove the retired guard_root_code.py" in capsys.readouterr().out
    assert settings.read_text() == before


def test_harness_without_a_checkout_is_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("MAESTRO_REPO", raising=False)
    monkeypatch.setattr(init_mod, "repo_dir", lambda explicit=None: None)
    with pytest.raises(init_mod.InitError):
        init_mod.init_harness(home=tmp_path / "home")


def test_repo_comes_from_the_environment_when_no_flag_is_given(repo, monkeypatch):
    monkeypatch.setenv("MAESTRO_REPO", str(repo))
    assert init_mod.repo_dir() == repo.resolve()


# ── the CLI surface ──────────────────────────────────────────────────────────

def test_cli_dispatches_project_mode(project, repo, capsys):
    before = snapshot(project)
    main(["init", f"--path={project}", f"--repo={repo}", "--dry-run"])
    out = capsys.readouterr().out
    assert "Dry run — nothing written" in out
    assert snapshot(project) == before
    assert not (project / "docs").exists()


def test_cli_rejects_path_together_with_harness(project, repo):
    with pytest.raises(SystemExit) as exc:
        main(["init", "--harness", f"--path={project}", f"--repo={repo}"])
    assert "--path" in str(exc.value)


def test_cli_rejects_an_unquoted_multi_word_value(project, repo, capsys):
    """init joins the same guard every other leaf has: an unquoted value fails loudly
    instead of silently keeping its first word."""
    with pytest.raises(SystemExit):
        main(["init", "--path", str(project), "and", "more"])
    assert "Quote the value" in capsys.readouterr().err


# ── the two guards that a dry run against maestro's own checkout exposed ──────


def test_a_tracked_path_is_never_excluded(project, repo, capsys):
    """docs/ tracking is a per-project choice (ADR 2). Excluding a path the project
    already tracks would hide every future change to it from `git status` — which is
    exactly what would have happened to maestro's own repo, where docs/ IS the product.
    """
    docs = project / "docs"
    docs.mkdir()
    (docs / "progress.md").write_text("# Progress\n")
    subprocess.run(["git", "-C", str(project), "add", "docs/progress.md"], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "track docs"], check=True)

    init_mod.init_project(path=project, repo=repo)

    exclude = (project / ".git" / "info" / "exclude").read_text().splitlines()
    assert "docs/" not in exclude
    assert ".claude/" in exclude          # the untracked ones still land
    assert "docs/ is tracked in git" in capsys.readouterr().out


def test_the_maestro_checkout_never_has_its_own_tools_deleted(tmp_path, repo, capsys):
    """In the source checkout tools/maestro_cli/ is the product, not a copy left by the
    old install model. The ADR 10 migration deleting it would remove the tool itself.
    """
    checkout = tmp_path / "maestro"
    (checkout / "tools" / "maestro_cli").mkdir(parents=True)
    (checkout / "tools" / "maestro_cli" / "cli.py").write_text("# the real thing\n")
    (checkout / "pyproject.toml").write_text('[project]\nname = "maestro"\nversion = "2.0.0"\n')
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)

    assert init_mod.is_maestro_checkout(checkout) is True
    init_mod.init_project(path=checkout, repo=repo)

    assert (checkout / "tools" / "maestro_cli" / "cli.py").read_text() == "# the real thing\n"
    assert "is the source, not a copy" in capsys.readouterr().out


def test_a_plain_project_with_copied_tools_is_still_migrated(project, repo):
    """The guard must not disarm the migration everywhere — a project that merely HAS a
    copied maestro_cli/ but is not the maestro package still gets it removed.
    """
    (project / "tools" / "maestro_cli").mkdir(parents=True)
    (project / "tools" / "maestro_cli" / "cli.py").write_text("# stale copy\n")
    (project / "pyproject.toml").write_text('[project]\nname = "someproject"\n')

    assert init_mod.is_maestro_checkout(project) is False
    init_mod.init_project(path=project, repo=repo)
    assert not (project / "tools" / "maestro_cli").exists()


# ── the tracker switch ───────────────────────────────────────────────────────

def tracker_of(project: Path):
    return init_mod.read_tracker((project / "pyproject.toml").read_text())


def test_tracker_flag_sets_the_key_on_a_fresh_project(project, repo, capsys):
    (project / "pyproject.toml").write_text('[project]\nname = "toy"\n')

    init_mod.init_project(path=project, repo=repo, tracker="wandb")
    out = capsys.readouterr().out

    assert tracker_of(project) == "wandb"
    assert '[project]\nname = "toy"' in (project / "pyproject.toml").read_text()
    assert 'tracker = "wandb"' in out
    assert "come from the environment" in out


def test_no_flag_writes_none_when_the_key_is_absent(project, repo, capsys):
    (project / "pyproject.toml").write_text('[project]\nname = "toy"\n')

    init_mod.init_project(path=project, repo=repo)
    capsys.readouterr()

    assert tracker_of(project) == "none"


def test_no_flag_never_clobbers_an_existing_value(project, repo, capsys):
    (project / "pyproject.toml").write_text(
        '[project]\nname = "toy"\n\n[tool.maestro]\ntracker = "mlflow"\n')

    init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out

    assert tracker_of(project) == "mlflow"
    assert "kept" in out


def test_neighbouring_keys_and_tables_survive_a_change(project, repo, capsys):
    (project / "pyproject.toml").write_text(
        '[project]\nname = "toy"\n\n'
        "[tool.maestro]\n"
        "# which client to load\n"
        'tracker = "none"   # "none" | "wandb" | "mlflow"\n'
        'kb_margin = 0.10\n\n'
        '[tool.pytest.ini_options]\naddopts = "-q"\n')

    init_mod.init_project(path=project, repo=repo, tracker="mlflow")
    capsys.readouterr()

    text = (project / "pyproject.toml").read_text()
    assert tracker_of(project) == "mlflow"
    assert 'tracker = "mlflow"   # "none" | "wandb" | "mlflow"' in text
    assert "# which client to load" in text
    assert "kb_margin = 0.10" in text
    assert '[tool.pytest.ini_options]\naddopts = "-q"' in text
    assert '[project]\nname = "toy"' in text


def test_tracker_is_idempotent(project, repo, capsys):
    (project / "pyproject.toml").write_text('[project]\nname = "toy"\n')
    init_mod.init_project(path=project, repo=repo, tracker="wandb")
    capsys.readouterr()
    before = snapshot(project)

    plan = init_mod.init_project(path=project, repo=repo, tracker="wandb")
    out = capsys.readouterr().out

    assert plan.changes == 0
    assert snapshot(project) == before
    assert "no changes" in out


def test_tracker_table_is_appended_when_absent(project, repo, capsys):
    (project / "pyproject.toml").write_text('[project]\nname = "toy"\n')
    init_mod.init_project(path=project, repo=repo, tracker="mlflow")
    capsys.readouterr()

    text = (project / "pyproject.toml").read_text()
    assert text.startswith('[project]\nname = "toy"\n')
    assert text.rstrip().endswith('[tool.maestro]\ntracker = "mlflow"')


def test_a_pyproject_is_not_invented_without_the_flag(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out

    assert not (project / "pyproject.toml").exists()
    assert "no pyproject.toml" in out


def test_the_flag_creates_a_pyproject_when_there_is_none(project, repo, capsys):
    init_mod.init_project(path=project, repo=repo, tracker="wandb")
    capsys.readouterr()

    assert tracker_of(project) == "wandb"


def test_tracker_dry_run_writes_nothing(project, repo, capsys):
    (project / "pyproject.toml").write_text('[project]\nname = "toy"\n')
    before = snapshot(project)

    init_mod.init_project(path=project, repo=repo, tracker="wandb", dry_run=True)
    out = capsys.readouterr().out

    assert snapshot(project) == before
    assert 'would set [tool.maestro] tracker = "wandb"' in out


def test_an_unknown_stored_tracker_is_reported_not_overwritten(project, repo, capsys):
    (project / "pyproject.toml").write_text('[tool.maestro]\ntracker = "neptune"\n')

    init_mod.init_project(path=project, repo=repo)
    out = capsys.readouterr().out

    assert tracker_of(project) == "neptune"
    assert "leaving it for you to fix" in out


def test_cli_passes_the_tracker_flag(project, repo, capsys):
    (project / "pyproject.toml").write_text('[project]\nname = "toy"\n')
    main(["init", f"--path={project}", f"--repo={repo}", "--tracker=mlflow"])
    capsys.readouterr()

    assert tracker_of(project) == "mlflow"


def test_cli_rejects_an_unknown_tracker(project, repo):
    with pytest.raises(SystemExit):
        main(["init", f"--path={project}", f"--repo={repo}", "--tracker=neptune"])


def test_tracker_is_rejected_in_harness_mode(project, repo):
    with pytest.raises(SystemExit):
        main(["init", "--harness", f"--repo={repo}", "--tracker=wandb"])


def test_dep_source_is_rejected_in_harness_mode(project, repo):
    # Both are project-mode flags: harness mode targets the machine, and a machine has
    # no [project] dependencies to point anywhere.
    with pytest.raises(SystemExit):
        main(["init", "--harness", f"--repo={repo}", f"--dep-source={repo}"])


def test_harness_mode_touches_settings_and_nothing_else(tmp_path, repo, capsys):
    """It wires two hooks. It does NOT install skills — those became CLI verbs.

    Three places used to say otherwise (install.sh, the --harness help, `info show`),
    which is how an agent ended up being told about /find-kb and /runs, neither of
    which exists. The claim is pinned here so it cannot drift back.
    """
    home = tmp_path / "home"
    home.mkdir()
    init_mod.init_harness(repo=repo, home=home)
    capsys.readouterr()
    assert (home / ".claude" / "settings.json").is_file()
    assert not (home / ".claude" / "skills").exists()
    assert sorted(p.name for p in (home / ".claude").iterdir()) == ["settings.json"]


