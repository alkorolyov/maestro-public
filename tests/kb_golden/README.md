# kb_golden — hard-negative gate benchmark for `maestro kb`

A statistically-meaningful ROC-AUC benchmark of the **kb relevance gate** — the
score threshold `maestro kb search` uses to decide whether a session query is
relevant to the project knowledge base (and should retrieve docs) or is just a
routine dev turn (and should retrieve nothing).

## Why this benchmark exists (and why "hard" negatives)

A naive gate eval uses **trivial** off-topic negatives ("what is the capital of
France"). Those are rejected with near-zero similarity, so they inflate AUC and
measure nothing. The real test is **near-domain hard negatives**: queries that
sound like they belong to the corpus's broad field (computational drug discovery /
molecular ML / structural & chemical biology / peptide science) but for which
**no paper in the corpus actually answers the query**. They deliberately share
vocabulary (molecular, peptide, MD, binding, structure, ML, simulation) — that
shared vocabulary is what makes them hard, and is the failure mode we probe
(e.g. "protein secondary structure" wrongly matching the OPM membrane-positioning
paper).

## It evaluates against an EXTERNAL corpus

maestro's own `docs/kb/` is empty, so this benchmark runs against a
**membrane-permeability kb from a separate project** (50 papers). There is no default corpus path: set `MAESTRO_KB_CORPUS` to a
directory of kb literature entries or the script exits with that message. The corpus
is loaded with maestro's own `maestro_cli.kb:load_entries`, so the benchmark
exercises the exact code path the gate uses; point `MAESTRO_KB_CORPUS` at any other
kb to re-benchmark on a different corpus.

## Contents

| file | what |
|------|------|
| `positives.tsv` | 113 within-domain queries, each grounded to one real paper in the corpus (`target_slug \t query`). These are the **positives** (gate should fire). |
| `negatives_hard.tsv` | 80 verified hard negatives (`query \t nearest_corpus_slug \t why_its_a_true_negative`). Same broad field, no answering paper. |
| `probes.txt` | 6 generic routine-dev probes used to **calibrate** the gate (kept separate from the test negatives). |
| `run_gate_auc.py` | the re-runnable eval (parameterized by `MAESTRO_KB_CORPUS` + `KB_DEVICE`). |

## How the sets were built

**Positives (113).** Each is a real question whose answer is one specific paper in
the 50-doc corpus; the paper's slug is the ground-truth target. Grounded by hand
against the corpus.

**Hard negatives (80).** ~120 candidates were generated from the same broad field
but about subtopics ABSENT from the corpus (protein structure prediction,
protein–ligand docking/FEP, hERG/Ames/tox QSAR, aqueous solubility, CYP450
clearance, plasma protein binding, retrosynthesis, crystal/polymorph prediction,
antibody design, PPI prediction, enzyme kinetics, GPCR/kinase signaling, de-novo
generative design, protein-folding MD, cryo-EM/NMR/X-ray structure determination,
shotgun proteomics, single-cell genomics, DFT reaction energetics, …). Each
candidate was **verified** against every corpus title + `## Takeaway` (and, for
the riskiest borderline cases, the full paper body): if any paper genuinely
answers it, the candidate was **dropped**. Borderline drops scrutinized hardest —
e.g. **blood-brain-barrier penetration classification was dropped** because PerMM
(`acs.jcim.9b00224` / `9b00225`) does an explicit BBB permeable/impermeable call at
`log P0 = −4.35`; `logP`/`logD`, membrane-water partition coefficient, pKa-in-a-
permeability-context, conformer generation, peptide similarity/fingerprints, and
MHC-I peptide binding were all dropped or excluded because the corpus addresses
them. Each kept negative records its nearest corpus paper + why it is still a true
negative.

**Calibration probes (6).** Generic non-kb dev turns ("what is the weather forecast
for tomorrow", "how do I install a python package with pip", …) that model the
gate's actual job — most session turns are routine dev, not kb queries.

## How to run

`MAESTRO_KB_CORPUS` is required — it names the kb the gate is scored against.

```bash
export MAESTRO_KB_CORPUS=/path/to/some-project/docs/kb/literature

# GPU (a Blackwell card needs a cu128+ torch build)
KB_DEVICE=cuda python run_gate_auc.py

# CPU
python run_gate_auc.py
```

The script runs 4 embedding models, each in an isolated subprocess, and reports
per-model AUC + bootstrap 95% CI, a calibrated gate confusion matrix, separation
gap, and a paired bootstrap of ΔAUC vs `bge-base`.

### Per model
- top-1 cosine similarity for every query (positives + hard negatives)
- ROC-AUC (positive = 1) with bootstrap 95% CI (2000 resamples, fixed seed 1234)
- paired bootstrap of ΔAUC vs `bge-base` (same resampled indices applied to both)
- gate confusion (TP/FP/FN/TN), precision, recall, specificity at the calibrated gate
- `gate = max(top1 over the 6 probes) + 0.10`
- separation gap = `min(pos top1) − max(neg top1)`

### Models + query prompts (held identical for fairness)
- `bge-small` `BAAI/bge-small-en-v1.5`, `bge-base` `BAAI/bge-base-en-v1.5`:
  queries prefixed `"Represent this sentence for searching relevant passages: "`; docs plain.
- `qwen3-0.6b` `Qwen/Qwen3-Embedding-0.6B`:
  queries `f"Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: {q}"`; docs plain.
- `yuan-2.0` `IEITYuan/Yuan-embedding-2.0-en`: its SentenceTransformers-defined `query` prompt.
- All: L2-normalize, cosine similarity.

## Results snapshot

> **The citable version of these numbers is a record, not this file.** Cite the experiment
> record and its run artifacts in the project that ran the benchmark; the table below is
> an index.


113 positives · 80 hard negatives · 6 calibration probes · 50-doc corpus.

Sorted by AUC:

| model | dim | AUC | AUC 95% CI | gate | FP | prec | spec | sep_gap |
|-------|-----|-----|------------|------|----|------|------|---------|
| qwen3-0.6b | 1024 | 0.9762 | [0.9544, 0.9923] | 0.308 | 79 | 0.589 | 0.013 | −0.2258 |
| bge-small  | 384  | 0.9375 | [0.8987, 0.9689] | 0.618 | 80 | 0.585 | 0.000 | −0.1785 |
| yuan-2.0   | 1024 | 0.8939 | [0.8492, 0.9335] | 0.618 | 73 | 0.605 | 0.087 | −0.1521 |
| bge-base   | 768  | 0.8751 | [0.8231, 0.9222] | 0.571 | 79 | 0.589 | 0.013 | −0.1876 |

Paired ΔAUC vs `bge-base` (2000 paired bootstrap iters):

| model | ΔAUC mean | ΔAUC 95% CI | significant? |
|-------|-----------|-------------|--------------|
| qwen3-0.6b | +0.1014 | [+0.0578, +0.1493] | YES |
| bge-small  | +0.0623 | [+0.0316, +0.0967] | YES |
| yuan-2.0   | +0.0194 | [−0.0240, +0.0671] | no (within noise) |

**Verdict.** With hard near-domain negatives, `bge-base` is NOT the best — it is
the worst of the four on AUC. `qwen3-0.6b` ranks best and beats `bge-base`
significantly (paired CI excludes 0); `bge-small` also beats it significantly;
`yuan-2.0` is within noise. **More important than the ranking:** every model has a
**negative separation gap** (`pos_min < neg_max`), and a gate calibrated on
*trivial* dev probes lets ~all hard negatives through (specificity ≈ 0,
FP = 73–80 of 80). A single global threshold tuned on easy probes does **not**
separate on-topic queries from hard near-domain ones. High ranking AUC ≠ a usable
gate: the gate needs calibration against hard negatives (or a different mechanism),
not just easy off-topic probes.
