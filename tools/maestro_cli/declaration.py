"""The project's maestro declaration — membership, rule layers, the dated shape history.

`maestro.toml` at the project root is the ONE switch (design.md → "Shape declaration").
Its absence used to be inferred from a `docs/` records dir, which also policed projects
that had never adopted maestro; its presence
now states three things the checker and the hooks read instead of assuming:

    layers = ["discipline", "research"]   # which half of core.md applies
    [[shape]]                             # the data shape, dated, append-only
    name  = "tiers"                       # data/raw/<dataset>/v<N> + data/processed: the default,
    since = "2026-01-01"                  #   the one layout the checker polices (paths, dir shas)
    [[shape]]
    name  = "other"                       # anything else (a lake, a catalog, a warehouse): the
    since = "2026-07-01"                  #   project owns its layout and documents it in its own
                                          #   CLAUDE.md; the checker leaves data paths alone

Optional ordered arcs group epics on the board (`maestro epic new|update --arc=NAME`):

    [[arcs]]
    name     = "foundation"
    question = "Data, universe and infrastructure to research on"

Declared order is board order; no `[[arcs]]` = no arc column, nothing checked.

Optional `kb_raw` names the directory that holds the kb's downloaded sources (the PDFs and
abstracts the literature_search protocol fetches and reads). It is a path relative to the
project root, or absolute, and may use `~`, `$VAR`, `${VAR}` and `${VAR:-default}` so a project
can keep downloads in its data root, outside git:

    kb_raw = "${PROJECT_DATA:-data}/raw/kb/literature/raw"

Absent, it is `docs/kb/literature/raw`, where every project had it before the key existed.

The same file carries the project's project-policy tables (`[items]`, `[epics]`, `[board]`,
`[agents.dsh]`; policy.py reads them) and any tables of the project's own; this module
reads only `layers`, `tracker`, `kb_raw`, `[[shape]]` and `[[arcs]]`.

Two shapes only. The common case is raw/processed and gets the checks; a project that
deviates says `other` and is not second-guessed about where its data lives (records,
statuses, indexes and the discipline rules still apply). No `[[shape]]` at all means
the default, `tiers`.

A record is judged under the shape valid at its date. A record dated before the CURRENT
shape's line — written under an earlier shape, or before adoption — describes a layout
that is gone: it is history, cited as it was written, never checked, never repointed.

`[tool.maestro]` in pyproject.toml stays the alias (the tracker key already lives
there); a `[[tool.maestro.shape]]` table reads the same way. `maestro.toml` wins when
both exist. A project with neither declares nothing — this module then answers None
and the caller decides what "undeclared" means for it (the transition keeps the
records-dir inference alive one release, with an advisory; see guards.is_maestro_project).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

DECLARATION_FILE = "maestro.toml"
LAYERS = ("discipline", "research")
SHAPES = ("tiers", "other")
DEFAULT_KB_RAW = "docs/kb/literature/raw"

# The one non-path evidence form a record may cite: a catalog table at a snapshot.
# Validated by FORM only (a catalog attach string is project-specific).
TABLE_REF = re.compile(r"^table:(?P<schema>[A-Za-z_][\w]*)\.(?P<name>[A-Za-z_][\w]*)(?:@(?P<snapshot>\w+))?$")


class DeclarationError(ValueError):
    """maestro.toml is present but says something the framework cannot act on."""


@dataclass(frozen=True)
class Shape:
    name: str
    since: date | None          # None: undated, i.e. valid since forever


@dataclass(frozen=True)
class Arc:
    """An ordered group of epics answering one question (optional; `[[arcs]]`)."""
    name: str
    question: str = ""


@dataclass
class Declaration:
    source: Path                                    # the file it was read from
    layers: tuple[str, ...] = LAYERS
    shapes: tuple[Shape, ...] = field(default_factory=tuple)
    tracker: str | None = None
    arcs: tuple[Arc, ...] = field(default_factory=tuple)   # optional, ordered; () = none declared
    kb_raw: str = DEFAULT_KB_RAW                    # where the kb's downloaded sources live

    @property
    def arc_names(self) -> tuple[str, ...]:
        return tuple(a.name for a in self.arcs)

    @property
    def research(self) -> bool:
        return "research" in self.layers

    @property
    def first_line(self) -> date | None:
        """The clean-start line: the earliest dated shape, or None when nothing is dated."""
        dated = [s.since for s in self.shapes if s.since is not None]
        return min(dated) if dated else None

    @property
    def line(self) -> date | None:
        """The clean-start line: the date the CURRENT shape holds from. A record written
        under an earlier shape describes a layout that is gone, so it cannot be checked
        against disk any more than one written before adoption — both are history."""
        current = self.current
        return current.since if current is not None else None

    def legacy(self, day: date | None) -> bool:
        """A record dated before the current shape's line is history, not drift."""
        line = self.line
        return line is not None and day is not None and day < line

    def shape_at(self, day: date | None) -> Shape | None:
        """The shape valid on `day` — the last one whose `since` is on or before it.

        No shapes declared → None (the checker keeps today's default, `tiers`). An
        undated day → the current shape, since a record with no date is judged as new.
        """
        if not self.shapes:
            return None
        if day is None:
            return self.shapes[-1]
        valid = [s for s in self.shapes if s.since is None or s.since <= day]
        return valid[-1] if valid else None

    @property
    def current(self) -> Shape | None:
        return self.shape_at(date.today())

    @property
    def polices_data(self) -> bool:
        """Whether the checker may judge data paths and dataset shas: under `tiers`, the
        default and the one layout it knows (no shape declared means tiers). `other`
        means the project owns its layout and the checker does not care where its data
        lives."""
        current = self.current
        return current is None or current.name == "tiers"


def _toml():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - 3.10 system Python
        import tomli as tomllib
    return tomllib


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DeclarationError(f"shape `since` is not a YYYY-MM-DD date: {value!r}") from exc


def _parse(table: dict, source: Path) -> Declaration:
    layers = table.get("layers", list(LAYERS))
    if not isinstance(layers, list) or not layers or any(l not in LAYERS for l in layers):
        raise DeclarationError(
            f"{source.name}: layers must be a non-empty list drawn from {list(LAYERS)}, got {layers!r}")
    if "discipline" not in layers:
        raise DeclarationError(f"{source.name}: the discipline layer is not optional — every "
                               "adopted project keeps it; drop `research` instead")
    shapes = []
    for i, row in enumerate(table.get("shape", []) or [], 1):
        if not isinstance(row, dict) or row.get("name") not in SHAPES:
            raise DeclarationError(
                f"{source.name}: [[shape]] #{i} needs `name` in {list(SHAPES)}, got {row!r}")
        since = _as_date(row.get("since"))
        if shapes and since is not None and shapes[-1].since is not None and since <= shapes[-1].since:
            raise DeclarationError(
                f"{source.name}: [[shape]] #{i} `since` {since} is not after the previous entry "
                f"({shapes[-1].since}) — shapes are appended in date order, never edited")
        shapes.append(Shape(str(row["name"]), since))
    arcs = []
    for i, row in enumerate(table.get("arcs", []) or [], 1):
        name = row.get("name") if isinstance(row, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise DeclarationError(f"{source.name}: [[arcs]] #{i} needs a non-empty `name`, got {row!r}")
        if name in [a.name for a in arcs]:
            raise DeclarationError(f"{source.name}: [[arcs]] #{i} repeats the arc {name!r}")
        arcs.append(Arc(name.strip(), str(row.get("question") or "").strip()))
    tracker = table.get("tracker")
    kb_raw = table.get("kb_raw", DEFAULT_KB_RAW)
    if not isinstance(kb_raw, str) or not kb_raw.strip():
        raise DeclarationError(f"{source.name}: kb_raw must be a non-empty path string, got {kb_raw!r}")
    return Declaration(source=source, layers=tuple(layers), shapes=tuple(shapes), arcs=tuple(arcs),
                       tracker=str(tracker) if tracker is not None else None, kb_raw=kb_raw.strip())


def declaration_file(root) -> Path | None:
    """`maestro.toml`, else a pyproject.toml carrying `[tool.maestro]`, else None."""
    root = Path(root)
    own = root / DECLARATION_FILE
    if own.is_file():
        return own
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            if re.search(r"^\s*\[tool\.maestro\]", pyproject.read_text(errors="ignore"), re.M):
                return pyproject
        except OSError:
            return None
    return None


def load(root) -> Declaration | None:
    """The declaration at `root`, None when the project declares nothing.

    Raises DeclarationError for a file that is there but unusable — the checker reports
    that as a blocking issue, because a half-declared project is the one state nothing
    can reason about.
    """
    path = declaration_file(root)
    if path is None:
        return None
    try:
        data = _toml().loads(path.read_text())
    except (OSError, ValueError) as exc:  # tomllib.TOMLDecodeError is a ValueError
        raise DeclarationError(f"{path.name}: cannot parse — {exc}") from exc
    table = data if path.name == DECLARATION_FILE else (data.get("tool", {}) or {}).get("maestro", {}) or {}
    return _parse(table, path)


_VAR = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}|\$(\w+)")


def expand_path(text: str, env=None) -> str:
    """`text` with `~`, `$VAR`, `${VAR}` and `${VAR:-default}` expanded. An unset variable with
    no default is an error, never an empty string that would silently point at the wrong place."""
    import os
    env = os.environ if env is None else env

    def sub(m):
        name = m.group(1) or m.group(3)
        value = env.get(name) or m.group(2)
        if value is None:
            raise DeclarationError(f"kb_raw uses ${name}, which is not set (write ${{{name}:-default}} "
                                   "to give it a default)")
        return value
    return os.path.expanduser(_VAR.sub(sub, text))


def kb_raw_dir(root, decl: Declaration | None = None, env=None) -> Path:
    """The directory of the kb's downloaded sources for the project at `root`: the declaration's
    `kb_raw`, else `docs/kb/literature/raw`; relative paths are taken from `root`."""
    root = Path(root)
    decl = decl if decl is not None else load(root)
    path = Path(expand_path(decl.kb_raw if decl is not None else DEFAULT_KB_RAW, env))
    return path if path.is_absolute() else root / path


def is_declared(root) -> bool:
    return declaration_file(root) is not None


def record_date(fm) -> date | None:
    """The date a record was written, from whichever key its kind carries."""
    for key in ("date", "opened", "created", "retrieved"):
        if fm.get(key):
            try:
                return _as_date(fm[key])
            except DeclarationError:
                return None
    return None


def render(layers=LAYERS, shape="tiers", since: date | None = None) -> str:
    """The maestro.toml `maestro init` writes: one shape, dated today unless told."""
    since = since or date.today()
    return (
        "# Maestro adoption declaration — membership, rule layers, the dated shape history.\n"
        "# Read by the maestro CLI, the hooks and the loaders. Shapes are appended with\n"
        "# `maestro shape add --name=<tiers|other> --since=YYYY-MM-DD`, never edited: a record\n"
        "# is checked under the shape valid at its date, and one dated before the first\n"
        "# entry is history.\n"
        "\n"
        "layers = [" + ", ".join('"%s"' % l for l in layers) + "]\n"
        "\n"
        "[[shape]]\n"
        f'name  = "{shape}"\n'
        f'since = "{since.isoformat()}"\n'
    )


def append_shape(path: Path, name: str, since: date) -> None:
    """Append one `[[shape]]` entry to an existing maestro.toml, refusing to go backwards."""
    if name not in SHAPES:
        raise DeclarationError(f"shape must be one of {list(SHAPES)}, got {name!r}")
    decl = load(path.parent)
    if decl is None or decl.source != path:
        raise DeclarationError(f"{path} is not this project's declaration — run `maestro init` first")
    last = decl.shapes[-1] if decl.shapes else None
    if last is not None and last.since is not None and since <= last.since:
        raise DeclarationError(
            f"`since` {since} is not after the current shape's {last.since} — a shape is "
            "appended in date order; to correct a wrong date, edit the entry and say so in an ADR")
    text = path.read_text()
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + f'\n[[shape]]\nname  = "{name}"\nsince = "{since.isoformat()}"\n')


# ── verbs ─────────────────────────────────────────────────────────────────────

def _root() -> Path:
    from . import frontmatter
    return Path(frontmatter.ROOT)


def describe(decl: Declaration | None) -> list[str]:
    """The declaration as `info show` and `shape show` print it."""
    if decl is None:
        return [f"  none — membership is inferred from docs/ record dirs (transition); "
                f"`maestro init` writes {DECLARATION_FILE}"]
    shapes = ", ".join(f"{s.name} since {s.since or 'always'}" for s in decl.shapes) \
        or "none declared (tiers assumed)"
    return [f"  {decl.source.name}: layers {', '.join(decl.layers)}",
            f"  shapes: {shapes}",
            f"  arcs: {', '.join(decl.arc_names) or 'none declared'}",
            f"  kb_raw: {decl.kb_raw}",
            "  a record dated before the current shape's line is history (cited as written,",
            "  never checked, never repointed); tiers = raw/processed, the layout the checker",
            "  polices; other = the project's own layout, data paths and shas not checked"]


def shape_show(_args=None):
    try:
        decl = load(_root())
    except DeclarationError as exc:
        import sys
        sys.exit(f"maestro shape show: {exc}")
    print("\n".join(["Declaration:", *describe(decl)]))


def shape_add(args):
    import sys
    root = _root()
    path = root / DECLARATION_FILE
    if not path.is_file():
        sys.exit(f"maestro shape add: no {DECLARATION_FILE} at {root} — `maestro init` writes it "
                 "(the pyproject alias holds no shape history).")
    try:
        since = _as_date(args.since)
        if since is None:
            raise DeclarationError("--since is required (YYYY-MM-DD)")
        append_shape(path, args.name, since)
    except DeclarationError as exc:
        sys.exit(f"maestro shape add: {exc}")
    print(f"Appended shape {args.name} since {since} to {DECLARATION_FILE}. Records dated from "
          "there are checked under it; write the ADR that says why.")
