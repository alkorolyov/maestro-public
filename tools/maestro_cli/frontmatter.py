"""Shared record I/O — project layout, YAML frontmatter read/write, INDEX re-render.

Every record kind (experiments, ADRs, datasets, epics) is a markdown file whose first block
is YAML frontmatter. This module owns that shape and the paths it lives at, so the
per-kind modules never hardcode a directory or re-implement the parse.
"""
import os
import re
from pathlib import Path

import yaml


def _find_root() -> Path:
    """The maestro project root.

    Normally the package sits at <project>/tools/maestro_cli/, so the root is three
    levels up — the same directory the retired sibling scripts derived from their own
    location. MAESTRO_ROOT overrides it; if the package was installed somewhere else
    entirely, fall back to the nearest ancestor of the working directory that looks
    like a project.
    """
    env = os.environ.get("MAESTRO_ROOT")
    if env:
        return Path(env).resolve()
    # The CLI is machine-level (ADR 10): the CALLER'S project wins. Preferring the
    # package's own checkout was a leftover of the copy-install model — it always has
    # a pyproject.toml, so it silently hijacked ROOT from every other project.
    cwd = Path.cwd().resolve()
    for d in (cwd, *cwd.parents):
        if (d / "docs").is_dir() or (d / "pyproject.toml").is_file():
            return d
    return Path(__file__).resolve().parent.parent.parent


ROOT = _find_root()
DATA_ROOT = ROOT / "data"
EXP_DIR = ROOT / "docs" / "experiments"
ADR_DIR = ROOT / "docs" / "adrs"
EPIC_DIR = ROOT / "docs" / "epics"
DATA_DIR = ROOT / "docs" / "data"
KB_LIT_DIR = ROOT / "docs" / "kb" / "literature"
FINDINGS = ROOT / "docs" / "findings.md"
FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def slugify(s: str) -> str:
    """The filename half of a record: lowercase, and nothing that is not a word.

    A slug becomes a path (`exp_07_<slug>.md`) and, for experiments, the name of a run
    directory too — so a stray `/`, `|` or `..` in it is a broken or misplaced file, not
    a cosmetic problem. Every record kind reduced spaces and lowercased; only datasets
    filtered the rest, and they keep their own variant because a dataset name has to
    match its `data/raw/<name>/` directory verbatim, case included.
    """
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def norm_epic(fm: dict) -> dict:
    """Old epic records say `in_progress`; the status is `active` now. Read both, write one."""
    if fm.get("status") == "in_progress":
        fm["status"] = "active"
    return fm


def load(directory: Path, kind: str) -> dict:
    """Load all records of a given kind from directory. Returns {N: (path, fm)}."""
    records = {}
    if not directory.exists():
        return records
    for p in sorted(directory.glob(f"{kind}_*.md")):
        m = FM_RE.match(p.read_text())
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        if kind in fm:
            if kind == "epic":
                norm_epic(fm)
            records[fm[kind]] = (p, fm)
    return records


def archive_dir(directory: Path) -> Path:
    """Where a record kind's retired files live: docs/<kind>s/ → docs/archive/<kind>s/."""
    return directory.parent / "archive" / directory.name


def archived_nums(directory: Path, kind: str) -> set:
    """Numbers held by archived records of a kind — frontmatter number, else the filename's.

    An archived record is history: it is never listed or checked as live, but its number
    stays taken, so a citation of it keeps meaning one decision. The filename is read too,
    because an archived file is not guaranteed to still carry readable frontmatter.
    """
    nums = set()
    d = archive_dir(directory)
    if not d.is_dir():
        return nums
    if kind == "exp":
        nums |= tombstoned_nums(directory)
    name_re = re.compile(rf"^{kind}_(\d+)")
    for p in d.glob(f"{kind}_*.md"):
        m = name_re.match(p.name)
        if m:
            nums.add(int(m.group(1)))
        fm_m = FM_RE.match(p.read_text(errors="replace"))
        if fm_m:
            try:
                fm = yaml.safe_load(fm_m.group(1)) or {}
            except yaml.YAMLError:
                continue
            if isinstance(fm.get(kind), int):
                nums.add(fm[kind])
    return nums


TOMBSTONE_NAME = "deleted.md"
_TOMBSTONE_RE = re.compile(r"^- exp (\d+) \|", re.MULTILINE)


def tombstone_path(exp_dir: Path) -> Path:
    """docs/archive/experiments/deleted.md: one line per deleted experiment (`exp delete`)."""
    return archive_dir(exp_dir) / TOMBSTONE_NAME


def tombstoned_nums(exp_dir: Path) -> set:
    """Experiment numbers whose record was deleted: taken for good, never reallocated."""
    p = tombstone_path(exp_dir)
    if not p.is_file():
        return set()
    return {int(m) for m in _TOMBSTONE_RE.findall(p.read_text(errors="replace"))}


def next_num(records: dict, directory: Path | None = None, kind: str | None = None) -> int:
    """The next free number: one past every live record AND every archived one.

    A number is never reused (an archived ADR 29 is still what "ADR 29" means in every
    record that cites it), so the archive counts when `directory` and `kind` are given —
    and so do the numbers other local branches and other worktrees already hold, since
    parallel sessions each see only their own tree (`gitstate.taken_elsewhere`).
    """
    taken = set(records.keys())
    if directory is not None and kind is not None:
        from .gitstate import taken_elsewhere
        taken |= archived_nums(directory, kind)
        taken |= taken_elsewhere(directory, kind)
    return max(taken, default=0) + 1


def load_datasets() -> dict:
    """Load dataset records from docs/data/*.md. Keyed by name (not an int). Returns {name: (path, fm)}."""
    records = {}
    if not DATA_DIR.exists():
        return records
    for p in sorted(DATA_DIR.glob("*.md")):
        if p.name == "INDEX.md":
            continue
        m = FM_RE.match(p.read_text())
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        if "dataset" in fm:
            records[fm["dataset"]] = (p, fm)
    return records


# ── the stamp: proof that the CLI wrote what it owns ─────────────────────────
#
# Rule 1 says records are written only via the CLI, and the guard hook enforces it
# for the Write/Edit tools of one harness. Nothing enforced it for a shell (`cat >>`,
# `sed -i`, an inline python) in any harness — which is exactly how an epic log
# and its conformance table were rewritten by hand. So every CLI write
# stamps the record with a hash of the surface the CLI owns — the frontmatter text
# and, for epics, the `## Log` section — and `maestro docs stamp --check` (also
# run inside `docs check`, as a post-tool hook, and at pre-commit) compares the file
# against its stamp. A hand edit of that surface breaks the hash no matter which tool
# or harness made it. Bodies stay hand-edited by design and are not hashed.

STAMP_KEY = "sig"
STAMP_SEP = "\n##ledger##\n"       # wire format — see stamp_of
_STAMP_LINE_RE = re.compile(rf"^{STAMP_KEY}: [0-9a-f]+\n", re.MULTILINE)
_LOG_RE = re.compile(r"^##\s+(?:Log|Ledger)\b[^\n]*\n", re.MULTILINE)
_NEXT_H2_RE = re.compile(r"^## ", re.MULTILINE)


def _log_section(body: str) -> str:
    m = _LOG_RE.search(body)
    if not m:
        return ""
    tail = _NEXT_H2_RE.search(body, m.end())
    return body[m.end():tail.start() if tail else len(body)]


def stamp_of(fm_text: str, body: str) -> str:
    """The stamp for a record whose frontmatter text (sans stamp line) and body are given."""
    import hashlib
    # STAMP_SEP is part of the hashed input. It is a wire-format constant, not prose:
    # changing one character invalidates every stamp in every adopted project.
    # test_stamp pins the format.
    owned = _STAMP_LINE_RE.sub("", fm_text) + STAMP_SEP + _log_section(body)
    return hashlib.sha256(owned.encode("utf-8")).hexdigest()[:16]


def split(text: str):
    """(frontmatter text, body) of a record, or None when it has no frontmatter block."""
    m = FM_RE.match(text)
    if not m:
        return None
    return m.group(1) + "\n", text[m.end():]


def stamp_status(path: Path) -> str:
    """'ok' | 'mismatch' | 'unstamped' | 'no-frontmatter' for one record file."""
    parts = split(path.read_text())
    if parts is None:
        return "no-frontmatter"
    fm_text, body = parts
    m = _STAMP_LINE_RE.search(fm_text)
    if not m:
        return "unstamped"
    return "ok" if m.group(0) == f"{STAMP_KEY}: {stamp_of(fm_text, body)}\n" else "mismatch"


def restamp(path: Path) -> None:
    """Re-sign a record AS IT IS on disk, without re-serialising its frontmatter.

    The adoption step (`maestro docs stamp --accept`), and the deliberate way to bless a
    hand fix. It never reformats a record: only the stamp line is inserted or replaced.
    """
    fm_text, body = split(path.read_text())
    bare = _STAMP_LINE_RE.sub("", fm_text)
    path.write_text("---\n" + bare + f"{STAMP_KEY}: {stamp_of(bare, body)}\n---\n" + body)


def write(path: Path, fm: dict, body: str = "") -> None:
    fm = {k: v for k, v in fm.items() if k != STAMP_KEY}
    fm_text = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    path.write_text("---\n" + fm_text + f"{STAMP_KEY}: {stamp_of(fm_text, body)}\n---\n" + body)


def record_files():
    """Every record file the CLI owns, in a stable order."""
    out = []
    for d, pat in ((EXP_DIR, "exp_*.md"), (ADR_DIR, "adr_*.md"), (EPIC_DIR, "epic_*.md")):
        if d.exists():
            out.extend(sorted(d.glob(pat)))
    if DATA_DIR.exists():
        out.extend(p for p in sorted(DATA_DIR.glob("*.md")) if p.name != "INDEX.md")
    return out


def render() -> None:
    """Regenerate every INDEX.md after a record write (imported late: indexes reads this module)."""
    from . import indexes
    indexes.render("all")


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)
