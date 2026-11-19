"""exp_01_rf_baseline: random-forest baseline on the toy wine dataset.

Logs ONE run to whatever tracker MAESTRO_TRACKER names (mlflow | wandb):
  run name   exp_01_rf_baseline__baseline__s0
  mlflow     tag exp=01            (+ group, git_sha, dataset)
  wandb      via maestro.tracking, three-leg provenance
             (git_sha + exp_code_sha + dataset_sha)
  metrics    accuracy, f1_macro

Trivial science — its only job is to exercise the maestro run flow against both
trackers. Read by tests/e2e/run_smoke.sh.
"""
import os
import subprocess
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

SEED = 0
EXP_NUM = "01"
SLUG = "rf_baseline"
GROUP = f"exp_{EXP_NUM}_{SLUG}"
RUN_NAME = f"{GROUP}__baseline__s{SEED}"
DATA = Path("data/raw/wine/wine.csv")
ARTIFACT_DIR = Path(f"data/experiments/{GROUP}")
# Tracker project name = repo dir name (maestro convention). On /tmp the dir is
# "maestro-smoke", so use that explicitly rather than Path.cwd().name (robust to
# being launched from elsewhere).
PROJECT = "maestro-smoke"


def git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()


def train():
    df = pd.read_csv(DATA)
    X = df.drop(columns=["target"])
    y = df["target"]
    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.3, random_state=SEED, stratify=y
    )
    clf = RandomForestClassifier(n_estimators=200, random_state=SEED)
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    acc = accuracy_score(yte, pred)
    f1 = f1_score(yte, pred, average="macro")
    return acc, f1, yte, pred


def log_mlflow(acc, f1, sha):
    import mlflow
    from mlflow.tracking import MlflowClient

    # A prior smoke run may have left this experiment in the "deleted" lifecycle
    # state on the tracker; mlflow refuses to reuse a deleted name. Restore it so
    # the harness is repeatable without manual server cleanup.
    client = MlflowClient()
    exp = client.get_experiment_by_name(PROJECT)
    if exp is not None and exp.lifecycle_stage == "deleted":
        client.restore_experiment(exp.experiment_id)
    mlflow.set_experiment(PROJECT)
    with mlflow.start_run(run_name=RUN_NAME):
        mlflow.set_tag("exp", EXP_NUM)
        mlflow.set_tag("mlflow.runName", RUN_NAME)
        mlflow.set_tag("group", GROUP)
        mlflow.set_tag("git_sha", sha)
        mlflow.set_tag("dataset", "wine")
        mlflow.set_tag("dataset_version", "v1")
        mlflow.log_param("n_estimators", 200)
        mlflow.log_param("seed", SEED)
        mlflow.log_metric("accuracy", acc)
        mlflow.log_metric("f1_macro", f1)


def log_wandb(acc, f1, sha):
    # Goes through the maestro tracking helper (NOT raw wandb): start_run stamps
    # three-leg provenance — git_sha (clean-tree gated), exp_code_sha + a code
    # artifact (from code_path), and dataset_sha (resolved from docs/data/wine.md).
    from maestro.tracking import start_run, log_metrics, finish

    run = start_run(
        exp_n=1, slug=SLUG, variant="baseline", seed=SEED,
        dataset="wine",                 # → dataset_sha gate (docs/data/wine.md)
        config={"n_estimators": 200, "seed": SEED},
        code_path=__file__,             # → exp_code_sha + uploaded code artifact
    )
    log_metrics({"accuracy": acc, "f1_macro": f1}, run=run)
    finish(run)


def main() -> None:
    tracker = os.environ.get("MAESTRO_TRACKER", "mlflow").strip().lower()
    acc, f1, yte, pred = train()
    sha = git_sha()

    if tracker == "wandb":
        log_wandb(acc, f1, sha)
    elif tracker == "mlflow":
        log_mlflow(acc, f1, sha)
    else:
        raise SystemExit(f"unknown MAESTRO_TRACKER={tracker!r} (expected mlflow|wandb)")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"y_true": yte.values, "y_pred": pred}).to_csv(
        ARTIFACT_DIR / "predictions.csv", index=False
    )
    print(f"tracker={tracker} run={RUN_NAME} accuracy={acc:.4f} f1_macro={f1:.4f}")


if __name__ == "__main__":
    main()
