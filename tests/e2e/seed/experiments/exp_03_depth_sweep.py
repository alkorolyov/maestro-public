"""exp_03_depth_sweep: a small max_depth ABLATION/SWEEP on the toy wine dataset.

No tracker. Trains a RandomForest at a few max_depth values and prints accuracy
per depth. Designed as a NEGATIVE result: the shallow baseline already separates
the wine classes, so going deeper does not beat it — deeper ≠ better here.

This stands in for a typical "swept a knob, it didn't help" experiment,
recorded with outcome=refuted and a prose takeaway, NO ML fields (the per-depth
numbers are an ablation table, not a headline tracked metric).
Read by tests/e2e/run_smoke.sh.
"""
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

SEED = 0
DEPTHS = [2, 4, 8, None]  # None == unbounded ("baseline" deepest tree)
DATA = Path("data/raw/wine/wine.csv")


def main() -> None:
    df = pd.read_csv(DATA)
    X = df.drop(columns=["target"])
    y = df["target"]
    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.3, random_state=SEED, stratify=y
    )

    results = {}
    for depth in DEPTHS:
        clf = RandomForestClassifier(
            n_estimators=200, max_depth=depth, random_state=SEED
        )
        clf.fit(Xtr, ytr)
        acc = accuracy_score(yte, clf.predict(Xte))
        results[depth] = acc
        print(f"max_depth={str(depth):>4}  accuracy={acc:.4f}")

    best_depth = max(results, key=results.get)
    print(f"best_depth={best_depth} best_accuracy={results[best_depth]:.4f}")


if __name__ == "__main__":
    main()
