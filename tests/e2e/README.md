# Maestro end-to-end smoke harness

A repeatable test that adopts a toy project as a maestro project **from zero**
every run, drives the whole flow, exercises **both** trackers (mlflow + wandb),
and prints `PASS`/`FAIL` per feature.

## Run

```bash
bash tests/e2e/run_smoke.sh
```

Each run wipes and recreates `/tmp/maestro-smoke`, copies `seed/` into it,
`git init`s it, then: runs `maestro init --path`, fills `CLAUDE.md` + docs,
sets `[tool.maestro] tracker`, registers the `wine` dataset, builds and searches
the kb index (on-topic hit, off-topic rejection, selftest, and a stale-index
warning after an entry is added behind the index's back), runs `exp_01` against mlflow then wandb and reads each metric back through
`maestro runs fetch`, creates exp/adr/finding records, fires the record-guard
hook, and runs the drift check. Ends with `RESULT: <n> passed, <n> failed` (exit 1 if any
failed). The adopted project is **left in place** at `/tmp/maestro-smoke` for
inspection; step logs are under `/tmp/smoke_*.log`.

## Requirements

- `~/.env` with tracker creds (`MLFLOW_TRACKING_URI`, `WANDB_API_KEY`,
  `WANDB_BASE_URL`).
- Network access (`uv` fetches the tracker clients and the kb embedder per step).
- The mlflow + wandb docker services running (the run+readback steps hit them).
- `uv` on `PATH` (deps are pulled per-step via `uv run --with ...`).

## What's here

- `seed/` — the pre-adoption toy project (no `docs/`, `tools/`, or maestro
  `CLAUDE.md`; `pyproject.toml` has a `[project]` block but no `[tool.maestro]`).
  Contains the `exp_01_rf_baseline.py` (RandomForest on sklearn `wine`, branches
  on `MAESTRO_TRACKER`), a `fixtures/` kb entry for the Breiman paper (so the kb
  pipeline is deterministic without an agent writing a summary), and the
  `claude_md_fill.md` KB-topics snippet.
- `run_smoke.sh` — the harness.
