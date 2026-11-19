---
doi: 10.1023/A:1010933404324
title: "Random Forests"
authors: "Leo Breiman"
year: 2001
tags: [random-forest, ensemble, bagging, decision-trees, tabular-classification]
file_type: pdf
status: complete
---

# Random Forests

**Authors**: Leo Breiman
**Year**: 2001
**DOI**: 10.1023/A:1010933404324

## Abstract

Random forests are a combination of tree predictors such that each tree depends on the values of a random vector sampled independently and with the same distribution for all trees in the forest. The generalization error for forests converges a.s. to a limit as the number of trees in the forest becomes large. The generalization error of a forest of tree classifiers depends on the strength of the individual trees in the forest and the correlation between them. Using a random selection of features to split each node yields error rates that compare favorably to Adaboost, but are more robust with respect to noise. Internal estimates monitor error, strength, and correlation, and these are used to show the response to increasing the number of features used in the splitting. Internal estimates are also used to measure variable importance. These ideas are also applicable to regression.

## Method

A random forest grows an ensemble of tree predictors; for the k-th tree a random vector Θ_k is generated independently of the past random vectors but with the same distribution, and a tree is grown using the training set and Θ_k. After many trees are generated they vote for the most popular class (p. 5–6). The paper studies the variant that uses a random selection of features at each node to determine the split (Section 3). Theorem 1.2 states that as the number of trees increases, the generalization error converges almost surely to a limit, so random forests do not overfit as more trees are added. An upper bound for the generalization error is derived in terms of the strength of the individual trees and the correlation between them (Theorem 2.3).

## Key Result

The results are reported as insensitive to the number of features selected to split each node: "selecting one or two features gives near optimum results" (p. 5, Section 1.2). Random selection of features to split each node yields error rates that compare favorably to Adaboost but are more robust with respect to noise (Abstract).

## Relevance

Directly relevant to this project's KB topic "random forests and bagging" — the foundational paper for the random-forest classifier used as a baseline tree-ensemble method on the toy tabular (wine) task. Explains why a random forest is a reasonable, low-tuning default for small tabular classification.

## Takeaway

A random forest with a small random feature subset per split is a strong, noise-robust, low-tuning baseline for tabular classification; adding more trees does not overfit (generalization error converges to a limit).

## Limitations

The paper's empirical accuracy claims compare against Adaboost on the datasets available in 2001; modern gradient-boosting methods are not covered. Theoretical bounds are upper bounds and may be loose in practice.
