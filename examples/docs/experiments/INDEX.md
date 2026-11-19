# Experiment Index

_Generated from `docs/experiments/exp_*.md` frontmatter. Do not edit by hand._
_Run `maestro index render --kind=exp` to regenerate. New experiment: `maestro exp new --slug=<slug>`._

## All Experiments

| # | Title | Status | Outcome | Takeaway | Tags |
|---|-------|--------|---------|----------|------|
| 1 | fleet stability overnight | done | infra | Fleet stable overnight: 500/500 jobs completed across 5 spot preemptions, zero loss; 3 duplicate executions confirm at-least-once delivery (consumers must stay idempotent). | infra, vastai |
| 2 | baseline model on benchmark | done | improved | Gradient-boosted trees on the standard feature set reach 0.842 AUC — the first real baseline on holdout-v1, above the 0.5 random floor. | baseline, benchmark |
| 3 | feature set ablation | done | improved | Dropping 12 leaky/low-signal features lifts AUC 0.842 → 0.866±0.010 (was 0.871 on a lucky split) — still new best on holdout-v1; leak removal is the real driver. | ablation, benchmark, features |
| 4 | deeper net vs baseline | done | refuted | A 3x-deeper network does NOT beat the gradient-boosted baseline (0.838 vs 0.842 AUC, single seed) — added capacity buys nothing here; do not re-try without more data. | ablation, deep-learning |

## Best by Track / Benchmark

| Track | Benchmark | Best Exp | Metric | Flags |
|-------|-----------|----------|--------|-------|
| demo-classification | holdout-v1 | 3 | auc=0.866±0.01 | — |

## Refuted Hypotheses (do not re-try)

| # | Takeaway | Date |
|---|----------|------|
| 4 | A 3x-deeper network does NOT beat the gradient-boosted baseline (0.838 vs 0.842 AUC, single seed) — added capacity buys nothing here; do not re-try without more data. | 2026-06-20 |

## Open / Inconclusive

| # | Title | Tags |
|---|-------|------|

## Lineage Roots

| # | Title | Children |
|---|-------|----------|
| 1 | fleet stability overnight | — |
| 2 | baseline model on benchmark | 3, 4 |

## External Pointers

_Where to follow when the markdown isn't enough — tracked runs, decisions, motivating papers. Resolve a run to its tracker via `runs fetch --exp <#>` (tracker set in pyproject [tool.maestro])._

| # | Best run | Runs | DOIs | ADR |
|---|----------|------|------|-----|
| 2 | — | — | — | adr_3 |

## Needs Review

_Experiments with one or more deterministic review flags. Re-verify before propagating the takeaway into a new experiment, write-up, or refuted-list rejection._

| # | Title | Flags | Takeaway |
|---|-------|-------|----------|
| 4 | deeper net vs baseline | single_seed | A 3x-deeper network does NOT beat the gradient-boosted baseline (0.838 vs 0.842 AUC, single seed) — added capacity buys nothing here; do not re-try without more data. |

## Source Artifacts (provenance)

_Per-experiment data files the takeaway is derived from. When an artifact is found wrong, grep this section to find every dependent claim (FAIR R1.2)._

| # | Sources |
|---|---------|
| 1 | data/experiments/exp_01_fleet_stability_overnight/run.log |
| 2 | data/experiments/exp_02_baseline_model_on_benchmark/metrics.json |
| 3 | data/experiments/exp_03_feature_set_ablation/metrics.json |
| 4 | data/experiments/exp_04_deeper_net_vs_baseline/metrics.json |

## Recent Revisions

_Append-only correction log. Original takeaway preserved; reason captures why it was wrong._

| Date | # | Title | By | Reason |
|------|---|-------|-----|--------|
| 2026-06-20 | 3 | feature set ablation | user | Re-ran with a fixed random split; the gain held but was smaller than first reported. |
