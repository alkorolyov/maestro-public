# Maestro — project templates

Copy the ones you need when scaffolding a new project. Conventions/rationale: [`../design.md`](../design.md); hot rules: [`../core.md`](../core.md).

| File | Copy to | Purpose |
|------|---------|---------|
| `CLAUDE.md` | `<project>/CLAUDE.md` | AI primary-context skeleton (TOC + quick-ref tables, not a textbook) |
| `progress.md` | `docs/progress.md` | active-sprint planning skeleton (≤200 lines) |
| `findings.md` | `docs/findings.md` | curated positive **+ negative** findings (the AI memory of what works) |
| `data.md` | `docs/data.md` | output-file catalog (dataset provenance lives in `docs/data/<name>.md` records) |
| `setup.md` | `docs/setup.md` | environment / infra setup (optional, for complex envs) |
| `kb_meetings.md` | `docs/kb/meetings.md` | meeting-notes skeleton |
| `gitignore` | `<project>/.gitignore` | **rename to `.gitignore`** |
| `pre-commit` | `<project>/.git/hooks/pre-commit` | commit-time guard — `maestro init` **installs it for you** (chmod 755): `maestro docs stamp --check` on every branch, and only `docs/` committed directly on `main` (rule 9). A hook the project already has is never overwritten |
| `pyproject.toml` | merge into `<project>/pyproject.toml` | `[tool.maestro] tracker` switch (`none` \| `wandb` \| `mlflow` — the load-bearing part) + `[pytest]` test-config snippet |
| `exp_NN.md` | *(reference only)* | per-experiment doc shape — `maestro exp new` **generates** the real ones |
| `adr_NN.md` | *(reference only)* | per-ADR shape — `maestro adr new` generates the real ones |
| `data_NN.md` | *(reference only)* | per-dataset record shape — `maestro dataset new` generates the real ones (sha computed; body hand-edited) |

`maestro init` copies the first three rows for you (`CLAUDE.md`, `progress.md`, `findings.md`) and skips any that already exist unless you pass `--force`; it also installs `pre-commit` into `.git/hooks/`. The rest are copied by hand when a project needs them.

The CLI (`tools/maestro_cli/`, invoked as `maestro`) is **not** templated here — that's live code, not a skeleton, and since ADR 10 it is **never copied into a project**: install it once per machine with `bash ../install.sh`, then adopt each project with `maestro init`, which also wires the `.git/info/exclude` entries and the pre-commit guard. The `INDEX.md` files are **generated** by `maestro index render`, never hand-copied.
