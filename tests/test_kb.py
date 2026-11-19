"""Tests for the literature kb — `maestro kb build|search|selftest`.

The embedder itself is not under test: it is a downloaded model, it is not
reproducible across machines, and a suite that needs one stops being runnable
offline. What the commands own is everything AROUND the vectors, and that is what is
pinned here:

  * an entry is embedded from its FIELDS (title, tags, and five named sections), not
    from the whole file — a change to prose the parser ignores must not invalidate it;
  * a rebuild re-embeds only what changed, keyed on the hash of that text;
  * the relevance gate is CALIBRATED per corpus (max off-topic probe + margin) rather
    than hardcoded, and search reports its verdict against that number;
  * an index that no longer covers the corpus on disk is REPORTED — search warns and
    selftest fails, so a stale index is never silently searched;
  * search without an index refuses and says which command builds one.

A deterministic hashed bag-of-words stands in for bge-small: shared words put two texts
close together, which is all the surrounding logic needs to be exercised.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from maestro_cli import kb  # noqa: E402
from maestro_cli.cli import main  # noqa: E402


class FakeEmbedder:
    """Deterministic stand-in for bge-small: each word lands in one of DIM buckets."""

    def __init__(self):
        self.embedded = []

    def embed(self, texts):
        for t in texts:
            self.embedded.append(t)
            v = np.zeros(kb.DIM, dtype="float32")
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.sha1(w.encode()).hexdigest(), 16) % kb.DIM] += 1.0
            yield v


@pytest.fixture
def model(monkeypatch):
    fake = FakeEmbedder()
    monkeypatch.setattr(kb, "_get_model", lambda: fake)
    return fake


ENTRY = """---
title: Random Forests
tags: ensembles, bagging
---

## Abstract

Bagging many decision trees lowers variance.

## Method

Bootstrap samples, random feature subsets at each split.

## Notes

Typo fixed on tuesday.
"""


@pytest.fixture
def kb_dir(tmp_path):
    d = tmp_path / "docs" / "kb" / "literature"
    d.mkdir(parents=True)
    (d / "breiman_forests.md").write_text(ENTRY)
    (d / "vaswani_attention.md").write_text(
        "---\ntitle: Attention Is All You Need\ntags: transformers\n---\n\n"
        "## Abstract\n\nSelf attention replaces recurrence entirely.\n")
    return d


def build(kb_dir, *extra):
    main(["kb", "build", f"--kb={kb_dir}", *extra])


def meta_of(kb_dir):
    return json.loads((kb.index_dir(kb_dir) / "meta.json").read_text())


def refusal(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None), f"{argv} was expected to refuse"
    return str(e.value)


# ── parsing: an entry is its fields, not its file ────────────────────────────

def test_embed_text_is_built_from_the_named_fields(tmp_path):
    p = tmp_path / "breiman_forests.md"
    p.write_text(ENTRY)
    slug, title, text = kb.parse_entry(p)
    assert (slug, title) == ("breiman_forests", "Random Forests")
    assert "Bagging many decision trees" in text and "Bootstrap samples" in text
    # A section the parser does not read stays out, so editing it changes no vector.
    assert "tuesday" not in text


def test_an_entry_without_a_title_falls_back_to_its_filename(tmp_path):
    p = tmp_path / "unnamed_paper.md"
    p.write_text("## Abstract\n\nSomething.\n")
    assert kb.parse_entry(p)[1] == "unnamed_paper"


def test_the_generated_index_is_not_an_entry(kb_dir):
    (kb_dir / "INDEX.md").write_text("# Literature Index\n")
    assert [slug for slug, _, _ in kb.load_entries(kb_dir)] == \
        ["breiman_forests", "vaswani_attention"]


def test_a_missing_kb_dir_names_the_path(tmp_path):
    with pytest.raises(SystemExit) as e:
        kb.load_entries(tmp_path / "nope")
    assert "nope" in str(e.value)


def test_the_index_sits_beside_the_entries_not_inside_them(kb_dir):
    assert kb.index_dir(kb_dir) == kb_dir.parent / ".index"


def test_a_zero_vector_normalises_without_dividing_by_zero(model):
    assert not np.isnan(kb._l2(np.zeros(kb.DIM))).any()
    assert not np.isnan(kb._l2(np.zeros((2, kb.DIM)))).any()
    rows = kb._l2(np.array([[3.0, 4.0] + [0.0] * (kb.DIM - 2)]))
    assert np.isclose(np.linalg.norm(rows[0]), 1.0)


# ── build: embed what changed, calibrate the gate ────────────────────────────

def test_build_writes_the_index_beside_the_corpus(kb_dir, model, capsys):
    build(kb_dir)
    meta, vectors = kb.load_index(kb_dir)
    assert vectors.shape == (2, kb.DIM)
    assert meta["model"] == kb.MODEL_NAME
    assert [e["slug"] for e in meta["entries"]] == ["breiman_forests", "vaswani_attention"]
    assert "2 embedded" in capsys.readouterr().out


def test_an_unchanged_entry_is_not_embedded_again(kb_dir, model, capsys):
    build(kb_dir)
    model.embedded.clear()
    build(kb_dir)
    assert "0 embedded, 2 reused" in capsys.readouterr().out
    # Only the off-topic probes were embedded on the second pass.
    assert len(model.embedded) == len(kb.OFFTOPIC_PROBES)


def test_only_the_edited_entry_is_re_embedded(kb_dir, model, capsys):
    build(kb_dir)
    (kb_dir / "vaswani_attention.md").write_text(
        "---\ntitle: Attention Is All You Need\ntags: transformers\n---\n\n"
        "## Abstract\n\nSelf attention replaces recurrence, and scales.\n")
    build(kb_dir)
    assert "1 embedded, 1 reused" in capsys.readouterr().out


def test_an_edit_the_parser_ignores_costs_no_embedding(kb_dir, model, capsys):
    """The cache key is the hash of the embed text, so untouched fields stay cached."""
    build(kb_dir)
    (kb_dir / "breiman_forests.md").write_text(ENTRY.replace("tuesday", "wednesday"))
    build(kb_dir)
    assert "0 embedded" in capsys.readouterr().out


def test_a_dropped_entry_leaves_the_index(kb_dir, model, capsys):
    build(kb_dir)
    (kb_dir / "vaswani_attention.md").unlink()
    build(kb_dir)
    meta, vectors = kb.load_index(kb_dir)
    assert [e["slug"] for e in meta["entries"]] == ["breiman_forests"]
    assert vectors.shape == (1, kb.DIM) and "1 dropped" in capsys.readouterr().out


def test_the_gate_sits_a_margin_above_this_corpus_noise_floor(kb_dir, model):
    build(kb_dir, "--margin=0.25")
    meta = meta_of(kb_dir)
    assert meta["margin"] == 0.25
    assert meta["gate"] == pytest.approx(meta["noise_floor"] + 0.25)


def test_a_corpus_with_no_entries_is_refused(tmp_path, model):
    empty = tmp_path / "docs" / "kb" / "literature"
    empty.mkdir(parents=True)
    assert "no kb entries" in refusal(["kb", "build", f"--kb={empty}"])


# ── search ───────────────────────────────────────────────────────────────────

def test_searching_without_an_index_says_what_to_run(kb_dir, model):
    assert "kb build" in refusal(["kb", "search", f"--kb={kb_dir}", "--query=forests"])


def _search(kb_dir, capsys, *extra, query):
    """Search on a built index, reading back ONLY what the search printed."""
    build(kb_dir)
    capsys.readouterr()                       # drop the build's own output
    main(["kb", "search", f"--kb={kb_dir}", f"--query={query}", *extra])
    return capsys.readouterr().out.strip().splitlines()


def test_a_matching_query_is_relevant_and_names_the_entry(kb_dir, model, capsys):
    lines = _search(kb_dir, capsys, query="bagging decision trees lowers variance")
    assert "VERDICT: RELEVANT" in lines[0]
    assert lines[1].split()[1] == "breiman_forests"


def test_an_off_topic_query_is_gated_out(kb_dir, model, capsys):
    lines = _search(kb_dir, capsys, query="what time is it right now")
    assert "NO STRONG MATCH" in lines[0]


def test_top_k_bounds_the_hits(kb_dir, model, capsys):
    assert len(_search(kb_dir, capsys, "--top-k=1", query="attention")) == 2   # verdict + 1


def test_top_k_larger_than_the_corpus_is_not_an_error(kb_dir, model, capsys):
    assert len(_search(kb_dir, capsys, "--top-k=50", query="attention")) == 3  # verdict + both


# ── drift: an index that no longer matches the corpus ────────────────────────

def test_a_fresh_index_reports_no_drift(kb_dir, model):
    build(kb_dir)
    meta = meta_of(kb_dir)
    assert kb.index_drift(kb_dir, meta) == ([], [], [])
    assert kb.drift_summary(*kb.index_drift(kb_dir, meta)) is None


def test_drift_separates_added_changed_and_dropped(kb_dir, model):
    build(kb_dir)
    meta = meta_of(kb_dir)
    (kb_dir / "he_bert.md").write_text("---\ntitle: BERT\n---\n\n## Abstract\n\nMasked.\n")
    (kb_dir / "breiman_forests.md").write_text(
        ENTRY.replace("lowers variance", "lowers variance a great deal"))
    (kb_dir / "vaswani_attention.md").unlink()
    added, changed, dropped = kb.index_drift(kb_dir, meta)
    assert (added, changed, dropped) == (["he_bert"], ["breiman_forests"], ["vaswani_attention"])


def test_an_edit_the_parser_ignores_is_not_drift(kb_dir, model):
    """Drift is keyed on the embed text, so prose no vector saw cannot be stale."""
    build(kb_dir)
    meta = meta_of(kb_dir)
    (kb_dir / "breiman_forests.md").write_text(ENTRY.replace("tuesday", "wednesday"))
    assert kb.index_drift(kb_dir, meta) == ([], [], [])


def test_the_drift_line_names_the_counts_and_the_entries(kb_dir, model):
    build(kb_dir)
    meta = meta_of(kb_dir)
    (kb_dir / "he_bert.md").write_text("---\ntitle: BERT\n---\n\n## Abstract\n\nMasked.\n")
    line = kb.drift_summary(*kb.index_drift(kb_dir, meta))
    assert "1 new" in line and "he_bert" in line


def test_a_long_drift_list_is_summarised_not_dumped(kb_dir, model):
    build(kb_dir)
    meta = meta_of(kb_dir)
    for i in range(6):
        (kb_dir / f"paper_{i}.md").write_text(
            f"---\ntitle: Paper {i}\n---\n\n## Abstract\n\nText {i}.\n")
    line = kb.drift_summary(*kb.index_drift(kb_dir, meta))
    assert "6 new" in line and "+3 more" in line


def test_search_on_a_stale_index_warns_and_still_answers(kb_dir, model, capsys):
    build(kb_dir)
    (kb_dir / "he_bert.md").write_text("---\ntitle: BERT\n---\n\n## Abstract\n\nMasked.\n")
    capsys.readouterr()
    main(["kb", "search", f"--kb={kb_dir}", "--query=bagging decision trees"])
    out, err = capsys.readouterr()
    assert "STALE" in err and "kb build" in err        # the warning goes to stderr...
    assert "VERDICT:" in out                            # ...and does not replace the answer
    assert "he_bert" not in out                         # the new entry is genuinely not searched


def test_search_on_a_current_index_is_silent_about_drift(kb_dir, model, capsys):
    build(kb_dir)
    capsys.readouterr()
    main(["kb", "search", f"--kb={kb_dir}", "--query=bagging decision trees"])
    assert "STALE" not in capsys.readouterr().err


def test_selftest_fails_on_a_stale_index(kb_dir, model, capsys):
    build(kb_dir)
    (kb_dir / "he_bert.md").write_text("---\ntitle: BERT\n---\n\n## Abstract\n\nMasked.\n")
    with pytest.raises(SystemExit) as e:
        main(["kb", "selftest", f"--kb={kb_dir}"])
    assert e.value.code == 1
    assert "[FAIL] freshness" in capsys.readouterr().out


# ── selftest ─────────────────────────────────────────────────────────────────

def test_selftest_passes_on_a_freshly_built_index(kb_dir, model, capsys):
    build(kb_dir)
    with pytest.raises(SystemExit) as e:
        main(["kb", "selftest", f"--kb={kb_dir}"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "[PASS] freshness" in out and "[PASS] wiring" in out
    assert "recall@1 = 2/2" in out


def test_selftest_without_an_index_says_what_to_run(kb_dir, model):
    assert "kb build" in refusal(["kb", "selftest", f"--kb={kb_dir}"])
