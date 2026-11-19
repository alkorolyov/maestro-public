---
adr: 4
title: adopt managed experiment tracking
status: accepted
date: '2026-06-20'
tags:
- infra
- tracking
- mlops
decision: Adopt a managed experiment-tracking service; retire the self-hosted MLflow
  server
context: "Self-hosted MLflow (ADR 3) became an ops drain \u2014 backups, version upgrades,\
  \ and an artifact store we kept babysitting. A managed service removes that toil\
  \ for a workload that is not data-sensitive."
consequences: No server to operate; small monthly cost + metadata leaves the box;
  client SDK swap is a one-file change behind our tracking wrapper; ADR 3 history
  retained.
---

# ADR 4 — adopt managed experiment tracking

> Example ADR — the **replacement** in a supersession pair. The protocol is:
> create the replacement first, then mark the old one `superseded` with
> `superseded_by`. This record cites the ADR it overturns (ADR 3) so the chain
> reads in both directions.

**Context**: The self-hosted MLflow from ADR 3 worked, but became an **ops drain** — database
backups, version upgrades, and an artifact store we kept babysitting consumed more time than the
tracking was worth. The data being tracked (metrics, hyperparameters) is **not sensitive**, so
the original "keep it on our box" force has weakened.

**Decision**: Adopt a **managed experiment-tracking service** and retire the self-hosted MLflow
server. Training code talks to a thin in-house tracking wrapper, so the backend swap is a
one-file change; existing run history is exported and archived.

**Consequences**:
- No server, DB, or artifact store to operate — the ops toil from ADR 3 disappears.
- A small monthly cost, and run **metadata now leaves the box** (acceptable: not sensitive).
- The tracking wrapper already abstracted the client, so the swap touches one module.
- ADR 3 stays on record as `superseded` — history is retained, not rewritten.
