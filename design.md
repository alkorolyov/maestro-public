# ML/Data Science Project Organization Template

A comprehensive prompt for organizing new ML/data science projects with AI-assisted development. Covers directory structure, CLAUDE.md structure, reference documentation, experiment tracking, naming conventions, and operational patterns.

---

## Architecture & Prior Art

This template implements **structured note-taking + a thin vector index for prose** — the canonical hybrid that emerged in 2024–2025 for managing AI-assistant context on long-running technical projects. It is grounded in published practice, not bespoke.

**Pattern named**: Anthropic's [*Effective context engineering for AI agents*](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (2025) identifies three primitives for long-horizon agent work — **compaction**, **structured note-taking**, and **sub-agents**. This template is squarely the *structured note-taking* branch: the agent reads/writes durable structured records (per-exp YAML frontmatter) outside the context window via deterministic CLI tools, instead of accumulating state in the prompt.

**Influences worth borrowing from**:

| Source | What we use |
|--------|-------------|
| [Anthropic — Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Three-pillar frame; "smallest set of high-signal tokens" principle. |
| [Anthropic — long-running Claude](https://www.anthropic.com/research/long-running-Claude) | "Lab notebook" pattern; explicit logging of failed approaches as first-class entries. |
| [HumanLayer — Writing a good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md) | Keep CLAUDE.md lean (maestro's hard cap, enforced by `maestro docs check`); progressive disclosure (link, don't inline). |
| [Cursor — Project Rules](https://cursor.com/docs/context/rules) | Many small scoped files with frontmatter beat one monolith. |
| MLflow / W&B / DVC | Experiment-record schema: `id`, `status`, `tags`, `metrics`, `params`, `parent`, `consumes`, `produces`. Lineage is a free DAG when stored as frontmatter. |
| [Manus — Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) | Separate storage from presentation; scope context per call. |

**Anti-pattern we explicitly avoid**: [Cline's "Memory Bank"](https://docs.cline.bot/prompting/cline-memory-bank). 5–6 overlapping markdown files (`activeContext.md`, `progress.md`, `systemPatterns.md`, …) updated in lockstep on a single "update memory bank" command. Same drift and bloat failure modes this template was designed to escape. If a fact lives in two files, it will eventually contradict itself in two files. **One fact, one place.**

**What we deliberately do *not* adopt**:

- Agentic memory frameworks (MemGPT/Letta, mem0, Zep) — they solve "agent learns user preferences from conversation," not "researcher logs authored experiments." Wrong shape.
- Knowledge-graph databases (Graphiti, Neo4j) — overkill below ~500 experiments. With `parent:` / `supersedes:` / `consumes:` in YAML frontmatter, a Python dict already *is* the graph. Revisit if cross-project queries become routine.

---

## AI Configuration Hierarchy

Claude Code loads CLAUDE.md files at three levels, from broadest to most specific. Each level inherits from the parent and can override or extend it. `<tree>` is the folder that holds your projects:

```
~/.claude/CLAUDE.md                          # Global — applies to ALL projects
  └── <tree>/{org}/CLAUDE.md                 # Organization — shared across org projects
      └── <tree>/{org}/{project}/CLAUDE.md   # Project — project-specific context
```

### What goes where

| Level | Contents | Examples |
|-------|----------|---------|
| **Global** (`~/.claude/CLAUDE.md`) | Server/workstation setup, shell preferences, cross-project coding standards, git hygiene rules | "Headless server, use SSH tunneling for localhost ports"; "Never commit AI config files"; "Use `python -u` for unbuffered output" |
| **Organization** (`{org}/CLAUDE.md`) | Shared credentials identity, org-wide conventions, cross-project patterns | Git identity (email, username); shared package conventions; org-specific tooling |
| **Project** (`{project}/CLAUDE.md`) | Everything specific to this project: data, models, experiments, terminology, findings | Dataset dimensions; experiment table; key findings; module API; terminology |

**Rules**:
- Global and org CLAUDE.md are **never committed** — they contain environment/identity info
- Project CLAUDE.md is also **never committed** (contains AI-specific context)
- Keep each level focused — don't repeat global rules in project CLAUDE.md

### Scaffold rules: enforcement vs rationale split

The scaffold ships **two** rule files. Keeping them separate is load-bearing:

| File | Role | When loaded |
|------|------|-------------|
| `<maestro>/core.md` | **Enforcement.** Tight, declarative, hot-loaded into every project session: layout, the 12 rules, size caps, the module load table. Situational rules in `modules/`. | Every session in a project under the tree |
| `<maestro>/design.md` | **Rationale.** This file. Long-form, explains *why* each rule exists, prior art, scaling thresholds, templates. | On-demand only (when an agent or human goes looking) |

**Wire-up** (do this once per machine when adopting the scaffold):

1. Place `core.md` and `design.md` at `<maestro>/`.
2. Add the `@-import` to the tree-level `CLAUDE.md` (NOT to `~/.claude/CLAUDE.md`):

   ```markdown
   ## Maestro Rules

   @<maestro>/core.md
   ```

3. **Why scoped to the tree-level `CLAUDE.md` and not the global `~/.claude/CLAUDE.md`**: the rules only apply to projects that follow the scaffold layout (`docs/experiments/`, `docs/progress.md`, `tools/maestro_cli/`, etc.). Sessions outside the tree (system admin, dotfile work, ad-hoc scripts) don't need them and shouldn't pay the token cost.

**Why this matters**: prior to the split, the rules lived only in `design.md` — archival, never auto-loaded. Agents would silently violate them (e.g. putting forward-looking "v2 plan" sections inside a per-exp file) because no rule reached working context. The fix is structural: enforcement-grade rules must be in a hot-loaded file; rationale stays archival. When updating either, update the other in the same change to keep them in sync.

### Auto-Memory vs CLAUDE.md vs docs/

Claude Code also maintains **auto-memory** — a persistent scratchpad that survives across conversations, reported to live at `.claude/projects/*/memory/MEMORY.md` (path and auto-loading are *unverified by any maestro tooling*; nothing here reads or writes it, so don't build a rule on it). Use each layer for its intended purpose:

| Layer | What to store | When it's loaded | Who writes it |
|-------|--------------|------------------|---------------|
| **CLAUDE.md** | Stable project context: structure, conventions, findings, experiment index | Every conversation (automatic) | Human (with AI help) |
| **Auto-memory** (`MEMORY.md`) | Learned patterns, gotchas, debugging insights, user preferences discovered during work | Every conversation (automatic) | AI (during work) |
| **docs/*.md** | Detailed reference: full experiment specs, data catalogs, API docs | On-demand (AI reads when needed) | Human + AI |

**Key distinction**: CLAUDE.md is the **curated truth** — carefully maintained, concise, authoritative. Auto-memory is the **working notebook** — informal, append-heavy, may contain session-specific learnings that become stable patterns over time. Promote confirmed patterns from auto-memory to CLAUDE.md periodically.

---

## Orchestrator + local leaf workers

An earlier design treated the harness as swappable: any agent CLI (Claude Code, Codex, Qwen Code, Gemini) × any model, all interchangeable. That is retired. **Claude Code is the single orchestrating harness.** The interchangeability that actually matters already lives one layer down: model **suppliers** interchange behind the Anthropic Messages API. Cloud vendors speak it, and local Ollama (≥0.20) exposes an Anthropic-compatible `/v1/messages` endpoint — so `ANTHROPIC_BASE_URL` swaps the supplier without touching the harness. Agent-portability on top of that bought nothing but 4× the doc maintenance (four instruction files, four skill layouts) and enforcement hooks that only Claude Code's `PreToolUse`/`Stop` model can actually run — the other agents' "git pre-commit" fallback was a guaranteed no-op.

The split is by **role**, not by product:

- **Capable model orchestrates.** Design, records, verification — the work the delegation rule keeps in the main session.
- **Local model executes tight-spec coding leafs.** A one-off coding subtask with a clear contract runs free and fast on the box.

**Why qwen-code for the leaf.** A small bench (9 tasks) ran the same leaf tasks through a qwen-code harness and a Claude Code harness, both pointed at the local model: correctness parity (8/9 vs 8/9), with qwen-code ~2.7× faster wall-clock (348 s vs 926 s total). The gap is the harness, not the model — qwen-code ships a much smaller system prompt and uses the model's native tool-call format, leaving the 128k context for code instead of scaffolding. Headless qwen-code needs `--approval-mode yolo` to enable its edit tools.

> **SUPERSEDED by ADR 6.** The qwen-code leaf lane below is history: dsh is now a
> co-equal orchestrating harness running full sessions, not a delegated leaf, and per-project
> `QWEN.md` is retired. Kept for the rationale trail.

**QWEN.md is a thin brief, not a second CLAUDE.md.** The project's `QWEN.md` is ~20 lines (unverified — the file and its lane were retired by ADR 6): an `@CLAUDE.md` import (verified working in qwen-code) plus the leaf-role constraints. All project context stays in CLAUDE.md — one source of truth, no parallel copy to drift. The leaf constraints encode the concurrency corollary: **leaf workers are code-only** — they never write `docs/`, records, findings, indexes, or `CLAUDE.md` (see `rules.md` § Concurrency); the orchestrating session owns every knowledge-base write. Invoke a leaf with `global/tools/qwen_leaf.sh "<task>"`.

**Verified fallback.** When a leaf genuinely needs Claude Code semantics, point headless Claude Code at the local model instead: `ANTHROPIC_BASE_URL=http://localhost:11434 ANTHROPIC_AUTH_TOKEN=ollama ANTHROPIC_MODEL=<ollama model> CLAUDE_CODE_MAX_CONTEXT_TOKENS=<ctx>` — tested end-to-end through Ollama's Anthropic-compatible endpoint.

---

## Directory Structure

```
project-name/
├── data/
│   ├── raw/                             # IMMUTABLE source: downloaded + project-generated originals. Never edited.
│   │   └── {dataset}/v{N}/             # Each dataset its own dir; versioned if multiple releases; record in docs/data/<name>.md
│   ├── processed/                       # DERIVED: cleaned/featurized/split — regenerable from raw by a script
│   ├── experiments/                     # Per-experiment output directories
│   │   ├── exp_NN_<slug>/              # One dir per experiment (pairs with docs/experiments/exp_NN_<slug>.md)
│   │   └── ...
│   ├── models/                          # Saved model checkpoints
│   └── plots/                           # Generated figures
├── docs/                                # AI-context documentation (untracked)
│   ├── progress.md                      # Active sprint planning only (≤200 lines)
│   ├── findings.md                      # Curated key findings (positive + negative)
│   ├── experiments/                     # Experiment records (science + infra runs)
│   │   ├── INDEX.md                     # Generated by `maestro index render` — DO NOT hand-edit
│   │   └── exp_01_{slug}.md             # YAML frontmatter + body
│   ├── adrs/                            # Architecture Decision Records
│   │   ├── INDEX.md                     # Generated by `maestro index render` — DO NOT hand-edit
│   │   └── adr_01_{slug}.md             # one live ADR per area: proposed | accepted
│   ├── kb/                              # Knowledge base: literature, meetings, transcripts
│   │   ├── literature/
│   │   │   ├── INDEX.md                 # Generated by `maestro index render` — DO NOT hand-edit
│   │   │   ├── raw/                     # Automated ingestion: PDFs + abstract_md (never hand-edited)
│   │   │   └── *.md                     # Processed summaries with frontmatter (one per paper)
│   │   ├── meetings.md
│   │   └── transcripts/
│   ├── archive/                         # Superseded sprints / phases; adrs/ (folded ADRs + README number map)
│   ├── data.md                          # Output-file catalog (script/model outputs)
│   ├── data/                            # Dataset records — one per dataset (maestro dataset new)
│   │   ├── INDEX.md                     # Generated by `maestro index render` — DO NOT hand-edit
│   │   └── {name}.md                    # Provenance frontmatter (sha computed) + hand-edited description
│   ├── setup.md                         # Environment/infra setup notes (optional)
│   └── {domain}.md                      # Domain-specific docs as needed
├── tools/                               # the `maestro` CLI the AI calls via Bash (ADR 8)
│   └── maestro_cli/                     # one entry point: maestro <group> <verb> --flag=value
│       ├── cli.py                       # argument parsing + dispatch only
│       ├── experiments.py               # maestro exp   new/update/revise/show/list/lineage/finding
│       ├── adrs.py                      # maestro adr   new/update/show/list
│       ├── datasets.py                  # maestro dataset new/update/show/list/verify
│       ├── epics.py                     # maestro epic  new/update/close/show/list
│       ├── indexes.py                   # maestro index render --kind=exp|adr|dataset|epic|all
│       ├── checks.py                    # maestro docs check (Stop hook / pre-commit)
│       ├── kb.py                        # maestro kb    build/search/selftest
│       ├── hashing.py                   # content hash of a dataset dir (shared by dataset + docs check)
│       └── info.py                      # maestro info show
├── .claude/
│   └── settings.json                    # Hooks: Stop → `maestro docs check` (wired by `maestro init`)
│                                        # (the record-guard PreToolUse and kb-index-regen PostToolUse hooks are
│                                        #  GLOBAL, in ~/.claude/settings.json; skills are global too, in
│                                        #  ~/.claude/skills/ — neither is per-project)
├── logs/                                # Training framework logs (TensorBoard, CSVLogger)
├── notebooks/                           # Polished, presentable notebooks (numbered)
├── scripts/                             # Production CLIs (preprocessing, training, deployment) — tracked
├── experiments/                         # Per-experiment code — gitignored by design (local, edited in place)
│   ├── exp_NN_<slug>.py                 # DEFAULT: single file per experiment
│   └── exp_NN_<slug>/                   # EXCEPTION: subdir when multi-file is unavoidable
├── reports/                             # Deliverable artifacts (slides, decks, formatted CSVs) — tracked
├── tests/                               # Pytest test suite
│   ├── conftest.py
│   └── test_{module}.py
├── src/{package_name}/                  # Installable Python package
│   ├── __init__.py                      # Version only — no re-exports
│   ├── config.py                        # Paths, constants, hardware config
│   ├── data.py
│   ├── models.py
│   ├── training.py
│   ├── features.py
│   └── viz.py
├── environment.yml
├── pyproject.toml
└── CLAUDE.md                            # AI assistant context (untracked; keep it lean, hard cap 200 lines)
```

### Key Principles

- **`src/` is the reusable library**: Stable, importable code. Functions/classes that take args and return values, no I/O orchestration. Tracked. If a function is missing, add it here first; do not duplicate logic in `scripts/` or `experiments/`.
- **`scripts/` is the production CLI**: End-to-end runnable tools that are rerun on a schedule or by 2+ experiments — preprocessing, training entry points, deployment, retrains. Tracked. Thin wrappers that import from `src/`.
- **`experiments/` is the lab bench**: Per-experiment code that tests one hypothesis. **Gitignored by design** — one-off, often private, edited in place; it is pinned per run by `exp_code_sha` instead of by git (see "Why experiment code is pinned on the tracker, not in git"). Default: a single `experiments/exp_NN_<slug>.py`. A subdirectory is the exception, not the rule (see "Single-file experiment rule" below).
- **`reports/` is the presentation layer**: Slides, decks, formatted deliverables. Tracked. Lives outside `experiments/` because deliverables are downstream of the result, not part of the experiment itself.
- **`notebooks/` is the polish stage**: Polished, numbered notebooks. Tracked. Created after a result is validated, for narrative communication. Notebooks produce **no durable outputs** — any result worth keeping is promoted to a script first (which then writes to `data/`).
- **`tests/` validates the library**: Pytest suite with markers for slow/integration tests. Fast tests run by default.
- **`docs/` is the AI memory**: Detailed context docs that keep the AI assistant effective across sessions. Untracked. Layered for scale:
  - `docs/experiments/exp_NN_*.md` — one file per experiment (frontmatter-driven, ≤150 lines each). `INDEX.md` is **generated**, never hand-edited.
  - `docs/findings.md` — curated positive + negative findings: *what we found out* (our own results). The single place new findings get promoted.
  - `docs/kb/` — long-form prose (papers, meeting notes, transcripts): *what is known* (external knowledge we rely on). Retrieved on demand by a two-stage semantic search (`maestro kb search` — vector top-k + a corpus-calibrated confidence gate, then a grounded read; see `protocols/memory_tiers.md` → kb semantic search); never auto-loaded into CLAUDE.md.
  - The dividing line: **kb answers "what is known?" — findings answers "what did *we* find out?"** Provenance of the *claim* decides the home (not who wrote it) — a synthesis we authored is kb if its proof is a paper; our computed result is a finding. Full routing model: `protocols/memory_tiers.md` → Content routing.
  - `docs/archive/` — completed sprints / superseded plans, and `archive/adrs/`: ADRs folded into a live one or dead, with a README mapping each old number to the live ADR (core rule 13). Grep-able, not loaded.
  - Domain-specific docs (e.g. `preprocessing.md`, `evaluation.md`) sit at `docs/` root or, once they spawn siblings, get promoted to a directory (`docs/literature/` instead of `literature_a.md`, `literature_b.md`).
- **`data/raw/` is immutable source**: Downloaded datasets and project-generated originals, treated as ground truth. Never edited in place — that is what destroys reproducibility. Each dataset lives in its own `data/raw/<dataset>/` (versioned under `v<N>/`) and gets a tool-written record at `docs/data/<name>.md` (`maestro dataset new`, sha computed); no `external/` subfolder — origin is the record's `source` field, not the path. A dataset may be registered while its pull is still running (`--collecting`, `sha256: pending`); the sha is stamped at completion by `maestro dataset update --name=<name> --complete`, and until then the drift check is advisory instead of blocking.
- **`data/processed/` is derived and regenerable**: Cleaned, filtered, normalized, featurized, split, descriptors — anything built from `raw/` by a script in `scripts/` (or `src/`). It must be 100% reproducible from `raw/`; if a "processed" file cannot be regenerated, it is actually raw and needs provenance.
- **`data/experiments/` is the output sink**: Each experiment gets its own directory (`exp_NN_<slug>/`), sharing the slug with its `docs/experiments/exp_NN_<slug>.md` write-up. Versioned reruns go in `exp_NN_<slug>/vK/`.

### Data Tiers (raw → processed → experiments)

```
 data/raw/   (immutable source — never edited in place)
┌──────────────────┐
│   IMMUTABLE      │   ground truth, downloaded + original measurements
│   source         │   each dataset in data/raw/<dataset>/v<N>/, record in docs/data/<name>.md
└────────┬─────────┘
         │  build — a script in scripts/ (or src/)
         ▼
┌──────────────────┐
│     DERIVED      │   cleaned / filtered / normalized / featurized / split
│   regenerable    │   must be 100% reproducible from raw, or it's raw
└────────┬─────────┘
         │  run — one experiment consumes it
         ▼
┌──────────────────┐
│ PER-RUN OUTPUTS  │   predictions, model weights, plots/figures, run.log
│                  │   (with a tracker configured, metrics live there, NOT here —
│                  │    see Experiment tracking)
└──────────────────┘
 data/experiments/exp_NN_<slug>/
```

- **raw is immutable.** Ground truth — never edit in place, never write outputs here. Each dataset in `data/raw/<dataset>/` (versioned under `v<N>/`) with a `docs/data/<name>.md` record; origin is the record's `source` field, not the path.
- **processed is regenerable.** Built from `raw/` by a script (clean, filter, normalize, featurize, split, descriptors). If it can't be regenerated, it is raw — give it provenance, don't fake-derive it.
- **Reuse decides processed vs experiments.** Shared inputs many experiments consume → `processed/`. One-off per-run artifacts (predictions, that run's model, its `run.log`) → `experiments/`.

### Experiment output directories

One directory per experiment, named with the experiment's slug so doc and data pair up:

```
data/experiments/exp_07_gbm_baseline/
  ├── results.csv
  ├── model.pkl
  ├── run.log
  └── plots/
```

### Experiment tracking (runs vs experiments)

*Rationale for the enforcement rules in `rules.md` → "Experiment tracking".*

The split that makes the rest cohere: a maestro **experiment** is one *hypothesis* (the `exp_NN`
record); a tracker **run** is one *execution*. One experiment has **N runs** — and N is genuinely
variable:

```
N = 0   a sim / comp-chem / data-analysis exp — no training, no tracker at all
N = 1   one training run
N = many a sweep or seed grid
```

Conflating the two is the classic failure: people make every hyperparameter combo its own
"experiment" and end up with 200 experiments and no hypothesis-level view. Keeping the hypothesis
(knowledge, in `docs/`) separate from the run (compute, in the tracker) is what prevents that.

**Why tracking is optional, and off by default.** Most projects — client work, sim / comp-chem,
data analysis — never open a run, and standing up a tracker for them buys nothing. So the default is
`tracker = "none"`: a project turns tracking on deliberately, by naming a tracker once in
`pyproject.toml` `[tool.maestro] tracker = "none" | "wandb" | "mlflow"` (key absent = `none`). Which
one is a per-project judgement, not a rule: W&B fits deep-learning runs (rich media, artifacts,
sweeps), MLflow fits classical-ML runs (params/metrics tables, model registry). Both sets of creds
live in the global `~/.env`, so "which one" can't be inferred — hence the explicit switch. Everything
else is *derived*, not configured: the tracker project name is the repo dir name; the run group is
`exp_NN_<slug>`. Nothing to keep in sync, nothing to typo.

**Why metrics live in the tracker, not the repo** (when there is one). A metric CSV in
`data/experiments/` is a second copy of numbers the tracker already owns — it drifts, bloats
git-ignored space, and tempts hand-editing (which the no-hallucination rule forbids). So metrics are
logged to W&B/MLflow and **read back** at write-up via the `runs` tool. The repo keeps only durable
artifacts other work consumes (weights, prediction CSVs) and plots/figures.

**With `tracker = "none"`, the artifact *is* the store.** There is no second copy to drift from: the
experiment script writes its metrics **machine-written** into its own output dir —
`data/experiments/exp_NN_<slug>/metrics.json` plus the `run.log` — and the write-up reads that file
back. The rule that survives untouched is the one that matters: numbers reach a record by being read
out of a machine-written artifact, never by being typed from memory.

**Why the naming convention is load-bearing.** Naming runs `exp_NN_<slug>__<variant>__s<seed>` makes
the maestro exp number the join key into the tracker (W&B `group=exp_NN_<slug>`; MLflow `tag exp=NN`).
Given any run you can find its experiment; given an experiment, `runs fetch --exp N` finds its runs.
Tag each run with `git_sha` + `exp_code_sha` + the dataset triple
(`dataset`/`dataset_version`/`dataset_sha`, pointing at the `docs/data/<name>.md` record) so a run is
fully reproducible. The exp record stores only `best_run:` (the run *name* behind the headline metric)
and `n_runs:` — no URLs, which rot.

**Why provenance is a hard gate, not a soft tag.** (This gate and the code freeze below are the
*tracker's* — they run inside `start_run`, so they exist only for a project that configured one. An
untracked project still owes its exp record the same two facts by hand: the `git_sha` of the library
code that ran, and the dataset it consumed — name, version, and the sha from its
`docs/data/<name>.md` record.) The failure mode that motivated this: a
never-commit-by-default workflow paired with a tracker that stamped the bare `HEAD` sha onto every
run. Runs ended up tagged with a commit that contained *none* of their code — the `git_sha` predated
the code that produced the metrics, so the run was unreproducible while *looking* reproducible. The
first patch tagged such runs `git_sha:<sha>-dirty` and logged anyway; that is worse, because it
normalizes logging unreproducible runs. The fix is to **BLOCK**: the tracker refuses to log from a
dirty tree (forcing a commit so `git_sha` == the run's *library* code) and refuses a `dataset` with no
resolvable `sha256` (no half-provenance). A throwaway/debug run gets a narrow, loud, explicit escape
hatch (`allow_dirty` / `allow_missing_dataset_prov`) that warns and tags the compromise visibly —
the default path can never reach it.

**Why experiment code is pinned on the tracker, not in git.** Provenance has *three* legs, not one,
because a run's inputs live in three different lifecycles. The committed library (`src/`, `scripts/`)
is shared, durable, and pinned by `git_sha` — the clean-tree gate above governs it. The dataset is
pinned by `dataset_sha`. But the **experiment script** (`experiments/exp_NN_*.py`) is throwaway and
often private — a one-off hypothesis trial, edited in place, that must stay *off* the shared team git
repo (it is gitignored by design). Forcing it into git to satisfy the clean-tree gate would defeat
that; leaving it unpinned would make every run unreproducible — the original failure mode all over
again. The resolution is to pin it *per-run on the tracker* instead of in git: each recorded run logs
its script as a content-addressed W&B code Artifact (`exp_NN_<slug>__code`) plus a short `exp_code_sha`
hash on the run config + tag. The tracker dedupes by digest, so a sweep of N identical variant/seed
runs stores the code **once**, not N times, and a new artifact version appears only when the script
actually changes. This keeps experiment code reproducible without ever committing it — `git_sha` stays
the library's identity, `exp_code_sha` is the experiment's, and the (private) tracker, which
is not the team repo, is the right home for the throwaway bytes.

### Code Layout Philosophy

Code lives in three places, separated by lifecycle (not by topic). The separation is what creates pressure to promote reusable logic out of one-off scripts.

| Tier | Goes in | Test for it | Lifecycle |
|---|---|---|---|
| Library | `src/<package>/` | "Does another file `import` this?" | Long-lived, versioned, tested. |
| Production CLI | `scripts/` | "Do I run it with `python scripts/foo.py …`?" | Long-lived, rerun on schedule or by 2+ exps. |
| Experiment | `experiments/exp_NN_<slug>.py` | "Will I run this again next month?" | One-off. Closed when the exp is done. |

**Promotion heuristic**:

- A **function** imported by 2+ files → `src/<package>/`. Promote when the second use appears, not the first (avoid speculative library code).
- A **CLI / orchestrator** rerun on schedule, or used by 2+ exps → `scripts/`.
- When you find yourself **copy-pasting a `.py`** between exp dirs, that's the signal to promote — not "should I clean this up later?". Do it now.

**Single-file experiment rule**:

An experiment is a singular hypothesis trial, not a mini-project. Default to one file: `experiments/exp_NN_<slug>.py`. A multi-file subdir is a smell — usually 1 file is the experiment and the rest are:

| Smell | Where it really belongs |
|---|---|
| Featurization, model loading, metric computation | `src/<package>/` (library) |
| "Aggregate the predictions into a wide CSV" | `scripts/` or `tools/` (rerunnable post-processing) |
| Plotting helpers | `src/<package>/viz/` |
| Slide / deck / report builders | `reports/` |
| Manual deliverable formatters (one-off CSV templates) | `scripts/reporting/` or accept as one-off |

A subdirectory is permitted only when (a) the exp genuinely has multiple stages with intermediate state too coupled to split, AND (b) the rationale is documented in the exp doc's Method section. Otherwise: split out the reusable parts and keep the experiment in one file.

**Why this hurts to follow but is worth it**: promoting code on the second use feels like premature refactoring; it is not. The alternative is 5 exps each with a slightly-different `compute_metrics.py`, which is unrecoverable a year later. The single-file rule creates the friction that forces the right thing.

**Counter-pressure (when subdir is genuinely OK)**:

- Time-pressured deliverables (24h client turnaround, demo deadlines) — accept the smell, plan the cleanup as a follow-up task in `progress.md`.
- Truly multi-stage exps with tightly-coupled intermediate artifacts (rare in ML; usually pickled intermediates suffice).
- Educational / demo repos where colocation aids reading.

### Workflow

1. **Experiment**: `maestro exp new --slug=<slug>` (scaffolds `docs/experiments/exp_NN_<slug>.md` once the design is locked) → write `experiments/exp_NN_<slug>.py` (single file by default) → run, redirecting stdout to `data/experiments/exp_NN_<slug>/run_1/run.log` → record the result with `maestro exp update --id=<N> --status=... --outcome=... --takeaway="..."`. Never hand-author the record: the CLI owns the frontmatter and regenerates `INDEX.md` on every write. Status lives in the per-exp frontmatter — `progress.md` only carries active sprint planning, not the experiment table.
2. **Notebook**: Once validated, create polished notebook in `notebooks/`
3. **Report**: If the result changes understanding, append a one-liner to `docs/findings.md`. CLAUDE.md only links to `findings.md` — never list findings directly there.
4. **Archive**: When `progress.md` exceeds ~200 lines, move completed sprints to `docs/archive/progress_{YYYY-QN}.md`.

### Concurrent sessions

Maestro assumes **one session at a time** for the knowledge base (`docs/`, the `maestro`
record CLI, INDEX, `findings.md`). Parallel *code* work uses a worktree + branch per feature,
merged by git; experiments and records stay in the single integration session. Two
sessions writing the knowledge base at once race the shared git index and `exp_NN`
number allocation — so don't. (See `rules.md → Concurrency`.)

**Why worktree staging is restricted (`rules.md → Concurrency`, the `git add -A`
ban).** The shared-memory design deliberately keeps big untracked data in ONE
physical home and symlinks it into worktrees. That creates a specific git trap:
gitignore patterns written as `dir/` match directories only, so the worktree's
SYMLINK at the same path is unignored and stageable. A blanket `git add -A`
then commits the symlink; merging the branch materializes it in the primary,
and git — which treats ignored files as expendable — replaces the real data
directory with a symlink pointing at itself. This chain actually fired (a sibling
project in the same tree): a `git add -A` in a rename commit destroyed
two vendored/served data directories at merge time, with every test gate green
throughout, because test gates cannot see tracked-file-list changes. Hence the three
defenses in rules.md: dual-form gitignore entries for every symlinked path, explicit-path
staging with a status review before each commit, and a merge-diffstat scan for
shared-memory paths before any `--no-ff` into the primary.

### Python environment tooling

**`uv` is the default package + environment tool for scaffolded projects — not pip.**
A project is a `pyproject.toml` + `uv.lock` with a `.venv/` that `uv` owns; run
everything with `uv run python …`. Reach for **conda (miniforge) only when a
dependency needs system libraries a wheel cannot provide**. The choice is per-project
and is recorded in that project's `docs/setup.md`; the runtime rule for *detecting*
which to use is in `~/.claude/CLAUDE.md → Python Environments`.

| Need | Tool | Run with |
|------|------|----------|
| Pure-Python / wheel-available deps (the common case) | `uv` | `uv run …` |
| Deps needing system libs (CUDA, `gdal`, `ffmpeg`, some MPI) | conda (miniforge) | `conda run --no-capture-output -n <env> …` |

## Templates

Project skeletons (`CLAUDE.md`, `progress.md`, `pyproject`, `.gitignore`, reference
docs) live in [`templates/`](templates/) — one file each (see `templates/README.md`); copy the ones you need
when scaffolding a new project.

## v2 redesign: layered rules, single-writer default

**Why.** A usage review (unverified; no artifact in this repo) showed the
v1 rulebook was one monolithic hot-loaded file where roughly half the text governed
features that were dead in practice: the tracker/three-leg-provenance section was never
adopted by any project (zero `[tool.maestro] tracker` keys anywhere), the presentations
pipeline was used once, local leaf workers (`qwen_leaf.sh`) had zero invocations. Meanwhile
the worktree shared-memory symlink machinery caused four incidents with
frontier models driving (in one sibling project: data destroyed by a staged
symlink; broken symlinks leaving sessions ruleless; silent docs-backup failure;
standing false test failures in fresh worktrees). A design that the strongest available models violate four ways is
over-constrained; smaller local models would fare
worse. v1's full text is preserved in git history (tag the pre-v2 tip if needed).

**What changed.**
- **Layered rules.** `core.md` (≤~2,100 tokens, always loaded, harness-neutral — the same
  file serves Claude Code and any AGENTS.md/CLAUDE.md-reading harness) + `modules/`
  loaded on demand: `concurrency.md`, `writeup.md`, `provenance.md`. `rules.md` remains
  the stable import path and is now a stub importing core.
- **Trunk-based development, single writer.** Default execution model: one checkout,
  `main` + short-lived feature branches, ONE code-writing executor at a time; executors
  never touch `docs/`/`data/`. Worktrees are no longer a maestro mechanism at all —
  when 2+ truly parallel executors are needed, harness-managed worktree isolation is
  used (code-only, nothing shared, nothing to symlink). `setup-worktree.sh` and the
  post-checkout symlink git hook are deleted; `maestro init` now removes a
  previously installed v1 hook. All four v1 incident classes are structurally
  impossible in this model, not merely forbidden by prose.
- **Dead features parked, not deleted.** Tracker provenance and formal dataset records
  moved to `modules/provenance.md` (opt-in); presentations to `modules/writeup.md`;
  the qwen leaf lane is gone entirely — `qwen_leaf.sh` and `templates/QWEN.md` no longer
  exist in the repo, and ADR 6 retires per-project `QWEN.md` outright.
- **Versioning.** Core carries a `version:` line; generated copies for other harnesses
  (e.g. a dsh user-global instruction file) must stamp the source version and date.

## Kanban layer: why epics, and why not Scrum

**Why.** v2 has three record kinds — `exp` (hypothesis + run + metric), `adr` (decision),
`data` (dataset). None of them holds a body of engineering work that spans many sessions:
a port, a refactor, a conformance sweep. The gap is not theoretical — projects improvise a
replacement in the wrong file. A sibling project in the same tree grew a hand-written
task register (`### STRUCTURAL THREADS (open, each needs its own session)`) and a
ticket-numbering scheme (`#87`…`#94`,
with a `| # | Item | Status | Notes |` table) inside `progress.md`, which let that file
grow far past the 200-line cap that rule 10 sets for the *current plan only*.
A hand-rolled tracker and a hand-rolled board are exactly what a missing primitive looks
like from the outside.

**The three words, since they get used loosely.** *Agile* is the umbrella idea (2001):
small slices, deliver often, change the plan when you learn something — a philosophy, not
a procedure. *Scrum* implements it around fixed time boxes: work is committed to a
2-week **sprint**, with roles (product owner / scrum master / team), scheduled meetings
(planning, daily standup, review, retrospective) and estimation in story points, from
which velocity is derived. *Kanban* implements it around continuous flow: no time boxes,
a visible board, a limit on how much work is in progress at once (WIP), pull instead of
push, and cycle time measured rather than promised. Jira is a tool carrying both — its
issue types (epic → story → task) come from the Scrum side, its column boards from Kanban.

**What fits a session-based, one-writer project.**

| Piece | From | Fits? | Why |
|---|---|---|---|
| Sprint (fixed timebox) | Scrum | no | the unit is a *session*; it ends when the task or the context window ends, not on a calendar |
| PO / scrum master / team roles | Scrum | no | no team — the project owner decides what, one executor does it |
| Daily standup | Scrum | no | meaningless without a team |
| Story points, velocity | Scrum | no | an agent's capacity is context window plus wall clock; no decision in these projects would change from a velocity number |
| Review + retrospective | Scrum | **yes, already present** | core rule 10 + the session protocol: read `## Current` at start, rewrite it at close |
| Visible board | Kanban | yes | missing today — status is scattered across `progress.md`, several backlog docs and git history |
| WIP limit | Kanban | **yes, already present but unnamed** | "one thread per session, finish or park before starting another" *is* a WIP limit of 1 |
| Pull, not push | Kanban | yes | a session pulls the next item when the previous one closed |
| Blocked as a flag | Kanban | yes | a sibling project's structural threads are blocked work; filed as plain "open" they read as merely neglected |
| Cycle time | Kanban | later | derivable from `opened` → `done`; no decision depends on it yet |

**Decisions.** Kanban mechanics, Jira's issue names: `epic` (spans sessions) → `item`
(one defect or gap, a row in whatever doc owns it) → `task` (one session, one branch).
Jira's *story* level is dropped — a fourth level is ceremony. Status is
`todo | in_progress | done`, and **`blocked` is a flag (`blocked_by: <reason>`), never a
status** — that is how real Kanban and Jira both work, and it matters: a blocked *status*
would erase where the work actually stands. WIP limits are stated as numbers (1 task per
session, ≤2 epics `in_progress`) rather than left as prose, because an unnamed limit is
not checkable.

**What this does not solve, and must not be mistaken for solving.** A board makes status
*visible*; it does not make status *true*. One example: a
row in a sibling project's status document (`G8-16 reachable: no`) was written once as a judgment
call, never re-verified, then cited as fact. No `CLAUDE.md`
mentioned that document, so `maestro docs check` never flagged it either: rule 12's check computes
(mentioned − triggered) and is blind to an orphan. Moving cards is the kind of activity
that *feels* like progress while the claim underneath stays unexamined, so the kanban layer
ships with two companion changes: extend rule 2 from metrics to
status claims — anything gating future work carries `verified: <sha|date>` or is written
`unverified` — and make the drift checker flag docs with no load trigger at all.

## Portability: the repo names no project but itself

Maestro is meant to be cloned onto any machine by anyone, so nothing in it should
identify its author or the other projects in their tree. Incident evidence throughout
this file and the ADRs therefore refers to **sibling projects by role rather than by
name** ("a sibling project in the same tree", "a Rust project in the same tree").
Machine-specific endpoints are placeholders (`http://<tracker-host>:<port>`): a tracker's
host and credentials come from the environment, never from a file in the repo.

## Shape declaration: discipline vs template, typed evidence, dated shapes

**Why.** An audit of five sibling projects (`maestro docs check` run in each) showed the
friction is not project size:

| project (role) | discipline layer | data-tier layer | `docs check` |
|---|---|---|---|
| Python model project, 20 exps, 13 datasets | fits | fits — the native shape | 0 errors / 44 advisories, all "run dir predates the convention" |
| Rust+TS game engine, 76 ADRs, 24 epics, driven by dsh on a local model | fits | opted out by its own CLAUDE.md ("ML machinery not used") | 1 / 43, clean in practice |
| Analytics project on a lake table store (bronze/silver/gold, dbt, services) | fits | breaks | 39 / 23 — 32 errors are `consumes:` paths stranded by two layout moves |
| Pipeline project that never adopted maestro | — | — | 25 items, from one abandoned `adr_01` stub in `docs/adrs/` |

Three structural causes, none of them a project mistake:

1. **Maestro bundles two things and enforces both on everyone.** A *knowledge discipline*
   (rules 1, 2, 5, 6, 9–12: records via CLI, evidence not memory, ADRs, epics, load
   triggers, one instruction file) that fits every project above, and a *research
   template* (rules 3, 4, 7, 8: exp files, run dirs with `metrics.json`, `data/raw/vN`
   with one sha) that fits one shape. The largest adopter runs the discipline alone on a
   local model with no friction — the existence proof that the discipline is the product.
2. **The checker hard-codes one data shape, so prose and code have drifted.** core.md's
   layout block gained a lake "OR" note; `checks.py` and `datasets.py` still know only
   `data/raw/`. Rule 2's "artifact" is a file path, but a lake-backed project's evidence is a
   catalog table at a snapshot id — those citations *cannot* exist as paths. Enforcement
   in code is what lets a local model follow the rules; the cost is that every widening of
   the rules must reach the code, and today nothing makes it.
3. **Time is not a first-class notion.** Records are near-immutable; the checker compares
   today's layout against every record ever written. A long-lived project invented a
   dated "clean-start line" by hand (old records are history, cited as they are);
   the checker already half-knows it ("expected for a dir predating the convention") but
   cannot be told the date. When the most mature project hand-rolls a concept, the
   framework is missing it.

And one portfolio-scale cause: **membership is inferred** (`is_maestro_project` = a
`docs/{experiments,adrs,epics,data}` dir exists), which was safe when every project in the
tree was the same kind and is not now. core.md is always loaded on both harnesses — the
Claude Code `@`-chain from the tree-level `CLAUDE.md`, and dsh's native files (its hand-owned instruction file plus the `CLAUDE.md` chain) — so fixing one loader alone changes nothing for dsh.

```
TODAY                                        AFTER
maestro = discipline + template, one shape   <project>/maestro.toml = the one switch
   │ loaded everywhere under the tree           layers = [discipline, research]
   ▼                                            shape  = <name> since <date>
checker: "artifact = file under data/raw"          │
   ├─ files ✔   (Python model, game engine)         ▼
   ├─ tables ✘  (lake: 39 errors)            checker asks the same 3 questions,
   └─ not adopted ✘ (pipeline: policed)       resolves them through the declared shape:
                                                does the cited artifact exist?
                                                did the immutable unit change?
                                                did the run leave its proof?
                                              records older than a shape's date are
                                              checked under the shape they were written in
```

**What changes.** Configure *resolution*, never *vocabulary*: what a record must cite
(`consumes`, `source_artifacts`, a run dir) stays fixed so records look the same across
projects that look nothing alike on disk; how a citation is resolved and how identity is
computed becomes pluggable.

- **Membership is declared.** `maestro.toml` at the project root (pyproject
  `[tool.maestro]` accepted as the alias — a non-Python project has no pyproject). No file
  → no rules, no hooks, no core.md, `docs check` exits 0 with "not a maestro project".
  `guard_records`, `guard_stamps`, `guard_spawn`, `regen_kb_index` gate on it;
  `guard_live_child` and `guard_executor` stay harness-wide (git safety, not maestro).
- **core.md splits into two layers by tag, one file.** Rules 3, 4, 7, 8 carry
  `[research]`, the rest `[discipline]`; `layers = [...]` says which apply. A project on
  the discipline alone (the game engine) declares it instead of writing a paragraph.
- **Shapes are dated records, appended never edited.** A `shape` record kind
  (`maestro shape new --name=lake`), one per layout change. The checker resolves each
  record under the shape valid at the record's date — a layout move costs one dated
  record, not a cleanup of history. This subsumes the hand-rolled clean-start line.
- **Evidence is typed.** Rule 2's artifact is a file path, a gate/sha token (already
  accepted since 2.24.0), or `table:<schema>.<name>@<snapshot>`; one resolver interface in
  `checks.py`, the default resolver is today's code, one new resolver (DuckDB lookup).
  Rule 7's "raw" is whatever the shape names as the immutable tier (`data/raw/vN`, or
  bronze by `fetch_date` whose identity is the snapshot id, not a dir sha).
- **`outcome: infra` is exempt from the `metrics.json` advisory** (the outcome exists in
  `experiments.py`; the checker never learned it).
- **Loaders go per project.** The tree-level `CLAUDE.md` drops the `@maestro/rules.md`
  import; `maestro init` writes the `@core.md` import into the adopted project's
  `CLAUDE.md` and creates `maestro.toml`. dsh's hand-owned instructions stop bundling core.md
  and inject it per project when `maestro.toml` is present — mechanism
  UNVERIFIED: whether dsh's plugin hooks can inject context has to be read
  from its API; the fallback is a kernel line "root has `maestro.toml` → read core.md
  first", weaker for a local model.

**What does not change.** The twelve rules' meaning, the CLI verbs, record frontmatter,
INDEX rendering, kanban's item rules (a lake-backed project's "title lists identifiers"
advisories are a project fix: paths belong in the epic body, `kanban.md:29`), epics /
findings / progress rules, hook-based enforcement, and Claude Code / dsh parity.

**Expected effect** (from the same audit): the lake-backed project's 39 errors drop to about
5 real ones; the Python model's 44 advisories drop to 0; the game engine's clean-start
paragraph becomes a framework feature. Migration = one `maestro.toml` and one
shape record per adopted project; no existing record is rewritten.

**Three deviations in the implementation.** The shape
history lives in `maestro.toml` as `[[shape]]` entries, not in a record kind — one dated
line per layout change plus the project's ADR is the whole need. The `table:` evidence
form is validated by shape only; opening the catalog needs a project-specific attach
string and is the follow-up. And the records-dir inference of membership survives one
release, with an advisory, so no live project loses its hooks before it carries a
declaration; the loader change is opt-in (`maestro init --core-import`) for the same
reason, and the dsh bundle is untouched until dsh's plugin API has been read.

**Guard against over-engineering.** Two layers, two shapes (`tiers`, the raw/processed
default the checker polices, and `other`, any layout the project owns and the checker
does not judge — the per-layout names `lake` and `catalog` were dropped as too specific),
one new evidence type, one date — exactly what the projects use today. Each generalisation is
pulled by an existing project, never pushed; profiles for project kinds that do not exist
yet are how maestro would stop being simple.

## Harnesses are not mirrors: one method, one project file, two kernels

**Why.** v2 kept the Claude Code and dsh sides in lockstep: every guard built twice, the two
kernels saying the same things, `core.md` rule 11 carrying both harnesses' loading mechanics.
The harnesses are not the same tool. Claude Code is the high-judgment top-level session that
thinks the work through and writes the code itself, parallel through `Agent` isolation. dsh
is a router: a planner that writes no code, one local child at a time, briefs with `Files:`
and `Done:`. An earlier decision (`modules/concurrency.md`)
already broke the symmetry for two guards; a later review made it the standing shape.

```
  METHOD    maestro core.md + modules/       ONE copy, names no harness
                          │
           ┌──────────────┴───────────────┐
  KERNEL   ~/.claude/CLAUDE.md           dsh hand-owned file                    FREE TO DIFFER
           writes code, Agent isolation  router, children one at a time
           @-imports expand              flat file, no render
           guards: shared-checkout set   guards: shared-checkout set + root-code + brief
           └──────────────┬───────────────┘
  PROJECT  <repo>/CLAUDE.md              ONE file, harness-neutral, a short adoption header
```

**Decisions.**
- **Method is one copy and names no harness.** Rule 11 now says only: one harness-neutral
  `CLAUDE.md` per project, the same chain for every harness, the loading mechanics in each
  harness's kernel. `modules/` may name a harness as an example of a mechanism.
- **Kernels are free to differ and each states how IT loads the chain.** Claude Code walks up
  from cwd and expands `@`-imports; dsh reads one rendered `$DSH_HOME/AGENTS.md` and finds the
  chain from the `.dsh-root` marker. No rule requires the two kernels to say the same thing.
- **The project file stays one and harness-neutral; core is never rendered into it.**
  Considered and rejected: generating `core.md` into every project's `CLAUDE.md` at
  `maestro init`. It makes N drifting copies with a commit per core bump in every repo that
  tracks the file, breaks the 8k-token cap on day one, and needs
  marker blocks plus a guard against hand edits inside them. The two cases it would serve
  are already served: a remote executor gets its spec in the brief and never reads `docs/`
  (`modules/concurrency.md`); dsh gets core through the one user-global render. For the
  same reason `maestro init --core-import` (2.36, an `@core.md` line appended to a project
  `CLAUDE.md`) is removed, and the `rules.md` stub is gone: the tree-level `CLAUDE.md` imports
  `core.md` directly.
- **A guard exists on a side because that side's lane needs it, never to mirror the other.**
  The table is `tests/test_guard_table.py`: `GUARDS` (both, because the rule is about a
  shared checkout), `DSH_ONLY` (the router's lane), `CLAUDE_ONLY` (a machine rule for the
  Claude Code session, `gh-auth-guard`), `UNARMED` (declared per project, installed by
  nothing — `merge-evidence-guard` stays there on purpose). Adding a guard means choosing
  its row, not building a twin.
- **The rules are the same in both lanes; how hard a gate stops is not.** A trial run showed the
  mechanical record gates were too strict for the
  high-judgment session and right for the weaker executors (dsh lanes, the local-model
  harness). `MAESTRO_GATES=warn` — set in Claude Code's `settings.json` `env`, nowhere else —
  turns the record guard, the stamp guard and the pre-commit stamp and drift guards into
  warnings with the same text; the default stays `block`. It is read only by the Claude Code
  adapters and the pre-commit template, never by a CLI verb's exit code, (the dsh plugins that
  used to delete it at load were removed). The safety
  guards (live child, executor, spawn, gh-auth) and the trunk guard blocked in both modes
  until a later change; see the next section.

## Claude Code: guidance, not guards

**Why.** The decision: the Claude Code side of the harness gives guidance on how to
DOCUMENT — layout, records, progress, findings, epics — and none on how code and git work
is organised, because Claude Code is good at that on its own. The dsh local/local combo
(a local planner routing local workers in one checkout) keeps the strict lane. The shared-
checkout guards were built for that lane's incidents and
then mirrored onto Claude Code, where they fought the way it actually works: several
top-level sessions and harness worktrees run in parallel, and one project's retro found
the spawn guard and a concurrent session's records "cost more time than the code did".

```
                     core.md — both harnesses
      ┌───────────────────────────────────────────────┐
      │ how to document: layout, records via the CLI, │
      │ progress / findings / epics / ADRs, data tiers│
      │ rule 9: records reach main, numbers unique    │
      │ across branches, no symlinks — NO git workflow│
      └───────────────────────────────────────────────┘
                 │                          │
     Claude Code (guidance)          dsh (strict lane)
     git/worktrees/parallel:         modules/concurrency.md,
       the session's call            one writer per checkout
     hooks: records, stamps,         all guards: records, stamps,
       kb-index, gh-auth             live-child, executor, spawn
                                     (tree + brief), root-code
     pre-commit trunk guard: off     pre-commit trunk guard: on
       (MAESTRO_GATES=warn)            (block)
```

**Decisions.**
- **Rule 9 keeps only the knowledge-base clauses.** Records reach `main`, their numbers are
  allocated by the CLI across every local branch and worktree, nothing is symlinked into a
  worktree. Everything about branches, sequencing and executors moved to
  `modules/concurrency.md`, which the dsh kernel loads.
- **live-child, executor and spawn guards are armed nowhere now.** The dsh plugins were removed;
  the Claude Code hook files still ship and are tested (`SHIPPED_UNWIRED` in `tests/test_guard_table.py`); `init --harness` no longer
  writes the Claude Code rows and removes them where installed. Accepted cost: the
  live-child guard's catches came from shared-tree children; a Claude Code session
  now avoids that by its own judgment.
- **The pre-commit trunk guard ("only docs/ directly on main") runs in block mode only**
  (template v4). Claude Code sets `MAESTRO_GATES=warn`; dsh deletes it at load.
- **Record numbers are unique across branches and worktrees** (`gitstate.taken_elsewhere`):
  parallel sessions each see only their own tree, and two sessions once allocated the same exp number.
  This is documentation safety, so it applies to both harnesses.
- **A project may still choose the strict lane for everyone.** A dsh-focused project may keep
  "no worktrees" in its `CLAUDE.md`; that is a project rule, not maestro's.
