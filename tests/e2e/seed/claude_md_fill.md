
## Knowledge Base

Project KB topics (used to calibrate the literature semantic-search gate and to
route fetched papers). This toy project studies tree-ensemble baselines on small
tabular data:

- **random forests and bagging** — bootstrap-aggregated decision-tree ensembles,
  out-of-bag error, random feature subsets per split, variable importance.
- **gradient-boosted trees** — additive tree boosting, regularized objectives,
  shrinkage/learning rate, XGBoost-style second-order boosting.
- **tabular classification baselines** — when tree ensembles beat linear models,
  low-tuning defaults for small-N tabular tasks (e.g. the sklearn `wine` set).

Fetched papers land in `docs/kb/literature/`; the foundational references are
Breiman 2001 (Random Forests) and Chen & Guestrin 2016 (XGBoost).
