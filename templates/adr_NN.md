---
adr: 1
title: Task queue selection
status: accepted        # proposed | accepted | superseded
date: 2026-05-03
superseded_by: null     # set when superseded by another ADR
decision: "Adopt a managed task queue (library X) for distributed execution"
context: "The custom in-house queue has no lease/redelivery — in-flight jobs are lost on worker death"
consequences: "The app becomes a thin queue consumer; the custom queue is removed"
tags: [infra, task-queue]
---

# ADR 1 — Task queue selection

**Context**: ...

**Decision**: ...

**Consequences**: ...
