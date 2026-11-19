# Module: Provenance (run tracking + formal dataset records)

Load when the project declares a tracker (`pyproject.toml` `[tool.maestro] tracker = "wandb" | "mlflow"`) or needs formal dataset provenance. Untracked exploratory projects need only core rules 2 and 7.

## Runs vs experiments

- **Experiment ≠ run.** One `exp_NN` record = one hypothesis; a run is one tracker execution. One experiment has N runs (0 for analysis-only, many for a sweep).
- Tracker is declared once per project in `pyproject.toml`; key absent = `none`. Creds from `~/.env`; tracker project name = repo dir name.
- **The logging side is a project dependency, and `maestro init --tracker=<name>` installs it.** The CLI is machine-level and isolated (ADR 10), so its environment is deliberately not on your import path: an experiment that calls `from maestro.tracking import start_run` needs `maestro[tracking]` in the project's OWN env. Turning a tracker on runs `uv add "maestro[tracking] @ git+<repo>@v<version>"` for you (a non-uv project — conda — gets the requirement printed to add itself). A project with `tracker = "none"` installs nothing, which is the point of the extra. `--dep-source=` repoints it at a checkout while the repo is not reachable at that URL.
- **Run naming is the join key**: `exp_NN_<slug>__<variant>__s<seed>` (W&B `group=exp_NN_<slug>`; MLflow `tag exp=NN`). The record stores only `best_run:` via `maestro exp update --id=<N> --best-run=<name>`.
- **Metrics come back out of the tracker, never out of memory** (core rule 2): `maestro runs fetch --exp=<N> [--metric=<key>]` resolves the group from the record on disk and prints what was logged; `--json` returns every run, `maestro runs url --exp=<N>` just prints the group's URL. Read it, then write it with `maestro exp update --metric=`. The client is fetched per call (`uv run --with <tracker>`), so never pass `--with` and never install wandb/mlflow to make it work.

## Three-leg run provenance

A run is reproducible only if all three inputs are pinned:

1. **Library code → `git_sha`**, clean-tree gated: commit `src/`/`scripts/` first; the tracker blocks logging from a dirty tracked tree (explicit escape for throwaway runs only).
2. **Experiment code → `exp_code_sha`**: `experiments/exp_NN_*.py` is gitignored, so each recorded run freezes the script to the tracker as a content-addressed code artifact (`exp_NN_<slug>__code`); deduped by digest, no local frozen copies.
3. **Data → `dataset_sha`** resolved from the dataset record; the tracker blocks a dataset with no resolvable sha.

## Dataset records (formal provenance)

- Every dataset under `data/raw/` gets a record at `docs/data/<name>.md` **before** first use — via `maestro dataset new --name=<name> --version=<vN> --source=<url|ref>` (sha256 computed from bytes, never typed). Body (schema, caveats, loading) is hand-edited.
- `outcome: infra` marks infrastructure runs (fleet tests, smoke benchmarks). An ADR is amended in place (`maestro adr amend`) and a folded one moves to `docs/archive/adrs/` (core rule 13); a legacy `status: superseded` still requires `superseded_by: N`.
- Datasets arriving as git clones: strip `.git/`, vendor only used files. Bulk binaries under `data/` are gitignored; the record makes them reproducible.
- **Shared datasets** live once in `~/data/<name>/v<N>/`, symlinked in at version level; each project still gets its own record. Never delete a pinned version while any project links it (`maestro docs check` warns on dangling links).
- `maestro dataset verify` recomputes shas and flags drift — run it when a result looks off or before a write-up citing the data.
