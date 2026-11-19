# Environment Setup

---

## Base Environment

**Package + env tool: `uv`** (not pip). The project is a `pyproject.toml` + `uv.lock`
with a `.venv/` that `uv` manages:

```bash
uv sync                              # create .venv + install locked deps
uv add <pkg>                         # add a runtime dependency
uv add --dev <pkg>                   # add a dev/test dependency
uv run python -u script.py           # run anything inside the project env
uv run pytest                        # tests (respects [tool.pytest.ini_options])
```

**Use conda (miniforge) — not uv — only when a dependency needs system libraries a
wheel can't provide**: the CUDA toolchain, or scientific/system libs like `gdal`,
`ffmpeg`, some OpenMPI/OpenBLAS builds. Then the env is a conda env and you run via
`conda run --no-capture-output -n <env> <cmd>` (never `source activate` in scripts —
see maestro `modules/python_env.md`).

- **Python**: {version}
- **Key pins**: {list}

---

## GPU / Hardware

{CUDA version, driver requirements, device-specific notes}

---

## Docker Containers

| Container | Purpose | Build |
|-----------|---------|-------|
| `docker/{name}/` | {what it isolates} | `docker build -t {name} docker/{name}` |

---

## Troubleshooting

- **{Issue}**: {Resolution}
