"""`maestro runs` — the read-back path from a tracker into a record.

The tracker calls themselves need a live W&B/MLflow (the e2e smoke harness exercises
those). What is unit-testable is everything around them: which tracker the project
names, which run group an experiment resolves to, which run gets quoted, and the argv
the re-exec hands to the client-loaded child.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import runs  # noqa: E402
from maestro_cli.cli import build_parser  # noqa: E402


def _project(root: Path, tracker=None):
    """A project root with an experiments dir and, optionally, a declared tracker."""
    (root / "docs" / "experiments").mkdir(parents=True, exist_ok=True)
    body = "[project]\nname = \"toy\"\n"
    if tracker is not None:
        body += f'\n[tool.maestro]\ntracker = "{tracker}"\n'
    (root / "pyproject.toml").write_text(body)
    return root


def _at(monkeypatch, root: Path):
    monkeypatch.setattr(runs, "ROOT", root)
    monkeypatch.setattr(runs, "EXP_DIR", root / "docs" / "experiments")


def _args(*argv):
    return build_parser().parse_args(list(argv))


# -- which tracker -------------------------------------------------------------

def test_a_tracker_output_dir_does_not_pass_for_its_client(tmp_path, monkeypatch):
    """The bug this guards: `wandb/` beside the project imports as an empty package.

    A tracker writes its runs into a directory named after itself, cwd is on sys.path,
    and Python treats a bare directory as a namespace package. Unguarded, `import wandb`
    then SUCCEEDS against the output dir, the re-exec that fetches the real client is
    skipped, and the fetch dies on `module 'wandb' has no attribute 'Api'`. A namespace
    package has no __file__, which is the distinction the check tests.
    """
    (tmp_path / "faketracker").mkdir()            # exactly what wandb/ and mlruns/ are
    monkeypatch.syspath_prepend(str(tmp_path))
    import importlib
    importlib.invalidate_caches()

    assert runs._importable("faketracker") is False
    assert runs._importable("json") is True       # a real module still answers yes
    assert runs._importable("no_such_tracker_pkg") is False


def test_declared_tracker_is_returned(tmp_path, monkeypatch):
    _at(monkeypatch, _project(tmp_path, "mlflow"))
    assert runs._tracker() == "mlflow"


def test_no_tracker_stops_and_points_at_the_artifacts(tmp_path, monkeypatch):
    _at(monkeypatch, _project(tmp_path))
    with pytest.raises(SystemExit) as e:
        runs._tracker()
    assert "data/experiments/" in str(e.value)
    assert "maestro init --tracker=" in str(e.value)


def test_missing_pyproject_is_the_same_clean_stop(tmp_path, monkeypatch):
    (tmp_path / "docs" / "experiments").mkdir(parents=True)
    _at(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as e:
        runs._tracker()
    assert "no tracker configured" in str(e.value)


def test_unknown_tracker_names_the_allowed_values(tmp_path, monkeypatch):
    _at(monkeypatch, _project(tmp_path, "neptune"))
    with pytest.raises(SystemExit) as e:
        runs._tracker()
    assert "'neptune'" in str(e.value) and "wandb" in str(e.value)


# -- which run group -----------------------------------------------------------

def test_exp_number_resolves_to_the_group_on_disk(tmp_path, monkeypatch):
    root = _project(tmp_path, "wandb")
    (root / "docs" / "experiments" / "exp_07_gbm_baseline.md").write_text("---\nid: 7\n---\n")
    _at(monkeypatch, root)
    assert runs._exp_group(7) == "exp_07_gbm_baseline"
    assert runs._exp_tag(7) == "07"


def test_missing_record_says_to_scaffold_it_first(tmp_path, monkeypatch):
    _at(monkeypatch, _project(tmp_path, "wandb"))
    with pytest.raises(SystemExit) as e:
        runs._exp_group(3)
    assert "maestro exp new" in str(e.value)


def test_explicit_group_yields_its_experiment_tag(tmp_path, monkeypatch):
    _at(monkeypatch, _project(tmp_path, "mlflow"))
    assert runs._resolve_target(_args("runs", "fetch", "--group=exp_07_gbm")) == ("exp_07_gbm", "07")
    # A group naming no experiment is passed through as the tag, not silently dropped.
    assert runs._resolve_target(_args("runs", "fetch", "--group=sweep_a")) == ("sweep_a", "sweep_a")


# -- which run gets quoted -----------------------------------------------------

def _run(name, state="finished", **metrics):
    return {"name": name, "state": state, "metrics": metrics}


def test_best_run_maximises_the_named_metric():
    got = runs._pick_best([_run("a", acc=0.7), _run("b", acc=0.9), _run("c", acc=0.8)], "acc")
    assert got["name"] == "b"


def test_unfinished_runs_are_not_quoted():
    got = runs._pick_best([_run("crashed", state="crashed", acc=0.99), _run("ok", acc=0.5)], "acc")
    assert got["name"] == "ok"


def test_mlflow_upper_case_state_counts_as_finished():
    assert runs._pick_best([_run("a", state="FINISHED", acc=0.1)], "acc")["name"] == "a"


def test_run_without_the_metric_is_skipped_not_ranked_at_zero():
    got = runs._pick_best([_run("no_metric"), _run("has_metric", acc=0.2)], "acc")
    assert got["name"] == "has_metric"


def test_no_metric_given_falls_back_to_the_first_finished_run():
    assert runs._pick_best([_run("x", state="running"), _run("y")])["name"] == "y"


def test_no_runs_is_none_not_a_crash():
    assert runs._pick_best([], "acc") is None


# -- the re-exec ---------------------------------------------------------------

def _missing(monkeypatch):
    """Pin the tracker client as absent — the re-exec path is unreachable otherwise.

    wandb is a declared dependency of this package, so whether the real client imports
    depends on the environment the suite runs in, not on the code being tested.
    """
    monkeypatch.setattr(runs, "_importable", lambda _: False)


@pytest.mark.parametrize("argv", [
    ["runs", "fetch", "--exp=7"],
    ["runs", "fetch", "--exp=7", "--metric=auc", "--json"],
    ["runs", "fetch", "--group=exp_07_gbm", "--metric=auc"],
])
def test_reexec_argv_round_trips_through_the_parser(argv):
    """The child must be handed the same invocation the parent parsed."""
    rebuilt = runs._reexec_argv(_args(*argv))
    assert vars(_args(*rebuilt)) == vars(_args(*argv))


def test_importable_client_does_not_reexec(monkeypatch):
    called = []
    monkeypatch.setattr(runs.subprocess, "run", lambda *a, **k: called.append(a))
    runs._ensure_client("json", ["runs", "fetch", "--exp=1"])  # stdlib stands in for a client
    assert called == []


def test_importable_is_decided_by_the_import_itself():
    """The seam the tests pin is the real answer, not a stub of one."""
    assert runs._importable("json")
    assert not runs._importable("a_tracker_client_that_is_not_installed")


def test_child_does_not_reexec_again(monkeypatch):
    """A client still missing inside the re-exec is a failure, not another round."""
    _missing(monkeypatch)
    monkeypatch.setenv(runs.REEXEC_ENV, "1")
    monkeypatch.setattr(runs.subprocess, "run", lambda *a, **k: pytest.fail("re-exec looped"))
    with pytest.raises(SystemExit) as e:
        runs._ensure_client("wandb", ["runs", "fetch", "--exp=1"])
    assert "still not importable" in str(e.value)


def test_without_uv_the_missing_client_is_named(monkeypatch):
    _missing(monkeypatch)
    monkeypatch.delenv(runs.REEXEC_ENV, raising=False)
    monkeypatch.setattr(runs.shutil, "which", lambda _: None)
    with pytest.raises(SystemExit) as e:
        runs._ensure_client("mlflow", ["runs", "fetch", "--exp=1"])
    assert "mlflow is not installed" in str(e.value)


def test_reexec_pins_root_and_this_checkout(tmp_path, monkeypatch):
    _at(monkeypatch, _project(tmp_path, "wandb"))
    _missing(monkeypatch)
    monkeypatch.delenv(runs.REEXEC_ENV, raising=False)
    monkeypatch.setattr(runs.shutil, "which", lambda _: "/usr/bin/uv")
    seen = {}

    def fake_run(cmd, env=None, **kw):
        seen["cmd"], seen["env"] = cmd, env
        return type("P", (), {"returncode": 0})()

    monkeypatch.setattr(runs.subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as e:
        runs._ensure_client("wandb", ["runs", "fetch", "--exp=1"])
    assert e.value.code == 0
    assert seen["cmd"][:5] == ["uv", "run", "--no-project", "--with", "wandb"]
    assert seen["cmd"][-6:] == ["python", "-m", "maestro_cli.cli", "runs", "fetch", "--exp=1"]
    # The child resolves the parent's project, and imports the parent's checkout.
    assert seen["env"]["MAESTRO_ROOT"] == str(tmp_path)
    assert Path(seen["env"]["PYTHONPATH"]) == Path(runs.__file__).resolve().parent.parent
    assert seen["env"][runs.REEXEC_ENV] == "1"


# -- MLflow: which server and experiment --------------------------------------

def _mlflow_env(monkeypatch, **env):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _maestro_toml(root: Path, body: str):
    (root / "maestro.toml").write_text(body)


def test_declared_mlflow_keys_are_read_from_maestro_toml(tmp_path, monkeypatch):
    _at(monkeypatch, _project(tmp_path, "mlflow"))
    _maestro_toml(tmp_path, 'mlflow_uri = "http://localhost:5000"\n'
                            'mlflow_experiment = "demo_predictive"\n')
    assert runs._declared_mlflow(tmp_path) == {
        "mlflow_uri": "http://localhost:5000",
        "mlflow_experiment": "demo_predictive",
    }


def test_no_maestro_toml_declares_nothing(tmp_path):
    assert runs._declared_mlflow(tmp_path) == {}


def test_maestro_toml_without_the_keys_declares_nothing(tmp_path):
    _maestro_toml(tmp_path, 'layers = ["discipline"]\n')
    assert runs._declared_mlflow(tmp_path) == {}


def test_a_non_string_mlflow_key_stops_with_its_name(tmp_path):
    _maestro_toml(tmp_path, "mlflow_experiment = 3\n")
    with pytest.raises(SystemExit) as e:
        runs._declared_mlflow(tmp_path)
    assert "mlflow_experiment" in str(e.value)


def test_unparseable_maestro_toml_stops_rather_than_ignoring_the_keys(tmp_path):
    _maestro_toml(tmp_path, "mlflow_experiment = \n")
    with pytest.raises(SystemExit) as e:
        runs._declared_mlflow(tmp_path)
    assert "cannot parse" in str(e.value)


def test_experiment_name_env_beats_toml_beats_dir_name(monkeypatch):
    declared = {"mlflow_experiment": "from_toml"}
    _mlflow_env(monkeypatch, MLFLOW_EXPERIMENT_NAME="from_env")
    assert runs.resolve_mlflow(os.environ, declared, "toy")[1:] == ("from_env", "MLFLOW_EXPERIMENT_NAME")

    _mlflow_env(monkeypatch)
    assert runs.resolve_mlflow(os.environ, declared, "toy")[1:] == (
        "from_toml", "mlflow_experiment in maestro.toml")

    assert runs.resolve_mlflow(os.environ, {}, "toy")[1:] == ("toy", "the project directory name")


def test_tracking_uri_env_beats_toml_beats_mlflow_default(monkeypatch):
    declared = {"mlflow_uri": "http://toml:5000"}
    _mlflow_env(monkeypatch, MLFLOW_TRACKING_URI="http://env:5000")
    assert runs.resolve_mlflow(os.environ, declared, "toy")[0] == "http://env:5000"

    _mlflow_env(monkeypatch)
    assert runs.resolve_mlflow(os.environ, declared, "toy")[0] == "http://toml:5000"

    assert runs.resolve_mlflow(os.environ, {}, "toy")[0] is None


def test_the_two_keys_resolve_independently(monkeypatch):
    """An env URI does not drag the experiment name off the toml key, and vice versa."""
    _mlflow_env(monkeypatch, MLFLOW_TRACKING_URI="http://env:5000")
    declared = {"mlflow_uri": "http://toml:5000", "mlflow_experiment": "demo_predictive"}
    assert runs.resolve_mlflow(os.environ, declared, "toy") == (
        "http://env:5000", "demo_predictive", "mlflow_experiment in maestro.toml")


def test_an_empty_env_var_counts_as_unset(monkeypatch):
    _mlflow_env(monkeypatch, MLFLOW_EXPERIMENT_NAME="", MLFLOW_TRACKING_URI="")
    declared = {"mlflow_uri": "http://toml:5000", "mlflow_experiment": "from_toml"}
    assert runs.resolve_mlflow(os.environ, declared, "toy") == (
        "http://toml:5000", "from_toml", "mlflow_experiment in maestro.toml")


def test_missing_experiment_error_names_its_source(tmp_path, monkeypatch):
    _at(monkeypatch, _project(tmp_path, "mlflow"))
    _maestro_toml(tmp_path, 'mlflow_experiment = "demo_predictive"\n')
    _mlflow_env(monkeypatch)
    fake_mlflow = SimpleNamespace(set_tracking_uri=lambda uri: None,
                                  get_experiment_by_name=lambda name: None)
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)
    with pytest.raises(SystemExit) as e:
        runs._fetch_mlflow("toy", "07")
    assert "'demo_predictive'" in str(e.value)
    assert "mlflow_experiment in maestro.toml" in str(e.value)
