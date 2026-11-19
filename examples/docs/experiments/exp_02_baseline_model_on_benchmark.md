---
exp: 2
title: baseline model on benchmark
status: done
date: '2026-06-20'
tags:
- baseline
- benchmark
outcome: improved
takeaway: "Gradient-boosted trees on the standard feature set reach 0.842 AUC \u2014\
  \ the first real baseline on holdout-v1, above the 0.5 random floor."
track: demo-classification
benchmark: holdout-v1
metric:
  auc: 0.842
  auc_sd: 0.011
n_seeds: 5
source_artifacts:
- data/experiments/exp_02_baseline_model_on_benchmark/metrics.json
mlflow_run: a1b2c3d4e5f6
adr: 3
---

# Exp 2 — baseline model on benchmark

> Example experiment — a **baseline** that opens a leaderboard. Because it sets
> `track:` + `metric:` with `outcome: improved`, it appears in the INDEX
> "Best by Track / Benchmark" table. It is the lineage **root** that Exp 3 and 4
> branch from, and it links out to its tracking run + the tracking ADR.

**Goal**: Establish the first real baseline on the `holdout-v1` benchmark — a number later
experiments must beat — using a standard, well-understood model.

**Data**: `data/processed/features_v1.parquet` (train/val/test split fixed in
`scripts/make_splits.py`). See [data.md](../data.md) for provenance.

**Method**:
1. Train a gradient-boosted tree classifier on the standard feature set.
2. Evaluate AUC on the held-out `holdout-v1` test split.
3. Repeat over **5 seeds**; report mean ± sd. Log metrics/params to the tracker (see
   frontmatter `mlflow_run`). Stdout → `run.log` in the data dir.

**Results**:

| Model | Features | AUC (5 seeds) | Notes |
|-------|----------|--------------:|-------|
| Gradient-boosted trees | standard | **0.842 ± 0.011** | first baseline |

**Takeaway**: Gradient-boosted trees reach **0.842 AUC** — the first real number on `holdout-v1`,
well above the 0.5 random floor. This is the bar Exp 3 (features) and Exp 4 (deeper net) try to beat.

**Outputs**: see frontmatter `source_artifacts:` and [data.md](../data.md).
