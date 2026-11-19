"""Read back tracked runs (W&B or MLflow) for a maestro experiment.

A maestro *experiment* (exp_NN) is one hypothesis; its *runs* live in W&B or MLflow.
This module resolves an experiment's runs and returns their metrics, so a record is
written from REAL logged numbers at write-up time (core rule 2) — never hand-typed,
never recalled. Read-only: it never logs or mutates a run.

    maestro runs fetch --exp=<N> [--metric=<key>] [--json]
    maestro runs fetch --group=<name> [--metric=<key>] [--json]
    maestro runs url --exp=<N>

Identity is derived, not configured:
  - tracker      <- pyproject.toml [tool.maestro] tracker (none | wandb | mlflow),
                    read through the same parser `maestro init --tracker=` writes with
  - project name <- the project root's directory name
  - run group    <- exp_NN_<slug> (W&B group; MLflow tag exp=NN)
  - creds        <- env: WANDB_BASE_URL/WANDB_API_KEY/WANDB_ENTITY, MLFLOW_TRACKING_URI
  - mlflow       <- optional maestro.toml `mlflow_uri` and `mlflow_experiment`, overridden by
                    env MLFLOW_TRACKING_URI and MLFLOW_EXPERIMENT_NAME (env beats toml);
                    with neither set, MLflow's default URI and the project directory name

The tracker client loads itself: with wandb/mlflow not importable, `fetch` re-execs the
CLI under `uv run --with <tracker>`. You never pass `--with`.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 system Python
    import tomli as tomllib

from .declaration import DECLARATION_FILE
from .frontmatter import EXP_DIR, ROOT
from .init import PYPROJECT, TRACKER_DEFAULT, TRACKERS, read_tracker

# Set in the re-exec'd child so it never re-execs again (an unimportable client there
# is a real failure, not a reason to loop).
REEXEC_ENV = "_MAESTRO_RUNS_REEXEC"


# -- identity ------------------------------------------------------------------

def _tracker():
    """The project's tracker, or exit with what to do about it.

    Fetching is only meaningful once a tracker is named, so "none" (the default) is a
    clean stop rather than an error: an untracked project's metrics are the artifacts
    under data/experiments/, and those are read from disk.
    """
    pp = ROOT / PYPROJECT
    name = read_tracker(pp.read_text()) if pp.exists() else None
    name = name or TRACKER_DEFAULT
    if name == "none":
        sys.exit(f"{ROOT.name}: no tracker configured ([tool.maestro] tracker in {PYPROJECT}) — "
                 "nothing to fetch. Read the run's artifacts under data/experiments/ instead, "
                 "or adopt one with `maestro init --tracker=wandb|mlflow`.")
    if name not in TRACKERS:
        sys.exit(f"[tool.maestro] tracker must be one of {', '.join(TRACKERS)}, got {name!r}.")
    return name


def _exp_group(n):
    """exp_NN -> 'exp_NN_<slug>', resolved from the record on disk."""
    for p in sorted(EXP_DIR.glob(f"exp_{n:02d}_*.md")) + sorted(EXP_DIR.glob(f"exp_{n}_*.md")):
        return p.stem
    rel = EXP_DIR.relative_to(ROOT) if EXP_DIR.is_relative_to(ROOT) else EXP_DIR
    sys.exit(f"No {rel}/exp_{n:02d}_*.md under {ROOT} — scaffold the experiment first: "
             "maestro exp new --slug=<slug>.")


def _exp_tag(n):
    """The MLflow tag value identifying an experiment's runs (zero-padded, matching the group)."""
    return f"{n:02d}"


# -- loading the client --------------------------------------------------------

def _reexec_argv(args):
    """This invocation, rebuilt as CLI arguments.

    Rebuilt from the parsed flags rather than read off sys.argv, because the CLI can be
    called in-process with an explicit argv (tests, and any embedding of `cli.main`).
    """
    argv = list(args._key)  # ("runs", "fetch")
    if getattr(args, "exp", None) is not None:
        argv.append(f"--exp={args.exp}")
    if getattr(args, "group", None):
        argv.append(f"--group={args.group}")
    if getattr(args, "metric", None):
        argv.append(f"--metric={args.metric}")
    if getattr(args, "json", False):
        argv.append("--json")
    return argv


def _importable(name):
    """Whether a tracker client can be imported from the environment we run in.

    Its own function because whether a client is present is a property of the machine,
    not of the code under test — the re-exec path is only reachable in a test by
    pinning this answer.

    A tracker writes its output beside the project (`wandb/`, `mlruns/`), and cwd is on
    sys.path, so that directory imports as an empty namespace package under the client's
    own name. Left unguarded it answers "installed" and the fetch then dies on
    `module 'wandb' has no attribute 'Api'`. A namespace package has no origin, which is
    exactly the distinction to test.
    """
    try:
        module = __import__(name)
    except ModuleNotFoundError:
        return False
    return getattr(module, "__file__", None) is not None


def _ensure_client(tracker, argv):
    """Re-exec under `uv run --with <tracker>` when the client is not importable.

    The CLI is machine-level (ADR 10) and installed in its own environment, so neither
    tracker client is there — and installing both into it would burden every project
    that tracks nothing. Instead the client is fetched per call, which is why the
    tracker is named in the project rather than passed on the command line.
    """
    if _importable(tracker):
        return
    if os.environ.get(REEXEC_ENV):
        sys.exit(f"{tracker} is still not importable inside `uv run --with {tracker}` — "
                 "the client failed to install; re-run with the uv output visible.")
    if not shutil.which("uv"):
        sys.exit(f"{tracker} is not installed, and uv is not on PATH to fetch it per call. "
                 "Install uv (https://docs.astral.sh/uv/), or install the client into the "
                 "environment maestro runs from.")
    cmd = ["uv", "run", "--no-project", "--with", tracker, "--with", "pyyaml",
           "python", "-m", "maestro_cli.cli", *argv]
    # --no-project: the ephemeral environment is the tracker client plus this checkout
    # on PYTHONPATH, never the consuming project's env (which need not exist at all).
    # ROOT is pinned so the child resolves the same project the parent did.
    env = {**os.environ, REEXEC_ENV: "1", "MAESTRO_ROOT": str(ROOT),
           "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    # Run from a neutral directory: MAESTRO_ROOT already pins the project, and the
    # project's own wandb/ or mlruns/ output dir would otherwise shadow the client
    # package on the child's sys.path.
    with tempfile.TemporaryDirectory(prefix="maestro-runs-") as neutral:
        sys.exit(subprocess.run(cmd, env=env, cwd=neutral).returncode)


# -- W&B -----------------------------------------------------------------------

def _fetch_wandb(project, group):
    import wandb
    entity = os.environ.get("WANDB_ENTITY")
    base = os.environ.get("WANDB_BASE_URL")
    if not os.environ.get("WANDB_API_KEY"):
        print("  ! WANDB_API_KEY not set — relying on cached login.", file=sys.stderr)
    api = wandb.Api(overrides={"base_url": base} if base else None)
    path = f"{entity}/{project}" if entity else project
    return [{
        "name": r.name,
        "state": r.state,
        "metrics": {k: v for k, v in dict(r.summary).items() if not k.startswith("_")},
        "config": {k: v for k, v in dict(r.config).items() if not k.startswith("_")},
        "url": r.url,
    } for r in api.runs(path, filters={"group": group})]


# -- MLflow --------------------------------------------------------------------

MLFLOW_KEYS = ("mlflow_uri", "mlflow_experiment")


def _declared_mlflow(root):
    """The `mlflow_uri` / `mlflow_experiment` keys of the project's maestro.toml, {} when unset."""
    path = Path(root) / DECLARATION_FILE
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, ValueError) as exc:
        sys.exit(f"{DECLARATION_FILE}: cannot parse — {exc}")
    for key in MLFLOW_KEYS:
        if key in data and not (isinstance(data[key], str) and data[key].strip()):
            sys.exit(f"{DECLARATION_FILE}: {key} must be a non-empty string, got {data[key]!r}.")
    return {key: data[key].strip() for key in MLFLOW_KEYS if key in data}


def resolve_mlflow(env, declared, project):
    """(tracking URI or None, experiment name, where the name came from).

    Env beats maestro.toml beats the default: the URI falls through to MLflow's own
    default when neither names one, the experiment name to the project directory name.
    """
    uri = env.get("MLFLOW_TRACKING_URI") or declared.get("mlflow_uri") or None
    if env.get("MLFLOW_EXPERIMENT_NAME"):
        return uri, env["MLFLOW_EXPERIMENT_NAME"], "MLFLOW_EXPERIMENT_NAME"
    if declared.get("mlflow_experiment"):
        return uri, declared["mlflow_experiment"], "mlflow_experiment in maestro.toml"
    return uri, project, "the project directory name"


def _fetch_mlflow(project, tag_value):
    import mlflow
    uri, exp_name, source = resolve_mlflow(os.environ, _declared_mlflow(ROOT), project)
    if uri:
        mlflow.set_tracking_uri(uri)
    exp = mlflow.get_experiment_by_name(exp_name)
    if exp is None:
        sys.exit(f"No MLflow experiment named '{exp_name}' (from {source}). Set "
                 "MLFLOW_EXPERIMENT_NAME or mlflow_experiment in maestro.toml to name another.")
    df = mlflow.search_runs(experiment_ids=[exp.experiment_id],
                            filter_string=f"tags.exp = '{tag_value}'")
    out = []
    for _, row in df.iterrows():
        metrics = {c[len("metrics."):]: row[c] for c in df.columns
                   if c.startswith("metrics.") and row[c] == row[c]}  # drop NaN
        config = {c[len("params."):]: row[c] for c in df.columns
                  if c.startswith("params.") and row[c] == row[c]}
        out.append({
            "name": row.get("tags.mlflow.runName") or row.get("run_id"),
            "state": row.get("status"),
            "metrics": metrics,
            "config": config,
            "url": f"{uri or ''}/#/experiments/{exp.experiment_id}/runs/{row.get('run_id')}",
        })
    return out


# -- verbs ---------------------------------------------------------------------

def _pick_best(runs, key=None):
    """The run to quote: highest `key` among finished runs, else the first finished one.

    A convenience for the human summary only — --json returns every run, and picking
    the headline run for a record is a judgement call, not a max().
    """
    finished = [r for r in runs if str(r.get("state", "")).lower() == "finished"] or runs
    if key:
        scored = [r for r in finished if key in (r.get("metrics") or {})]
        if scored:
            return max(scored, key=lambda r: r["metrics"][key])
    return finished[0] if finished else None


def _resolve_target(args):
    """(group, mlflow tag value) for --exp or --group."""
    if args.exp is not None:
        return _exp_group(args.exp), _exp_tag(args.exp)
    m = re.search(r"exp_(\d+)", args.group)
    return args.group, m.group(1) if m else args.group


def cmd_fetch(args):
    tracker = _tracker()
    _ensure_client(tracker, _reexec_argv(args))
    project = ROOT.name
    group, tag_value = _resolve_target(args)

    runs = _fetch_wandb(project, group) if tracker == "wandb" else _fetch_mlflow(project, tag_value)
    best = _pick_best(runs, args.metric)
    if args.json:
        print(json.dumps({"tracker": tracker, "project": project, "group": group,
                          "n_runs": len(runs), "best": best, "runs": runs},
                         indent=2, default=str))
        return
    print(f"tracker={tracker}  project={project}  group={group}  n_runs={len(runs)}")
    if best:
        print(f"best run: {best['name']}  ({best.get('state')})")
        for k, v in (best.get("metrics") or {}).items():
            print(f"  {k} = {v}")
    elif not runs:
        print("  (no runs found — an N=0 experiment, or runs not named exp_NN_<slug>__*.)")


def cmd_url(args):
    """The tracker URL for an experiment's run group. No API call, so no client needed."""
    tracker = _tracker()
    project = ROOT.name
    group = _exp_group(args.exp)
    if tracker == "wandb":
        base = os.environ.get("WANDB_BASE_URL", "https://wandb.ai").rstrip("/")
        entity = os.environ.get("WANDB_ENTITY", "<entity>")
        print(f"{base}/{entity}/{project}/groups/{group}")
    else:
        uri, exp_name, _ = resolve_mlflow(os.environ, _declared_mlflow(ROOT), project)
        print(f"{(uri or '').rstrip('/')}/#/experiments  (experiment '{exp_name}', "
              f"filter tags.exp = '{_exp_tag(args.exp)}')")
