"""exp_04_featurize_speed: an INFRA timing measurement, no science claim.

No tracker. Times how long it takes to load + standardize the wine data over K
repeats and prints the mean milliseconds per pass. This is an engineering
measurement (how fast is our featurize step), not a hypothesis about the data.

Stands in for a typical infra/benchmark run, recorded with outcome=infra
and a prose takeaway, NO ML fields. Read by tests/e2e/run_smoke.sh.
"""
import time
from pathlib import Path

import pandas as pd
from sklearn.preprocessing import StandardScaler

K = 50
DATA = Path("data/raw/wine/wine.csv")


def featurize() -> None:
    df = pd.read_csv(DATA)
    X = df.drop(columns=["target"])
    StandardScaler().fit_transform(X)


def main() -> None:
    # warm up the file cache / imports so the timing reflects steady state
    featurize()

    t0 = time.perf_counter()
    for _ in range(K):
        featurize()
    elapsed = time.perf_counter() - t0

    mean_ms = (elapsed / K) * 1000.0
    print(f"repeats={K} mean_ms={mean_ms:.3f}")


if __name__ == "__main__":
    main()
