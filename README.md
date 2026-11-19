# maestro

> **This repo is the framework only** — instructions, templates, the `maestro` CLI and
> its unit/smoke tests. It is deliberately NOT a maestro-adopted project: no records,
> no experiments, no epics here, so nothing an adopting agent could confuse with
> template content. Framework decisions are recorded in this repo's git history.

Reusable protocols, tools, and skills for AI-assisted research and ML projects. v2 is **harness-neutral**: `CLAUDE.md` is the only instruction file, read natively by Claude Code and by any harness that loads CLAUDE.md/AGENTS.md-style instructions (e.g. dsh); model suppliers swap behind the endpoint (cloud vendors or local Ollama).

Clone once per machine. Reference protocols by path. Copy local tools per project.

---

## Harness model

One instruction file, one execution model. Every session — Claude Code with a cloud model, or dsh with a local model — reads the same `CLAUDE.md` chain and follows `core.md` (12 rules, always loaded) plus on-demand `modules/`. **Claude Code and dsh are co-equal orchestrating harnesses** and both read the name `CLAUDE.md` natively, so that is the only per-project instruction file; `AGENTS.md` and `QWEN.md` are retired, the sole exception being `$DSH_HOME/AGENTS.md`, whose name dsh hard-codes (ADR 6). How code and git work is organised belongs to each harness: Claude Code organises its own (worktrees, parallel agents), while a dsh lane runs strictly — one checkout, one code-writing executor at a time (`modules/concurrency.md`).

```
 ┌───────────────────────────────────────────────┐
 │  ANY HARNESS  (Claude Code · dsh · headless)  │
 │  reads CLAUDE.md → core.md (+ modules/)       │
 │  records via the maestro CLI · one KB writer  │
 └──────────────────────┬────────────────────────┘
                        │ optional executor subagent
                        ▼
 ┌───────────────────────────────────────────────┐
 │  EXECUTOR — same checkout, feature branch      │
 │  code-only (no docs/, no data/, no records)    │
 └───────────────────────────────────────────────┘
```

**Local models.** Point the harness at Ollama (`ANTHROPIC_BASE_URL=http://localhost:11434` for headless Claude Code, or, for dsh, a route in its own config) — same rules, same tools. v1's dedicated qwen-code leaf-worker lane (`qwen_leaf.sh` + per-project `QWEN.md` briefs) was retired in v2: zero usage in practice (unverified), and a local model works better as the single session than as a delegated leaf (history: ADR 1, exp 1). **Caveat for dsh:** it expands no `@`-imports, so anything it must read has to be self-contained — share by symlink or generation, never by reference (ADR 6).

---

## How it works (at a glance)

**One sentence:** load little → do the work → write results *only* through `maestro` (which auto-rebuilds the index) → `maestro docs check` guards consistency → always treat a stored summary as a pointer to the real data, never as truth.

### The session loop (the spine)

```
┌──────────────────────────────────────────────────────────────┐
│  SESSION START — load only what's needed (see tiers below)     │
│   WORKING:  CLAUDE.md · progress.md                            │
│   RECALL :  experiments/INDEX · adrs/INDEX · findings.md · kb/literature/INDEX       │
└───────────────┬───────────────────────────────────────────────┘
                ▼
        ┌────────────────┐   need a detail / verify a number?
        │  DO THE WORK    │ ─────────────────────────────────┐
        │  code · run ·   │                                   ▼
        │  experiment     │                   ARCHIVAL (load on demand only)
        └───────┬─────────┘                   exp_NN.md · kb/ · data/experiments/
                │                                          │
        got a   │   ◄────── READ-TIME DEFENSE ─────────────┘
        result? │          re-read the data dir BEFORE
                ▼          trusting any takeaway
   ┌────────────────────────────────────┐
   │  WRITE via  maestro <group> <verb> │  ← NEVER hand-edit exp_*.md / adr_*.md
   │    exp  new · update · revise · delete │
   │         finding                    │
   │    adr  new · update               │
   └───────┬────────────────────────────┘
           │ (auto, every write)
           ▼
   maestro index render ──► INDEX.md rebuilt
           │
           ▼
   maestro docs check  (pre-commit --staged, or by hand) ──► stale INDEX? broken links?
                                                          size caps? missing provenance?  ──► FIX
```

### Where does a new claim go? (content routing)

```
                         a new claim / note
                                │
                   is it OURS or EXTERNAL?
              ┌─────────────────┴──────────────────┐
          EXTERNAL                                 OURS
     (proof = paper / spec / report)     (proof = our data / run / decision)
              │                                     │
        verified?                ┌─────────┬────────┼─────────┬──────────┐
       ┌──────┴──────┐         result   decision  activity  detailed-evidence
     yes            no           │         │         │            │
      │              │       findings.md  adrs/   progress.md  experiments/
   docs/kb/      kb/meetings  "what we    "what    "what we're  exp_NN.md
  "what is       (a lead,      found       we        doing       + data/exp/
   known"        until         out"       decided"  now/next"
                 reproduced)

  TIEBREAKER: who typed it doesn't matter — the PROOF decides.
  A synthesis we wrote whose proof is a paper = kb (not a "finding").
```

### Memory tiers (why it stays cheap & accurate)

```
 WORKING   ████  always in context       CLAUDE.md · progress.md
 RECALL    ██    load at session start   INDEX(exp) · INDEX(adr) · findings.md · INDEX(kb)
 ARCHIVAL  ░     load only when a        exp_NN.md · kb/literature · data/exp/
                 recall pointer says so
```

### The one guarantee that stops rot

```
  takeaway in INDEX ──is only an INDEX──► data/experiments/exp_NN/  = THE TRUTH
         │                                            ▲
         └─ before you cite it / build on it /  ──────┘
            call it "already refuted":  RE-READ the data dir first
```

### What the agent reaches for

You prompt the agent in plain language; the agent reads the prompt and picks the matching
tool or skill:

```
  WRITE      maestro exp / maestro adr    → records, written ONLY via the CLI
                                            (a PreToolUse hook blocks hand-edits;
                                             methodology: protocols/record_writeup.md)
  READ       maestro exp list / exp show  → query the experiment + ADR indexes
             maestro kb search            → semantic kb search (read the hit)
             grep docs/kb/                → kb fallback / exact-token search
  VERIFY     maestro runs fetch --exp=N   → read an experiment's real logged metrics
                                            back out of W&B / MLflow
```

Everything is written and read through `maestro`. **This repo ships no skills.** The ones
that were generic — fetching papers and generating images — moved to their own repo
(`agent-skills`), because they never read a maestro tree. The rest were retired: each was
prose wrapping a CLI verb that already existed, and `log-exp` was a third copy of a
procedure already carried by `protocols/record_writeup.md` and enforced by
`maestro exp update --flags`. A wrapper that restates its tool is a second place to
update and a second place to go stale.

---

## What's included

| Path | Type | Purpose |
|------|------|---------|
| `protocols/literature_search.md` | Protocol | Phase-by-phase literature search, fetch, and KB entry writing |
| `protocols/write_up.md` | Protocol | Drafting external content from KB without fabrication/drift |
| `protocols/memory_tiers.md` | Protocol | What to load when (working / recall / archival) + content routing |
| `tools/maestro_cli/` | Local tool | The `maestro` command (ADR 8) — one entry point, `maestro <group> <verb> --flag=value`, one module per record kind |
| `maestro exp` / `adr` / `dataset` / `epic` | Local tool | Record management — `new`/`update`/`show`/`list` (+ `exp revise`/`delete`/`lineage`/`finding`, `epic done-when`/`close`) |
| `maestro option` | Local tool | Project options — candidate work belonging to no epic yet, parked with a date in `progress.md` `## Up next` |
| `maestro index render --kind=all` | Local tool | Regenerate `docs/{experiments,adrs,epics}/INDEX.md` + `docs/data/INDEX.md` + `docs/kb/literature/INDEX.md` from frontmatter |
| `maestro docs check` | Local tool | Drift detector for docs/ consistency (wired as the project's `Stop` hook by `maestro init`) |
| `maestro docs stamp --check` | Local tool | Verifies every record against its stamp — run by the post-tool guard and by the pre-commit hook `maestro init` installs |
| `maestro kb build` / `search` / `selftest` | Local tool | Semantic search over `docs/kb/literature/` (fastembed/bge-small); corpus-calibrated relevance gate |
| `maestro dataset verify` | Local tool | Recompute every dataset's content hash and report drift |
| `maestro runs fetch` / `url` | Local tool | Read back an experiment's tracked runs (W&B / MLflow) — real metrics for write-up |
| `src/maestro/tracking.py` | Package | `start_run` / `log_metrics` — W&B run logging with three-leg provenance (git sha, exp code artifact, dataset sha) |
| `global/hooks/guard_records.py` | Global hook | PreToolUse guard — blocks hand-editing `exp_*.md`/`adr_*.md`/`INDEX.md`, points at `maestro` |
| `global/hooks/regen_kb_index.py` | Global hook | PostToolUse — regenerates the project's indexes after a kb literature edit |
| `protocols/record_writeup.md` | Protocol | Experiment + ADR write-up methodology (flags, sceptical pass, provenance) |
| `templates/CLAUDE.md` | Instruction-file template | Per-project starter `CLAUDE.md` |
| `templates/pre-commit` | Git hook | The commit-time guard `maestro init` installs as `.git/hooks/pre-commit`: the record stamp on every branch, and rule 9's "only `docs/` is committed directly on `main`" |
| `templates/` (doc skeletons) | Template | `exp_NN.md`, `progress.md`, `findings.md`, `data.md`, `setup.md`, etc. — stamped at project setup |
| `design.md` | Reference | Full design rationale, template structures, architecture decisions |

The protocols, tools, and skills are plain markdown + Python — the harness is Claude Code, wired in through `CLAUDE.md`, its skills in `~/.claude/skills/`, and its hooks in `settings.json` (see Install).

---

## Install (once per machine)

```bash
git clone <repo-url> <maestro>
bash <maestro>/install.sh
```

The CLI is **machine-level** (ADR 10): `install.sh` is a thin bootstrap that runs `uv tool install --force .` (or `pipx install --force .`) to put `maestro` in its own isolated environment with its own Python, then hands off to `maestro init --harness`. **One rolling version serves every project on the machine** — nothing is copied into a project, so a project needs no Python environment of its own to use the records.

```
  bash install.sh
    ├─ uv tool install --force .      → the `maestro` command, machine-wide
    └─ maestro init --harness
         └─ record-guard PreToolUse + kb-index-regen PostToolUse hooks
                                       → ~/.claude/settings.json
```

`maestro init --harness` wires the two global hooks into `~/.claude/settings.json`. It installs no skills — this repo has none. Add `--dry-run` to see every file and hook it would touch and write nothing. To adopt a specific project, run `maestro init` inside it (see *Use in a new project* below).

> **`uv` (or `pipx`) is a hard prerequisite**, not a soft one — the old script degraded to printing instructions, the new one exits 1. Where `maestro` is not yet on `PATH` after the install, `install.sh` says so and prints the `maestro init --harness` line to run once `uv tool update-shell` has fixed the path.

### What a fresh machine needs

> **Packages yes, services no.** Pulling pip/uv packages (and at most one optional system binary, `pdftotext`) is fine to do unprompted — that is all maestro setup ever needs. **Standing up a service is not.** No maestro tool requires Docker, a daemon, a database, or a background server, so if a workflow starts to look like it needs one — a Docker container running a browser-impersonation stack to get past a publisher bot wall, a local vector database, a self-hosted tracking server — **stop and ask the machine's owner first**. Never as part of setup, and never as a silent fallback when a fetch fails.

Maestro installs no Python packages globally. Two prerequisites, then every tool below resolves its own deps:

| Prerequisite | Why |
|---|---|
| **`uv`** on PATH ([install](https://docs.astral.sh/uv/)) | Every global tool is invoked through `uv run --with <dep>` from inside its skill, so its deps are fetched per call instead of being installed on the machine. |
| **`pdftotext`** (`apt install poppler-utils`) — optional | the fetch-paper skill's plain-text sidecar (now in the agent-skills repo). Without it the PDF is still saved; only `.txt` extraction is skipped. |

Where each dependency comes from:

| Tool | Deps | How they arrive |
|---|---|---|
| `tools/maestro_cli/` (the `maestro` command) | **PyYAML** | Comes with the tool: `uv tool install` builds the isolated environment from this repo's `pyproject.toml`, which declares `pyyaml`. Nothing to add per project. |
| `maestro kb ...` | `fastembed`, `numpy` | Pulled per call: `uv run --no-project --with fastembed --with numpy python -m maestro_cli.cli kb ...` (with `PYTHONPATH=tools`). Skip it and `maestro kb search` is unavailable; grep is the fallback and needs nothing. |
| `maestro runs fetch` | `wandb` **or** `mlflow` (whichever `[tool.maestro] tracker` names; nothing if it names `none`) | Pulled per call: the verb re-execs itself under `uv run --no-project --with <tracker>`; you never pass `--with`. |
| `src/maestro/tracking.py` | `wandb`, `numpy` | A separate artefact from the CLI: an ordinary **project** dependency, added only in projects that log runs — `uv add --editable <maestro>`. |
| `global/hooks/*.py` | stdlib only | Nothing to install. |


## Use in a new project

**1. Adopt the project** (the CLI is already installed machine-wide, and so are the skills — see *Install* above):
```bash
cd <project-path> && maestro init                    # or: maestro init --path=<project-path>
cd <project-path> && maestro init --tracker=none     # ...and pick the experiment tracker
maestro init --dry-run                               # first, to read every change before it happens
```
`maestro init` does seven things, and nothing else:
```
  0  write the declaration     maestro.toml: rule layers (--layers=discipline[,research])
                                and the data shape (--shape=tiers|other) dated today;
                                written once, never rewritten — a later layout change
                                is `maestro shape add --name=<shape> --since=<date>`
  1  scaffold the layout        docs/{experiments,adrs,epics,data,kb,archive}/
                                data/{raw,processed,experiments}/  + the starter
                                CLAUDE.md, docs/progress.md, docs/findings.md
  2  remove retired hook rows   <project>/.claude/settings.json: the `maestro docs check`
                                Stop hook (retired 2.38.0 — it blocked every turn-end)
                                and `guard_root_code.py`; the file goes when nothing is left
  3  git excludes               docs/ · CLAUDE.md · .claude/ · data/presentations/
                                  → .git/info/exclude (never .gitignore)
  4  install the commit guard   templates/pre-commit → .git/hooks/pre-commit:
                                  `maestro docs stamp --check` on every branch, and
                                  only docs/ committed directly on main (rule 9).
                                  A hook the project already wrote is never
                                  overwritten; core.hooksPath is reported, not
                                  written into
  5  set the tracker            pyproject.toml [tool.maestro] tracker = the
                                  --tracker= value, else "none" when the key is
                                  absent; an existing value is never overwritten
                                  without the flag (see Experiment tracking below)
  6  migrate off the copies     deletes tools/{rec,render_index,check_drift,index_kb,
                                dataset_hash}.py and tools/maestro_cli/ left by the
                                pre-ADR-10 install model, reporting each removal
```
It is idempotent — a second run reports `no changes`. An existing file is kept unless you pass `--force`, and a `settings.json` that is not valid JSON is left untouched, with the hook printed for you to add by hand.
> Record write-up methodology lives in `protocols/record_writeup.md`, enforced at write time by the record-guard `PreToolUse` hook (`global/hooks/guard_records.py`). There are no per-project skill wrappers.

> `maestro kb` (semantic search) needs `fastembed` + `numpy` — no project install required if you call it as `PYTHONPATH=tools uv run --no-project --with fastembed --with numpy python -m maestro_cli.cli kb ...` Without them, grep is the fallback, which is the better tool anyway until a project's kb passes ~50 entries.

**2. Edit the `CLAUDE.md`** that step 1 placed in the project root (it is a skeleton, not a finished file). The other optional templates — `data.md`, `setup.md`, `kb_meetings.md`, `gitignore`, the `[tool.maestro]` `pyproject.toml` snippet — are copied by hand from `<maestro>/templates/` when the project needs them.

**3. Reference protocols in `CLAUDE.md`:**
```markdown
**Literature search**: follow `<maestro>/protocols/literature_search.md`
```

**4. Wire maestro's rules in** — once per machine, by adding an import to the tree-level `CLAUDE.md` (`<tree>/CLAUDE.md`: the file in the folder that holds your projects). Never per project: a project `CLAUDE.md` is harness-neutral and carries only a short adoption header (core rule 11, `design.md → Harnesses are not mirrors`):
```markdown
## Maestro Rules

@<maestro>/core.md
```
> Claude Code expands the `@`-import verbatim. Harnesses without `@`-import support (e.g. dsh) instead get a generated user-global instruction file stamped with the maestro core version — one source, one generated copy.
>
> For dsh there is no generation: it reads its own hand-owned instruction file, then every `CLAUDE.md` from the projects folder down. dsh runs with no maestro guard plugins (removed; history keeps them), so the record, stamp and gate rules are not enforced there.

**5. Add project-specific relevance topics** to `CLAUDE.md` under `## Knowledge Base` — the literature search protocol uses this to score paper candidates.

---

## Experiment tracking (optional)

Tracking is **optional and off by default** (`tracker = "none"`) — fine to skip for client work and for sim / comp-chem / data-analysis projects that have no runs. Without a tracker, an experiment's metrics stay **machine-written artifacts** in `data/experiments/exp_NN_*/` (`metrics.json`, `run.log`) and the write-up reads them back from there. Turn it on and maestro keeps **metrics in your tracker (W&B or MLflow), never in repo CSVs** — read back at write-up time. Either way, records never carry hand-typed numbers.

**Bring your own tracker.** Maestro ships no endpoint and no account: whichever tracker a project names, its host and credentials come from the **environment**, never from a file in the repo. Point the standard variables at your own server (self-hosted or vendor-hosted) — e.g. `MLFLOW_TRACKING_URI=http://<tracker-host>:5000`, or `WANDB_BASE_URL=http://<tracker-host>:<port>` plus `WANDB_API_KEY`. The convention is to keep them in `~/.env`, outside every repo, so no URL or key is ever committed.

To turn tracking on for a project:

**1. Choose the tracker at setup time** — `maestro init` writes the per-project switch for you:
```bash
maestro init --tracker=wandb      # "none" (default) | "wandb" | "mlflow"
```
That sets, in the project's `pyproject.toml`:
```toml
[tool.maestro]
tracker = "wandb"   # "none" (default) | "wandb" | "mlflow"
```
With no `--tracker` flag, an existing value is left alone and `none` is written when the key is absent — so tracking stays off until someone opts in. Re-run `maestro init --tracker=<other>` to change it later; the flag only ever touches that one key.

Neither tracker is mandated — pick per project: **W&B** fits deep-learning runs, **MLflow** fits classical-ML runs. Everything else is derived — the tracker project name is the repo dir name; runs join back to their experiment via `tag exp=NN` (MLflow) / `group=exp_NN_<slug>` (W&B).

**2. Name runs** `exp_NN_<slug>__<variant>__s<seed>` so each run points back to its experiment; tag with `git_sha`, `exp_code_sha`, `dataset`, `dataset_version`, `dataset_sha`.

**3. Read metrics back** at write-up time with `maestro runs`. It reads `[tool.maestro] tracker` and re-execs itself under `uv run --with <tracker>`, so the client is fetched per call and you **never pass `--with`**:
```bash
maestro runs fetch --exp=<N> [--metric=<key>] [--json]
maestro runs url --exp=<N>          # the group's tracker URL; no API call
```
It returns the experiment's runs + metrics, so you write **real** numbers into the record via `maestro exp update --id=<N> --best-run=… --metric=…` — never hand-typed (the no-hallucination rule).

The *how/when* lives once in `core.md` (shared, hot-loaded) — you don't copy it per project; you only set the pyproject switch above.

---

## Update

```bash
cd <maestro> && git pull
bash <maestro>/install.sh   # re-install the CLI + refresh the global hooks
maestro init --harness --force                # only if the skills changed
```

The CLI itself needs no per-project update: **one rolling version** serves every project, so a project picks up the new one the moment the machine does. That cuts both ways — a check added today can fail a session in an unrelated project the moment that project is re-adopted, which is what ADR 9's staged enforcement absorbs. Projects still carrying pre-ADR-10 tool copies keep working on them until someone runs `maestro init` there, which deletes them.

---

## Contributing back

Protocols improve through real failures across projects. When a new rule is added to any project's protocol copy, update the canonical file here and commit.

See [design.md](design.md) for full architecture rationale, document templates, and scaling guidance.
