# Record write-up protocol (experiments + ADRs)

How to create and update experiment / ADR records with the `maestro` CLI. Records are written
through that CLI directly; this protocol is the methodology behind it. `core.md`
links here; `maestro info show` points at it.

> **Not this one?** For drafting *outward-facing* content (reports, decks, Confluence, paper sections) **from** the KB, see `protocols/write_up.md`. This file is about **writing into** the KB; that file is about drafting **out of** it.

**The CLI is the only writer.** `exp_*.md`, `adr_*.md`, and the `INDEX.md` files are
owned by the `maestro` CLI — never hand-edit them with Write/Edit (a PreToolUse hook blocks it,
see `global/hooks/guard_records.py`). The CLI regenerates the INDEX on every write.

---

## Experiments

### 0. Check for overlap before scaffolding new

Read `docs/experiments/INDEX.md` — every section, but especially **Refuted Hypotheses**
and **Open / Inconclusive**. Confirm the proposed work does not duplicate or directly
re-test a refuted hypothesis. If it overlaps, surface that to the human before scaffolding
and ask whether to proceed (new conditions, different benchmark, lineage child) or abandon.
In the new exp's Goal section note one of: "Similar to exp_NN — extends/varies in <way>" /
"No overlap with prior work" / "Re-test of refuted exp_NN under <new condition>".

> Why this matters: the exp KB is agent-maintained state the human rarely reads directly.
> A duplicate experiment costs days of compute; a 30-second INDEX read is trivial. Always
> pay the read cost. (Defer `maestro exp new` until design is locked — see `core.md` rule 3.)

### 1. Scaffold

```
maestro exp new --slug="<slug>"
```

Then fill in Goal, Method, and initial notes in the created file body (the body is free
text — only the frontmatter is CLI-owned, so editing the prose under the frontmatter is
fine; the guard only blocks Write/Edit on the whole record file, so make body edits via
`maestro exp set_body --id=<N> --from-file=<path>` too, or keep them in the initial scaffold).

### 2. Sceptical second pass — MANDATORY before writing any takeaway

Pure introspective self-critique is empirically weak
([survey on LLM self-correction](https://www.researchgate.net/publication/385650033));
what works is **tool-grounded critique** ([CRITIC, ICLR](https://openreview.net/forum?id=Sx038qxjek)).
For each completed experiment:

a. **Re-read source artifacts** in `data/experiments/exp_NN_*/` (logs, output CSVs,
   checkpoints). Quote at least one verbatim number from a specific file. Do not
   paraphrase from memory of the run.

b. **Determine deterministic flags** — objective rules, NOT a subjective confidence rating
   (verbalized confidence is consistently overconfident —
   [UQ Survey 2503.15850](https://arxiv.org/html/2503.15850)):

   | Flag | Set when |
   |------|----------|
   | `single_seed` | Only one seed was run (auto-set if `n_seeds=1`) |
   | `large_unexpected_gain` | Result beats current INDEX `Best by Track` by more than 3× the prior `metric_sd`, and the magnitude wasn't predicted in the Goal |
   | `conflicts_prior` | Outcome contradicts an existing Refuted entry, or a new refuted contradicts an existing Best-by-Track entry |
   | `setup_unverified` | A setup element (data split, label assignment, env reproducibility) was not independently verified after the run |
   | `interpretation_uncertain` | Multiple plausible interpretations remain after artifact re-read |

c. **Generate the strongest alternative interpretation.** Ask: *"What's the most likely
   reading of these artifacts other than the one I'm about to write?"* If credible, document
   it in `## Caveats` AND add `interpretation_uncertain` to flags.

d. **List source artifacts.** Every quantitative claim in the takeaway must trace to a path
   in `--source-artifacts` (FAIR R1.2 provenance —
   [Wilkinson et al. 2016](https://www.nature.com/articles/sdata201618)). Inline the source
   for the headline number, e.g.
   `takeaway: "ESM2 auc=0.940±0.011 across 5 seeds (data/experiments/exp_03/seeds_summary.csv)"`.

### 3. Write the update

```
maestro exp update --id=<N> --status=<done|failed> --outcome=<...> --takeaway="<...>"
    [--track=<...>] [--benchmark=<...>]
    [--metric="auc=0.84±0.02"]                       # ±SD recommended (variance info)
    [--n-seeds=N]                                    # auto-flags single_seed if 1
    [--source-artifacts="path,path"]                 # FAIR R1.2 — mandatory if takeaway has numbers
    [--consumes="path,path"] [--produces="path,path"] # data lineage edges (inputs read / outputs written)
    [--flags="single_seed,large_unexpected_gain,..."]
    [--parent=N] [--related="N,M,..."]
    [--best-run="exp_NN_<slug>__<variant>__s<seed>"]  # tracker pointer (NAME, not URL)
    [--dois="..."] [--adr=N] [--tags="a,b"]
```

Field guidance:
- `--benchmark`: pass whenever the evaluation setup (dataset version, split, ground-truth
  source) differs from earlier runs on the same track.
- `--metric`: prefer `key=val±sd`. Plain `key=val` works but loses variance.
- `--n-seeds`: integer seed count aggregated into the metric. `1` auto-adds `single_seed`.
- `--source-artifacts`: comma-separated paths the takeaway depends on. When you later find a
  wrong artifact, grep this field across all experiments to find every dependent claim.
- `--parent` vs `--related`: parent = direct lineage child; related = cross-cutting link.
- `--consumes` / `--produces`: data-flow lineage — inputs the exp reads (`data/raw` or `data/processed`)
  and outputs it writes (`data/experiments/...`). Surfaced by `maestro exp lineage --id=<N>`.

### 3b. Results that are not numbers (ADR 9)

Rule 2 covers every result, not only metrics. A conformance pass, an audit, a
reachability sweep, a port-status review — each produces a **list**, and the list is the
result. Prose is a summary of it.

Write the per-item file into the run dir BEFORE writing the takeaway:

```
data/experiments/exp_NN_<slug>/run_K/conformance.csv     (or audit.csv, coverage.csv)

item_id, verdict, ours,  theirs, source_ref,              checked_at
OP_07,   match,   1.25,  1.25,   spec/opcodes.md:412,     2026-08-24
OP_19,   differ,  1.00,  0.75,   spec/opcodes.md:588,     2026-08-24
```

- `verdict` is a closed vocabulary the grader can count: `match | differ | missing | unchecked`.
- `source_ref` points INTO the external oracle — file and line, not a description — and the
  run's `params.json` records which version of that oracle was read.
- `unchecked` rows are written explicitly. An item absent from the file is an item nobody
  looked at, and that is not the same as a pass.

Then the takeaway cites the file and states its scope:

```
✗  "the parser is conformant to the reference implementation"
✓  "41 of the reference spec's 41 opcodes checked; 38 match on value, 3 differ (OP_19, OP_22,
    OP_31) — run_1/conformance.csv, source at v1.0.3.279. Opcodes outside
    the core table were NOT checked."
```

The last sentence is the load-bearing one. Saying what was **not** checked is what stops
the next session inheriting a wider claim than the evidence. Pass the file in
`--source-artifacts`; a takeaway carrying a verdict or a count with no artifact behind it
is a drift-checker failure.

### 4. Corrections — never silent-edit a takeaway

```
maestro exp revise --id=<N> --reason="<why the original was wrong>" --new-takeaway="<corrected>"
```

This appends to a `revisions:` log (FAIR-style errata,
[ELN ten simple rules](https://pmc.ncbi.nlm.nih.gov/articles/PMC11189195/)). The original
takeaway stays visible so future sessions can see how the error happened — which prevents
the same failure mode recurring. Memory-poisoning literature
([MemoryGraft 2512.16962](https://arxiv.org/html/2512.16962v1)) frames provenance as the
core defense: agents that treat memories as ground truth without provenance propagate errors
at ~87%/4hr in adversarial settings; the same dynamic compounds honest mistakes.

### 5. Promote to a finding (optional)

```
maestro exp finding --id=<N> --text="<one-line finding text>"            # positive (default)
maestro exp finding --id=<N> --text="<one-line finding text>" --negative # negative / dead-end
```

### Outcome vocabulary

| Value | When |
|-------|------|
| `confirmed` | Hypothesis proven correct |
| `refuted` | Hypothesis disproven — log to prevent re-trying |
| `improved` | Metric improved over baseline (requires `--track` + `--metric`) |
| `parity` | Matched baseline (requires `--track` + `--metric`) |
| `regression` | Worse than baseline (requires `--track` + `--metric`) |
| `infra` | Infrastructure / engineering run — fleet test, worker stability, pipeline smoke test |
| `inconclusive` | Ran but no clear signal |

`infra` runs are first-class records — log them the same way, with a clear takeaway about
what held up or broke. If an infra run produced a **design decision** (e.g. "switch task
queue"), that decision is an ADR, not part of the experiment record.

---

## ADRs

### When to create an ADR

- Choosing a technology or architecture (task queue, storage backend, wire protocol)
- Deciding **not** to use something, and why — prevents re-litigating closed decisions
- Any pivot significant enough that reversing it would require substantial rework
- **Not** for experiment results (`maestro exp`) or sprint plans (`docs/progress.md`)

### Creating

```
maestro adr new --slug="<slug>"
```

Fill in the body: **Context** (the situation/failure that triggered it), **Decision** (the
choice in one clear sentence), **Consequences** (what it enables, what it closes off, what
must happen next). Then accept:

```
maestro adr update --id=<N> --status=accepted --decision="<one-line summary>"
```

### Amending — one live ADR per decision area (core rule 13)

An ADR holds the rules that govern its area TODAY, not the decision as first taken. A
change to the area amends the owning ADR in place; a new ADR is opened only when no live
ADR owns the area.

1. Rewrite the body's **Decision** (and Context/Consequences where they changed) by hand
   so it states the current rule — the body is the rule, and a reader should not have to
   replay amendments to learn it.
2. Record the change:

```
maestro adr amend --id=<N> --decision="<the rule as it now stands, one line>" \
                  --note="<what changed, and why>"
```

`amend` rewrites the frontmatter `decision` and appends a dated entry to the body's single
final `History:` line (creating it when absent):
`History: …; amended 2026-09-28: <note> (prior text in git <sha>).` The sha is the last
commit that wrote the file, so the text being replaced stays one `git show` away.

### Folding and archiving

When one ADR's area is absorbed by another (or the decision is dead), fold its surviving
rules into the owning ADR (step 1 above, `--note="folds in ADR <n>"`), then move the file:

```
git mv docs/adrs/adr_<n>_<slug>.md docs/archive/adrs/
maestro index render --kind=adr
```

and add a row to `docs/archive/adrs/README.md`, the number map (`| <n> | <live ADR or —> |
<which section it became, or "dead: why"> |`). The archived file keeps its frontmatter as
it was; it is history — never listed, checked or updated as live — and its number is never
reissued (`adr new` counts the archive). Records that cite the old number read it there.

A folded ADR is never marked `superseded` in place. Projects that adopted maestro before
2.43.0 may still carry `status: superseded` + `superseded_by` records; those keep passing
`docs check`, and fold into the new model whenever they are next touched.

### Renaming

A decision whose name no longer fits its content is retitled in place; its number and
date never change:

```
maestro adr update --id=<N> --title="<new title>" --slug=<new_slug>
```

`--slug` renames `adr_NN_<slug>.md` (a `git mv` when the file is tracked) and is refused
when another live ADR already has that slug. Paths citing the old filename are not
rewritten — `maestro docs check` names the ones in live docs.

### Retiring a stale standalone doc

If a floating `docs/*.md` is really a design decision (e.g. `reliability_design.md`):
create the ADR, fill context/decision/consequences from the old doc, delete the old doc, and
if already superseded mark it so immediately.

### ADR status vocabulary

| Status | When |
|--------|------|
| `proposed` | Decision drafted, not yet committed |
| `accepted` | Decision is active and governing |
| `superseded` | Legacy (pre-2.43.0): replaced by a newer ADR, kept in place (requires `--superseded-by`). New work archives instead |

---

## Datasets

A dataset is a **stable set of files (≥1)** under `data/raw/`. Its record is `docs/data/<name>.md`:
tool-owned frontmatter (provenance + a **computed** sha) plus a hand-edited description body.

### Creating

```
maestro dataset new --name=<name> --version=<vN> --source="<url | internal: ref>" [--license=...]
```

- Run this **after the bytes are in `data/raw/<name>/<vN>/`** — `dataset new` computes the sha256 over
  the file-set. If the data isn't there yet, the sha is left empty; fill it later with
  `maestro dataset update --name=<name> --rehash`.
- The hook **blocks hand-creating** `docs/data/<name>.md` (so the sha is never typed). Once it exists,
  **edit the description body freely** — what it is, schema, collection method, caveats, how to load.
- Record `--used` (the columns/files experiments actually consume) once you know them.

### Versioning & integrity

- A new release is a **new version** (`data/raw/<name>/v<N+1>/`), never an in-place edit. Re-pulling on
  top of old bytes destroys reproducibility for any experiment that cited the old sha.
- `maestro dataset verify` recomputes every sha and flags: **drift** (bytes changed in place → make a new
  version), **missing sha**, or **absent/dangling** data (e.g. a `~/data` shared-dataset symlink whose
  target moved). Run it before any write-up that cites the data.

### Citing in an experiment

Name the dataset **and version** in the exp write-up, and wire the lineage:
`maestro exp update --id=<N> --consumes="data/raw/<name>/<vN>/..."`. Tag tracked runs with
`dataset`/`dataset_version`/`dataset_sha` so a run points back to this record.

---

## Read-time rule (consulting the KB, not writing)

When you load `INDEX.md`, a per-experiment file, or a refuted-list takeaway and are about to
**propagate** the conclusion — motivate new work, cite it in a write-up, or reject a
hypothesis as "already refuted" — treat the takeaway as a **summary, not verified data**:

1. Re-read the underlying `data/experiments/exp_NN_*/` artifacts before propagating.
2. Check the entry's `flags:` field — `single_seed`, `large_unexpected_gain`, etc. are direct warnings.
3. Check the entry's `revisions:` field — if the takeaway was revised, the failure history is informative.
4. If you cannot verify the original artifact (deleted/lost), explicitly note `setup_unverified`
   rather than silently assuming the takeaway is correct.

This is the single most load-bearing defense against compounding error. **The takeaway is an
index entry; the data dir is the truth.** (INDEX.md is the *recall tier* — see
`protocols/memory_tiers.md` for the full load order.)
