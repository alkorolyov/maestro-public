"""exp_02_feature_correlation: pure DATA ANALYSIS on the toy wine dataset.

No model, no tracker. Computes the Pearson correlation between two wine
features (flavanoids vs total_phenols) and prints it. Fully deterministic.

This stands in for a typical non-ML experiment: a data-analysis run whose
result is a single relationship, recorded with outcome+takeaway and NO ML fields
(no metric/track/n_runs/best_run). Read by tests/e2e/run_smoke.sh.
"""
from pathlib import Path

import pandas as pd

DATA = Path("data/raw/wine/wine.csv")


def main() -> None:
    df = pd.read_csv(DATA)
    r = df["flavanoids"].corr(df["total_phenols"], method="pearson")
    print(f"pearson_r(flavanoids, total_phenols)={r:.4f}")


if __name__ == "__main__":
    main()
