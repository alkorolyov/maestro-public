"""W1: an ADR records a decision and its evidence, never epics, items or the plan.

Dated (the rule takes effect W1_SINCE): text written on or after it blocks, older text
is one folded legacy advisory per ADR. The base body is dated by the frontmatter `date`,
each `**Amendment (YYYY-MM-DD` paragraph by its own date.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import yaml  # noqa: E402

from maestro_cli import checks  # noqa: E402

NEW = "2026-09-27"
OLD = "2026-09-12"


def adr(tmp_path, body, date=NEW, n=1):
    fm = {"adr": n, "title": "x", "status": "accepted", "date": date}
    p = tmp_path / f"adr_{n:02d}_x.md"
    p.write_text("---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n# ADR\n\n" + body)
    return {n: (p, fm)}


def test_new_adr_citing_an_epic_blocks(tmp_path):
    issues, notes = checks.adr_work_ref_findings(
        adr(tmp_path, "**Decision**: book tables first, as epic 5 item 3 plans."))
    assert len(issues) == 1 and notes == []
    assert "epic 5" in issues[0] and "item 3" in issues[0] and "W1" in issues[0]


def test_old_adr_base_text_is_a_legacy_note_only(tmp_path):
    issues, notes = checks.adr_work_ref_findings(
        adr(tmp_path, "The Databento pull is Epic 5's first step.", date=OLD))
    assert issues == []
    assert len(notes) == 1 and isinstance(notes[0], checks.NonActionable)
    assert "legacy" in notes[0] and "Epic 5" in notes[0]


def test_old_adr_with_a_new_amendment_citing_an_epic_blocks(tmp_path):
    body = ("Layered float, see exp 12.\n\n"
            "**Amendment (2026-09-18)**: layer 3 moves to epic 2.\n\n"
            f"**Amendment ({NEW})**: replaced; the work is tracked in docs/epics/.\n")
    issues, notes = checks.adr_work_ref_findings(adr(tmp_path, body, date=OLD))
    assert len(issues) == 1 and "docs/epics" in issues[0] and "epic 2" not in issues[0]
    assert len(notes) == 1 and "epic 2" in notes[0]


def test_clean_adr_reports_nothing(tmp_path):
    body = ("**Decision**: two options: A (a lake) or B (files). B, because an epic "
            "amount of glue is avoided. Item 3 of the decision: rebuild whole.\n")
    assert checks.adr_work_ref_findings(adr(tmp_path, body)) == ([], [])


def test_an_exp_reference_is_not_work_tracking(tmp_path):
    body = "**Decision**: the 5 s sample stays (exp 152, run_2 metrics.json).\n"
    assert checks.adr_work_ref_findings(adr(tmp_path, body)) == ([], [])


def test_pattern_edges():
    assert checks.work_refs("see epic_07 and Epics\n2") == ["epic_07", "Epics 2"]
    # an item counts only in a sentence that names an epic
    assert checks.work_refs("item 21 is done. Epic 3 is open.") == ["Epic 3"]
    assert checks.work_refs("It is in Up next.") == ["Up next"]
