---
exp: 3
title: feature set ablation
status: done
date: '2026-06-20'
tags:
- ablation
- benchmark
- features
outcome: improved
takeaway: "Dropping 12 leaky/low-signal features lifts AUC 0.842 \u2192 0.866\xB1\
  0.010 (was 0.871 on a lucky split) \u2014 still new best on holdout-v1; leak removal\
  \ is the real driver."
track: demo-classification
benchmark: holdout-v1
metric:
  auc: 0.866
  auc_sd: 0.01
parent: 2
n_seeds: 5
source_artifacts:
- data/experiments/exp_03_feature_set_ablation/metrics.json
revisions:
- date: '2026-06-20'
  by: user
  reason: Re-ran with a fixed random split; the gain held but was smaller than first
    reported.
  previous_takeaway: "Dropping 12 leaky/low-signal features lifts AUC 0.842 \u2192\
    \ 0.871 \u2014 new best on holdout-v1; the leak was the dominant error source,\
    \ not model capacity."
  new_takeaway: "Dropping 12 leaky/low-signal features lifts AUC 0.842 \u2192 0.866\xB1\
    0.010 (was 0.871 on a lucky split) \u2014 still new best on holdout-v1; leak removal\
    \ is the real driver."
---

# Exp 3 — feature set ablation

> Example experiment — a **child** of Exp 2 (`parent: 2`) that becomes the new
> best on the track, and carries a **revision** in its frontmatter. The revision
> log (visible in the INDEX "Recent Revisions" table) is how a corrected takeaway
> stays honest: the original is preserved, the reason is recorded — never a
> silent edit.

**Goal**: Test whether removing leaky / low-signal features beats the Exp 2 baseline — i.e.
is the error driven by data quality rather than model capacity?

**Data**: same split as Exp 2; feature set reduced from the standard set by dropping 12 columns
flagged as target-leaking or near-zero importance.

**Method**:
1. Drop the 12 flagged features; retrain the **same** gradient-boosted model as Exp 2 (only the
   feature set changes — a clean ablation).
2. Evaluate AUC on `holdout-v1`, 5 seeds, mean ± sd.

**Results**:

| Feature set | AUC (5 seeds) | Δ vs Exp 2 |
|-------------|--------------:|-----------:|
| standard (Exp 2) | 0.842 ± 0.011 | — |
| leak-removed | **0.866 ± 0.010** | +0.024 |

**Takeaway**: Removing the 12 leaky/low-signal features lifts AUC **0.842 → 0.866** — new best on
`holdout-v1`. The leak was the dominant error source, not model capacity.

> **Revision (2026-06-20):** first reported as 0.871 on a single lucky split; re-running with a
> fixed split gave 0.866 ± 0.010. The gain held, smaller than first stated. (Corrected via
> `maestro exp revise`, not a silent edit — see frontmatter `revisions:`.)

**Outputs**: see frontmatter `source_artifacts:` and [data.md](../data.md).
