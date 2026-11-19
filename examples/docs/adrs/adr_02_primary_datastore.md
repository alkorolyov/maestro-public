---
adr: 2
title: primary datastore
status: accepted
date: '2026-06-20'
tags:
- infra
- storage
- datastore
decision: Use PostgreSQL as the primary datastore; SQLite for local dev/tests
context: 'Need relational integrity + concurrent writers for the run registry. Options:
  SQLite (zero-ops, single-writer), PostgreSQL (concurrent, richer types), a document
  store (flexible but no joins we rely on).'
consequences: One engine in prod; SQLite parity kept for fast local tests; must run
  migrations; JSONB covers semi-structured columns without a second store.
---

# ADR 2 — primary datastore

> Example ADR — a textbook "pick a technology" decision. Note how the Context
> lists the *forces*, the Decision says what we picked AND what we rejected, and
> the Consequences carry both the wins and the new burdens.

**Context**: The run registry needs relational integrity (foreign keys across runs,
artifacts, and metrics) and **concurrent writers** — several workers record results at once.
We also have a few semi-structured columns (per-run config blobs). Options weighed:

- **SQLite** — zero-ops, single file, great for tests; but single-writer, so concurrent
  workers serialize or hit "database is locked".
- **PostgreSQL** — true concurrent writers, rich types (JSONB, arrays), mature tooling; costs
  one service to run and a migration discipline.
- **Document store (Mongo-style)** — flexible schema, but we depend on multi-table joins the
  registry makes constantly, which a document store makes awkward.

**Decision**: Use **PostgreSQL** as the primary datastore. Keep **SQLite** as a drop-in for
local dev and tests (same ORM models, so parity is cheap). Reject the document store — the
joins we rely on are first-class in SQL and awkward without it. Semi-structured columns use
Postgres **JSONB** rather than standing up a second store.

**Consequences**:
- One engine to operate in prod; one more service in the compose file.
- Schema changes now require **migrations** — no more editing tables by hand.
- JSONB absorbs the semi-structured columns, so no second datastore.
- SQLite parity keeps tests fast and offline, but anything Postgres-specific (JSONB operators)
  must stay behind a thin query layer or tests drift from prod.
