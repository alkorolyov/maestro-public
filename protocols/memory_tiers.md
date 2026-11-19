# Agent Memory Tiers

How the agent should load project state across a session — adapted from the [MemGPT](https://arxiv.org/abs/2310.08560) hierarchical-memory pattern, with operational thresholds drawn from [Long Context vs RAG (2025)](https://arxiv.org/html/2501.01880v1) and [A-MEM (2025)](https://arxiv.org/pdf/2502.12110).

This document tells the agent **what to load when**. Follow it instead of grepping everything every turn.

---

## The three tiers

```
  WORKING        RECALL                  ARCHIVAL
  (always-on)    (load on session start) (load on demand)
  ──────────     ───────────────────     ──────────────────────
  CLAUDE.md      docs/experiments/INDEX  docs/experiments/exp_NN_*.md
  progress.md    docs/adrs/INDEX         docs/kb/literature/<slug>.md
  MEMORY.md (?)  docs/findings.md        <kb raw>/<slug>.{pdf,txt}
                 docs/kb/literature/INDEX  data/experiments/exp_NN_*/
```

`<kb raw>` is the project's `kb_raw` directory (default `docs/kb/literature/raw/`; `maestro info show` prints it).

### Working set — loaded every turn

- **CLAUDE.md** (project + parent dirs) — always in context
- **progress.md** — active sprint, current priorities, what's running now
- **MEMORY.md** — auto-memory index, reportedly loaded by the runtime (unverified by any maestro tooling — nothing here reads or writes it, so treat it as a bonus, never as a place a rule depends on)

These are small, hot, and define what "now" means. Keep them under ~200 lines each.

### Recall set — load on session start, keep available

- **`docs/experiments/INDEX.md`** — full table + Best by Track/Benchmark + Refuted + Open + Lineage + Related Networks + External Pointers
- **`docs/adrs/INDEX.md`** — accepted decisions + superseded-by chains
- **`docs/findings.md`** — curated positive + negative findings
- **`docs/kb/literature/INDEX.md`** — generated catalog of every kb paper (year/title/tags/takeaway). The "what literature exists at all" cue; drives whether to run `maestro kb search`. (Only present once the kb is populated.)

These are summaries-of-summaries. They tell the agent *what exists* without spending tokens on full content. INDEX.md is the single most important file the agent loads from this tier — it's how duplicate experiments and refuted hypotheses get caught **before** the agent proposes new work.

### Archival — load only when the recall tier points there

- **`docs/experiments/exp_NN_*.md`** — full per-experiment write-up. Load only when:
  - INDEX flagged a similar prior run (overlap check — `protocols/record_writeup.md` §0)
  - the human asked about a specific experiment by number
  - a write-up is being drafted that cites this experiment
- **`docs/kb/literature/<slug>.md`** — load only when generating a write-up that cites the paper, or when planning an experiment in that paper's domain. Find the right entry with `maestro kb search --query="..."` (`/find-kb`) — semantic top-k + a confidence gate — then read the surfaced `<slug>.md`.
- **`<kb raw>/<slug>.{pdf,txt}`** — load only when verifying a quoted number or recipe-level method during a write-up. The `.txt` sidecar is preferred for grep across the corpus.
- **`data/experiments/exp_NN_*/`** — the actual run artifacts. Load when (a) re-verifying a markdown summary against truth, (b) drafting external content per the `write_up.md` protocol.

---

## Content routing (what belongs where)

Tiers tell the agent *when* to load a doc. This tells it *which doc a new claim belongs in* — the defense against the other failure mode, mis-filing (literature syntheses landing in `findings.md`, reported leads treated as results, etc.).

> **The one-line test: kb answers "what is known?" — findings answers "what did *we* find out?"**

Every home is fixed by three axes: **provenance** (ours vs. external) × **kind** (result / decision / reference / activity) × **lifecycle**.

| Home | Provenance | Kind | Lifecycle | Answers |
|---|---|---|---|---|
| `docs/kb/` | external | reference | edit-in-place, by topic | what is known? |
| `docs/kb/meetings`, `kb/transcripts` | external, *unverified* | reported context | by source, until reproduced | what were we told? |
| `docs/experiments/exp_NN` | ours | result (detailed) | immutable record + `revisions:` | what did this run show? |
| `docs/findings.md` | ours | result (distilled) | append-only, linked to evidence (`Exp N` / artifact) | what did *we* find out? |
| `docs/adrs/` | ours | decision | append-only, supersedable | what did we decide, & why? |
| `docs/progress.md` | ours | activity / state / plan | mutable, churns | what are we doing now / next? |

**The tiebreaker (provenance of the claim, not the author):** who wrote the words doesn't decide the home — the provenance of the *claim* does. A synthesis we authored is **kb** if its proof is a paper; our computed number is a **finding** if its proof is our data/run. So "literature finding" is a category error — it's a kb entry that happens to be authored by us. When a source gets re-tiered or a reference fact changes, you edit only the kb doc; the finding holds its dated conclusion + link and doesn't move.

---

## Why this matters

Loading everything every turn defeats the design. The 1M-token attention window is unreliable past ~32K–64K tokens of dense content (the "lost in the middle" problem); even when nominally fitting, retrieval accuracy drops 10–20 points compared to focused loading. The recall tier is engineered to be small and dense so it stays inside reliable attention range; the archival tier expands lazily and only when a recall pointer justifies it.

---

## kb semantic search (`maestro kb`)

The kb archival tier is retrieved **on demand** via a two-stage search (`/find-kb` drives it). Stage 1 is a cheap vector top-k; stage 2 is a grounded read of whatever stage 1 surfaces — the hit is a *pointer*, never the answer.

```
question ──embed (bge-small)──► cosine top-k vs entry vectors
                                      │
              ┌── top ≥ gate ─────────┴── top < gate ──┐
              ▼                                          ▼
   read the <slug>.md (frozen summary)        "NO STRONG MATCH" — proceed
   → raw/<slug>.{pdf,txt} only to verify        without kb (don't force a
     a number                                    marginal paper into context)
```

The vectors are a **build artifact, not a live view**: entries written after the last
`maestro kb build` are invisible to search. Search compares the entries on disk against
the hashes the index was built from and prints a `STALE` warning naming what is missing;
`maestro kb selftest` fails outright on one. Treat either as "rebuild before you trust
the miss" — a `NO STRONG MATCH` on a stale index means nothing.


Three things make this safe, and each is a deliberate defense:

1. **Embed the entry, not raw PDF chunks.** The vector is built from the curated `title + tags + Abstract + Method + Key Result + Takeaway + Relevance` — the summary that was written *once, against the source*, and frozen. (Method + Key Result are included so method/metric-detail queries retrieve; they are grounded, signal-rich sections, not raw page text.) We never re-summarize the corpus at query time. (The one-grounded-compression rule: lossy compression happens at ingestion with the source in hand, never repeatedly at load with only prior summaries — that is how overgeneralization creeps in.)
2. **A corpus-calibrated gate — but it only judges *domain*, not *answerability*.** `build` measures this corpus's response to generic routine-dev probes (the *noise floor*) and sets `gate = noise_floor + margin`. That is enough to reject **routine / off-domain turns** (dev, ops, trivia — the gate's real job: "is this even a kb-domain question?"). It is **not** enough to decide whether the corpus actually *answers* a domain-adjacent question — see bullet 4.
3. **Model + composition were chosen empirically — and a naive eval was overturned.** A first 17-query / trivial-negative eval crowned `bge-base`; the proper benchmark (`tests/kb_golden/`: 113 grounded positives + 80 *verified near-domain hard* negatives, ROC-AUC with bootstrap 95% CIs + paired ΔAUC) reversed it. On hard negatives: qwen3-0.6b AUC 0.98 > **bge-small 0.94** > yuan 0.89 ≈ bge-base 0.88 — bge-base significantly *worst*, bge-small's +0.06 edge over it is significant. We ship **`bge-small-en-v1.5`**: the best *fastembed* (ONNX, no-torch, CPU) ranker and the lightest. `qwen3-0.6b` ranks best overall but needs a torch/sentence-transformers backend + GPU, so it is deliberately **not** adopted — the tool stays lightweight. Composition C (Method + Key Result) is kept. Re-run `tests/kb_golden/run_gate_auc.py` to re-validate when corpus or model changes; `maestro kb selftest` is the quick label-free check.
4. **A cosine gate cannot reject "domain-adjacent but absent" — by design, not by tuning.** On hard negatives every model's positive/negative score distributions *overlap* (negative separation gap; specificity ≈ 0 at any routine-probe threshold). "Predict protein secondary structure" looks, to cosine, just like the corpus's membrane-positioning papers. So **never read a `RELEVANT` verdict as proof the corpus answers the question** — it means only "domain-adjacent." The real relevance defense is the **read-the-source step** (the agent opens `<slug>.md`, sees it doesn't actually answer, moves on), backed by the always-on INDEX and the agent's own judgment. The gate filters routine turns; the agent filters relevance.

## When to switch from grep to RAG

`maestro kb search` exists, but grep still wins below the thresholds here — semantic search only earns its keep once the corpus is big enough that lexical grep starts missing synonyms. Heuristics for when to graduate:

| Signal | Threshold | What to switch to |
|---|---|---|
| Total markdown content in `docs/kb/` exceeds reliable attention | ~200 entries × ~4KB ≈ 800KB ≈ 200K tokens | sentence-level vector index over entries (not chunks) |
| Full-text search across PDF sidecars becomes slow / noisy | ~50 PDFs OR ~5 MB of `.txt` | targeted index over `raw/<slug>.txt` |
| Cross-experiment "find similar to this idea" | when `related:` graph density > ~5 edges/exp on average | embed exp takeaways, cluster |

**The trigger is attention reliability, not raw token count.** Long-context models can technically hold 1M tokens; they cannot reliably *use* dense content past ~64K. The 200-entry cutoff is roughly where our recall tier hits this wall.

Until then: grep + frontmatter filters + INDEX.md beat retrieval pipelines on both cost and recall for our scale.

---

## Cross-tier rules

1. **Archival never replaces recall.** If a fact is load-bearing (decision, refuted hypothesis, current best), it must surface in INDEX or findings — not only in a per-experiment file.
2. **Recall summaries must trace to archival truth.** `write_up.md` makes this enforceable at write-up time: re-read source artifacts, fix any drift in markdown, then draft.
3. **External pointers (W&B, MLFlow, DOI, ADR) live in archival but are surfaced in recall** via INDEX's "External Pointers" section. The agent should follow them out-of-tier when the markdown isn't enough.
4. **Working tier is for "today" only.** Don't dump experiment notes there. Move durable facts to archival, leave only active sprint state in `progress.md`.

## Read-time rule (the core defense against error propagation)

When loading a recall-tier entry — any takeaway in INDEX.md, any line in the Refuted Hypotheses table, any Best by Track row — the agent must treat it as a **summary, not verified data**, especially before:

- proposing a new experiment that builds on its conclusion
- citing it in a Confluence / report draft
- rejecting a hypothesis as "already refuted"
- recommending a parameter setting based on a prior best

In each of these cases the agent must re-read the underlying `data/experiments/exp_NN/` artifacts (or `<kb raw>/<slug>.{pdf,txt}` for literature) **before** propagating. Check the entry's `flags:` for review markers (the authoritative flag table is in `protocols/record_writeup.md`) and `revisions:` for known correction history.

This rule exists because the documented failure mode of agent-maintained KBs is exactly this: agents treat retrieved summaries as ground truth and amplify whatever errors are baked in ([MemoryGraft (2512.16962)](https://arxiv.org/html/2512.16962v1), [Memory Control Flow Attacks (2603.15125)](https://arxiv.org/html/2603.15125v1)). The defense is provenance-checking before propagation ([FAIR R1.2](https://www.go-fair.org/fair-principles/)). The takeaway is an *index*; the data dir is the *truth*.
