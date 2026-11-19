"""Deterministic dataset hashing — the single source of truth for dataset shas.

A dataset is a STABLE SET OF FILES (min 1) at a path under `data/` — usually a directory,
sometimes a single loose file. This computes ONE digest for the whole set so a dataset
version has a single content-addressed identity for its docs/data/<name>.md record.

A record locates its bytes by a `path:` field relative to `data/` (e.g.
`processed/cohorts/PAMPA_TRUSTED.csv`, or `raw/scott_lokey/v2`). When a record carries no
`path`, the path defaults to `raw/<name>[/<version>]` — so the raw/processed split is just a
folder convention, not something the record schema knows about.

Imported by both datasets.py (writes the sha) and checks.py (re-verifies it).
Keeping ONE implementation guarantees the stored sha and the recomputed sha can never diverge.
"""
import hashlib
from pathlib import Path


# Volatile sidecars a database writes NEXT TO its data file. They are journal/cache
# state, not dataset content: SQLite creates `-wal`/`-shm` on any connection and rewrites
# them on a READ, so folding them in makes a dataset's sha change merely because someone
# opened it. That fires the drift check as "data changed in place (breaks immutability)"
# when nothing changed, e.g. a test that replays a corpus dirties its own provenance record. The
# durable bytes (the `.sqlite` file itself) are still hashed, so real edits are still caught.
VOLATILE_SUFFIXES = ("-wal", "-shm", "-journal")


def _is_volatile(p: Path) -> bool:
    return p.name.endswith(VOLATILE_SUFFIXES)


def hash_fileset(base: Path) -> str:
    """sha256 of the file-set at `base` (a file or a directory). '' if `base` is absent.

    Folds (relative_posix_path, file_sha256) for every file in sorted order into one digest.
    The formula is identical for a 1-file set and a 1000-file set, so a dataset that grows
    stays comparable. Follows symlinks (shared datasets under ~/data). Database sidecars
    (see VOLATILE_SUFFIXES) are skipped so reading a dataset cannot change its sha."""
    if not base.exists():
        return ""
    if base.is_file():
        files, root = [base], base.parent
    else:
        files, root = sorted(p for p in base.rglob("*") if p.is_file() and not _is_volatile(p)), base
    fold = hashlib.sha256()
    for p in files:
        fold.update(p.relative_to(root).as_posix().encode())
        fold.update(b"\0")
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        fold.update(h.hexdigest().encode())
        fold.update(b"\n")
    return fold.hexdigest()


def resolve_base(data_root: Path, name: str, version: str = "", path: str = "") -> Path:
    """Absolute path to a dataset's bytes. `path` (relative to data_root) wins; else
    `raw/<name>[/<version>]` (the legacy default for records with no `path`)."""
    if path:
        return data_root / path
    base = data_root / "raw" / name
    return base / version if version else base


def dataset_sha_rel(data_root: Path, name: str, version: str = "", path: str = "") -> str:
    """sha256 of a dataset located by (`path` relative to `data_root`) or the legacy
    `raw/<name>[/<version>]` default. The single entry point for datasets.py / checks.py."""
    return hash_fileset(resolve_base(data_root, name, version, path))


def dataset_sha(raw_dir: Path, name: str, version: str = "") -> str:
    """Legacy path-free API: sha256 of the file-set under `raw_dir/<name>[/<version>]`.
    Retained for callers that hash a raw dataset directly; new code uses dataset_sha_rel."""
    base = raw_dir / name
    if version:
        base = base / version
    return hash_fileset(base)
