"""Tests for the pure `_append_finding` helper in tools/maestro_cli/experiments.py.

`_append_finding(content, section, line)` inserts a finding `line` under `section`
in findings.md text, self-healing by creating the section if it is absent. A
'## Superseded findings' block, if present, must stay last.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli.experiments import _append_finding  # noqa: E402

POS = "## Positive findings (what works)"
NEG = "## Negative findings (what doesn't work)"
LINE = "- **My exp**: it worked — Exp 5\n"


def test_section_present_inserts_under_heading():
    content = (
        "# Findings\n\n"
        f"{POS}\n\n"
        "- **Old**: prior — Exp 1\n\n"
        f"{NEG}\n\n"
        "- **Bad**: nope — Exp 2\n"
    )
    out = _append_finding(content, POS, LINE)
    # New line sits directly under the Positive heading.
    assert f"{POS}\n\n{LINE}" in out
    # Existing positive + negative content untouched.
    assert "- **Old**: prior — Exp 1" in out
    assert NEG in out
    assert "- **Bad**: nope — Exp 2" in out


def test_section_present_negative_heading():
    content = f"# Findings\n\n{POS}\n\n- **Old**: prior — Exp 1\n\n{NEG}\n\n- **Bad**: nope — Exp 2\n"
    out = _append_finding(content, NEG, LINE)
    assert f"{NEG}\n\n{LINE}" in out
    # Positive section untouched, no stray duplicate of the new line.
    assert out.count(LINE) == 1
    assert "- **Old**: prior — Exp 1" in out


def test_section_absent_no_superseded_appends_at_end():
    content = "# Findings\n\nSome preamble prose that must survive.\n"
    out = _append_finding(content, POS, LINE)
    assert "Some preamble prose that must survive." in out
    # New section appended at the very end.
    assert out.rstrip().endswith(LINE.rstrip())
    assert f"{POS}\n\n{LINE}" in out


def test_section_absent_with_superseded_inserts_before_it():
    superseded = "## Superseded findings"
    content = (
        "# Findings\n\n"
        "Some active prose.\n\n"
        f"{superseded}\n\n"
        "- **Overturned**: was wrong — Exp 0\n"
    )
    out = _append_finding(content, POS, LINE)
    # Original content preserved.
    assert "Some active prose." in out
    assert "- **Overturned**: was wrong — Exp 0" in out
    # New section comes BEFORE Superseded, which stays last.
    assert out.index(POS) < out.index(superseded)
    assert out.index(LINE) < out.index(superseded)
    # Superseded is still the last heading in the file.
    assert out.rfind("## ") == out.rfind(superseded)


@pytest.mark.parametrize("section", [POS, NEG])
def test_no_content_lost(section):
    marker = "UNIQUE_PREAMBLE_MARKER_xyz"
    content = f"# Findings\n\n{marker}\n"
    out = _append_finding(content, section, LINE)
    assert marker in out
    assert LINE in out


def test_section_absent_then_present_is_consistent():
    # First call creates the section; a second call inserts under the now-existing one.
    content = "# Findings\n\nPreamble.\n"
    first = _append_finding(content, POS, LINE)
    line2 = "- **Second**: also worked — Exp 6\n"
    second = _append_finding(first, POS, line2)
    assert "Preamble." in second
    assert LINE in second
    assert line2 in second
    # Both lines live under the single Positive heading (only one such heading).
    assert second.count(POS) == 1
