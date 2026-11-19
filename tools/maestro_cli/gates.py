"""The gate mode: do maestro's mechanical gates BLOCK, or only WARN?

The rules do not change with the mode — records are written by the CLI (rule 1), a
result is read back from an artifact (rule 2), raw data is never edited (rule 7). What
changes is what happens when a check catches a breach. Three gates are affected:

    gate                         where it runs                            block     warn
    ───────────────────────────  ───────────────────────────────────────  ────────  ──────────────
    record guard (pre-write)     global/hooks/guard_records.py            deny      allow + warning
    stamp guard (post-tool)      global/hooks/guard_stamps.py             block     warning, once
    pre-commit stamp + drift     templates/pre-commit (guards 1 and 2)    exit 1    warning, commit

WHY A SWITCH. The gates were written for
weaker executors — dsh lanes, the local-model harness — that do breach rule 1 by
accident and cannot be trusted to notice. A high-judgment Claude Code session trips
them on legitimate work instead: resolving a merge, folding ADRs, a docs check that
fires in a worktree without `data/`. For that session a refusal costs more than the
breach it prevents, while the warning still puts the breach in front of it.

WHERE IT IS READ. Only in the Claude Code adapters and the pre-commit template — never
in the CLI verbs. `maestro docs stamp --check`, `docs check` and `docs guard` keep their
exit codes whatever the environment says, so a dsh plugin that shells out to them (and
any script that trusts an exit code) is unaffected even if it inherits the variable. The
dsh plugins also drop the variable from their process environment at load, so a dsh
started from inside a warn-mode session still commits under blocking gates.

The default is `block`; anything other than exactly `warn` is `block`, so a typo never
weakens a gate.
"""
from __future__ import annotations

import os

ENV = "MAESTRO_GATES"
BLOCK, WARN = "block", "warn"


def mode(environ=None) -> str:
    """`warn` when MAESTRO_GATES says exactly that (case and spaces forgiven), else `block`."""
    env = os.environ if environ is None else environ
    return WARN if str(env.get(ENV, "")).strip().lower() == WARN else BLOCK


def warns(environ=None) -> bool:
    return mode(environ) == WARN


def warning(gate: str, reason: str) -> str:
    """The text a warn-mode gate shows in place of its refusal."""
    return (f"maestro {gate} — WARNING only ({ENV}=warn, nothing was blocked). The rule "
            f"still holds; fix this unless it is deliberate:\n{reason}")
