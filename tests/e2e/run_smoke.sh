#!/usr/bin/env bash
# Maestro end-to-end smoke harness.
#
# Starts from a NON-set-up toy project (tests/e2e/seed/), adopts it as a maestro
# project from zero in a throwaway /tmp dir, runs the whole flow, exercises BOTH
# trackers (mlflow + wandb), and prints PASS/FAIL for each feature.
#
# Run:   bash tests/e2e/run_smoke.sh
# Needs: ~/.env (tracker creds), running mlflow + wandb docker services, uv on PATH
#        (which fetches the tracker clients and the kb embedder per call).
# Leaves /tmp/maestro-smoke in place for inspection.
#
# NOTE: NOT `set -e` — we keep going past failures and record each one.
set -uo pipefail

# ── locations ────────────────────────────────────────────────────────────────
# The checkout under test is the one this script lives in — never a hardcoded path,
# so the harness runs from any clone on any machine.
MAESTRO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SEED="$MAESTRO/tests/e2e/seed"
GUARD="$MAESTRO/global/hooks/guard_records.py"
WORK="/tmp/maestro-smoke"

PY="python3"
# The CLI under test is this checkout's (machine-level, never copied into a
# project). PYTHONPATH pins it so a differently versioned `maestro` on PATH cannot
# shadow the code being smoke-tested.
export PYTHONPATH="$MAESTRO/tools"
MCLI="$PY -m maestro_cli.cli"

SLUG_BREIMAN="random_forests_breiman"   # the fixture kb entry, seeded below

N_PASS=0
N_FAIL=0

pass() { echo "PASS $1: ${2:-}"; N_PASS=$((N_PASS + 1)); }
fail() { echo "FAIL $1: ${2:-}"; N_FAIL=$((N_FAIL + 1)); }

# check <feature> <note-on-pass>  — uses last command's exit status
# (call `chk` right after the command you want to judge)
hr() { echo "── $1 ──"; }

# ── 0. fresh throwaway project ───────────────────────────────────────────────
hr "setup: fresh /tmp project"
rm -rf "$WORK"
mkdir -p "$WORK"
cp -r "$SEED"/. "$WORK"/
cd "$WORK" || { echo "FATAL: cannot cd $WORK"; exit 2; }

git init -q
# Throwaway identity: the /tmp repo only needs commits to be possible, and the
# caller's own git identity must not leak into it.
git config --local user.name "maestro smoke"
git config --local user.email "maestro-smoke@example.invalid"
git add -A >/dev/null 2>&1
git commit -qm "seed: toy project before maestro adoption" >/dev/null 2>&1
if [ -d "$WORK/.git" ] && [ ! -d "$WORK/docs" ] && [ ! -d "$WORK/tools" ]; then
  pass "seed_project" "fresh non-maestro toy project at $WORK"
else
  fail "seed_project" "seed dir not in expected pre-adoption state"
fi

# ── 1. adopt as a maestro project ────────────────────────────────────────────
hr "adopt"
$MCLI init --path="$WORK" --repo="$MAESTRO" >/tmp/smoke_install.log 2>&1
# Drift is caught at pre-commit, so adoption installs the pre-commit hook and wires
# no Stop hook.
if [ -d "$WORK/docs/experiments" ] && [ -d "$WORK/data/experiments" ] \
   && grep -q "^# maestro pre-commit v" "$WORK/.git/hooks/pre-commit" 2>/dev/null \
   && ! grep -qs "maestro docs check" "$WORK/.claude/settings.json" \
   && grep -qxF "docs/" "$WORK/.git/info/exclude" 2>/dev/null; then
  pass "adopt_tools" "layout scaffolded, pre-commit hook installed, no Stop hook, git excludes added"
else
  fail "adopt_tools" "maestro init did not adopt the project (see /tmp/smoke_install.log)"
fi

# uv manages this project from here on, so `init --tracker=` can `uv add` the tracking
# library into it. (`uv run` would create the venv lazily later; init needs it to exist
# before it can tell a uv project from a conda one.)
uv venv -q --project "$WORK" "$WORK/.venv" >/dev/null 2>&1 || (cd "$WORK" && uv venv -q >/dev/null 2>&1)

# the wandb run uses maestro.tracking's clean-tree gate (counts untracked files);
# keep regenerable artifacts + the uv venv out of git so the tree can be clean.
printf 'data/\n.venv/\nwandb/\nmlruns/\n__pycache__/\n*.pyc\n' > "$WORK/.gitignore"

# CLAUDE.md from template + append the KB-topics snippet
cp "$MAESTRO/templates/CLAUDE.md" "$WORK/CLAUDE.md"
cat "$SEED/claude_md_fill.md" >> "$WORK/CLAUDE.md"
if grep -q "## Knowledge Base" "$WORK/CLAUDE.md"; then
  pass "fill_claude_md" "CLAUDE.md templated + KB-topics snippet appended"
else
  fail "fill_claude_md" "KB snippet not present in CLAUDE.md"
fi

# docs skeletons
mkdir -p "$WORK/docs"
cp "$MAESTRO/templates/progress.md" "$WORK/docs/progress.md"
cp "$MAESTRO/templates/findings.md" "$WORK/docs/findings.md"
if [ -f "$WORK/docs/progress.md" ] && [ -f "$WORK/docs/findings.md" ]; then
  pass "docs_skeletons" "progress.md + findings.md placed in docs/"
else
  fail "docs_skeletons" "progress/findings skeletons missing"
fi

# ── 2. tracker config in pyproject ───────────────────────────────────────────
hr "tracker config"
# `init` writes the block itself, off by default; the SWITCH is what this exercises, so
# it goes through `init --tracker=` rather than appending the section by hand.
# Match the section header at line start (a comment mentioning it doesn't count).
if ! grep -qE '^\[tool\.maestro\]' "$WORK/pyproject.toml"; then
  fail "tracker_config" "init did not write the [tool.maestro] block"
elif ! grep -qE '^tracker = "none"' "$WORK/pyproject.toml"; then
  fail "tracker_config" "init wrote [tool.maestro] but tracker is not the default 'none'"
else
  # --dep-source points at THIS checkout: the default is a pinned git URL, which
  # would test a released version instead of this one.
  $MCLI init --path="$WORK" --repo="$MAESTRO" --tracker=mlflow --dep-source="$MAESTRO" \
    >/tmp/smoke_tracker.log 2>&1
  if ! grep -qE '^tracker = "mlflow"' "$WORK/pyproject.toml"; then
    fail "tracker_config" "--tracker=mlflow did not switch the block (see /tmp/smoke_tracker.log)"
  elif (cd "$WORK" && uv run python -c "import maestro.tracking" >/dev/null 2>&1); then
    pass "tracker_config" "init switched to mlflow and uv-added maestro[tracking] (import resolves)"
  else
    fail "tracker_config" "tracker switched but maestro.tracking does not import (see /tmp/smoke_tracker.log)"
  fi
fi

# ── 3. dataset: dump wine, register, assert sha + record + INDEX ─────────────
hr "dataset"
mkdir -p "$WORK/data/raw/wine"
uv run --no-project --with scikit-learn --with pandas $PY - <<'PY' >/tmp/smoke_wine.log 2>&1
import pandas as pd
from sklearn.datasets import load_wine
d = load_wine(as_frame=True)
df = d.frame.rename(columns={"target": "target"})
df.to_csv("data/raw/wine/wine.csv", index=False)
print("wrote", len(df), "rows")
PY
if [ -f "$WORK/data/raw/wine/wine.csv" ]; then
  pass "dataset_dump" "wine.csv written to data/raw/wine/"
else
  fail "dataset_dump" "wine.csv not written (see /tmp/smoke_wine.log)"
fi

$MCLI dataset new --name=wine --source=sklearn >/tmp/smoke_datanew.log 2>&1
DATA_RC=$?
if [ $DATA_RC -eq 0 ] && [ -f "$WORK/docs/data/wine.md" ] \
   && grep -qiE '^sha256:\s*[0-9a-f]{16,}' "$WORK/docs/data/wine.md"; then
  pass "dataset_record" "docs/data/wine.md created with computed sha256"
else
  fail "dataset_record" "dataset new failed or sha missing (see /tmp/smoke_datanew.log)"
fi
if [ -f "$WORK/docs/data/INDEX.md" ] && grep -q "wine" "$WORK/docs/data/INDEX.md"; then
  pass "dataset_index" "docs/data/INDEX.md regenerated with wine"
else
  fail "dataset_index" "data INDEX missing or lacks wine"
fi

# ── 4. literature: kb entry, index, gate both ways, staleness, render ───────
# No DOI fetch: the paper-fetch tool lives outside this repo, and a harness cannot
# assert a tool this repo does not ship.
hr "literature"
mkdir -p "$WORK/docs/kb/literature/raw"

# deterministic fixture kb entry (agent-written summaries are not scriptable)
cp "$SEED/fixtures/$SLUG_BREIMAN.md" "$WORK/docs/kb/literature/$SLUG_BREIMAN.md"
if [ -f "$WORK/docs/kb/literature/$SLUG_BREIMAN.md" ]; then
  pass "kb_entry" "fixture Breiman kb entry placed in docs/kb/literature/"
else
  fail "kb_entry" "fixture kb entry not placed"
fi

# build + search the semantic index in an isolated env
uv run --no-project --with fastembed --with numpy $PY -m maestro_cli.cli kb build \
    >/tmp/smoke_kbbuild.log 2>&1
if grep -qiE 'built [0-9]+ entries' /tmp/smoke_kbbuild.log; then
  pass "kb_index_build" "vector index built ($(grep -oiE 'built [0-9]+ entries' /tmp/smoke_kbbuild.log | head -1))"
else
  fail "kb_index_build" "index build failed (see /tmp/smoke_kbbuild.log)"
fi
if [ -f "$WORK/docs/kb/.index/meta.json" ] && [ -f "$WORK/docs/kb/.index/vectors.npy" ]; then
  pass "kb_index_files" "vector index artifacts present (docs/kb/.index/ meta.json + vectors.npy)"
else
  fail "kb_index_files" "vector index files missing under docs/kb/.index/"
fi

uv run --no-project --with fastembed --with numpy $PY -m maestro_cli.cli kb search \
    --query="random forest bagging decision tree ensemble" >/tmp/smoke_kbsearch.log 2>&1
if grep -q "RELEVANT" /tmp/smoke_kbsearch.log \
   && grep -q "$SLUG_BREIMAN" /tmp/smoke_kbsearch.log; then
  pass "kb_search" "fixture paper returned RELEVANT for a tree-ensemble query"
else
  fail "kb_search" "search did not return Breiman as RELEVANT (see /tmp/smoke_kbsearch.log)"
fi

# The gate must also say NO. A search step that only ever asks an on-topic question
# cannot tell a working gate from one that answers RELEVANT to everything.
uv run --no-project --with fastembed --with numpy $PY -m maestro_cli.cli kb search \
    --query="how do I renew my passport at the embassy" >/tmp/smoke_kbgate.log 2>&1
if grep -q "NO STRONG MATCH" /tmp/smoke_kbgate.log; then
  pass "kb_gate_rejects" "off-topic query gated out ($(grep -oE 'top=[0-9.]+ < gate [0-9.]+' /tmp/smoke_kbgate.log | head -1))"
else
  fail "kb_gate_rejects" "off-topic query was not gated out (see /tmp/smoke_kbgate.log)"
fi

uv run --no-project --with fastembed --with numpy $PY -m maestro_cli.cli kb selftest \
    >/tmp/smoke_kbselftest.log 2>&1
if [ $? -eq 0 ] && grep -q "\[PASS\] freshness" /tmp/smoke_kbselftest.log; then
  pass "kb_selftest" "selftest green on the freshly built index"
else
  fail "kb_selftest" "selftest did not pass clean (see /tmp/smoke_kbselftest.log)"
fi

# Staleness: an entry added after the build must be REPORTED, not silently missed.
# The probe is removed again before the INDEX render, so it never reaches a record.
cat > "$WORK/docs/kb/literature/_drift_probe.md" <<'PROBE'
---
title: A Probe Entry Added After The Index Was Built
tags: drift
---

## Abstract

Placed after `kb build` so the index no longer covers the corpus on disk.
PROBE
uv run --no-project --with fastembed --with numpy $PY -m maestro_cli.cli kb search \
    --query="random forest bagging decision tree ensemble" >/tmp/smoke_kbstale.log 2>&1
uv run --no-project --with fastembed --with numpy $PY -m maestro_cli.cli kb selftest \
    >/tmp/smoke_kbstale_selftest.log 2>&1
STALE_RC=$?
rm -f "$WORK/docs/kb/literature/_drift_probe.md"
if grep -q "STALE" /tmp/smoke_kbstale.log && grep -q "_drift_probe" /tmp/smoke_kbstale.log \
   && grep -q "VERDICT:" /tmp/smoke_kbstale.log; then
  pass "kb_stale_search" "search warned the index was stale and still answered"
else
  fail "kb_stale_search" "stale index went unreported by search (see /tmp/smoke_kbstale.log)"
fi
if [ "$STALE_RC" -ne 0 ] && grep -q "\[FAIL\] freshness" /tmp/smoke_kbstale_selftest.log; then
  pass "kb_stale_selftest" "selftest failed on the stale index (exit $STALE_RC)"
else
  fail "kb_stale_selftest" "selftest passed a stale index (see /tmp/smoke_kbstale_selftest.log)"
fi

$MCLI index render --kind=all >/tmp/smoke_render.log 2>&1
if [ -f "$WORK/docs/kb/literature/INDEX.md" ]; then
  pass "kb_render_index" "docs/kb/literature/INDEX.md generated"
else
  fail "kb_render_index" "literature INDEX.md not generated (see /tmp/smoke_render.log)"
fi

# ── 5. experiment ×2 trackers (mlflow then wandb) ────────────────────────────
hr "experiment runs (both trackers)"
mkdir -p "$WORK/data/experiments/exp_01_rf_baseline"

# Scaffold the exp record FIRST — `maestro runs fetch --exp=1` resolves the run group
# by finding docs/experiments/exp_01_*.md, so the record must exist before readback.
$MCLI exp new --slug=rf_baseline >/tmp/smoke_expnew.log 2>&1
if ls "$WORK"/docs/experiments/exp_01_rf_baseline.md >/dev/null 2>&1 \
   && grep -q "rf_baseline" "$WORK/docs/experiments/INDEX.md"; then
  pass "exp_new" "exp_01_rf_baseline record created + experiments INDEX regenerated"
else
  fail "exp_new" "exp new failed (see /tmp/smoke_expnew.log)"
fi

if [ -f "$HOME/.env" ]; then
  set -a; source "$HOME/.env"; set +a
else
  echo "  ! ~/.env not found — tracker creds unavailable; tracker steps will likely FAIL."
fi

run_tracker() {
  local TR="$1"
  hr "tracker=$TR"
  # point pyproject (and so `maestro runs`) at this tracker
  $PY - "$TR" <<'PY'
import re, sys
tr = sys.argv[1]
p = "pyproject.toml"
s = open(p).read()
s = re.sub(r'(?m)^tracker\s*=.*$', f'tracker = "{tr}"', s)
open(p, "w").write(s)
PY
  export MAESTRO_TRACKER="$TR"
  # maestro.tracking (wandb leg) refuses to log from a dirty tree; commit so git_sha
  # reflects the run's code. Harmless for the mlflow leg (raw, no gate).
  git add -A >/dev/null 2>&1
  git commit -qm "smoke: clean tree before $TR run" >/dev/null 2>&1 || true
  # Fail-fast preflight (wandb only): the self-hosted W&B homepage returns 200 even
  # when its run-init backend is wedged, which can hang wandb.init ~90s and orphan
  # wandb-core daemons. A bounded viewer query catches a dead/wedged server fast.
  if [ "$TR" = wandb ]; then
    if timeout 25 uv run --with wandb $PY - >/tmp/smoke_wandb_ping.log 2>&1 <<'PY'
import sys, wandb
try:
    wandb.Api(timeout=15).viewer
    print("WANDB_OK")
except Exception as e:
    print("WANDB_DOWN:", str(e)[:120]); sys.exit(1)
PY
    then
      pass "wandb_online" "W&B server responsive (viewer query within 25s)"
    else
      fail "wandb_online" "W&B server not responding within 25s — skipping wandb run/readback (see /tmp/smoke_wandb_ping.log)"
      pkill -f 'wandb-core' >/dev/null 2>&1
      pkill -f 'wandb-xpu' >/dev/null 2>&1
      return
    fi
  fi
  # Canonical run.log (maestro rule) + a per-tracker copy so the second tracker's
  # run doesn't clobber the first's for inspection.
  local LOG="data/experiments/exp_01_rf_baseline/run_1/run.log"
  mkdir -p "$(dirname "$LOG")"
  timeout -k 10 200 uv run --with scikit-learn --with pandas --with "$TR" $PY -u \
      experiments/exp_01_rf_baseline.py > "$LOG" 2>&1
  local RUN_RC=$?
  pkill -f 'wandb-core' >/dev/null 2>&1
  pkill -f 'wandb-xpu' >/dev/null 2>&1
  cp "$LOG" "data/experiments/exp_01_rf_baseline/run.$TR.log"
  if [ $RUN_RC -eq 0 ] && grep -q "accuracy=" "$LOG"; then
    pass "${TR}_run" "exp_01 logged a run to $TR ($(grep -oE 'accuracy=[0-9.]+' "$LOG" | head -1))"
  else
    fail "${TR}_run" "exp_01 run failed under $TR (rc=$RUN_RC; see $WORK/$LOG)"
    return
  fi
  # Read the metric back through the CLI. No `--with` here on purpose: `maestro runs`
  # re-execs itself under `uv run --with $TR`, and that self-loading is part of what
  # this step is testing.
  $MCLI runs fetch --exp=1 --metric=accuracy >/tmp/smoke_readback_$TR.log 2>&1
  if grep -qE 'accuracy = [0-9.]+' /tmp/smoke_readback_$TR.log; then
    pass "${TR}_readback" "maestro runs fetch --exp=1 returned accuracy from $TR"
  else
    fail "${TR}_readback" "maestro runs fetch did not return accuracy from $TR (see /tmp/smoke_readback_$TR.log)"
  fi
}

run_tracker mlflow
run_tracker wandb

# the wandb run goes through maestro.tracking → assert three-leg provenance landed
hr "wandb provenance (maestro.tracking)"
$MCLI runs fetch --exp=1 --json >/tmp/smoke_prov.log 2>&1
if grep -q "exp_code_sha" /tmp/smoke_prov.log && grep -q "dataset_sha" /tmp/smoke_prov.log; then
  pass "wandb_provenance" "wandb run carries exp_code_sha + dataset_sha (3-leg provenance)"
else
  fail "wandb_provenance" "provenance fields missing from wandb run (see /tmp/smoke_prov.log)"
fi

# negative: a dirty tracked tree must BLOCK a maestro.tracking run
hr "clean-tree gate (negative)"
echo "" >> pyproject.toml   # dirty a tracked file
GATE_OUT=$(uv run --with wandb --with numpy $PY - <<'PY' 2>&1
from maestro.tracking import start_run
try:
    start_run(exp_n=1, slug="rf_baseline", variant="gatecheck",
              dataset="wine", mode="disabled")
    print("NO_RAISE")
except RuntimeError as e:
    print("BLOCKED" if "dirty" in str(e).lower() else "OTHER:" + str(e)[:80])
except Exception as e:
    print("ERR:" + str(e)[:80])
PY
)
git checkout -- pyproject.toml >/dev/null 2>&1
if echo "$GATE_OUT" | grep -q "BLOCKED"; then
  pass "gate_blocks_dirty" "maestro.tracking refused to log from a dirty tree"
else
  fail "gate_blocks_dirty" "clean-tree gate did not block (got: $GATE_OUT)"
fi

# leave pyproject on mlflow for the remaining record steps (drift, etc.)
$PY - <<'PY'
import re
p = "pyproject.toml"
s = open(p).read()
s = re.sub(r'(?m)^tracker\s*=.*$', 'tracker = "mlflow"', s)
open(p, "w").write(s)
PY

# ── 6. records: exp update / finding / adr (exp new ran in step 5) ───────────
hr "records"
# outcome=improved requires --track + --metric (CLI validation); supply them.
$MCLI exp update --id=1 --status=done --outcome=improved \
    --track="wine-holdout" --metric="accuracy=1.0" \
    --best-run="exp_01_rf_baseline__baseline__s0" \
    --takeaway="RF is a solid low-tuning baseline on wine." >/tmp/smoke_expupd.log 2>&1
if grep -qiE '^outcome:\s*improved' "$WORK/docs/experiments/exp_01_rf_baseline.md"; then
  pass "exp_update" "exp update wrote outcome=improved to frontmatter"
else
  fail "exp_update" "exp update did not set outcome (see /tmp/smoke_expupd.log)"
fi

$MCLI exp finding --id=1 \
    --text="Random forest reaches high accuracy on the wine set with no tuning." \
    >/tmp/smoke_finding.log 2>&1
if grep -qi "Random forest reaches high accuracy" "$WORK/docs/findings.md"; then
  pass "exp_finding" "exp finding appended to docs/findings.md"
else
  fail "exp_finding" "finding not appended (see /tmp/smoke_finding.log)"
fi

$MCLI adr new --slug=use_mlflow_tracker >/tmp/smoke_adrnew.log 2>&1
if ls "$WORK"/docs/adrs/adr_01_use_mlflow_tracker.md >/dev/null 2>&1 \
   && grep -q "use_mlflow_tracker" "$WORK/docs/adrs/INDEX.md"; then
  pass "adr_new" "adr_01 created + adrs INDEX regenerated"
else
  fail "adr_new" "adr new failed (see /tmp/smoke_adrnew.log)"
fi

# ── 6b. varied NON-ML experiment kinds (analysis / sweep / infra) ────────────
# Much research work is non-ML: data analysis, sweeps that come back
# negative, and infra timing. These record with outcome + a prose takeaway and
# leave the ML fields (metric/track/n_seeds/n_runs/best_run) BLANK — that's the
# whole point of this section. Each runs stdlib+sklearn only, logs next to its
# data (never /tmp), then is recorded via the maestro CLI and asserted.
hr "non-ML experiment kinds"

# run_nonml <slug> <script> <outcome> <takeaway-prefix>
#   runs the script → data/experiments/exp_NN_<slug>/run_1/run.log,
#   creates the record, sets a realistic body containing the printed number,
#   and sets status=done + outcome (+ takeaway), WITHOUT any ML flags.
run_nonml() {
  local SLUG="$1" SCRIPT="$2" OUTCOME="$3" TAKE_PREFIX="$4"
  hr "exp $SLUG ($OUTCOME)"

  # 1) run it, capturing stdout into the canonical run.log under the data dir.
  #    The exp number isn't known until `exp new` runs, so stage the log under a
  #    temp dir keyed by slug, then move it into place once the number is known.
  local STAGE="data/experiments/_stage_$SLUG"
  mkdir -p "$STAGE"
  uv run --no-project --with scikit-learn --with pandas $PY -u \
      "experiments/$SCRIPT" > "$STAGE/run.log" 2>&1
  local RUN_RC=$?
  # Grab the first "<key>=<number>" token printed by the script (the key may
  # contain parens/commas, e.g. pearson_r(flavanoids, total_phenols)=0.86).
  local PRINTED
  PRINTED=$(grep -oE '[A-Za-z_][A-Za-z_(), ]*=-?[0-9][0-9.]*' "$STAGE/run.log" | head -1)
  if [ $RUN_RC -eq 0 ] && [ -n "$PRINTED" ]; then
    pass "${SLUG}_run" "ran experiments/$SCRIPT ($PRINTED)"
  else
    fail "${SLUG}_run" "experiments/$SCRIPT failed (rc=$RUN_RC; see $WORK/$STAGE/run.log)"
    return
  fi

  # 2) create the record. Snapshot the INDEX content first; `exp new` must
  #    regenerate it to list the new slug (content check, not mtime — same-second
  #    writes share an mtime so a checksum/content compare is the robust signal).
  local IDX="docs/experiments/INDEX.md"
  local IDX_BEFORE; IDX_BEFORE=$(md5sum "$IDX" 2>/dev/null | cut -d' ' -f1)
  $MCLI exp new --slug="$SLUG" >/tmp/smoke_nonml_${SLUG}_new.log 2>&1
  local NEWFILE; NEWFILE=$(ls docs/experiments/exp_*_"$SLUG".md 2>/dev/null | head -1)
  local IDX_AFTER; IDX_AFTER=$(md5sum "$IDX" 2>/dev/null | cut -d' ' -f1)
  if [ -n "$NEWFILE" ] && grep -q "$SLUG" "$IDX"; then
    pass "${SLUG}_new" "record $(basename "$NEWFILE") created + in experiments INDEX"
  else
    fail "${SLUG}_new" "exp new failed (see /tmp/smoke_nonml_${SLUG}_new.log)"
    return
  fi
  if [ "$IDX_AFTER" != "$IDX_BEFORE" ] && grep -q "$SLUG" "$IDX"; then
    pass "${SLUG}_new_index" "exp new regenerated experiments INDEX (now lists $SLUG)"
  else
    fail "${SLUG}_new_index" "experiments INDEX not regenerated by exp new"
  fi

  # 3) move the staged run.log into the real data dir next to the record.
  local EXPDIR="data/experiments/$(basename "$NEWFILE" .md)"
  mkdir -p "$EXPDIR"
  mkdir -p "$EXPDIR/run_1"
  mv "$STAGE/run.log" "$EXPDIR/run_1/run.log"
  rmdir "$STAGE" 2>/dev/null
  if [ -f "$EXPDIR/run_1/run.log" ]; then
    pass "${SLUG}_log" "run.log lives in its run dir at $EXPDIR/run_1/run.log (not /tmp)"
  else
    fail "${SLUG}_log" "run.log not placed under $EXPDIR/run_1/ (ADR 3)"
  fi

  # 4) fill the body via set-body with a realistic prose takeaway containing the
  #    printed number, then set status=done + outcome + takeaway. Note: NO ML
  #    flags (--metric/--track/--n-runs/--best-run) — these are non-ML.
  local EXPNUM; EXPNUM=$(basename "$NEWFILE" | sed -E 's/^exp_0*([0-9]+)_.*/\1/')
  local TAKEAWAY="$TAKE_PREFIX $PRINTED."
  printf '\n# %s\n\n**Method**: see experiments/%s; stdout in %s/run_1/run.log.\n\n**Takeaway**: %s\n' \
      "$SLUG" "$SCRIPT" "$EXPDIR" "$TAKEAWAY" \
      | $MCLI exp set_body --id="$EXPNUM" --from-stdin \
      >/tmp/smoke_nonml_${SLUG}_body.log 2>&1

  local IDX_B2; IDX_B2=$(md5sum "$IDX" 2>/dev/null | cut -d' ' -f1)
  $MCLI exp update --id="$EXPNUM" --status=done --outcome="$OUTCOME" \
      --takeaway="$TAKEAWAY" >/tmp/smoke_nonml_${SLUG}_upd.log 2>&1
  local UPD_RC=$?
  local IDX_A2; IDX_A2=$(md5sum "$IDX" 2>/dev/null | cut -d' ' -f1)
  if [ $UPD_RC -eq 0 ] && grep -qiE "^outcome:\s*$OUTCOME" "$NEWFILE"; then
    pass "${SLUG}_outcome" "recorded outcome=$OUTCOME (no ML fields passed)"
  else
    fail "${SLUG}_outcome" "exp update rejected outcome=$OUTCOME — $(cat /tmp/smoke_nonml_${SLUG}_upd.log)"
  fi
  # The update flips status planned→done + writes the outcome, so the regenerated
  # INDEX content must change (status/outcome columns) vs the post-`exp new` state.
  if [ "$IDX_A2" != "$IDX_B2" ]; then
    pass "${SLUG}_upd_index" "exp update regenerated experiments INDEX (content changed)"
  else
    fail "${SLUG}_upd_index" "experiments INDEX not regenerated by exp update"
  fi
}

run_nonml feature_correlation exp_02_feature_correlation.py confirmed \
    "Flavanoids and total_phenols move together on wine; Pearson r is"
run_nonml depth_sweep exp_03_depth_sweep.py refuted \
    "Deeper RandomForest trees do not beat the shallow baseline on wine; best held at"
run_nonml featurize_speed exp_04_featurize_speed.py infra \
    "Load+standardize of the wine table is fast; mean per pass"

# ── 6c. assert the non-ML adaptation: exp_02 has outcome+takeaway, NO ML fields ─
hr "non-ML record shape (exp_02)"
E2=$(ls docs/experiments/exp_*_feature_correlation.md 2>/dev/null | head -1)
# Slice the YAML frontmatter (between the first two '---' lines) and check it.
if [ -n "$E2" ]; then
  FM2=$(awk 'NR==1&&/^---/{f=1;next} f&&/^---/{exit} f{print}' "$E2")
  HAS_OUTCOME=$(printf '%s\n' "$FM2" | grep -cE '^outcome:\s*\S')
  HAS_TAKEAWAY=$(printf '%s\n' "$FM2" | grep -cE '^takeaway:\s*\S')
  HAS_ML=$(printf '%s\n' "$FM2" | grep -cE '^(metric|track|n_runs|best_run):')
  if [ "$HAS_OUTCOME" -ge 1 ] && [ "$HAS_TAKEAWAY" -ge 1 ] && [ "$HAS_ML" -eq 0 ]; then
    pass "nonml_shape" "exp_02 frontmatter: outcome+takeaway present, metric/track/n_runs/best_run absent"
  else
    fail "nonml_shape" "exp_02 frontmatter wrong (outcome=$HAS_OUTCOME takeaway=$HAS_TAKEAWAY ml_fields=$HAS_ML)"
  fi
else
  fail "nonml_shape" "exp_02_feature_correlation.md not found"
fi

# ── 7. guard hook (invoke directly with a JSON payload) ──────────────────────
hr "guard hook"
GUARD_OUT=$(printf '{"tool_input":{"file_path":"docs/experiments/exp_01_rf_baseline.md"}}' \
            | $PY "$GUARD" 2>/dev/null)
if echo "$GUARD_OUT" | grep -q '"permissionDecision": *"deny"'; then
  pass "guard_hook" "guard_records denied a direct edit of an exp_*.md record"
else
  fail "guard_hook" "guard did not deny exp record edit (got: $GUARD_OUT)"
fi

# ── 8. drift check ───────────────────────────────────────────────────────────
hr "drift"
$MCLI docs check >/tmp/smoke_drift.log 2>&1
DRIFT_RC=$?
# The maestro CLAUDE.md TEMPLATE is itself ~157 lines (>100 cap), so the adopted
# project trips the size cap before we even append the KB snippet. That's a known
# template condition, not a flow failure — tolerate it if it's the ONLY drift.
OTHER_DRIFT=$(grep -E '^\s+- ' /tmp/smoke_drift.log | grep -vi 'CLAUDE.md is .* lines' | wc -l)
if [ $DRIFT_RC -eq 0 ]; then
  pass "drift" "docs check reports clean"
elif [ "$OTHER_DRIFT" -eq 0 ]; then
  pass "drift" "only drift is the CLAUDE.md line-cap (known template condition; not a flow failure)"
else
  fail "drift" "docs check reported real drift (rc=$DRIFT_RC; see /tmp/smoke_drift.log)"
fi

# ── summary ──────────────────────────────────────────────────────────────────
echo
echo "RESULT: $N_PASS passed, $N_FAIL failed"
echo "Inspect the adopted project at: $WORK"
[ "$N_FAIL" -eq 0 ] || exit 1
