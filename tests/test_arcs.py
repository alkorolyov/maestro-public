"""Optional epic arcs: declared in maestro.toml `[[arcs]]`, set per epic with `--arc`,
grouped on the board, and checked by `docs check` only when declared."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import checks, declaration, epics, indexes  # noqa: E402
from maestro_cli.cli import main  # noqa: E402

ARCS = ('[[arcs]]\nname = "foundation"\nquestion = "Data to research on"\n\n'
        '[[arcs]]\nname = "prediction"\nquestion = "Does a model beat costs"\n')


@pytest.fixture
def project(tmp_path, monkeypatch):
    epic_dir = tmp_path / "docs" / "epics"
    epic_dir.mkdir(parents=True)
    monkeypatch.setattr(epics, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(epics, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(indexes, "ROOT", tmp_path)
    return tmp_path


def fm_of(project, n):
    path = next((project / "docs" / "epics").glob(f"epic_{n:02d}_*.md"))
    return yaml.safe_load(path.read_text().split("---\n")[1]), path.read_text()


def test_arcs_parse_in_order(tmp_path):
    (tmp_path / "maestro.toml").write_text('layers = ["discipline"]\n' + ARCS)
    assert declaration.load(tmp_path).arc_names == ("foundation", "prediction")


def test_duplicate_arc_is_an_error(tmp_path):
    (tmp_path / "maestro.toml").write_text('[[arcs]]\nname="a"\n[[arcs]]\nname="a"\n')
    with pytest.raises(declaration.DeclarationError):
        declaration.load(tmp_path)


def test_no_arcs_declared_leaves_everything_alone(project):
    main(["epic", "new", "--slug=one"])
    fm, _ = fm_of(project, 1)
    assert "arc" not in fm
    assert "## Arcs" not in (project / "docs" / "epics" / "INDEX.md").read_text()
    path = project / "x.md"
    path.write_text("body")
    assert checks.kanban_findings({1: (path, {**fm, "done_when": []})}, arcs=())[0] == []


def test_new_and_update_set_and_clear_arc(project):
    (project / "maestro.toml").write_text(ARCS)
    main(["epic", "new", "--slug=one", "--arc=foundation"])
    assert fm_of(project, 1)[0]["arc"] == "foundation"
    main(["epic", "update", "--id=1", "--arc=prediction"])
    fm, text = fm_of(project, 1)
    assert fm["arc"] == "prediction" and "arc set to prediction" in text
    main(["epic", "update", "--id=1", "--arc="])
    fm, text = fm_of(project, 1)
    assert "arc" not in fm and "arc cleared" in text


def test_undeclared_arc_refused(project):
    (project / "maestro.toml").write_text(ARCS)
    with pytest.raises(SystemExit) as e:
        main(["epic", "new", "--slug=one", "--arc=nope"])
    assert "not a declared arc" in str(e.value)
    main(["epic", "new", "--slug=one"])
    with pytest.raises(SystemExit):
        main(["epic", "update", "--id=1", "--arc=nope"])


def test_board_groups_by_arc_with_derived_status(project):
    (project / "maestro.toml").write_text(ARCS)
    main(["epic", "new", "--slug=a", "--arc=foundation"])
    main(["epic", "new", "--slug=b", "--arc=foundation"])
    main(["epic", "new", "--slug=c", "--arc=prediction"])
    main(["epic", "new", "--slug=d"])
    main(["epic", "update", "--id=1", "--status=active"])
    main(["epic", "update", "--id=3", "--blocked-by=waiting"])
    board = (project / "docs" / "epics" / "INDEX.md").read_text()
    assert board.index("### foundation") < board.index("### prediction") < board.index("### no arc")
    assert "### foundation — active" in board and "### prediction — todo" in board
    assert "epic 1 \u2014 a \u00b7 active \u00b7 items 0/0" in board
    assert "epic 3 \u2014 c \u00b7 todo \u00b7 items 0/0 \u00b7 blocked" in board
    assert "## TODO" not in board and "## Blocked" not in board


def test_arc_status_rules():
    done, todo, rev, act = ({"status": s} for s in ("done", "todo", "review", "active"))
    assert indexes.arc_status([done, done]) == "done"
    assert indexes.arc_status([done, todo]) == "todo"
    assert indexes.arc_status([done, rev]) == "review"
    assert indexes.arc_status([rev, todo, act]) == "active"
    assert indexes.arc_status([]) == "later"


def test_docs_check_flags_missing_and_undeclared_arc(tmp_path):
    (tmp_path / 'r.md').write_text('body')
    base = {"title": "t", "status": "todo", "opened": str(date.today()), "closed": None,
            "blocked_by": None, "done_when": [{"id": 1, "text": "x", "result": "y"}],
            "items": [], "options": [], "outcome": None}
    recs = {1: (tmp_path / "r.md", {**base, "epic": 1}),
            2: (tmp_path / "r.md", {**base, "epic": 2, "arc": "ghost"}),
            3: (tmp_path / "r.md", {**base, "epic": 3, "arc": "foundation"}),
            4: (tmp_path / "r.md", {**base, "epic": 4, "status": "done"})}
    issues, _ = checks.kanban_findings(recs, arcs=("foundation",))
    assert any("epic_1" in i and "no arc" in i for i in issues)
    assert any("epic_2" in i and "not declared" in i for i in issues)
    assert not any("epic_3" in i or "epic_4" in i for i in issues)


def test_drift_check_renders_the_board_with_arcs(project):
    """A board rendered with its arcs is not reported as drift (the check must pass the arcs)."""
    (project / "maestro.toml").write_text('layers = ["discipline"]\n' + ARCS)
    main(["epic", "new", "--slug=data", "--arc=foundation"])
    board = (project / "docs" / "epics" / "INDEX.md").read_text()
    assert "### foundation" in board
    expected = indexes.build_epic_board(indexes.load_epics(indexes.EPIC_DIR),
                                        indexes._declared_arcs())
    assert expected.strip() == board.strip()
