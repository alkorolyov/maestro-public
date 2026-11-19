# Data Catalog

Pipeline: `data/raw/` (immutable source) → `data/processed/` (derived, regenerable by a script) → `data/experiments/` (per-run outputs). Cross-ref with [experiments/INDEX.md](experiments/INDEX.md).

---

## Raw Data — immutable source, never edited in place

Each dataset under `data/raw/` is a **record**, not a row here: `docs/data/<name>.md` (frontmatter
provenance + description), generated index at [data/INDEX.md](data/INDEX.md). **Create with the CLI**
(never hand-author): `maestro dataset new --name=<name> --version=v1 --source="<url|ref>"` — it computes the
sha256 from the bytes and scaffolds the description. See core.md rule 7.

- Downloaded or project-generated — both get a record; origin goes in the `source` field.
- A new release is a **new version** (`data/raw/<name>/v<N>/`), never an in-place edit.
- Shared big datasets live in `~/data/<name>/v<N>/`, symlinked at version level into `data/raw/`.
- Verify integrity any time: `maestro dataset verify`.

---

## Processed Data — derived, regenerable from raw by a script

Every file here must be 100% reproducible from `data/raw/` (cleaned, filtered, normalized, featurized, descriptors, splits). If it can't be regenerated, it belongs in `raw/` with provenance — not here.

| File | Built from | Description |
|------|------------|-------------|
| `data/processed/{name}` | `data/raw/...` via `scripts/...` | {what it contains (dimensions)} |

---

## Model Checkpoints

| File | Description |
|------|-------------|
| `data/models/{filename}` | {model type + key config + metric} |

---

## Script Outputs (matches exp_XX.py)

| File | Description |
|------|-------------|
| `{NN}_{name}.csv` | {description} |
