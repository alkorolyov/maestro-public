"""The record stamp (rule 1, enforced): the CLI signs the surface it owns.

What is pinned: a CLI write stamps; a body edit keeps the stamp valid (bodies are
hand-edited by design); a frontmatter or epic-log hand edit breaks it, whatever
tool made it; `--accept` re-signs without reformatting; `--check` exits 2 on a break.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import checks, frontmatter as fm  # noqa: E402
from maestro_cli.cli import main  # noqa: E402

BODY = "\n# Epic 1\n\nWhy: because.\n\n## Log\n\n- 2026-09-01 — opened.\n\n## Notes\n\nfree text\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in ("EXP_DIR", "ADR_DIR", "EPIC_DIR", "DATA_DIR"):
        monkeypatch.setattr(fm, name, tmp_path / "docs" / name.split("_")[0].lower())
    monkeypatch.setattr(fm, "ROOT", tmp_path)
    fm.EPIC_DIR.mkdir(parents=True)
    return tmp_path


def _epic(project):
    p = fm.EPIC_DIR / "epic_01_x.md"
    fm.write(p, {"epic": 1, "title": "x", "status": "todo", "items": []}, BODY)
    return p


def test_a_cli_write_is_stamped_and_checks_ok(project):
    p = _epic(project)
    assert "sig: " in p.read_text().split("---\n")[1]
    assert fm.stamp_status(p) == "ok"


def test_a_body_edit_keeps_the_stamp_valid(project):
    p = _epic(project)
    p.write_text(p.read_text().replace("free text", "hand-edited prose, allowed"))
    assert fm.stamp_status(p) == "ok"


def test_a_frontmatter_hand_edit_breaks_the_stamp(project):
    p = _epic(project)
    p.write_text(p.read_text().replace("status: todo", "status: done"))
    assert fm.stamp_status(p) == "mismatch"


def test_a_log_hand_append_breaks_the_stamp(project):
    # cat >> ... — a hand append to the log. No tool text is inspected; the file is.
    p = _epic(project)
    text = p.read_text().replace("- 2026-09-01 — opened.\n",
                                 "- 2026-09-01 — opened.\n- 2026-09-02 — all merged.\n")
    p.write_text(text)
    assert fm.stamp_status(p) == "mismatch"


def test_an_unstamped_legacy_record_is_reported_once_not_blocked(project):
    p = fm.EPIC_DIR / "epic_02_legacy.md"
    p.write_text("---\nepic: 2\ntitle: old\nstatus: todo\nitems: []\n---\n" + BODY)
    assert fm.stamp_status(p) == "unstamped"
    issues, notes = checks.stamp_findings()
    assert issues == [] and len(notes) == 1 and "1 record(s) carry no stamp" in notes[0]


def test_accept_restamps_without_reformatting(project):
    p = fm.EPIC_DIR / "epic_02_legacy.md"
    raw = "---\nepic: 2\ntitle: \"quoted title\"\nstatus: todo\nitems: []\n---\n" + BODY
    p.write_text(raw)
    main(["docs", "stamp", "--accept"])
    text = p.read_text()
    assert fm.stamp_status(p) == "ok"
    assert 'title: "quoted title"' in text          # not re-serialised
    assert text.replace(text.split("---\n")[1].splitlines()[-1] + "\n", "") == raw


def test_check_exits_2_on_a_hand_edit_and_names_the_cli(project, capsys):
    p = _epic(project)
    main(["docs", "stamp", "--check"])                 # clean: no exit
    p.write_text(p.read_text().replace("status: todo", "status: in_progress"))
    with pytest.raises(SystemExit) as exc:
        main(["docs", "stamp", "--check"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "epic_01_x.md" in err and "maestro epic" in err and "--accept" in err


def test_check_refuses_no_flag_and_both_flags(project):
    for argv in (["docs", "stamp"], ["docs", "stamp", "--check", "--accept"]):
        with pytest.raises(SystemExit, match="exactly one"):
            main(argv)


def test_the_stamp_format_is_frozen():
    # Golden value. If this fails, every stamp in every adopted project
    # just became a false "hand-edited" — restore the format rather than re-accepting.
    fm_text = "epic: 1\ntitle: x\n"
    body = "\n## Log\n\n- 2026-09-01 — opened.\n"
    assert fm.stamp_of(fm_text, body) == fm.stamp_of(fm_text, body.replace("## Log", "## Ledger"))
    assert fm.stamp_of(fm_text, body) == "c05d46761dcfd1f8"
