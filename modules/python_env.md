# Python Environments (uv / conda)

Load when running Python in a project — choosing how to invoke a script, or setting up
an environment. Values (env names, versions) live in the project's own docs; this module
is the procedure.

- **Detect the project's env manager first, then run with the matching tool.**
  - **uv project** (`pyproject.toml` + `uv.lock`, or a `.venv/` created by uv): run via
    `uv run python -u ...` (or `uv run <cmd>`). Never `conda run` a uv project; never
    `source .venv/bin/activate` inside a tool call.
  - **conda project** (no uv markers; env named in project docs): if the required env is
    already active (`$CONDA_DEFAULT_ENV`), run directly; otherwise
    `conda run --no-capture-output -n <env> <cmd>`.
- **Never** `source .../conda.sh && conda activate <env> && <cmd>` in a fresh shell:
  the activation does not reliably propagate to the command and has silently imported
  from the wrong site-packages. `uv run` / `conda run` are deterministic one-liners.
- Always `python -u` (unbuffered) so long jobs stream output in real time.
- **New projects default to uv.** Reach for conda only when a dependency needs system
  libraries a wheel cannot provide (CUDA toolchain, gdal, ffmpeg, MPI/BLAS builds).
- Library warnings that `warnings.filterwarnings()` / `-W` cannot silence (sklearn,
  LightGBM internals): prefix the command with `PYTHONWARNINGS="ignore::UserWarning"`.
- Launching a long run: check it is not already running (`ps aux | grep <script>` —
  never trust a log file for liveness), background it with output redirected per rule 4
  (`run.log` inside the run dir), and print the `tail -f` command for monitoring.
