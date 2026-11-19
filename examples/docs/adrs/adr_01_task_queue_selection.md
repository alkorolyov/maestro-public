---
adr: 1
title: task queue selection
status: accepted
date: '2026-05-03'
tags:
- infra
- task-queue
- vastai
decision: Use jobrunner + K3s for distributed task execution
context: "Distributed jobs dispatched over a custom SSH protocol with no lease/redelivery\
  \ \u2014 a worker dying mid-job silently loses that job (2026-05-02 fleet failure)."
consequences: One task system to operate, not two; reliability primitives owned in
  one place; jobrunner is young so its bugs are now ours; local dev uses an in-process
  LocalDispatcher.
---

# ADR 1 — task queue selection

> Example ADR. This is what a *filled* record looks like — the value is in the
> tradeoff reasoning (forces weighed, alternatives rejected, both-sided
> consequences), not the headings. Replace with your own decision.

**Context**: Distributed jobs were dispatched over a custom SSH protocol (`ssh_jobqueue`)
with no lease or redelivery: when a worker died mid-job, that job was silently lost.
The 2026-05-02 overnight fleet run lost 11/240 jobs this way. We need at-least-once
delivery on preemptible (spot) GPU workers. Options weighed:

- **Celery + Redis** — mature, well-understood, but adds a Redis broker to operate and
  a second task system alongside the in-house `jobrunner` already being built.
- **Cloud-managed queue (SQS / Pub-Sub)** — no broker to run, but ties dispatch to one
  cloud and adds per-message cost + egress for a workload that runs mostly on vast.ai.
- **jobrunner (in-house) + K3s** — reuses infra we already maintain; lease/redelivery and
  a stale-claim sweeper are first-class; young, so fewer battle-tested edges.

**Decision**: Use **jobrunner + K3s** for distributed task execution. The project becomes a
thin jobrunner consumer; K3s schedules pods onto vast.ai spot workers; jobrunner owns the
atomic claim, stale-claim sweep, and redelivery. We explicitly reject Celery (avoids
standing up and monitoring a second broker) and managed queues (avoids cloud lock-in for a
vast.ai-first workload). `ssh_jobqueue` stays in the tree as dead code until the migration
is validated, then is deleted.

**Consequences**:
- One task system to operate, not two; reliability primitives (claim, sweep, redelivery)
  owned in one place.
- Delivery is **at-least-once**, not exactly-once → every consumer must be idempotent
  (verified by Exp 1: 3 duplicate executions on 5 preemptions).
- jobrunner is young, so its bugs are now ours to find and fix.
- Local dev needs no broker — an in-process `LocalDispatcher` backs the same interface.
- The idle-worker cost watchdog (stop idle vast.ai instances) is still unsolved and tracked
  separately.
