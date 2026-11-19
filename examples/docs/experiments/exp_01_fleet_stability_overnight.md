---
exp: 1
title: fleet stability overnight
status: done
date: '2026-05-03'
tags:
- infra
- vastai
outcome: infra
takeaway: 'Fleet stable overnight: 500/500 jobs completed across 5 spot preemptions,
  zero loss; 3 duplicate executions confirm at-least-once delivery (consumers must
  stay idempotent).'
metric:
  jobs: 500.0
  completed: 500.0
  lost: 0.0
  dup: 3.0
source_artifacts:
- data/experiments/exp_01_fleet_stability_overnight/run.log
---

# Exp 1 — fleet stability overnight

> Example experiment (`outcome: infra` — a platform-validation run, not a
> hypothesis test). Shows what a *filled* record looks like: Goal / Method /
> Results / Takeaway, numbers traceable to the data dir. Replace with your own.

**Goal**: Validate that the jobrunner + K3s stack (ADR 1) survives spot preemptions
overnight with no job loss — the failure mode that killed `ssh_jobqueue`.

**Method**:
1. Submit 500 no-op sleep jobs (30 s each) to jobrunner on a 4-worker vast.ai K3s fleet.
2. Run unattended overnight (~8 h); let spot preemptions happen naturally.
3. Each job writes a unique marker to its output; a reconciler diffs submitted vs.
   completed markers and counts duplicates. Stdout → `vK/run.log` in the data dir.

**Results**:

| Metric | Value | Notes |
|--------|------:|-------|
| Jobs submitted | 500 | |
| Jobs completed | **500** | zero loss |
| Spot preemptions | 5 | workers killed mid-job |
| Duplicate executions | 3 | redelivered after preemption |

All 5 preempted jobs were redelivered and finished on another worker. The 3 duplicates
are jobs whose original worker died *after* finishing but *before* acking the lease.

**Takeaway**: Stack is stable under preemption — 500/500 completed, zero loss. Delivery is
**at-least-once**, not exactly-once: the 3 duplicates prove consumers must be idempotent.
This validates the ADR 1 decision and feeds back the idempotency requirement.

**Outputs**: see frontmatter `source_artifacts:` and [data.md](../data.md).
