---
# --- Identity (always required) ---
epic: 2
title: Split the engine god file
status: active               # review | todo | active | done
opened: 2026-08-23
closed: null                  # date; set by `close`, never by hand

# --- Flag, not a state (Kanban/Jira semantics) ---
blocked_by: null              # free-text reason. Settable in ANY status; the board
                              # renders flagged cards in their own lane, and the card
                              # keeps showing where the work actually stands.

# --- The closing condition. Written at OPEN, answered at CLOSE. ---
done_when:                    # `maestro epic done-when` — never hand-edited
  - id: 1
    text: no source file over 1500 lines   # a CONDITION, not a task
    check: "wc -l src/core/*.rs | sort -rn | head -1"
    result: null              # what the check MEASURED; close refuses while null
  - id: 2
    text: the full cargo suite stays green
    check: cargo nextest run --workspace
    result: null

# --- Scope: items. One item ~= one session ~= one branch. ---
items:
  - id: 1
    title: Extract the renderer
    status: done
  - id: 2
    title: Extract physics and collision
    status: in_progress
    blocked_by: null
  - id: 3
    title: Delete the old entry points
    status: todo

# --- Result (required when status = done) ---
outcome: null                 # one sentence: what the epic actually delivered

# --- Links ---
exps: []                      # experiment numbers produced inside this epic
adrs: []                      # decisions taken inside it
tags: [refactor, engine]
---

# Epic 2 — Split the engine god file

**Arc**: `deep-refactor` — {the README §Route arc this epic is drawn from, cited by SLUG,
never by its position number. Omit the line for an epic that belongs to no arc.}

**Why**: {The standing problem. One paragraph — an epic outlives many sessions, so a
reader arriving cold needs the motivation, not just the task list. The closing condition
is NOT repeated here: it lives in `done_when` above, where the CLI can refuse a close
that has not measured it.}

**Out of scope**: {What this epic deliberately does NOT cover, so items stop multiplying.}

## Log

_Append-only. One dated line per session; written by the CLI's `--note`, never by hand._

- 2026-08-23 — opened; items 1-3 seeded from the backlog.
