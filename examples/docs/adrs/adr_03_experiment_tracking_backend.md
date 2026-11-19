---
adr: 3
title: experiment tracking backend
status: superseded
date: '2026-06-20'
tags:
- infra
- tracking
- mlops
decision: Track experiments with a self-hosted MLflow instance
context: Experiments need metric/param/artifact logging beyond the per-exp markdown.
  Self-hosted MLflow is free and local; a managed SaaS is less ops but costs and sends
  data off-box.
consequences: Own the MLflow server + its backing DB and artifact store; no external
  data egress; we carry upgrade/backup burden.
superseded_by: 4
---

# ADR 3 — experiment tracking backend

> Example ADR — shows the **superseded** lifecycle. This decision was later
> overturned by ADR 4; its `status: superseded` + `superseded_by: 4` is what
> puts it in the INDEX "Superseded (history only)" table. The record is kept,
> never deleted — that's how the next person learns *why* it changed.

**Context**: Experiments need metric / parameter / artifact logging beyond the per-exp
markdown record — searchable runs, plots, and stored model files. Options:

- **Self-hosted MLflow** — free, runs on our own box, no data leaves the network; we own the
  server, its backing DB, and the artifact store.
- **Managed SaaS tracker** — almost no ops, but a monthly cost and run metadata leaves the box.

At this stage the team is small and cost-sensitive, and we already run our own infra.

**Decision**: Stand up a **self-hosted MLflow** instance as the tracking backend. All training
runs log metrics, params, and artifacts to it; the per-exp markdown links to the MLflow run.

**Consequences**:
- No external data egress, no per-seat cost.
- We own the MLflow server, its database, **backups, and version upgrades**.
- The artifact store is one more thing to size and monitor.

_(Superseded by ADR 4 — the ops burden above is exactly what tipped the decision later.)_
