# Literature Search Protocol

Follow this protocol exactly whenever asked to search for papers on a topic or add papers to the KB.

**Input is always free-text from the human — never DOIs.** The human describes a topic, an intent ("refetch the broken ones", "audit KB"), or a list of paper titles. DOIs and slugs are internal artifacts the protocol must derive; do not ask the human for them.

**The raw directory.** Every `<raw>` below is the kb's directory of downloaded sources: `docs/kb/literature/raw/` unless the project's `maestro.toml` sets `kb_raw` (a project that keeps downloads out of git points it at its data root). `maestro info show` prints the resolved path (`kb raw`); read it once and use it wherever this protocol says `<raw>`. The entries (`docs/kb/literature/<slug>.md`) always stay in `docs/`.

---

## Phase 0 — Mode selection

Inspect the human's request and pick exactly one mode. If unclear, ask the human a one-line clarifying question — do not guess.

| User says... | Mode | Where to start |
|---|---|---|
| "find papers on X", "add papers about Y", "search for Z" | **topic** | Phase 1 |
| "refetch the broken ones", "retry placeholders", "fix unfetchable entries" | **retry-placeholders** | Phase 0a |
| "audit the KB", "what's missing/wrong", "check for orphans" | **audit** | Phase 0b |
| "fill in entries for raw PDFs without entries", "regenerate missing entries" | **regen-from-raw** | Phase 0c |
| "rewrite \<title\>" or "redo the X paper" | **rewrite-named** | Phase 0d |

The human will not give you a DOI or slug. You derive them by scanning `docs/kb/literature/` and `<raw>/`.

### Phase 0a — retry-placeholders

```bash
grep -l "^status: placeholder" docs/kb/literature/*.md
```

For each match, extract the DOI from frontmatter (`grep "^doi:"`) and re-run Phase 2 fetch. If the new fetch returns a real PDF or ≥500 B abstract, proceed to Phase 3 to overwrite the placeholder. If it still returns a stub, leave the placeholder unchanged and report which DOIs are persistently unfetchable.

### Phase 0b — audit

Run all four checks and report; do not change files until the human confirms which to fix:

1. **Placeholders awaiting refetch:** `grep -l "^status: placeholder" docs/kb/literature/*.md`
2. **Orphan PDFs (raw exists, no entry):**
   ```bash
   for pdf in <raw>/*.pdf; do
     slug=$(basename "$pdf" .pdf)
     [ ! -f "docs/kb/literature/$slug.md" ] && echo "ORPHAN: $slug"
   done
   ```
3. **Stub abstracts mislabeled:**
   ```bash
   for abs in <raw>/*_abstract.md; do
     bytes=$(wc -c < "$abs")
     [ "$bytes" -lt 500 ] && echo "STUB ($bytes B): $abs"
   done
   ```
4. **Frontmatter / disk mismatch:** for each entry, confirm `file_type` matches what's actually in `raw/<slug>*`.

Report findings as a table; let the human pick which to act on.

### Phase 0c — regen-from-raw

Find PDFs in `raw/` without a corresponding entry (Phase 0b check 2). For each, treat the PDF as the source and run Phase 3 directly (skip Phase 1/2 — DOI is the slug, source is on disk).

### Phase 0d — rewrite-named

User gives a paper title or topic phrase. Find the existing entry by title:

```bash
grep -l -i "<phrase from user>" docs/kb/literature/*.md
```

If exactly one match: extract DOI from frontmatter, treat the existing `raw/<slug>*` as source, run Phase 3 to overwrite. If multiple matches or none: ask the human to disambiguate. Never guess.

---

## Phase 1 — Search

**Search budget.** `WebSearch` is capped per session (200 calls on Claude Code) and the cap
is shared by every subagent the session spawns. When it is exhausted, blocked, or returns
empty results, do not stall and do not report failure: switch to the machine's local
search endpoint and the free scholarly APIs, which need no budget —

```bash
# a local SearXNG instance, if you run one (set its host and port); add site:ssrn.com / site:arxiv.org / site:nber.org to target papers
curl -s "http://<searx-host>:<port>/search?q=<url-encoded query>&format=json" | python3 -c "import json,sys; [print(r['title'],'|',r['url']) for r in json.load(sys.stdin)['results'][:10]]"
# OpenAlex (date filter optional)
curl -s "https://api.openalex.org/works?search=<query>&filter=from_publication_date:2023-01-01&per-page=15" | python3 -c "import json,sys; [print(w.get('publication_year'),'|',w.get('title'),'|',w.get('doi')) for w in json.load(sys.stdin)['results']]"
# CrossRef bibliographic
curl -s "https://api.crossref.org/works?query.bibliographic=<query>&rows=15" | python3 -c "import json,sys; [print(i.get('issued',{}).get('date-parts',[['']])[0][0],'|',i.get('title',[''])[0],'|',i.get('DOI')) for i in json.load(sys.stdin)['message']['items']]"
# arXiv
curl -s "http://export.arxiv.org/api/query?search_query=all:<query>&max_results=15&sortBy=submittedDate"
```

Semantic Scholar rate-limits anonymous calls; do not lean on it. Every subagent brief that
searches carries this fallback verbatim, so a child never has to be messaged mid-run
(search children can stall on an exhausted budget until told).

1. Use `WebSearch` to find the top papers on the given topic. Queries like:
   - `"<topic>" site:pubmed.ncbi.nlm.nih.gov`
   - `"<topic>" DOI filetype:pdf`
   - `"<topic>" review 2020..2025`
2. For each candidate, resolve the **exact DOI** — verify title + author via CrossRef:
   ```bash
   curl -s "https://api.crossref.org/works/<DOI>" | python3 -c "import json,sys; w=json.load(sys.stdin)['message']; print(w['title'][0], w.get('author',[''])[0])"
   ```
   If CrossRef title does not match your target paper, **discard the DOI and search again**. Never guess DOIs.
3. Check for duplicates before fetching:
   ```bash
   grep -r "<DOI>" docs/kb/literature/*.md
   ```
   Skip any DOI already in the KB.
4. Score each candidate for project relevance — defined in the project's CLAUDE.md under `## Knowledge Base`. Drop papers with no direct relevance.

Target: 5 papers per topic unless user specifies otherwise.

---

## Phase 2 — Fetch

For each confirmed DOI, invoke the fetch-paper skill:

```
/fetch-paper <DOI> <raw>/
```

The skill handles slug derivation, the fetch, and stub validation — it returns `file_type` directly.

After fetch, verify what was saved:
```bash
ls -lh <raw>/<slug>*
```

Record the result for each paper from the tool's JSON, never from file sizes or by
grepping the file (every abstract file carries the same footer, so a grep for it
classifies real abstracts as stubs):
- `pdf` — `file_type: pdf` with `pages` > 2
- `abstract_md` — `file_type: abstract_md` with `has_abstract: true`
- `unfetchable` — anything else: `has_abstract: false`, a `pdf` with `pages` ≤ 2 (a cover
  sheet or abstract page; delete it), or no file

**Fetch in the foreground, then commit, then spawn.** The maestro spawn guard refuses to
launch a child while `docs/` holds uncommitted files, because a child sharing the checkout
can wipe them. A fetch loop running in the background writes into
`<raw>/` every few seconds, so every spawn attempt fails until it ends. Run the fetch loop to completion in the orchestrating agent, then
`git add <raw>/ && git commit -m "docs: kb raw sources for <topic>"`, and
only then launch Phase 3 children. When `<raw>` is outside the repo or ignored by git, there is
nothing to commit: confirm the fetch has ended and go on. Docs-only commits are allowed directly on `main`.

### Frontmatter fields: `file_type` vs `status`

`file_type` and `status` are orthogonal. `file_type` describes what is on disk in `raw/`; `status` describes the entry itself.

| `file_type` | `status` | Meaning |
|---|---|---|
| `pdf` | `complete` | Full entry, all sections sourced from PDF and verified |
| `abstract_md` | `abstract_only` | Real abstract retrieved; Method/Key Result are thin or absent (intentional) |
| `unfetchable` | `placeholder` | No usable source; entry is metadata-only awaiting refetch |
| any | `flagged` | Entry has known issues — needs review/rewrite. Add `## Flag` section explaining why |

`status: complete` requires `file_type: pdf`. `status: abstract_only` requires `file_type: abstract_md` (real, ≥500 B). `status: placeholder` requires `file_type: unfetchable`.

---

## Phase 3 — Write KB Entry

### Single-source rule (read this first)

**The ONLY source for entry content is the file in `<raw>/<slug>*`.** Nothing else. Specifically forbidden during entry writing:

- ❌ `WebFetch` to PMC, PubMed, bioRxiv, ACS, publisher pages, ResearchGate, etc.
- ❌ `WebSearch` to find numbers, abstracts, or method details
- ❌ Reading other entries in `docs/kb/literature/` and reusing their content
- ❌ Training memory / general knowledge about the paper
- ❌ Inferred or "likely" content based on the title

If a number, method, or claim is not present in the raw file, **it does not go in the entry.** Period.

### MANDATORY: Read before writing

Before writing a single word of content for a paper:
- If `pdf`: `Read` the PDF file. Read at least the abstract + methods + results sections. Note the page numbers of key claims.
- If `abstract_md`: `Read` the abstract stub. It contains CrossRef abstract only — no full text. Method/Result sections must be very thin or absent.
- If `unfetchable`: do **not** write a content entry. Either skip the paper entirely, or — only if the human explicitly wants a placeholder — write a metadata-only stub (see below).

**Never write content from training data or memory.**

### Unfetchable handling

Entry must contain ONLY:
- Frontmatter (with `file_type: unfetchable`)
- Title, Authors, Year, DOI header
- `## Status`: `Source not retrieved. Only DOI metadata available — no abstract, no full text. Re-attempt fetch later or remove from KB.`

No Abstract, no Method, no Key Result, no Relevance, no Takeaway, no Limitations.

### Entry file

Save to: `docs/kb/literature/<slug>.md`

```markdown
---
doi: <doi>
title: "<exact title from source>"
authors: "<First Author, Second Author et al.>"
year: <year>
tags: [tag1, tag2, ...]
file_type: pdf | abstract_md | unfetchable
status: complete | abstract_only | placeholder | flagged
---

# <Title>

**Authors**: <authors>
**Year**: <year>
**DOI**: <doi>

## Abstract

<Extract verbatim or closely paraphrased from source page 1.>

## Method

<Sourced from paper. Cite page in parentheses where useful, e.g. "(p. 3)".>

## Key Result

<Quantitative results with exact numbers from the paper. Never round or extrapolate.
Every load-bearing number carries a per-claim ANCHOR in parentheses — `(p. 7)` for a PDF,
`(l. 42)` for an `abstract_md`, and `(<slug> p. 7)` when the claim comes from a different
entry's source. A URL bundle in `## Sources` locates the paper; the anchor locates the
claim, which is what makes it re-checkable a year later without re-reading anyone's
reasoning. A number with no anchor is not ready to be written (ADR 9).>

## Relevance

<How this paper relates to this project specifically — see project CLAUDE.md for domain context.>

## Takeaway

<One or two sentences: the single most actionable conclusion for this project.>

## Limitations

<Limitations stated in the paper or directly observable from the methods. Do not invent.>
```

### Rules that prevented failures before

| Rule | Violation that caused it |
|---|---|
| `file_type` must match `ls raw/<slug>*` output | Two entries had `abstract_md` despite PDFs being present |
| Abstract must come from page 1 of source | Entries used boilerplate "not available" text |
| Benchmark numbers must be exact from paper | An entry had invented speedup figures not in the paper |
| Samplers/features only from the paper's year | An entry listed a feature released after the paper's year |
| If abstract_md only: write "from abstract only" and avoid specific numbers not present | An entry had fabricated dataset stats |
| Stub `_abstract.md` (<500 B / "PDF not available") = `unfetchable`, not `abstract_md` | Empty 218–342 B stubs labeled `abstract_md` were filled with fabricated content |
| No WebFetch / WebSearch / external scrape during entry writing | Agent fetched summary pages to scrape numbers and wrote them as if from the abstract |
| `(from abstract only)` prefix is reserved for content actually IN the abstract | Used as cover for content scraped from summary pages |
| No biographical claims about authors unless in source | Relevance asserted an affiliation that was not in the source |

**Cross-reference escape hatch.** If a cross-paper link is genuinely useful, state it with an explicit provenance tag: `(cross-ref: <slug>)`. Without the tag, the claim must be in the source or removed.

---

## Phase 4 — Verify

After writing each entry:
1. Every load-bearing claim in `## Key Result` must already carry its anchor. Re-check the 3 most specific ones against the source: open `raw/<slug>*` at the anchor and confirm the number is there. An anchor that does not resolve is treated as a missing claim, not a typo.
2. If any claim cannot be found in the source: remove it.
3. Confirm `file_type` in frontmatter matches what `ls raw/` shows.
4. For `unfetchable` entries: confirm only Status + frontmatter — no Method, Key Result, etc.
5. Grep the authoring trail: any `WebFetch` / `WebSearch` after Phase 2 is a red flag — re-audit the entry.
6. Scan Relevance / Takeaway / Limitations for biographical claims. For each, either find it in `raw/<slug>*` or replace with `(cross-ref: <slug>)`. If neither, delete it.

---

## Phase 5 — Cleanup

- Delete any stale `*_abstract.md` stub in `raw/` if a PDF for the same paper is present.

---

## Phase 6 — Scaling up: when to delegate to subagents

For runs of >5 papers in a single session, batch entry-writing eats main-context fast — each PDF text sidecar is 2–10K lines, and reading 14 of them in series consumes tens of thousands of tokens that never get reused. Delegate Phase 3 to subagents instead.

### Phase split for delegated runs

| Phase | Where | Why |
|---|---|---|
| **Phase 1** (search + verify DOIs) | Main agent | Cross-paper context useful for de-dup + relevance scoring; needs project's `## Knowledge Base` topics in scope |
| **Phase 2** (fetch) | Bash, no agent | `/fetch-paper` + `curl` for arXiv; pure I/O |
| **Phase 3** (write entries) | One subagent per paper | Mechanically uniform per protocol; max parallelism; framework-level isolation enforces single-source rule (subagent literally can't see other papers); failure stays scoped to one agent |
| **Phase 4** (verify) | Main agent | Spot-check 3 specific claims per entry against `raw/<slug>*`; decide which to flag |
| **Cross-refs** | Main agent, final pass | Subagents can't see the full KB; main agent adds `(cross-ref: <slug>)` tags after all entries land |

### Model tiers (from `~/.claude/CLAUDE.md`, restated so the protocol is self-contained)

| Work | Shape | Tier |
|---|---|---|
| Phase 1 search per stream (plan queries, screen candidates, verify DOIs, judge the gap) | orchestrates | **opus** |
| Phase 2 fetch | shell loop, no agent | none |
| Phase 3 entry writing, one paper per child | leaf: read one source, write one file | **sonnet** |
| Phase 4 verification, cross-refs, synthesis | judge | the orchestrating agent |

Pass `model` explicitly on every `Agent` call. A child that inherits the session's model
runs the top tier by default; such children can cost more than the rest of the run. A sonnet search child stalls on the screening step, so the tier is set by the task's shape, never by its topic.

### Phase 3 subagent prompt structure

Launch one subagent per paper, in parallel batches (multiple Agent calls in a single message). Each subagent must receive:

1. **The protocol itself** — link or inline `protocols/literature_search.md` Phase 3.
2. **Per-paper assignment** — DOI, slug, raw file path, file_type from Phase 2.
3. **Project relevance topics** — from project CLAUDE.md `## Knowledge Base` section, so Relevance/Takeaway sections can be project-specific.
4. **Strict no-extrapolation reminder**: *"If a claim isn't in the source, omit it. Do not write 'likely', 'commonly', or 'typically' to fill gaps. Better a missing section than a plausible default."*
5. **Cross-ref instruction**: *"Do NOT add `(cross-ref: <slug>)` tags. The main agent adds those in a final pass once all entries land."*
6. **Output expectation**: subagent writes the entry directly to `docs/kb/literature/<slug>.md` with the Write tool, then returns a brief confirmation only — NOT the entry content. Format: *"Wrote <slug>.md (NN lines). Top-3 quantitative claims sourced to: claim 1 → p. X; claim 2 → p. Y; claim 3 → p. Z."* This keeps main-thread context clean — entries can be read during Phase 4 instead of duplicated through tool results.

### When NOT to delegate

- ≤3 papers: faster to do in main thread; subagent overhead exceeds savings.
- `regen-from-raw` mode (Phase 0c): often a single-paper fix; main agent handles directly.
- `rewrite-named` mode (Phase 0d): user-driven, single paper; main agent handles directly.
- When entries depend on heavy cross-paper analysis (rare — the protocol normally forbids cross-paper claims without explicit `(cross-ref: <slug>)` tags).

### Quality bar still applies

Phase 4 verification is non-negotiable for delegated runs — subagents are the most likely source of plausible-sounding but unsourced content. Spot-check the 3 most-quantitative claims per entry against `raw/<slug>*` before considering Phase 3 complete.

---

## Phase 7 — Regenerate the index

After writing or updating any kb entries, refresh the catalog `docs/kb/literature/INDEX.md`:

```bash
maestro index render --kind=all
```

This is the kb analog of how the `maestro` CLI auto-regenerates the exp/adr/dataset INDEX on every record write. A PostToolUse hook (`global/hooks/regen_kb_index.py`) runs this automatically when the **main** Claude agent writes a kb entry — but it does **not** fire for subagent batches (Phase 6) or other agents. So for any batched / delegated run, the main agent must run `maestro index render --kind=all` **once** after all entries land, as a backup. When in doubt, run it — it's idempotent.

**`index render` is not `kb build`.** The render regenerates the human-readable catalog
(`INDEX.md`); the vector index behind `maestro kb search` is a separate artifact and no
hook rebuilds it. After entries land, run both:

```bash
maestro index render --kind=all     # the catalog
maestro kb build                    # the vectors + the recalibrated gate
```

`kb build` is incremental — it re-embeds only entries whose text changed — so running it
after every batch is cheap. Skip it and search silently answers from the old corpus; it
will warn that it is `STALE`, but a warning is not a rebuild.

---

## Entry Quality Checklist

- [ ] `file_type` matches disk AND respects the stub rule
- [ ] `status` matches `file_type` per the combination table
- [ ] Abstract is from source (not boilerplate)
- [ ] No fabricated numbers — every stat traceable to a page/line in `raw/<slug>*`
- [ ] Relevance section mentions a specific component of this project
- [ ] `raw/` contains the source file used (and only that file was used)
- [ ] No `WebFetch` / `WebSearch` / external scrape was run between Phase 2 and Phase 4
- [ ] `placeholder` entries contain only Status + frontmatter, no fabricated sections
- [ ] No biographical claims unless in source OR carrying an explicit `(cross-ref: <slug>)` tag
