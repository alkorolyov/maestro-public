"""Tests for the generated INDEX tables — `indexes.py`.

An INDEX is not a second source of truth: every cell is read back from record
frontmatter, so the tables can be rebuilt from the records at any time (rule 1). That
makes the builders pure functions of a list of frontmatter dicts, and this file tests
them as such — no CLI, no disk.

Pinned here are the DERIVED parts, the ones a reader could not check by eye:

  * `single_seed` is added from `n_seeds == 1` by rule, never by an agent's judgement;
  * "best" is per (track, benchmark), so a benchmark change does not silently shadow
    the prior best with a number measured on a different setup;
  * the sections that route a reader — refuted, open, lineage, needs review, revisions;
  * every table survives a record with fields missing, because rendering is what
    `maestro docs check` runs BEFORE it can report that a record is malformed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import indexes  # noqa: E402


def exp(n, **fields):
    """One experiment's frontmatter, as `load_kind` would hand it over."""
    return {"exp": n, "title": f"e{n}", **fields}


def section(text, name):
    """The lines of one '## <name>' section, headings and separators dropped."""
    if f"## {name}" not in text:
        return []
    body = text.split(f"## {name}", 1)[1].split("\n## ")[0]
    return [ln for ln in body.splitlines()
            if ln.startswith("|") and not ln.startswith("|--") and not ln.startswith("| #")
            and not ln.startswith("| Track") and not ln.startswith("| Date")]


# ── the deterministic review flag ────────────────────────────────────────────

def test_one_seed_flags_itself():
    """Verbalized confidence is miscalibrated, so the flag is a rule over a field."""
    text = indexes.build_exp_index([exp(1, n_seeds=1, takeaway="t")])
    assert "single_seed" in text


def test_a_seed_count_above_one_flags_nothing():
    text = indexes.build_exp_index([exp(1, n_seeds=5, takeaway="t")])
    assert "Needs Review" not in text


def test_the_auto_flag_does_not_displace_a_recorded_one():
    text = indexes.build_exp_index([exp(1, n_seeds=1, flags=["conflicts_prior"])])
    row = section(text, "Needs Review")[0]
    assert "conflicts_prior" in row and "single_seed" in row


# ── best by track and benchmark ──────────────────────────────────────────────

def _competitor(n, track, bench, value, outcome="improved"):
    return exp(n, track=track, benchmark=bench, outcome=outcome, metric={"auc": value})


def test_the_highest_metric_on_a_track_wins():
    text = indexes.build_exp_index([_competitor(1, "wine", "cv5", 0.7),
                                    _competitor(2, "wine", "cv5", 0.9),
                                    _competitor(3, "wine", "cv5", 0.8)])
    rows = section(text, "Best by Track / Benchmark")
    assert len(rows) == 1 and rows[0].split("|")[3].strip() == "2"


def test_a_different_benchmark_keeps_its_own_best():
    """Otherwise a new evaluation setup silently shadows a result it never competed with."""
    text = indexes.build_exp_index([_competitor(1, "wine", "cv5", 0.9),
                                    _competitor(2, "wine", "holdout", 0.5)])
    assert len(section(text, "Best by Track / Benchmark")) == 2


def test_only_a_comparative_outcome_competes():
    text = indexes.build_exp_index([_competitor(1, "wine", "cv5", 0.99, outcome="infra"),
                                    _competitor(2, "wine", "cv5", 0.5)])
    rows = section(text, "Best by Track / Benchmark")
    assert len(rows) == 1 and rows[0].split("|")[3].strip() == "2"


def test_a_track_without_a_metric_does_not_compete():
    text = indexes.build_exp_index([exp(1, track="wine", outcome="improved")])
    assert section(text, "Best by Track / Benchmark") == []


# ── the routing sections ─────────────────────────────────────────────────────

def test_refuted_experiments_are_listed_so_they_are_not_retried():
    text = indexes.build_exp_index([exp(1, outcome="refuted", takeaway="does not work"),
                                    exp(2, outcome="confirmed")])
    rows = section(text, "Refuted Hypotheses (do not re-try)")
    assert len(rows) == 1 and "does not work" in rows[0]


def test_running_and_inconclusive_share_the_open_section():
    text = indexes.build_exp_index([exp(1, status="running"),
                                    exp(2, outcome="inconclusive"),
                                    exp(3, status="done", outcome="confirmed")])
    assert [r.split("|")[1].strip() for r in section(text, "Open / Inconclusive")] == ["1", "2"]


def test_lineage_roots_list_their_children():
    text = indexes.build_exp_index([exp(1), exp(2, parent=1), exp(3, parent=1), exp(4)])
    rows = section(text, "Lineage Roots")
    assert [r.split("|")[1].strip() for r in rows] == ["1", "4"]
    assert rows[0].split("|")[3].strip() == "2, 3"
    assert rows[1].split("|")[3].strip() == "—"


def test_revisions_are_listed_newest_first_and_capped_at_ten():
    revs = [{"date": f"2026-08-{d:02d}", "by": "user", "reason": f"r{d}"} for d in range(1, 13)]
    text = indexes.build_exp_index([exp(1, revisions=revs)])
    rows = section(text, "Recent Revisions")
    assert len(rows) == 10
    assert "2026-08-12" in rows[0] and "2026-08-03" in rows[-1]


def test_sections_with_nothing_in_them_are_not_printed():
    text = indexes.build_exp_index([exp(1)])
    for name in ("Related Networks", "External Pointers", "Needs Review",
                 "Source Artifacts (provenance)", "Recent Revisions"):
        assert f"## {name}" not in text


# ── a malformed record must not take the render down ─────────────────────────

@pytest.mark.parametrize("record", [
    {"exp": 1},                                            # nothing but its number
    {"exp": 1, "flags": ["single_seed"]},                  # in Needs Review, no title
    {"exp": 1, "revisions": [{"date": "2026-08-01"}]},     # in Recent Revisions, no title
    {"exp": 1, "related": [2], "source_artifacts": ["a"]},
])
def test_a_record_missing_its_title_still_renders(record):
    """`docs check` renders before it reports, so a KeyError here hides the finding."""
    assert "| 1 |" in indexes.build_exp_index([record])


def test_the_dataset_table_flags_the_records_with_no_checksum():
    text = indexes.build_data_index([{"dataset": "wine", "sha256": "abc123def456789"},
                                     {"dataset": "pending", "sha256": ""}])
    assert "abc123def456" in text                      # truncated to 12 chars
    assert "## Missing sha256" in text and "pending" in text.split("## Missing sha256")[1]


def test_the_adr_table_points_a_superseded_decision_at_its_replacement():
    text = indexes.build_adr_index([{"adr": 1, "title": "old", "status": "superseded",
                                     "superseded_by": 2},
                                    {"adr": 2, "title": "new", "status": "accepted"}])
    assert "adr_2" in text.split("Superseded")[-1]


def test_a_superseded_decision_keeps_its_text_out_of_the_decisions_table():
    """The index is read into a session's context, so a retracted rule must not sit in it
    next to the rule that replaced it: a superseded record keeps only its pointer row."""
    text = indexes.build_adr_index([
        {"adr": 1, "title": "old", "status": "superseded", "superseded_by": 2,
         "decision": "RETRACTED RULE"},
        {"adr": 2, "title": "new", "status": "accepted", "decision": "the standing rule"},
    ])
    decisions = text.split("## Decisions")[1].split("##")[0]
    assert "RETRACTED RULE" not in decisions
    assert "the standing rule" in decisions
    assert "| 1 |" not in decisions                    # the superseded number is absent too
    history = text.split("Superseded")[-1]
    assert "| 1 |" in history and "adr_2" in history   # still reachable as history
    assert "RETRACTED RULE" not in text                # and never quoted anywhere


def test_the_data_index_marks_a_collecting_dataset(tmp_path):
    text = indexes.build_data_index([
        {"dataset": "wine", "sha256": "abc123def456789"},                       # no status field
        {"dataset": "ticks", "status": "collecting", "sha256": "pending"},
    ])
    assert "| Status |" in text
    wine, ticks = [l for l in text.splitlines() if l.startswith("| [")]
    assert "| complete |" in wine and "| collecting |" in ticks
    assert "## Still collecting" in text and "ticks" in text.split("## Still collecting")[1]
