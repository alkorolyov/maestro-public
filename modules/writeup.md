# Module: Write-up (external content: reports, papers, slides, Confluence)

Load before drafting anything external-facing that cites project results.

## Read-time defense

A retrieved summary is a summary, not data. Before building new work on a conclusion, citing it externally, rejecting a hypothesis as "already refuted", or recommending a parameter from a prior best: re-read the underlying `data/experiments/exp_NN_*/` artifacts (or `<kb raw>/<slug>.{pdf,txt}` for literature). Check the record's `flags:` (`single_seed`, `large_unexpected_gain`, `conflicts_prior`, `setup_unverified`, `interpretation_uncertain`) and `revisions:`. The takeaway is an index; the data dir is the truth.

## Drafting protocol

- Verify every quoted number against the data dir, not the takeaway field. Verify metric definitions (split, subset, seed) against run config.
- If markdown disagrees with data: fix the markdown via `maestro exp revise` (never a silent edit) and tell the owner what changed before continuing.
- Cite datasets by name AND version ("MyDataset v2.0", not "the benchmark set").
- Full protocol: `protocols/write_up.md`.

## Presentations

Two-step pipeline: `slides.md` (markdown source, subject to this module) → `.pptx` generated mechanically, never the source of truth. Artifacts in `data/presentations/<YYYY-MM-DD>_<topic>/`, untracked. Scope and audience are set by the owner, not the agent. Slide format conventions: `protocols/write_up.md → ## Slides / pptx`.
