"""Dead references: a live doc cites a repo path that does not exist."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from maestro_cli.checks import dead_path_findings  # noqa: E402


def _tree(root: Path):
    """A minimal project: real top-level dirs so a cite can be judged at all."""
    for d in ("docs", "docs/adrs", "docs/epics", "docs/archive", "src", "tools"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "src" / "real.py").write_text("x = 1\n")
    return root


def test_dead_path_in_claude_md_blocks(tmp_path):
    _tree(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("See `docs/gone.md` for the policy.\n")
    issues, notes = dead_path_findings(tmp_path)
    assert any("docs/gone.md" in i for i in issues)
    assert notes == []


def test_live_path_is_not_flagged(tmp_path):
    _tree(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("Library code lives in `src/real.py`.\n")
    assert dead_path_findings(tmp_path) == ([], [])


def test_record_dirs_are_historical_and_never_judged(tmp_path):
    _tree(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("nothing cited here\n")
    # An ADR is a DATED decision: its paths describe the tree as it was, so a path that
    # has since been deleted is correct as written, not a defect.
    (tmp_path / "docs/adrs/adr_01_x.md").write_text("Ported from `src/deleted_engine.py`.\n")
    (tmp_path / "docs/archive/old.md").write_text("Was `src/also_gone.py`.\n")
    assert dead_path_findings(tmp_path) == ([], [])


def test_live_doc_outside_records_is_advisory_not_blocking(tmp_path):
    _tree(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("nothing cited here\n")
    (tmp_path / "docs/epics/epic_01_a.md").write_text("The table is `docs/vanished.md`.\n")
    issues, notes = dead_path_findings(tmp_path)
    assert issues == []
    assert any("docs/vanished.md" in n for n in notes)


def test_doc_relative_link_resolves_against_its_own_dir(tmp_path):
    _tree(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("nothing cited here\n")
    (tmp_path / "docs/adrs/INDEX.md").write_text("# idx\n")
    # From inside docs/, `adrs/INDEX.md` is a valid relative link — not a dead repo path.
    (tmp_path / "docs/progress.md").write_text("Index: [x](adrs/INDEX.md)\n")
    assert dead_path_findings(tmp_path) == ([], [])


def test_placeholders_and_urls_are_not_paths(tmp_path):
    _tree(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        "Scaffold `docs/experiments/exp_NN_<slug>.md`, see https://example.com/docs/x.md "
        "and `${HOME}/docs/y.md` and `/etc/docs/z.md`.\n")
    assert dead_path_findings(tmp_path) == ([], [])


def test_advisories_are_capped_per_file(tmp_path):
    _tree(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("nothing cited here\n")
    (tmp_path / "docs/audit.md").write_text(
        "\n".join(f"gone `src/missing_{i}.py`" for i in range(9)) + "\n")
    issues, notes = dead_path_findings(tmp_path)
    assert issues == []
    per_path = [n for n in notes if "which does not exist" in n]
    assert len(per_path) == 3                      # capped
    assert any("cites 9 paths that do not exist" in n for n in notes)


def test_blocking_list_is_never_capped(tmp_path):
    _tree(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        "\n".join(f"gone `src/missing_{i}.py`" for i in range(9)) + "\n")
    issues, _ = dead_path_findings(tmp_path)
    assert len(issues) == 9
