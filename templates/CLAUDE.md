# CLAUDE.md

Guidance for any agent harness working in this repository: project facts and project
rules only. How a harness loads, spawns or guards is its own kernel's business, never this
file's (maestro core rule 11).

## IMPORTANT

agent-attribution: off

Commit trailers naming the agent/harness are OFF for this repo. Set
`agent-attribution: trailer` instead to record which tool did the work as a
`Co-Authored-By:` trailer — do that only in repos where that is welcome, never in
client or org repos. Either way, code, comments and `.gitignore` stay free of
AI-tool mentions: attribution is git metadata, not source text.

- Never stage `.claude/`. {Whether `CLAUDE.md` and `docs/` are tracked is THIS repo's
  decision (maestro core rule 11 / harness common.md) — state it here.}

---

## Maestro project

Adopted {YYYY-MM-DD} (ADR {N}); `maestro.toml` declares the rule layers and the data shape.
The rules are maestro `core.md` — every harness loads it, it is never copied here — and
`maestro info show` prints them with this project's layout: run it once per session before
touching records. Every CLI argument is a named flag (`maestro <group> <verb> --flag=value`).
Project-specific facts only:

- Tracker: `{none|wandb|mlflow}` (`pyproject.toml [tool.maestro]`); with `none`, metrics are
  machine-written `metrics.json` + `run.log` under `data/experiments/exp_NN_*/run_<K>/`.
- {Which runs are `outcome: infra`; evidence paths; anything the checker leaves to the project.}

---

## Project Overview

{1-2 sentence project description.}

Goals, the route (ordered arcs the next epics are drawn from), and non-goals live in
`README.md` §Goals / §The route / §Non-goals — the strategic layer (kanban module). This
file links them, never restates them.

**Team**: {Name (role), Name (role), ...}

---

## Environment Setup

**Package + env tool: `uv`** (not pip). The project is a `pyproject.toml` + `uv.lock` with a `.venv/` that `uv` manages — run everything via `uv run`:

```bash
uv sync && uv run python -u ...
```

{Key dependencies list.} Use **conda (miniforge) instead — only when a dependency needs system libraries a wheel can't provide** (CUDA toolchain, `gdal`, `ffmpeg`, some MPI builds). See `docs/setup.md`.

**Import convention**: {How to import from the package — always explicit submodule imports.}

**Deprecated modules/functions** (do NOT use):
- `{old_module}.{old_func}` → use `{new_module}.{new_func}` instead
- `{removed_module}` — removed in favor of `{replacement}`

{Track deprecated code here so the AI never suggests or uses outdated APIs. Remove entries once all references are cleaned up.}

---

## Quick Reference

### Dataset Summary

| Dimension | Value |
|-----------|-------|
| Samples | {N (breakdown by class)} |
| Features | {N} |
| Class balance | {ratio} |
| ... | ... |

### Key Technical Decisions

1. **{Decision}**: {Rationale}
2. **{Decision}**: {Rationale}

---

## Key Findings

Top 3-5 highest-impact findings only (one line each). Full curated list — including negative/dead-end findings — in [docs/findings.md](docs/findings.md).

- **{Finding}**: {one-line summary with numbers}

---

## Experiments

{N} experiments completed. Index in [docs/experiments/INDEX.md](docs/experiments/INDEX.md) (generated). Per-experiment specs in `docs/experiments/exp_NN_*.md`. Active planning in [docs/progress.md](docs/progress.md).

---

## Conventions

### Output File Naming
- Script outputs: `{NN}_{description}.{ext}` (e.g., `21_feature_importance.pkl`) — matches `experiments/exp_NN_<slug>.py`
- Notebooks produce **no durable outputs**. Any result worth keeping is promoted to a script first.

### Model Save/Load
{Code snippet showing the save/load pattern with hyperparameters embedded in checkpoint.}

### Experiment tracking
- Tracking is optional — default `none`, set per project in `pyproject.toml [tool.maestro] tracker` (`none` | `wandb` | `mlflow`). With a tracker: metrics live there, **not** in repo CSVs, and are read back at write-up with `runs fetch --exp <N>`. With `none`: metrics live as machine-written artifacts in `data/experiments/exp_NN_*/` (`metrics.json`, `run.log`), read back from there. Either way, never hand-typed.
- Name runs `exp_NN_<slug>__<variant>__s<seed>` so each run links back to its experiment (W&B `group=exp_NN_<slug>`; MLflow `tag exp=NN`). Tag runs with `git_sha` + `exp_code_sha` + `dataset`/`dataset_version`/`dataset_sha`.
- `data/experiments/exp_NN_*/` holds durable artifacts (weights, prediction CSVs) + plots/figures — never metric tables.

---

## Terminology

### {Concept Category} (disambiguation)
- **{Term A}**: {definition + shape/type if relevant}
- **{Term B}**: {definition}
- Never say just "{ambiguous term}" without specifying which one.

### Key Metrics / Sources Table

| Source | Method | Level | Per-sample? | Output File |
|--------|--------|-------|-------------|-------------|
| ... | ... | ... | ... | ... |

---

## Pipeline Modules

| Module | Purpose |
|--------|---------|
| `data.py` | {purpose} |
| `models.py` | {purpose} |
| ... | ... |

---

## Detailed Documentation

| Doc | Contents |
|-----|----------|
| [docs/progress.md](docs/progress.md) | Active sprint planning only (≤200 lines) |
| [docs/findings.md](docs/findings.md) | Curated positive + negative findings — *our* results (the AI memory of what works and what doesn't) |
| [docs/experiments/INDEX.md](docs/experiments/INDEX.md) | Generated index of experiment records — produced by `maestro index render` |
| [docs/experiments/](docs/experiments/) | Per-experiment files. AI accesses via `maestro exp show --id=<N>` / `maestro exp list`, not by reading the dir |
| [docs/adrs/INDEX.md](docs/adrs/INDEX.md) | Generated index of ADRs — produced by `maestro index render` |
| [docs/adrs/](docs/adrs/) | Per-ADR files. AI accesses via `maestro adr show --id=<N>` / `maestro adr list` |
| [docs/data.md](docs/data.md) | Output-file catalog (script/model outputs). Dataset provenance lives in `docs/data/<name>.md` records |
| [docs/kb/](docs/kb/) | Literature, meeting notes, transcripts — external knowledge (search via `/find-kb` · `maestro kb search`; grep fallback) |
| [docs/archive/](docs/archive/) | Superseded sprints / phases — grep-able, not auto-loaded |
| [docs/setup.md](docs/setup.md) | Environment/infra setup (optional, for complex envs) |

### How the AI accesses these (the navigation surface)

CLAUDE.md should not embed *reference* content from these docs — it should tell the AI *how to fetch* what it
needs. **Rules are the exception**: a rule that must hold every session belongs inline here, or in a doc with
a load trigger (below). Core rule 12 — a rule-bearing doc named only in prose is loaded by no harness, so its
rules are dead.

- Layout & conventions: `maestro info show` (the single runtime source of truth for paths — don't hardcode them elsewhere)
- Records lookup: `maestro exp show --id=<N>` / `maestro exp list [--status=X] [--outcome=X]` (and the `adr` equivalents)
- Findings: `Read docs/findings.md`
- Knowledge base: `/find-kb` (semantic search via `maestro kb search --query="..."`), grep `docs/kb/` as fallback

### When to load (core rule 12)

Every `docs/*.md` that carries RULES needs a row here — a trigger, not just a mention. Without one it never loads.
Reference-only docs (no rules) do not belong in this table; they live in the navigation list above.

| Situation | Load |
|---|---|
| Opening an epic, pulling an option, or weighing what to work on next | `README.md` §Goals + §The route |
| {e.g. touching the release/verification path} | `docs/{doc}.md` |

---

## Project Structure

{ASCII tree of the directory layout with inline comments.}
