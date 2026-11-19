"""W&B experiment-tracking helper (maestro tracker conventions). No domain deps.

Tracking is **optional** and off by default: the project declares it in
``pyproject.toml`` as ``[tool.maestro] tracker = "none" | "wandb" | "mlflow"`` (key
absent = ``"none"``). ``start_run`` resolves that key and exits with a clear message
unless it names ``"wandb"`` — the only write-side implemented here. With
``tracker = "none"`` an experiment writes its metrics as machine-written artifacts in
``data/experiments/exp_NN_*/`` instead (``metrics.json``, ``run.log``). ``wandb`` is
imported lazily, so this module imports fine on a machine without it.

Maestro contract (see ``[tool.maestro] tracker`` + project CLAUDE.md):

- **project** = the repo directory name (e.g. ``my-project``), derived from the repo
  root so the literal lives in one place.
- **run name** = ``exp_NN_<slug>__<variant>__s<seed>`` (NN zero-padded 2-digit).
- **group** = ``exp_NN_<slug>`` — the join key tying every run of one experiment.
- **tags** carry the short ``git_sha`` and optional ``dataset`` provenance, so a run
  always points back to the code + data it scored.
- Headline (one-per-run) metrics live in ``run.summary`` so they are queryable as a
  single value; time-series go through ``wandb.log``.

Credentials (``WANDB_API_KEY`` / ``WANDB_BASE_URL``) are loaded from ``~/.env`` into
``os.environ`` on demand if absent — values are never printed.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path


try:
    import tomllib  # stdlib on Python 3.11+
except ModuleNotFoundError:  # 3.10 system Python: use the tomli backport
    import tomli as tomllib

# WANDB_* keys we copy from ~/.env into the process environment if missing.
_WANDB_ENV_KEYS = ("WANDB_API_KEY", "WANDB_BASE_URL", "WANDB_LICENSE_KEY")


def _wandb():
    """Import ``wandb`` on demand.

    Kept out of module scope so a project whose tracker is "none" (the default) can
    import this module — and get the readable message from ``_require_wandb_tracker``
    — without having the client installed.
    """
    import wandb
    return wandb


# NOTE: tiny repo-root finder is deliberately NOT shared with the CLI's own
# (maestro_cli.frontmatter). Different code tier — the machine-level CLI vs. this
# importable library, added as an ordinary project dependency — so no cross-import.
def _repo_root(start: Path) -> Path:
    """Nearest ancestor containing pyproject.toml (falls back to start)."""
    start = start.resolve()
    for d in (start, *start.parents):
        if (d / "pyproject.toml").exists():
            return d
    return start


def _project_root() -> Path:
    """Repo root of the *consuming project* (cwd-based) — NOT this package's
    install dir. Provenance (git_sha, dirty, project name, dataset records)
    must describe the project running the experiment, not maestro itself."""
    return _repo_root(Path.cwd())


def _load_env_creds() -> None:
    """Populate absent ``WANDB_*`` vars from ``~/.env`` (values never printed)."""
    if all(os.environ.get(k) for k in ("WANDB_API_KEY", "WANDB_BASE_URL")):
        return
    env_path = Path.home() / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key in _WANDB_ENV_KEYS and not os.environ.get(key):
            os.environ[key] = val.strip().strip('"').strip("'")


def project_name() -> str:
    """W&B project = the repo directory name (single source for the literal)."""
    return _project_root().name


def tracker() -> str:
    """The project's ``[tool.maestro] tracker`` — ``"none"`` when unset or unreadable."""
    pp = _project_root() / "pyproject.toml"
    if not pp.exists():
        return "none"
    try:
        data = tomllib.loads(pp.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return "none"
    cfg = (data.get("tool") or {}).get("maestro") or {}
    return str(cfg.get("tracker") or "none")


def _require_wandb_tracker() -> None:
    """Exit with a readable message unless this project's tracker is W&B.

    Tracking is opt-in per project, and only the W&B write side exists here; MLflow is
    supported read-side (``maestro runs fetch``) but not for logging.
    """
    name = tracker()
    if name == "wandb":
        return
    if name == "mlflow":
        raise SystemExit(
            "mlflow write-side not implemented yet — read-back via "
            "`maestro runs fetch` works; use wandb for logging, or keep tracker = none"
        )
    if name == "none":
        raise SystemExit(
            "tracking is disabled for this project — set [tool.maestro] "
            'tracker = "wandb" to enable'
        )
    raise SystemExit(
        f'[tool.maestro] tracker must be "none", "wandb" or "mlflow", got {name!r}.'
    )


def _git(*args: str) -> str | None:
    """Run ``git <args>`` in the repo root; return stripped stdout or None."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=_project_root(), capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def short_git_sha() -> str | None:
    """``git rev-parse --short HEAD`` for the repo, or None if unavailable."""
    return _git("rev-parse", "--short", "HEAD") or None


def git_dirty() -> bool:
    """True if the working tree has uncommitted changes (``git status --porcelain``).

    Returns False when git is unavailable or the tree is clean, so a missing repo
    never blocks a run.
    """
    out = _git("status", "--porcelain")
    return bool(out)


def git_branch() -> str | None:
    """Current branch name (``git rev-parse --abbrev-ref HEAD``), or None."""
    return _git("rev-parse", "--abbrev-ref", "HEAD") or None


def _save_uncommitted_diff(run) -> None:
    """Best-effort: attach ``git diff HEAD`` to the run as ``uncommitted.patch``.

    Only reached on the explicit ``allow_dirty=True`` escape hatch — a dirty run is
    only even partially reproducible if its tracked-file changes are captured. This
    writes the diff next to the run files and uploads it via ``run.save``; any failure
    is downgraded to a warning so it never crashes the run.
    """
    try:
        diff = _git("diff", "HEAD")
        if not diff:
            return
        run_dir = getattr(run, "dir", None) or "."
        patch_path = Path(run_dir) / "uncommitted.patch"
        patch_path.write_text(diff + "\n")
        run.save(str(patch_path), policy="now")
    except Exception as exc:  # noqa: BLE001 — best-effort provenance, never fatal
        warnings.warn(f"could not save uncommitted.patch for dirty run: {exc}")


def _resolve_code_path(code_path: str | os.PathLike | None) -> Path | None:
    """Resolve the experiment script that defines a run, or None if unavailable.

    Explicit ``code_path`` wins; otherwise infer the running script from
    ``sys.modules['__main__'].__file__`` (falling back to ``sys.argv[0]``). Returns
    None for a REPL / interactive session, or when the path is not a real file.
    """
    if code_path is not None:
        p = Path(code_path)
        return p if p.is_file() else None
    main = sys.modules.get("__main__")
    cand = getattr(main, "__file__", None) or (sys.argv[0] if sys.argv else None)
    if not cand:
        return None
    p = Path(cand)
    return p if p.is_file() else None


def _hash_exp_code(code_path: str | os.PathLike | None):
    """Resolve the experiment script and hash its bytes.

    Experiment scripts (``experiments/exp_NN_*.py``) are gitignored/local-only by
    design, so ``git_sha`` (which pins the committed library only) cannot pin them.
    The short sha256 is the cheap, non-sensitive identity/drift check that rides on
    the run alongside the uploaded code.

    Returns ``(exp_code_sha12, basename, source_path)``; all-None when no script can
    be resolved or read (REPL/interactive, or an unreadable file) — warns and never
    raises so a run is never crashed by code capture.
    """
    src = _resolve_code_path(code_path)
    if src is None:
        warnings.warn(
            "could not resolve the experiment script (REPL/interactive or no "
            "__main__ file); skipping exp_code_sha + code upload. Pass "
            "code_path=__file__ to pin the experiment code."
        )
        return None, None, None
    try:
        raw = src.read_bytes()
    except OSError as exc:  # noqa: BLE001 — best-effort provenance, never fatal
        warnings.warn(f"could not read experiment script {src}: {exc}")
        return None, None, None
    return hashlib.sha256(raw).hexdigest()[:12], src.name, src


def _log_exp_code_artifact(run, exp_n: int, slug: str, src: Path,
                           sha: str | None) -> None:
    """Log the experiment script ``src`` as a content-addressed W&B code Artifact.

    The W&B tracker is private and is **not** the team git repo, so the
    experiment code is stored there per experiment instead of being committed.
    A *single* stable artifact name ``exp_NN_<slug>__code`` collects all versions, and
    W&B dedupes by content digest: identical script content across a run's
    variant/seed runs is stored **once** — a new artifact version is created only when
    the code actually changes. The short ``exp_code_sha`` rides along as an alias +
    metadata so a run's code version is identifiable by hash. Best-effort: any failure
    is downgraded to a warning so it never crashes the run.
    """
    try:
        artifact = _wandb().Artifact(
            name=f"{run_group(exp_n, slug)}__code",
            type="code",
            metadata={"exp_code_sha": sha, "exp_code_file": src.name},
        )
        artifact.add_file(str(src))
        run.log_artifact(artifact, aliases=[sha] if sha else None)
    except Exception as exc:  # noqa: BLE001 — best-effort upload, never fatal
        warnings.warn(f"could not log experiment-code artifact for {src}: {exc}")


def resolve_dataset(name: str) -> tuple[str | None, str | None]:
    """Read ``docs/data/<name>.md`` frontmatter; return ``(version, sha256)``.

    Reads the maestro dataset record's YAML frontmatter (the block fenced by the
    first two ``---`` lines) and pulls the ``version`` and ``sha256`` fields. Returns
    ``(None, None)`` if the record is absent; either element is None if that field is
    missing or blank. ``docs/`` is a symlink — read through it normally.
    """
    rec = _project_root() / "docs" / "data" / f"{name}.md"
    if not rec.exists():
        return None, None
    text = rec.read_text()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    front = m.group(1) if m else text

    def _field(key: str) -> str | None:
        fm = re.search(rf"^{re.escape(key)}\s*:\s*(.*)$", front, re.MULTILINE)
        if not fm:
            return None
        val = fm.group(1).strip().strip('"').strip("'").strip()
        return val or None

    sha = _field("sha256")
    # `sha256: pending` is the placeholder a still-collecting record carries (maestro
    # dataset new --collecting). It is not a digest, so a run must not pin provenance to
    # it — treat it as no sha, which routes into the same refusal an unhashed record gets.
    if sha == "pending":
        sha = None
    return _field("version"), sha


def run_name(exp_n: int, slug: str, variant: str, seed: int = 0) -> str:
    """Build ``exp_NN_<slug>__<variant>__s<seed>`` (NN zero-padded 2-digit)."""
    return f"{run_group(exp_n, slug)}__{variant}__s{seed}"


def run_group(exp_n: int, slug: str) -> str:
    """Build the join-key group ``exp_NN_<slug>`` (NN zero-padded 2-digit)."""
    return f"exp_{exp_n:02d}_{slug}"


def start_run(exp_n: int, slug: str, variant: str, *, seed: int = 0,
              dataset: str | None = None, dataset_version: str | None = None,
              dataset_sha: str | None = None, config: dict | None = None,
              project: str | None = None, mode: str | None = None,
              code_path: str | os.PathLike | None = None,
              log_code: bool = True,
              allow_dirty: bool = False,
              allow_missing_dataset_prov: bool = False):
    """Open a W&B run per the maestro naming/grouping/tagging conventions.

    **Three-leg code+data provenance.** The committed library is pinned by ``git_sha``
    (clean-tree gated, below); the **experiment script** (``experiments/exp_NN_*.py``,
    gitignored/local-only by design) is captured separately as ``exp_code_sha`` plus an
    uploaded copy on the tracker; the dataset is pinned by ``dataset_sha`` (gated). The
    experiment code never enters git — it lives on the private tracker as a
    content-addressed code Artifact (deduped across a run's variants).

    Provenance is **enforced with hard guards**, not soft tags: a run is logged only
    when its metrics are reproducible from its tags. Two gates block by default —

    - **Clean-tree gate.** A dirty *tracked* tree means ``git_sha`` (bare ``HEAD``) does
      not contain the committed-tier code (``src/``, ``scripts/``) that produced these
      metrics, so that leg is not reproducible. ``start_run`` raises ``RuntimeError``
      unless ``allow_dirty=True`` is passed. (Experiment code in ``experiments/`` is
      gitignored and pinned separately via ``exp_code_sha`` + the code Artifact, so it
      does not trip this gate.)
    - **Dataset provenance gate.** A ``dataset`` with no resolvable ``sha256`` (no
      ``docs/data/<name>.md`` record, or an empty ``sha256``, and no explicit
      ``dataset_sha``) is half-provenance. ``start_run`` raises ``RuntimeError`` unless
      ``allow_missing_dataset_prov=True`` is passed. (``dataset_version`` is best-effort:
      an empty version only warns.)

    Parameters
    ----------
    exp_n, slug, variant, seed : the run-name parts (see module docstring).
    dataset, dataset_version, dataset_sha : optional provenance; explicit version/sha
        win over the ``docs/data/<name>.md`` record. Each resolved one becomes a
        ``key:value`` tag so a run points back to the data it scored.
    config : hyperparameters / run config stored on the run.
    project : W&B project override (defaults to the repo dir name).
    mode : ``"online"`` (default), ``"offline"``, or ``"disabled"`` — passed to
        ``wandb.init`` so tests / dry-runs avoid the network.
    code_path : explicit path to the experiment script; defaults to the running
        ``__main__`` file (``sys.argv[0]`` fallback). Its short sha256 is logged as
        ``exp_code_sha`` (config + tag) with ``exp_code_file`` (basename).
    log_code : upload the experiment script to the run as a content-addressed code
        Artifact named ``exp_NN_<slug>__code`` (default True). W&B dedupes by digest,
        so a new version appears only when the code changes — not once per run. A
        REPL/interactive session with no resolvable script warns and continues.
    allow_dirty : explicit, loud escape hatch for a throwaway/debug run from a dirty
        tree. Proceeds with a warning, tags ``provenance:dirty-override``, sets
        ``git_dirty=True`` in config, and saves the ``git diff HEAD`` patch.
    allow_missing_dataset_prov : explicit, loud escape hatch to log a ``dataset`` with
        no resolvable sha. Proceeds with a warning and tags ``provenance:dataset-unverified``.

    Returns the ``wandb.Run``.

    Raises
    ------
    RuntimeError
        if the git tree is dirty and ``allow_dirty`` is False, or a ``dataset`` has no
        resolvable sha and ``allow_missing_dataset_prov`` is False.
    """
    _require_wandb_tracker()
    _load_env_creds()
    cfg = dict(config or {})
    cfg.update(exp_n=exp_n, slug=slug, variant=variant, seed=seed)
    tags = []

    # --- Clean-tree gate -----------------------------------------------------
    # A run must be logged only from a clean tree so git_sha is the code that
    # produced its metrics. A dirty tree BLOCKS by default; allow_dirty is a narrow,
    # loud escape for throwaway runs that makes the compromise visible on the run.
    sha = short_git_sha()
    dirty = git_dirty()
    if dirty and not allow_dirty:
        n_changed = len(_git("status", "--porcelain").splitlines()) \
            if _git("status", "--porcelain") else 0
        raise RuntimeError(
            f"Refusing to log: tracked library tree is dirty ({n_changed} files). "
            f"Commit the committed-tier code (src/, scripts/) so git_sha reflects it, "
            f"then re-run. (Experiment code in experiments/ is gitignored/local-only "
            f"and is captured separately as exp_code_sha + an uploaded code artifact; "
            f"data is pinned by dataset_sha.) For a throwaway/debug run only, pass "
            f"allow_dirty=True."
        )
    if sha:
        tags.append(f"git_sha:{sha}")
    cfg["git_sha"] = sha
    cfg["git_dirty"] = dirty
    cfg["git_branch"] = git_branch()
    if dirty and allow_dirty:
        warnings.warn(
            "allow_dirty=True: logging a W&B run from a DIRTY git tree — git_sha does "
            "not reflect the run's code. This run is reproducible only via the saved "
            "uncommitted.patch. Use for throwaway/debug runs only."
        )
        tags.append("provenance:dirty-override")

    # --- Dataset provenance gate ---------------------------------------------
    # Explicit version/sha win; otherwise read the maestro record. sha is mandatory
    # (BLOCK with no resolvable sha); version is best-effort (warn, don't block).
    if dataset:
        rec_version, rec_sha = (None, None)
        if dataset_version is None or dataset_sha is None:
            rec_version, rec_sha = resolve_dataset(dataset)
        if dataset_version is None:
            dataset_version = rec_version
        if dataset_sha is None:
            dataset_sha = rec_sha

        if dataset_sha is None:
            if not allow_missing_dataset_prov:
                raise RuntimeError(
                    f"dataset '{dataset}' has no resolvable sha256 (no "
                    f"docs/data/{dataset}.md record or empty sha). Create/repair it "
                    f"with `maestro dataset new --name={dataset}`, or pass dataset_sha explicitly."
                )
            warnings.warn(
                f"allow_missing_dataset_prov=True: logging dataset '{dataset}' with no "
                "resolvable sha256 — provenance unverified."
            )
            tags.append("provenance:dataset-unverified")
        if not dataset_version:
            warnings.warn(
                f"dataset '{dataset}' record has empty version — pinning by sha only"
            )

        tags.append(f"dataset:{dataset}")
        cfg["dataset"] = dataset
        if dataset_version:
            tags.append(f"dataset_version:{dataset_version}")
            cfg["dataset_version"] = dataset_version
        if dataset_sha:
            tags.append(f"dataset_sha:{dataset_sha[:12]}")
            cfg["dataset_sha"] = dataset_sha

    # --- Experiment-code provenance ------------------------------------------
    # Experiment scripts (experiments/exp_NN_*.py) are gitignored/local-only by
    # design, so git_sha (committed library only) can't pin them. Capture the script
    # separately: its short sha256 is logged to the run (cheap, non-sensitive drift
    # check), and the bytes are uploaded as a content-addressed code Artifact below.
    code_sha, code_file, code_src = _hash_exp_code(code_path)
    if code_sha:
        cfg["exp_code_sha"] = code_sha
        cfg["exp_code_file"] = code_file
        tags.append(f"exp_code_sha:{code_sha}")

    run = _wandb().init(
        project=project or project_name(),
        name=run_name(exp_n, slug, variant, seed),
        group=run_group(exp_n, slug),
        tags=tags,
        config=cfg,
        mode=mode,
    )
    if dirty and allow_dirty:
        _save_uncommitted_diff(run)
    if log_code and code_src is not None:
        _log_exp_code_artifact(run, exp_n, slug, code_src, code_sha)
    return run


def _resolve_run(run):
    """Use the explicit run, else the active ``wandb.run``; error if neither."""
    run = run or _wandb().run
    if run is None:
        raise RuntimeError("no active wandb run; pass run= or call start_run first")
    return run


def log_metrics(metrics: dict, *, run=None, summary: bool = True) -> None:
    """Record ``metrics``; write headline values to ``run.summary`` and time-series.

    ``summary=True`` (default) updates ``run.summary`` so each metric is queryable
    as one value per run; the metrics are always also sent via ``wandb.log`` for the
    time-series view.
    """
    run = _resolve_run(run)
    if summary:
        for key, val in metrics.items():
            run.summary[key] = val
    _wandb().log(dict(metrics))


def log_cv(name: str, values, *, run=None) -> None:
    """Log cross-validation summary stats ``{name}_mean/_std/_n`` to ``run.summary``.

    ``_std`` is the population standard deviation (``numpy.std``, ddof=0). ``_n`` is
    the number of folds. Use this for fold-aggregated headline metrics (e.g. the
    25-fold Spearman) so the leaderboard query reads one mean/std per run.
    """
    run = _resolve_run(run)
    import numpy as np    # the `tracking` extra, not a base dep
    arr = np.asarray(list(values), dtype=float)
    run.summary[f"{name}_mean"] = float(np.mean(arr))
    run.summary[f"{name}_std"] = float(np.std(arr))  # ddof=0 (population std)
    run.summary[f"{name}_n"] = int(arr.size)


def finish(run=None) -> None:
    """Close the active (or given) run — flushes summary + uploads."""
    _wandb().finish()


def fetch_runs(exp_n: int, *, project: str | None = None) -> list[dict]:
    """All runs of experiment ``exp_n`` (group ``exp_NN_*``) via the W&B API.

    Returns one dict per run: ``{name, group, summary, config, tags}``. Matches on
    ``group.startswith("exp_NN_")`` so every variant/seed of the experiment is
    included regardless of slug.
    """
    _load_env_creds()
    api = _wandb().Api()
    prefix = f"exp_{exp_n:02d}_"
    proj = project or project_name()
    entity = os.environ.get("WANDB_ENTITY")
    path = f"{entity}/{proj}" if entity else proj
    out = []
    for r in api.runs(path):
        group = r.group or ""
        if not group.startswith(prefix):
            continue
        out.append({
            "name": r.name,
            "group": group,
            "summary": dict(r.summary),
            "config": dict(r.config),
            "tags": list(r.tags),
        })
    return out


def best_run(exp_n: int, metric: str, *, mode: str = "max",
             project: str | None = None):
    """Return ``(run_name, value)`` of the best run of ``exp_n`` on ``metric``.

    ``mode="max"`` maximizes (correlations), ``"min"`` minimizes (RMSE). Runs whose
    summary lacks the metric (or stores a non-finite value) are skipped. Returns
    ``(None, None)`` if no run qualifies.
    """
    best_name, best_val = None, None
    for r in fetch_runs(exp_n, project=project):
        val = r["summary"].get(metric)
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        import numpy as np    # the `tracking` extra, not a base dep
        if not np.isfinite(val):
            continue
        if best_val is None or (val > best_val if mode == "max" else val < best_val):
            best_name, best_val = r["name"], val
    return best_name, best_val
