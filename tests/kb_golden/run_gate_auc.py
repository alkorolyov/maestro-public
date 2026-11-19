#!/usr/bin/env python3
"""HARD-NEGATIVE ROC-AUC benchmark for the kb relevance GATE (maestro kb search).

Measures how well each of 4 embedding models separates ON-topic queries (113
positives, each grounded to a real paper in the corpus) from HARD near-domain
negatives (~80 queries from the same broad field — comp drug discovery, molecular
ML, structural biology — but about subtopics ABSENT from the corpus). Trivial
off-topic negatives ("capital of France") would inflate AUC; near-domain negatives
that share vocabulary (molecular, peptide, MD, binding, structure) are the real test.

The corpus is EXTERNAL — a 50-paper membrane-permeability kb from a separate project —
because maestro's own kb is empty. See README.md.

Per model:
  1. top-1 cosine for every query (positives + hard negatives)
  2. ROC-AUC (ON=1) + bootstrap 95% CI (2000 resamples, fixed seed)
  3. paired bootstrap of dAUC vs bge-base (same resampled indices both models)
  4. gate confusion (TP/FP/FN/TN), precision, recall, specificity at calibrated gate
  5. separation gap = min(pos top1) - max(neg top1); dim; embed_s

Gate calibration: noise_floor = max(top1 over the 6 generic dev probes); gate =
noise_floor + 0.10. Probes model real non-kb dev turns (the gate's actual job).

Each model runs in an isolated subprocess; doc embeddings cached per model.

  driver:  KB_DEVICE=cuda python run_gate_auc.py
  worker:  python run_gate_auc.py --worker <key> <out.json>

Env:
  KB_DEVICE           cpu (default) | cuda
  MAESTRO_KB_CORPUS   corpus dir holding the kb entries — REQUIRED, no default
                      (KB_CORPUS is accepted as an alias)
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
# load_entries lives in the maestro CLI package (this golden set ships with maestro)
TOOLS = HERE.parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
from maestro_cli.kb import load_entries  # noqa: E402

_corpus = os.environ.get("MAESTRO_KB_CORPUS") or os.environ.get("KB_CORPUS")
if not _corpus:
    sys.exit("MAESTRO_KB_CORPUS is not set. This benchmark scores the gate against an\n"
             "EXTERNAL knowledge base (maestro's own docs/kb/ is empty), so point it at a\n"
             "directory of kb literature entries:\n"
             "  MAESTRO_KB_CORPUS=/path/to/project/docs/kb/literature python run_gate_auc.py")
KB = Path(_corpus).expanduser()
if not KB.is_dir():
    sys.exit(f"MAESTRO_KB_CORPUS={KB} is not a directory.")
CACHE = Path(os.environ.get("KB_CACHE", "/tmp/kb_gate_cache"))
CACHE.mkdir(exist_ok=True)

POS_TSV = HERE / "positives.tsv"          # query \t target_slug  (actually: slug \t query)
NEG_TSV = HERE / "negatives_hard.tsv"     # query \t nearest_slug \t why
PROBES = HERE / "probes.txt"              # 6 generic dev probes

BOOT_N = 2000
BOOT_SEED = 1234
GATE_MARGIN = 0.10

# ---------------------------------------------------------------- corpus
entries = load_entries(KB)                  # [(slug, title, embed_text), ...]
doc_texts = [e[2] for e in entries]
doc_titles = [e[1] for e in entries]
slugs = [e[0] for e in entries]

# ---------------------------------------------------------------- queries
def _load_positives():
    qs = []
    for ln in POS_TSV.read_text().splitlines():
        if not ln.strip() or "\t" not in ln:
            continue
        slug, q = ln.split("\t", 1)
        q = q.strip()
        if q:
            qs.append(q)
    return qs


def _load_negatives():
    qs = []
    for ln in NEG_TSV.read_text().splitlines():
        if not ln.strip():
            continue
        parts = ln.split("\t")
        q = parts[0].strip()
        if q:
            qs.append(q)
    return qs


POS = _load_positives()
NEG = _load_negatives()
PROBE_QS = [ln.strip() for ln in PROBES.read_text().splitlines() if ln.strip()]

BGE_INSTR = "Represent this sentence for searching relevant passages: "


def qwen_fmt(q):
    return (f"Instruct: Given a web search query, retrieve relevant passages "
            f"that answer the query\nQuery: {q}")


MODELS = [
    ("bge-small",  "BAAI/bge-small-en-v1.5",          lambda q: BGE_INSTR + q),
    ("bge-base",   "BAAI/bge-base-en-v1.5",           lambda q: BGE_INSTR + q),
    ("qwen3-0.6b", "Qwen/Qwen3-Embedding-0.6B",        qwen_fmt),
    ("yuan-2.0",   "IEITYuan/Yuan-embedding-2.0-en",  None),
]
MODEL_MAP = {k: (hf, qfn) for k, hf, qfn in MODELS}


def l2(mat):
    mat = np.asarray(mat, dtype="float32")
    if mat.ndim == 1:
        return mat / (np.linalg.norm(mat) or 1.0)
    return mat / np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-12, None)


def docs_fingerprint():
    h = hashlib.sha1()
    for t in doc_texts:
        h.update(t.encode("utf-8")); h.update(b"\x00")
    return h.hexdigest()[:12]


def roc_auc(labels, scores):
    """AUC via Mann-Whitney U with tie handling. labels: 1=pos, 0=neg."""
    labels = np.asarray(labels)
    scores = np.asarray(scores, dtype="float64")
    order = np.argsort(scores, kind="mergesort")
    s = scores[order]
    ranks = np.empty(len(s), dtype="float64")
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        ranks[i:j + 1] = (i + j) / 2.0 + 1.0   # 1-based average rank
        i = j + 1
    rank_full = np.empty(len(s), dtype="float64")
    rank_full[order] = ranks
    n_pos = int(labels.sum())
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    sum_pos = rank_full[labels == 1].sum()
    auc = (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(auc)


def eval_model(key, hf_id, qfn):
    import torch
    torch.set_num_threads(4)
    from sentence_transformers import SentenceTransformer

    device = os.environ.get("KB_DEVICE", "cpu")
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    model = SentenceTransformer(hf_id, device=device, trust_remote_code=True)
    try:
        dim = model.get_embedding_dimension()
    except AttributeError:
        dim = model.get_sentence_embedding_dimension()

    if qfn is None:  # yuan: use its ST-defined query prompt
        prompts = getattr(model, "prompts", {}) or {}
        if "query" in prompts and prompts["query"]:
            qp = prompts["query"]; qfn = lambda q, _p=qp: _p + q
            prompt_desc = f'ST "query" prompt: {qp!r}'
        else:
            qfn = lambda q: q; prompt_desc = "NONE (no instruction)"
    elif key.startswith("bge"):
        prompt_desc = f"BGE instruction on queries: {BGE_INSTR!r}"
    else:
        prompt_desc = "Qwen instruct query format"

    fp = docs_fingerprint()
    dcache = CACHE / f"{key}__docs__{fp}.npy"
    if dcache.exists():
        dvecs = np.load(dcache); embed_s = 0.0; cached = True
    else:
        t0 = time.time()
        dvecs = l2(model.encode(doc_texts, normalize_embeddings=True,
                                batch_size=4, show_progress_bar=False))
        embed_s = time.time() - t0
        np.save(dcache, dvecs); cached = False

    def top1(queries):
        if not queries:
            return np.array([], dtype="float64")
        qv = l2(model.encode([qfn(q) for q in queries], normalize_embeddings=True,
                             batch_size=8, show_progress_bar=False))
        sims = qv @ dvecs.T
        return sims.max(axis=1)

    pos_t1 = top1(POS)
    neg_t1 = top1(NEG)
    probe_t1 = top1(PROBE_QS)

    return dict(key=key, hf_id=hf_id, dim=dim, embed_s=embed_s, cached=cached,
                prompt_desc=prompt_desc,
                pos_top1=pos_t1.tolist(), neg_top1=neg_t1.tolist(),
                probe_top1=probe_t1.tolist())


def run_worker(key, out_path):
    hf_id, qfn = MODEL_MAP[key]
    print(f"[worker {key}] pos={len(POS)} neg={len(NEG)} probes={len(PROBE_QS)} "
          f"docs={len(doc_texts)}", flush=True)
    r = eval_model(key, hf_id, qfn)
    Path(out_path).write_text(json.dumps(r))
    tag = "CACHED" if r["cached"] else f"embed_s={r['embed_s']:.1f}"
    print(f"[worker {key}] done dim={r['dim']} {tag}", flush=True)


if __name__ == "__main__" and len(sys.argv) >= 4 and sys.argv[1] == "--worker":
    run_worker(sys.argv[2], sys.argv[3]); sys.exit(0)


def analyze(results):
    rng = np.random.default_rng(BOOT_SEED)
    n_pos, n_neg = len(POS), len(NEG)
    # shared bootstrap index sets (paired across models)
    boot_pos_idx = [rng.integers(0, n_pos, n_pos) for _ in range(BOOT_N)]
    boot_neg_idx = [rng.integers(0, n_neg, n_neg) for _ in range(BOOT_N)]

    per = {}
    for r in results:
        pos = np.array(r["pos_top1"]); neg = np.array(r["neg_top1"])
        probe = np.array(r["probe_top1"])
        labels = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
        scores = np.concatenate([pos, neg])
        auc = roc_auc(labels, scores)

        boot_aucs = np.empty(BOOT_N)
        for b in range(BOOT_N):
            bp = pos[boot_pos_idx[b]]; bn = neg[boot_neg_idx[b]]
            lab = np.concatenate([np.ones(len(bp)), np.zeros(len(bn))])
            sc = np.concatenate([bp, bn])
            boot_aucs[b] = roc_auc(lab, sc)
        ci = (float(np.percentile(boot_aucs, 2.5)),
              float(np.percentile(boot_aucs, 97.5)))

        noise_floor = float(probe.max()) if len(probe) else 0.0
        gate = noise_floor + GATE_MARGIN
        tp = int((pos >= gate).sum()); fn = int((pos < gate).sum())
        fp = int((neg >= gate).sum()); tn = int((neg < gate).sum())
        prec = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        spec = tn / (tn + fp) if (tn + fp) else float("nan")
        sep_gap = float(pos.min() - neg.max())

        per[r["key"]] = dict(
            key=r["key"], dim=r["dim"], embed_s=r["embed_s"], cached=r["cached"],
            prompt_desc=r["prompt_desc"], auc=auc, ci=ci, boot_aucs=boot_aucs,
            noise_floor=noise_floor, gate=gate, probe_top1=probe.tolist(),
            tp=tp, fp=fp, fn=fn, tn=tn, prec=prec, recall=recall, spec=spec,
            sep_gap=sep_gap, pos_min=float(pos.min()), neg_max=float(neg.max()))

    # paired bootstrap dAUC vs bge-base
    ref = per.get("bge-base")
    for k, p in per.items():
        if ref is None or k == "bge-base":
            p["dauc"] = None
            continue
        diffs = p["boot_aucs"] - ref["boot_aucs"]
        p["dauc"] = dict(mean=float(diffs.mean()),
                         ci=(float(np.percentile(diffs, 2.5)),
                             float(np.percentile(diffs, 97.5))))
    return per


def main():
    print(f"positives={len(POS)}  hard_negatives={len(NEG)}  probes={len(PROBE_QS)}  "
          f"corpus={len(doc_texts)} docs  device={os.environ.get('KB_DEVICE','cpu')}",
          flush=True)
    print(f"corpus dir: {KB}", flush=True)

    results = []
    for key, hf_id, qfn in MODELS:
        print(f"\n{'='*70}\n{key}  ({hf_id})\n{'='*70}", flush=True)
        out = CACHE / f"gate_res_{key}.json"
        if out.exists():
            out.unlink()
        proc = subprocess.run([sys.executable, __file__, "--worker", key, str(out)],
                              capture_output=True, text=True)
        for line in proc.stdout.splitlines():
            if line.startswith("[worker"):
                print("  " + line, flush=True)
        if out.exists():
            results.append(json.loads(out.read_text()))
            print("  -> OK", flush=True)
        else:
            tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
            print(f"  !! FAILED {key} exit={proc.returncode}\n{tail}", flush=True)

    if not results:
        print("no results"); return
    per = analyze(results)

    print("\n\n" + "#" * 70 + "\n# SECTION B — per-model gate + AUC\n" + "#" * 70)
    for k in [m[0] for m in MODELS]:
        if k not in per:
            continue
        p = per[k]
        print(f"\n### {p['key']}  dim={p['dim']}  ({p['prompt_desc']})")
        print(f"  AUC          : {p['auc']:.4f}  95% CI [{p['ci'][0]:.4f}, {p['ci'][1]:.4f}]")
        print(f"  noise_floor  : {p['noise_floor']:.4f}  ->  gate = {p['gate']:.4f}")
        print(f"  confusion    : TP={p['tp']} FP={p['fp']} FN={p['fn']} TN={p['tn']}  "
              f"(of {p['tp']+p['fn']} pos / {p['fp']+p['tn']} neg)")
        print(f"  precision    : {p['prec']:.4f}   recall: {p['recall']:.4f}   "
              f"specificity: {p['spec']:.4f}")
        print(f"  sep_gap      : {p['sep_gap']:.4f}  (pos_min {p['pos_min']:.4f} - neg_max {p['neg_max']:.4f})")
        print(f"  embed_s      : {p['embed_s']:.1f}  cached={p['cached']}")

    print("\n\n" + "#" * 70 + "\n# SECTION C — final table (sorted by AUC desc)\n" + "#" * 70)
    print("\n| model | dim | AUC | AUC 95% CI | gate | FP | prec | spec | sep_gap |")
    print("|" + "---|" * 9)
    for k in sorted(per, key=lambda x: -per[x]["auc"]):
        p = per[k]
        print(f"| {p['key']} | {p['dim']} | {p['auc']:.4f} | "
              f"[{p['ci'][0]:.4f}, {p['ci'][1]:.4f}] | {p['gate']:.3f} | {p['fp']} | "
              f"{p['prec']:.3f} | {p['spec']:.3f} | {p['sep_gap']:+.4f} |")

    print("\n\n" + "#" * 70 + "\n# SECTION D — paired dAUC vs bge-base (2000 iters, paired indices)\n" + "#" * 70)
    print("\n| model | dAUC mean | dAUC 95% CI | significant (CI excludes 0)? |")
    print("|---|---|---|---|")
    for k in [m[0] for m in MODELS]:
        if k not in per or k == "bge-base":
            continue
        d = per[k]["dauc"]
        sig = "YES" if (d["ci"][0] > 0 or d["ci"][1] < 0) else "no (within noise)"
        print(f"| {k} | {d['mean']:+.4f} | [{d['ci'][0]:+.4f}, {d['ci'][1]:+.4f}] | {sig} |")

    print("\nDONE.")


if __name__ == "__main__":
    main()
