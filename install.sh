#!/usr/bin/env bash
# Bootstrap maestro (ADR 10): install the CLI machine-wide, then hand off to `maestro init`.
#
# Usage:
#   bash install.sh              # install the CLI, then set this machine up
#   bash install.sh --dry-run    # install the CLI, then only REPORT what init would change
#
# The CLI is MACHINE-LEVEL (ADR 10): one isolated environment with its own Python, so a
# project needs no virtualenv and nothing is copied into it. The rest is tested Python now:
#
#   maestro init --harness           record-guard + kb-index-regen hooks
#                                    → ~/.claude/settings.json
#   maestro init --path <project>    project layout, drift-check Stop hook, git excludes,
#                                    deletion of tool copies left by the old model
#
# `maestro.tracking` is the separate artefact — the CLI's environment is sealed, so a
# project that LOGS runs needs the library in its own env. Turning a tracker on does it:
#   maestro init --path <project> --tracker=wandb    (uv add maestro[tracking])

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DRY=""
case "${1:-}" in
  "")        ;;
  --dry-run) DRY="--dry-run" ;;
  -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
  *)         echo "Unknown argument: $1 (use [--dry-run])" >&2; exit 2 ;;
esac

if command -v uv >/dev/null 2>&1; then
  uv tool install --force "$REPO_DIR"
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force "$REPO_DIR"
else
  echo "Neither uv nor pipx is on PATH; one of them is required (ADR 10)." >&2
  echo "  uv: https://docs.astral.sh/uv/   ·   pipx: https://pipx.pypa.io/" >&2
  exit 1
fi

if command -v maestro >/dev/null 2>&1; then
  MAESTRO_REPO="$REPO_DIR" maestro init --harness $DRY
  echo ""
  echo "Next, in each project:  maestro init --path <project-path>"
else
  echo "'maestro' is not on PATH yet — add the tool bin directory (uv tool update-shell),"
  echo "then run:  MAESTRO_REPO=$REPO_DIR maestro init --harness"
fi
