"""Tests for `maestro.tracking` — the logging library an adopted project imports.

547 lines that decide whether a recorded run can be believed, and until now the only
thing exercising any of it was the e2e smoke, which needs a live tracker and touches
three of its functions.

Nothing here needs a tracker, and almost nothing is mocked. Two facts make that possible:

  * every GATE fires before the first wandb import — `start_run` calls
    `_require_wandb_tracker()`, then reads git, then the dataset record, and only then
    reaches `_wandb().init(...)`. The refusals are therefore plain Python over a
    throwaway git repo;
  * `_wandb()` is the single seam to the client. Replacing it captures the whole
    assembled run — name, group, tags, config — which is the three-leg provenance
    contract itself, not a mock of it.

`_project_root()` resolves from the working directory, so `monkeypatch.chdir` is all it
takes to make a temp directory BE the project.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from maestro import tracking  # noqa: E402


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway git repo that IS the project, tracker set to wandb, tree clean."""
    root = tmp_path / "demo-project"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n\n[tool.maestro]\ntracker = "wandb"\n')
    git("init", "-q", ".", cwd=root)
    git("config", "user.email", "smoke@example.invalid", cwd=root)
    git("config", "user.name", "Smoke", cwd=root)
    git("add", "-A", cwd=root)
    git("commit", "-qm", "initial", cwd=root)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def fake_wandb(monkeypatch):
    """Replace the ONE seam to the client; return the recorded init() kwargs."""
    recorded = {}

    def init(**kwargs):
        recorded.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(tracking, "_wandb", lambda: MagicMock(init=init))
    return recorded


# ── which project am I describing? ───────────────────────────────────────────

def test_provenance_describes_the_consuming_project_not_maestro(project):
    # The whole point of the cwd-based root: a run's git sha, project name and dataset
    # records must describe the experiment's repo, never the library's install dir.
    assert tracking.project_name() == "demo-project"
    assert tracking._project_root() == project.resolve()


def test_tracker_reads_the_project_toml_and_defaults_to_none(project):
    assert tracking.tracker() == "wandb"
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    assert tracking.tracker() == "none"
    # Unreadable TOML must not crash a run — tracking is opt-in, absence means off.
    (project / "pyproject.toml").write_text("[project\nname = broken")
    assert tracking.tracker() == "none"
    (project / "pyproject.toml").unlink()
    assert tracking.tracker() == "none"


# ── leg 1: library code ──────────────────────────────────────────────────────

def test_git_facts_come_from_the_project_repo(project):
    sha = tracking.short_git_sha()
    assert sha and len(sha) >= 7
    assert tracking.git_branch() in ("main", "master")
    assert tracking.git_dirty() is False

    (project / "pyproject.toml").write_text('[project]\nname = "changed"\n')
    assert tracking.git_dirty() is True


def test_git_helpers_return_none_outside_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert tracking.short_git_sha() is None
    assert tracking.git_branch() is None
    # False, not None: a missing repo must never block a run on its own.
    assert tracking.git_dirty() is False


def test_a_dirty_tree_refuses_the_run_and_counts_the_files(project, fake_wandb):
    (project / "pyproject.toml").write_text('[project]\nname = "dirty"\n\n'
                                            '[tool.maestro]\ntracker = "wandb"\n')
    with pytest.raises(RuntimeError) as e:
        tracking.start_run(exp_n=1, slug="x", variant="v")
    msg = str(e.value)
    assert "tracked library tree is dirty (1 files)" in msg
    assert "allow_dirty=True" in msg
    assert fake_wandb == {}, "the gate must refuse BEFORE the client is touched"


def test_allow_dirty_passes_the_gate_and_marks_the_run(project, fake_wandb):
    (project / "pyproject.toml").write_text('[project]\nname = "dirty"\n\n'
                                            '[tool.maestro]\ntracker = "wandb"\n')
    with pytest.warns(UserWarning, match="DIRTY git tree"):
        tracking.start_run(exp_n=1, slug="x", variant="v", allow_dirty=True,
                           log_code=False)
    # The escape is narrow and LOUD: the compromise is visible on the run itself.
    assert "provenance:dirty-override" in fake_wandb["tags"]
    assert fake_wandb["config"]["git_dirty"] is True


# ── leg 2: experiment code ───────────────────────────────────────────────────

def test_exp_code_sha_is_the_script_bytes_and_changes_with_them(project):
    script = project / "exp.py"
    script.write_text("print('one')\n")
    sha, name, src = tracking._hash_exp_code(script)
    assert len(sha) == 12 and name == "exp.py" and src == script
    assert tracking._hash_exp_code(script)[0] == sha        # same bytes, same digest

    script.write_text("print('two')\n")
    assert tracking._hash_exp_code(script)[0] != sha


def test_unresolvable_exp_code_warns_and_never_raises(project):
    # Provenance capture is best-effort: a REPL session or an unreadable file must
    # degrade to "no exp_code_sha", never crash somebody's training run.
    with pytest.warns(UserWarning, match="could not resolve the experiment script"):
        assert tracking._hash_exp_code(project / "nope.py") == (None, None, None)


# ── leg 3: data ──────────────────────────────────────────────────────────────

def _record(project, name, body):
    path = project / "docs" / "data" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_dataset_provenance_is_read_out_of_the_record(project):
    _record(project, "wine", "---\nname: wine\nversion: v2\nsha256: abc123def456\n---\n\nbody\n")
    assert tracking.resolve_dataset("wine") == ("v2", "abc123def456")


def test_a_missing_record_or_field_resolves_to_none(project):
    assert tracking.resolve_dataset("absent") == (None, None)
    _record(project, "half", "---\nname: half\nversion: v1\nsha256:\n---\n")
    assert tracking.resolve_dataset("half") == ("v1", None)


def test_a_dataset_with_no_resolvable_sha_refuses_the_run(project, fake_wandb):
    with pytest.raises(RuntimeError) as e:
        tracking.start_run(exp_n=1, slug="x", variant="v", dataset="wine")
    assert "no resolvable sha256" in str(e.value)
    assert "maestro dataset new --name=wine" in str(e.value)
    assert fake_wandb == {}


def test_the_dataset_gate_has_a_loud_escape(project, fake_wandb):
    with pytest.warns(UserWarning, match="provenance unverified"):
        tracking.start_run(exp_n=1, slug="x", variant="v", dataset="wine",
                           allow_missing_dataset_prov=True, log_code=False)
    assert "provenance:dataset-unverified" in fake_wandb["tags"]


def test_an_explicit_sha_beats_the_record(project, fake_wandb):
    _record(project, "wine", "---\nversion: v2\nsha256: fromtherecord00\n---\n")
    git("add", "-A", cwd=project)                      # the clean-tree gate comes first
    git("commit", "-qm", "add record", cwd=project)
    tracking.start_run(exp_n=1, slug="x", variant="v", dataset="wine",
                       dataset_sha="explicit0000", log_code=False)
    assert fake_wandb["config"]["dataset_sha"] == "explicit0000"


# ── the join key ─────────────────────────────────────────────────────────────

def test_run_name_and_group_pad_the_number(project):
    assert tracking.run_group(7, "batch_sweep") == "exp_07_batch_sweep"
    assert tracking.run_name(7, "batch_sweep", "wide", 3) == "exp_07_batch_sweep__wide__s3"
    assert tracking.run_name(112, "x", "v") == "exp_112_x__v__s0"      # no truncation


# ── all three legs, on one assembled run ─────────────────────────────────────

def test_a_clean_run_carries_every_leg_of_its_provenance(project, fake_wandb):
    _record(project, "wine", "---\nversion: v2\nsha256: 0123456789abcdef\n---\n")
    script = project / "exp_01_x.py"
    script.write_text("print('hello')\n")
    git("add", "-A", cwd=project)
    git("commit", "-qm", "add script and record", cwd=project)

    tracking.start_run(exp_n=1, slug="rf", variant="base", seed=5,
                       dataset="wine", code_path=script, log_code=False)

    cfg, tags = fake_wandb["config"], fake_wandb["tags"]
    assert fake_wandb["name"] == "exp_01_rf__base__s5"
    assert fake_wandb["group"] == "exp_01_rf"
    assert fake_wandb["project"] == "demo-project"
    # leg 1 library code, leg 2 experiment code, leg 3 data — a run is reproducible
    # only if all three are pinned (modules/provenance.md).
    assert cfg["git_sha"] == tracking.short_git_sha() and cfg["git_dirty"] is False
    assert cfg["exp_code_sha"] == tracking._hash_exp_code(script)[0]
    assert cfg["dataset"] == "wine" and cfg["dataset_sha"] == "0123456789abcdef"
    assert f"git_sha:{cfg['git_sha']}" in tags
    assert f"exp_code_sha:{cfg['exp_code_sha']}" in tags
    assert "dataset:wine" in tags and "dataset_version:v2" in tags


# ── the write side is W&B only ───────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    ("none", "tracking is disabled"),
    ("mlflow", "mlflow write-side not implemented"),
    ("nonsense", 'must be "none", "wandb" or "mlflow"'),
])
def test_a_non_wandb_tracker_says_exactly_what_to_do(project, value, expected):
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\n\n[tool.maestro]\ntracker = "{value}"\n')
    with pytest.raises(SystemExit) as e:
        tracking.start_run(exp_n=1, slug="x", variant="v")
    assert expected in str(e.value)


# ── the read/write helpers that carry real logic ─────────────────────────────
#
# The rest of the module is thin wrappers over run.log / run.save / wandb.Api, and the
# e2e smoke tests those against the live trackers. Mocking them here would only assert
# that the mock was written. These four DO compute something.

def test_logging_with_no_run_says_how_to_get_one(project, monkeypatch):
    monkeypatch.setattr(tracking, "_wandb", lambda: MagicMock(run=None))
    with pytest.raises(RuntimeError, match="no active wandb run"):
        tracking.log_metrics({"accuracy": 0.9})


def test_metrics_go_to_the_summary_and_the_time_series(project, monkeypatch):
    logged = {}
    client = MagicMock(log=lambda d: logged.update(d))
    monkeypatch.setattr(tracking, "_wandb", lambda: client)
    run = MagicMock(summary={})

    tracking.log_metrics({"accuracy": 0.87}, run=run)
    # summary = one queryable value per run; log = the time series. Both, always.
    assert run.summary["accuracy"] == 0.87
    assert logged == {"accuracy": 0.87}

    run.summary.clear()
    tracking.log_metrics({"accuracy": 0.5}, run=run, summary=False)
    assert run.summary == {}


def test_cross_validation_stats_are_population_std_and_a_fold_count(project):
    run = MagicMock(summary={})
    tracking.log_cv("spearman", [0.1, 0.2, 0.3], run=run)
    assert run.summary["spearman_mean"] == pytest.approx(0.2)
    # ddof=0, documented: the folds ARE the population, not a sample of one.
    assert run.summary["spearman_std"] == pytest.approx(0.081649658)
    assert run.summary["spearman_n"] == 3


@pytest.mark.parametrize("mode, expected", [("max", ("b", 0.9)), ("min", ("a", 0.1))])
def test_best_run_skips_what_it_cannot_compare(project, monkeypatch, mode, expected):
    monkeypatch.setattr(tracking, "fetch_runs", lambda exp_n, project=None: [
        {"name": "a", "summary": {"auc": 0.1}},
        {"name": "b", "summary": {"auc": 0.9}},
        {"name": "missing", "summary": {}},              # no metric at all
        {"name": "text", "summary": {"auc": "n/a"}},     # not a number
        {"name": "nan", "summary": {"auc": float("nan")}},   # not finite
    ])
    assert tracking.best_run(1, "auc", mode=mode) == expected


def test_best_run_of_nothing_is_nothing(project, monkeypatch):
    monkeypatch.setattr(tracking, "fetch_runs", lambda exp_n, project=None: [])
    assert tracking.best_run(1, "auc") == (None, None)


# ── credentials ──────────────────────────────────────────────────────────────

def test_env_creds_fill_gaps_but_never_overwrite(project, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('WANDB_API_KEY="from-file"\nWANDB_BASE_URL=http://x\n')
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("WANDB_API_KEY", "already-set")
    monkeypatch.delenv("WANDB_BASE_URL", raising=False)

    tracking._load_env_creds()
    import os
    assert os.environ["WANDB_API_KEY"] == "already-set"      # the session wins
    assert os.environ["WANDB_BASE_URL"] == "http://x"        # the gap is filled


def test_a_still_collecting_dataset_is_not_resolvable_provenance(project):
    """`sha256: pending` is a placeholder, not a digest — a run must not pin to it."""
    (project / "docs" / "data").mkdir(parents=True, exist_ok=True)
    (project / "docs" / "data" / "ticks.md").write_text(
        "---\ndataset: ticks\nversion: v1\nstatus: collecting\nsha256: pending\n---\n")
    assert tracking.resolve_dataset("ticks") == ("v1", None)
