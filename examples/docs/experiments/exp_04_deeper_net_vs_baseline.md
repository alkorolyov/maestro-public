---
exp: 4
title: deeper net vs baseline
status: done
date: '2026-06-20'
tags:
- ablation
- deep-learning
outcome: refuted
takeaway: "A 3x-deeper network does NOT beat the gradient-boosted baseline (0.838\
  \ vs 0.842 AUC, single seed) \u2014 added capacity buys nothing here; do not re-try\
  \ without more data."
parent: 2
n_seeds: 1
source_artifacts:
- data/experiments/exp_04_deeper_net_vs_baseline/metrics.json
---

# Exp 4 — deeper net vs baseline

> Example experiment — a **refuted** hypothesis run on a **single seed**. Two
> mechanics on display: (1) `outcome: refuted` lands it in the INDEX "Refuted
> Hypotheses (do not re-try)" table, so the dead end is recorded once and not
> repeated; (2) `n_seeds: 1` auto-adds the `single_seed` flag, which surfaces it
> in "Needs Review" — a one-seed result is suggestive, not settled.

**Goal**: Test the hypothesis that a higher-capacity model (a 3×-deeper network) beats the
gradient-boosted baseline (Exp 2) on `holdout-v1`.

**Data**: same split and leak-removed feature set as Exp 3, for a fair capacity comparison.

**Method**:
1. Train a 3×-deeper MLP (more layers/units) on the same inputs.
2. Evaluate AUC on `holdout-v1`. **Single seed** — a quick look, not a full sweep.

**Results**:

| Model | AUC (1 seed) | vs baseline |
|-------|-------------:|------------:|
| Gradient-boosted trees (Exp 2) | 0.842 | — |
| 3×-deeper MLP | 0.838 | −0.004 |

**Takeaway**: The deeper network does **not** beat the gradient-boosted baseline (0.838 vs 0.842,
single seed). Added capacity buys nothing at this data scale — **do not re-try without more data.**

> Flagged `single_seed` (auto, from `n_seeds: 1`): one seed is enough to *not pursue* this now,
> but not enough to call it settled. Re-verify with multiple seeds before treating it as final.

**Outputs**: see frontmatter `source_artifacts:` and [data.md](../data.md).
