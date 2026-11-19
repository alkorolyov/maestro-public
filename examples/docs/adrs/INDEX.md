# ADR Index

_Generated from `docs/adrs/adr_*.md` frontmatter. Do not edit by hand._
_Run `maestro index render --kind=adr` to regenerate. New decision: `maestro adr new --slug=<slug>`._

## All Decisions

| # | Title | Status | Decision | Tags |
|---|-------|--------|----------|------|
| 1 | task queue selection | accepted | Use jobrunner + K3s for distributed task execution | infra, task-queue, vastai |
| 2 | primary datastore | accepted | Use PostgreSQL as the primary datastore; SQLite for local dev/tests | infra, storage, datastore |
| 3 | experiment tracking backend | superseded → adr_4 | Track experiments with a self-hosted MLflow instance | infra, tracking, mlops |
| 4 | adopt managed experiment tracking | accepted | Adopt a managed experiment-tracking service; retire the self-hosted MLflow server | infra, tracking, mlops |

## Active Decisions

| # | Title | Decision |
|---|-------|----------|
| 1 | task queue selection | Use jobrunner + K3s for distributed task execution |
| 2 | primary datastore | Use PostgreSQL as the primary datastore; SQLite for local dev/tests |
| 4 | adopt managed experiment tracking | Adopt a managed experiment-tracking service; retire the self-hosted MLflow server |

## Superseded (history only)

| # | Title | Superseded by |
|---|-------|--------------|
| 3 | experiment tracking backend | adr_4 |
