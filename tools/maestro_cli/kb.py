"""Two-stage semantic search over a project's literature kb.

Embeds per-paper kb entries (docs/kb/literature/*.md) with bge-small-en-v1.5,
then answers queries with a cosine top-k AND a corpus-calibrated confidence gate
so off-topic dev turns get rejected instead of returning spurious "relevant" hits.

maestro kb build   [--kb=PATH] [--margin=FLOAT]     # (re)build index + calibrate gate
maestro kb search  --query="<text>" [--top-k=N]     # cosine top-k + VERDICT line
maestro kb selftest [--kb=PATH]                     # label-free health check

search and selftest compare the entries on disk against the hashes the index was
built from, so an index that has gone stale is reported rather than silently used.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384
# bge-v1.5 is asymmetric: the instruction is prepended to QUERIES only, not docs.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
DEFAULT_KB = Path("docs/kb/literature")
DEFAULT_MARGIN = 0.10

# Generic, project-agnostic off-topic probes: routine non-kb dev turns. The gate is
# calibrated from THIS corpus's response to these — not a hardcoded constant — because
# an off-topic query still scores ~0.5-0.6 against bge embeddings (a compressed band),
# so the gate must sit ABOVE the measured noise floor of this specific corpus.
OFFTOPIC_PROBES = [
    "what is the capital of France",
    "how do I fix a python import error",
    "what time is it right now",
    "rerun the experiment with more epochs",
    "write a bash loop over files",
    "explain what this function does",
]

FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


# ── parsing (mirrors the spike: entry-level fields, never raw PDF chunks) ──────

def parse_entry(path: Path):
    """Return (slug, title, embed_text) for one kb entry."""
    text = path.read_text(errors="ignore")
    fm = {}
    body = text
    m = FM_RE.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip('"')
        body = text[m.end():]

    def sect(name):
        mm = re.search(rf"^##\s+{name}\s*\n(.*?)(?=\n##\s|\Z)", body, re.S | re.M)
        return mm.group(1).strip() if mm else ""

    embed_text = "\n".join([
        fm.get("title", ""),
        fm.get("tags", ""),
        sect("Abstract"),
        sect("Method"),
        sect("Key Result"),
        sect("Takeaway"),
        sect("Relevance"),
    ]).strip()
    return path.stem, fm.get("title", path.stem), embed_text


def load_entries(kb_dir: Path):
    if not kb_dir.is_dir():
        sys.exit(f"error: kb dir not found: {kb_dir}")
    return [parse_entry(p) for p in sorted(kb_dir.glob("*.md")) if p.name != "INDEX.md"]


def index_dir(kb_dir: Path) -> Path:
    # Sibling .index under docs/kb/ (kb_dir is docs/kb/literature). docs/ is untracked.
    return kb_dir.parent / ".index"


def text_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


# ── embedding (lazy import so --help works without fastembed) ─────────────────

def _get_model():
    try:
        from fastembed import TextEmbedding
    except ImportError:
        sys.stderr.write(
            "error: fastembed not installed. Install with:\n"
            "  pip install fastembed numpy   (or: uv add fastembed numpy)\n"
            "Without it, /find-kb falls back to grep.\n"
        )
        sys.exit(2)
    return TextEmbedding(model_name=MODEL_NAME)


def _l2(mat):
    import numpy as np
    mat = np.asarray(mat, dtype="float32")
    if mat.ndim == 1:
        return mat / (np.linalg.norm(mat) or 1.0)
    return mat / np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-12, None)


def embed_docs(model, texts):
    """Embed plain (documents get NO instruction prefix). Returns L2-normed matrix."""
    import numpy as np
    if not texts:
        return np.zeros((0, DIM), dtype="float32")
    return _l2(list(model.embed(list(texts))))


def embed_query(model, text):
    """Embed a query with the bge instruction prefix. Returns one L2-normed vector."""
    vecs = list(model.embed([QUERY_INSTRUCTION + text]))
    return _l2(vecs[0])


# ── index io ──────────────────────────────────────────────────────────────────

def load_index(kb_dir: Path):
    import numpy as np
    idir = index_dir(kb_dir)
    meta_p, vec_p = idir / "meta.json", idir / "vectors.npy"
    if not (meta_p.exists() and vec_p.exists()):
        return None, None
    meta = json.loads(meta_p.read_text())
    return meta, np.load(vec_p)


def index_drift(kb_dir: Path, meta: dict):
    """(added, changed, dropped) slugs — the corpus on disk vs what the index holds.

    Keyed on the same embed-text hash `cmd_build` caches on, so an edit the parser
    ignores is not drift. Cheap: it re-reads the entries, it never embeds.
    """
    disk = {slug: text_hash(text) for slug, _, text in load_entries(kb_dir)}
    indexed = {e["slug"]: e.get("hash") for e in meta.get("entries", [])}
    added = sorted(set(disk) - set(indexed))
    dropped = sorted(set(indexed) - set(disk))
    changed = sorted(s for s in set(disk) & set(indexed) if indexed[s] != disk[s])
    return added, changed, dropped


def drift_summary(added, changed, dropped, limit=3):
    """One line naming what the index is missing, or None when it is current."""
    if not (added or changed or dropped):
        return None
    counts = ", ".join(f"{len(g)} {name}" for name, g in
                       (("new", added), ("changed", changed), ("dropped", dropped)) if g)
    named = added + changed + dropped
    shown = ", ".join(named[:limit])
    if len(named) > limit:
        shown += f", +{len(named) - limit} more"
    return f"{counts} since the index was built ({shown})"


# ── commands ────────────────────────────────────────────────────────────────

def cmd_build(args):
    import numpy as np
    kb_dir = Path(args.kb)
    entries = load_entries(kb_dir)
    if not entries:
        sys.exit(f"error: no kb entries (*.md) under {kb_dir}")

    old_meta, old_vecs = load_index(kb_dir)
    old_rows = {}
    if old_meta and old_vecs is not None and old_meta.get("model") == MODEL_NAME:
        for i, e in enumerate(old_meta.get("entries", [])):
            if i < len(old_vecs):
                old_rows[(e["slug"], e["hash"])] = old_vecs[i]

    model = None
    rows, new_meta_entries = [], []
    n_embed = n_reuse = 0
    to_embed = []  # (row_index, text)
    for slug, title, embed_text in entries:
        h = text_hash(embed_text)
        rel_path = str((kb_dir / f"{slug}.md"))
        new_meta_entries.append({"slug": slug, "title": title, "path": rel_path, "hash": h})
        cached = old_rows.get((slug, h))
        if cached is not None:
            rows.append(cached)
            n_reuse += 1
        else:
            rows.append(None)
            to_embed.append((len(rows) - 1, embed_text))

    if to_embed:
        model = _get_model()
        fresh = embed_docs(model, [t for _, t in to_embed])
        for (ri, _), vec in zip(to_embed, fresh):
            rows[ri] = vec
        n_embed = len(to_embed)

    n_drop = max(0, len(old_rows) - n_reuse) if old_meta else 0
    vectors = np.asarray(rows, dtype="float32")

    # Calibrate the gate on this corpus via the SAME embed_query path as real search.
    if model is None:
        model = _get_model()
    probe_top1 = []
    for q in OFFTOPIC_PROBES:
        qv = embed_query(model, q)
        probe_top1.append(float((vectors @ qv).max()))
    noise_floor = max(probe_top1)
    gate = noise_floor + args.margin

    idir = index_dir(kb_dir)
    idir.mkdir(parents=True, exist_ok=True)
    np.save(idir / "vectors.npy", vectors)
    meta = {
        "model": MODEL_NAME,
        "margin": args.margin,
        "noise_floor": noise_floor,
        "gate": gate,
        "entries": new_meta_entries,
    }
    (idir / "meta.json").write_text(json.dumps(meta, indent=2))

    print(f"built {len(entries)} entries ({n_embed} embedded, {n_reuse} reused, {n_drop} dropped)")
    print(f"noise_floor = {noise_floor:.3f} (max over {len(OFFTOPIC_PROBES)} off-topic probes)")
    print(f"gate = {gate:.3f} (noise_floor + margin {args.margin:.2f})")


def cmd_search(args):
    kb_dir = Path(args.kb)
    meta, vectors = load_index(kb_dir)
    if meta is None:
        sys.exit(f"error: no index at {index_dir(kb_dir)} — run `maestro kb build` first")
    drift = drift_summary(*index_drift(kb_dir, meta))
    if drift:
        print(f"warning: kb index is STALE — {drift}. These hits come from the OLD "
              f"corpus; run `maestro kb build` to bring it up to date.", file=sys.stderr)

    model = _get_model()
    qv = embed_query(model, args.query)
    sims = vectors @ qv
    k = min(args.top_k, len(sims))
    import numpy as np
    order = np.argsort(-sims)[:k]
    gate = meta["gate"]
    top = float(sims[order[0]]) if k else 0.0

    if top >= gate:
        print(f"VERDICT: RELEVANT (top={top:.2f} ≥ gate {gate:.2f})")
    else:
        print(f"VERDICT: NO STRONG MATCH (top={top:.2f} < gate {gate:.2f}) — proceeding without kb")
    for i in order:
        e = meta["entries"][i]
        title = e["title"][:70]
        print(f"{sims[i]:.3f}  {e['slug']}   {title}   {e['path']}")


def cmd_selftest(args):
    import numpy as np
    kb_dir = Path(args.kb)
    meta, vectors = load_index(kb_dir)
    if meta is None:
        sys.exit(f"error: no index at {index_dir(kb_dir)} — run `maestro kb build` first")
    n = len(meta["entries"])
    ok = True

    # freshness: the index covers exactly the corpus on disk, at its current text
    drift = drift_summary(*index_drift(kb_dir, meta))
    print(f"[{'FAIL' if drift else 'PASS'}] freshness: "
          + (f"index is stale — {drift}" if drift else f"index matches all {n} entries on disk"))
    ok &= not drift

    # wiring: vectors shape == (N, 384)
    wiring = vectors.shape == (n, DIM)
    print(f"[{'PASS' if wiring else 'FAIL'}] wiring: vectors shape {vectors.shape} (expected ({n}, {DIM}))")
    ok &= wiring

    # self-retrieval recall@1: each entry's TITLE should retrieve itself at rank 1.
    model = _get_model()
    hits = 0
    for i, e in enumerate(meta["entries"]):
        qv = embed_query(model, e["title"])
        if int(np.argmax(vectors @ qv)) == i:
            hits += 1
    recall = hits / n if n else 0.0
    rpass = recall >= 0.90
    print(f"[{'PASS' if rpass else 'FAIL'}] self-retrieval recall@1 = {hits}/{n} ({recall * 100:.0f}%)")
    ok &= rpass

    # gate report (informational, no pass/fail)
    print(f"[INFO] gate report: noise_floor={meta['noise_floor']:.3f}, "
          f"gate={meta['gate']:.3f}, margin={meta['margin']:.2f}")

    sys.exit(0 if ok else 1)
