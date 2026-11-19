---
# --- Identity (always required) ---
exp: 7
title: Gradient-boosting baseline
status: done                  # planned | running | done | failed | superseded
date: 2026-01-15

# --- Finding (required when status = done | failed) ---
outcome: improved             # confirmed | refuted | improved | parity | regression | infra | inconclusive
takeaway: "Gradient boosting reaches 0.91 accuracy on the val split — above the linear baseline (0.88)."

# --- Optional, set only when applicable ---
metric: {accuracy: 0.91, accuracy_sd: 0.01}  # set via --metric "accuracy=0.91±0.01"; <k>_sd pairs with <k> in INDEX.
track: main-classifier              # opt-in to "Best by Track" — only set when this exp competes for a leaderboard.

# --- Lineage (W&B-style; gives you a free DAG) ---
parent: 4                           # exp this branched from (experimental lineage)
supersedes: []                      # list of exp numbers this definitively replaces
consumes: [data/processed/train_features_v2.parquet]
produces: [data/experiments/exp07_gbm_baseline/model.pkl]

tags: [baseline, tabular, classification]
---

# Exp 7 — Gradient-boosting baseline

**Goal**: {What hypothesis is being tested, or what's being measured.}

**Data**: {Input description.}

**Method**: {Numbered steps or brief description.}

**Results**:

| Config | {Metric 1} | {Metric 2} | Notes |
|--------|-----------|-----------|-------|
| A | 0.88 | ... | linear baseline |
| B | **0.91** | ... | + feature X |

**Takeaway**: {One paragraph elaborating the frontmatter `takeaway:`. Bold best result.}

**Outputs**: see frontmatter `produces:` and [data.md](../data.md).
