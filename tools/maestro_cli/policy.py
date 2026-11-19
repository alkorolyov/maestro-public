"""Per-project policy — the policy tables of `<project>/maestro.toml`, the human-owned half.

WHY THIS EXISTS. A dsh planner (the root agent, `delegationDepth` 0) can take a large
epic item, spawn many children and write code itself, while the briefs name no file list
at all. Three rules already said not to do any of that: an item is one session (kanban),
the orchestrator does not edit code (core rule 9), and a brief carries its own scope.
Rules the model has to remember are not rules, so the three became refusals —
the item-shape check in `epics.py`, the root-writes-code guard and the spawn-brief check
in `guards.py`.

Every refusal needs a number, and a number hardcoded in a framework is a number that
fits one project. So the LIMITS are declared per project, as tables in `maestro.toml` at
the project root (beside the declaration's `layers`, `[[shape]]` and `[[arcs]]`), and the
defaults below are what a project that declares nothing gets:

    [items]
    max_files = 40             # above this an item must declare itself a mechanical pass

    [epics]
    max_open_items = 8         # an epic with more open items than this is two epics
    max_in_progress = 2        # epics in_progress at once per project (ADR 7)

    [board]
    max_note_chars = 500       # a board line is an index entry, not the reasoning
    max_title_chars = 700

    [agents.dsh]
    root_writes_code = false   # true = the dsh planner may edit code itself (small items)

A project may carry tables of its own beside these (for example `[branching]` or
`[gates]`, read by its own tools); maestro reads only the keys above and ignores the
rest.

A section name may be DOTTED, and `agents` is why: everything under it is a per-HARNESS
table (`[agents.dsh]`, and a project may carry `[agents.claude]`, `[agents.qwen]` of its
own), so a bare boolean directly under `[agents]` is a schema error in a project that
validates the file — a project's own validator may refuse it with "agents.root_writes_code
must be a table". The root-code guard is dsh-only, so its opt-out
is `[agents.dsh] root_writes_code`; there is no fallback to a flat key.

WHY maestro.toml, and not `[tool.maestro]` in pyproject.toml where the merge-evidence
guard reads its config: this file is the HUMAN's, and the `root_writes_code` opt-out is
only meaningful if the agent cannot quietly grant it to itself. pyproject.toml is edited
by agents constantly (dependencies, tool config, the version); maestro.toml is written
once by `maestro init` and appended to only by `maestro shape add`, so an unexplained
diff to it is visible. The root-code guard refuses a write to it like any other tracked
non-docs path — the WHOLE file, not just these tables — which is the other half of the
same claim.

Every uncertainty answers with the DEFAULT: no file, unreadable, unparseable, no TOML
parser, a value of the wrong type or a non-positive limit. A project must not lose a
verb because its policy file has a typo in it — the limit simply stays where the
framework put it.
"""
from __future__ import annotations

from pathlib import Path

FILENAME = "maestro.toml"

# (section, key) → the value a project that declares nothing gets. A section may be
# dotted: `agents.dsh` is the table `[agents.dsh]`.
DEFAULTS = {
    ("items", "max_files"): 40,
    ("epics", "max_open_items"): 8,
    ("epics", "max_in_progress"): 2,
    ("board", "max_note_chars"): 500,
    ("board", "max_title_chars"): 700,
    ("agents.dsh", "root_writes_code"): False,
}


def path_for(root) -> Path:
    return Path(root) / FILENAME


def load(root) -> dict:
    """The parsed `maestro.toml`, or {} when there is nothing usable to read."""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - 3.10 system Python
        try:
            import tomli as tomllib
        except ModuleNotFoundError:
            return {}
    try:
        data = tomllib.loads(path_for(root).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - unreadable policy is "undeclared", never a crash
        return {}
    return data if isinstance(data, dict) else {}


def table(doc, section: str) -> dict:
    """The table `section` names — dotted sections walk down — or {} when there is none."""
    node = doc
    for part in section.split("."):
        if not isinstance(node, dict) or not isinstance(node.get(part), dict):
            return {}
        node = node[part]
    return node


def setting(root, section: str, key: str, data=None):
    """One policy value, falling back to `DEFAULTS[(section, key)]`.

    `data` is an already-loaded document, for a caller reading several keys at once.
    A value of the wrong type — or a limit that is not a positive integer — is treated
    as undeclared: a policy file cannot make a verb refuse everything by accident.
    """
    default = DEFAULTS[(section, key)]
    doc = load(root) if data is None else data
    value = table(doc, section).get(key)
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default
