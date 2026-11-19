# Maestro Core (v2.0)

version: 2.0 (layered) · rationale: `design.md` · situational rules: `modules/` (see "When to load a module" below)

The only always-loaded maestro file, harness-neutral: every harness loads this same text and none is named in it. Keep it under ~2,100 tokens — additions must displace something or go to a module.

A project's own docs (its `CLAUDE.md`, README, local conventions) may add specifics on top of these rules. Where one **contradicts** a rule here, say so and follow the rule here until the conflict is resolved — never silently follow either side.

## Layout

```
project/
├── CLAUDE.md            # TOC + quick reference (token-capped, see House rules)
├── docs/
│   ├── progress.md      # current plan ONLY (max 200 lines)
│   ├── findings.md      # append-only: what WE measured (max 300 lines)
│   ├── experiments/     # exp_NN_<slug>.md records + INDEX.md (generated)
│   ├── adrs/            # one live ADR per decision area + INDEX.md (generated)
│   ├── epics/           # multi-session work: epic_NN_<slug>.md + INDEX.md (board)
│   ├── kb/              # external knowledge: papers, meetings, notes
│   ├── data/            # dataset records
│   └── archive/         # finished/dated docs (audits, old plans, old sprints)
├── data/
│   ├── raw/             # immutable source, versioned <dataset>/v<N>/
│   ├── processed/       # 100% regenerable from raw by a script
│   ├── experiments/     # exp_NN_<slug>/run_<K>/ — one dir per run
│   └── <anything else>  # OR shape `other` (maestro.toml): the project owns its layout (a lake, a
│                        #   catalog) and documents it in CLAUDE.md; data paths go unchecked
├── src/<package>/       # importable library code
├── scripts/             # reusable CLIs (rerun on schedule or by 2+ exps)
├── experiments/         # exp_NN_<slug>.py — one-off, single file, tracked in git
└── reports/             # decks, write-ups, deliverables
```

## Rules

`maestro.toml` at the project root declares membership, the rule layers and the data shape, dated (`maestro init`, `maestro shape add`). Rules tagged `[research]` hold only where the research layer is declared; the rest are the discipline every adopted project keeps. A record is checked under the shape valid at its date; one dated before the first shape is history — cited as written, never repointed.

1. **Records only via the `maestro` CLI** (`maestro exp new|update|revise|delete`, `maestro adr new|amend`, `maestro dataset new`). Never hand-write `exp_*.md`, `adr_*.md`, `docs/data/*.md` frontmatter, or `INDEX.md` (generated — edit `tools/maestro_cli/indexes.py` to change schema). Record bodies (Method, description) are hand-edited after scaffolding. Correcting a *wrong* value in a record = `exp revise` (keeps a revision trace); `exp update` only fills in new results.
2. **Never state a result from memory.** A result is anything asserted as an outcome of our work — a metric, a count, a pass/fail verdict, a conformance list, a status word like `unported`. Every one is read back from an artifact under the exp's run dir (or the tracker), never recalled. A result with no per-item artifact is not a result yet: write the list to the run dir first, then cite it. Every claim names its SCOPE and asserts nothing wider than what was checked. Missing → `NA`; unchecked → `unverified`; never an estimate. A `takeaway:` or INDEX line is an index, not data — re-read the run dir before building on it or citing it externally.
3. `[research]` **One experiment = one hypothesis = one file.** `experiments/exp_NN_<slug>.py` + its record + `data/experiments/exp_NN_<slug>/`. Don't scaffold the record until the design is locked (the slug is effectively immutable). Prefer method-anchored slugs (`batch_size_sweep`) over hypothesis-anchored ones.
4. `[research]` **Every run writes to `data/experiments/exp_NN_*/run_<K>/`** (`run_1` for the first): params + code provenance (git sha, and `dirty: true` when the tree was uncommitted) at the start, `run.log` and `metrics.json` in the same dir. Never `/tmp`, never overwrite an existing run. Re-running the same question → the next `run_<K>`; a different question → a new experiment with `parent:` set. (Run = the MLflow/W&B unit; `v<N>/` stays reserved for dataset versions, rule 7.)
5. **`findings.md` is append-only** — overturned findings move to `## Superseded findings` with a link, never deleted. Every finding cites an exp number AND the artifact path behind it, and states nothing wider than that artifact shows.
6. **kb answers "what is known", findings answers "what did WE find out".** Provenance of the claim decides the home: proof is a paper → `kb/`; proof is our run/data → `findings.md`.
7. `[research]` **NEVER edit any file under `data/raw/` — not even a typo fix.** A "fix" or update means creating a new `data/raw/<dataset>/v<N+1>/` (or a regenerable `data/processed/` output) — the old version stays byte-identical. `data/processed/` must be fully regenerable from raw by a script in `scripts/` or `src/`. One-off run outputs → `data/experiments/`; promote to `processed/` once 2+ experiments consume them. A pull still running registers as collecting (`dataset new --collecting`); its sha is stamped at completion (`dataset update --complete`), never mid-pull.
8. `[research]` **Code tiers by lifecycle**: `src/` = library, `scripts/` = reusable CLIs, `experiments/` = one-offs. All three are tracked in git — a script that produced a recorded number is evidence, not scratch. Reused by 2+ exps or rerun on schedule → must live in `src/`/`scripts/`. Copying a `.py` between exp dirs means promote it first.
9. **The knowledge base stays whole; how code and git work is organised is the harness kernel's business.** Records reach `main` (by commit or merge) with numbers the CLI allocates across every local branch and worktree; nothing is shared into a worktree by symlink — an isolated tree reads `data/` through the project's data-root variable. A harness that routes work to local executors in one shared checkout runs them one at a time, under `modules/concurrency.md` loaded from its own kernel; any other harness organises branches, worktrees and parallel agents by its own judgment.
10. **`progress.md` holds only what has no other home** — `## Current` (a sentence + a link to the active epic), `## Up next` (project options — `maestro option`), `## Loose ends`, `## Open questions`. Anything with a body (goal, items, history) is an `epic` instead — vocabulary is epic / item / task only, no synonyms (`modules/kanban.md`) — and work performed inside ANOTHER repo belongs to that repo, not here (ADR 11). Epic status is `review | todo | active | done`: a session runs `todo` and `active` epics to the end and never starts a `review` one (only a human moves `review` to `todo`); it sets `active` + `--runner` when it starts and back to `todo` when it stops unfinished — `active` means a session is on it NOW, a paused one is not (`modules/kanban.md`). Experiment status and metric values live in records only — never copied into progress.md or CLAUDE.md; link the record instead. Dated one-off docs (audits, finished plans) go to `docs/archive/` from birth, not flat into `docs/`.

11. **One instruction file per project: `CLAUDE.md`** (ADR 6), harness-neutral: it holds project facts and project rules, never how a harness loads, spawns or guards. Every harness reads the chain: tree-level `CLAUDE.md` → `<org>/CLAUDE.md` → `<repo>/CLAUDE.md`; HOW it finds the chain is its own kernel's business (`~/.claude/CLAUDE.md`, dsh's own file). The rules are never copied into a project file — a project carries a short adoption header and `maestro info show` (`design.md → Harnesses are not mirrors`).
12. **Moving detail out of `CLAUDE.md` requires a load trigger.** Any `docs/*.md` that holds RULES must earn a row in a "when to load" table inside `CLAUDE.md` — the shape this file uses for `modules/` below. A doc named only in prose is loaded by no harness: its rules are dead. `maestro docs check` flags them.
13. **One live ADR per decision area, holding only today's rules.** A change amends the owning ADR in place (`maestro adr amend`: Decision rewritten, a dated entry on its single final `History:` line naming folded numbers and the git sha of the prior text); a new ADR only when no ADR owns the area. A folded or dead ADR moves to `docs/archive/adrs/` with a row in that README's number map — never `superseded` in place. A change to a backend, library or schema that recorded results depend on is decided there before the work.

House rules: no AI traces in committed code, comments, or commit messages. Never cite an epic, exp, ADR or item by number alone: add a one-two word name ("epic 11 (prediction)", "exp 149 (indicators)"). Size caps — `CLAUDE.md` **~8,000 tokens** (≈32 KB; tokens, not lines — rationale in `design.md`), `progress.md` 200 lines, `findings.md` 300, exp record 150; when over, archive or split — and a split is only legal under rule 12.

## When to load a module

| Situation | Load |
|---|---|
| Work spanning many sessions: opening/updating/closing an `epic` | `modules/kanban.md` |
| Routing code to executors that share one checkout (the strict lane) | `modules/concurrency.md` |
| Drafting external content: report, paper, slides, Confluence | `modules/writeup.md` |
| Project uses a run tracker (W&B/MLflow) or formal dataset provenance | `modules/provenance.md` |
| Running Python (uv/conda invocation, long jobs) | `modules/python_env.md` |
| Repo wiring: git identity, credentials, remotes | `modules/repo_setup.md` |
| Writing/refactoring durable code (`src/`, `scripts/`) | `modules/code.md` |
| Two or more data pipelines, or a raw pull / processed build rerun on a schedule: DVC stage graph and dataset versioning | `modules/pipelines.md` |

## Tools

One command, `maestro <group> <verb> --flag=value` (ADR 8): `exp`/`adr`/`dataset`/`epic` (records; `epic option` is the intake above the commitment point, `epic item --status=done` requires `--evidence`, `epic close` requires every `done_when` clause answered), `index render` (INDEX), `shape add|show` (the dated data shape in `maestro.toml`), `docs check` (docs↔data consistency), `kb search` (semantic search; grep is a fine fallback), `runs fetch --exp=N` (a tracked run's metrics, read back not retyped — rule 2), `info show` (layout). Full protocols on demand in `protocols/`: `record_writeup`, `write_up`, `memory_tiers`, `literature_search`.
