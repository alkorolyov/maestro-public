"""Moving an item between epics: `epic item --move-to` and `--moved-to`.

A moved row LEAVES its epic — there is no `moved` state, so nothing has to learn to
skip one: the row is simply not in the source's counts any more, and the log line is
the one trace of where it went. Pinned here:

  * --move-to writes the new todo row into the target, deletes the source row, and
    logs one line on each side naming the other;
  * --moved-to records a row already copied by hand: the pointer must resolve, the
    target is untouched, and it is the one move allowed on a CLOSED source;
  * only todo rows move; a closed target is refused;
  * ids are stable — the gap stays a gap and a moved-out id is never reused;
  * the board and `close` count only what is left, and K10 does not read a move line
    (which quotes the moved title) as a claim that work happened.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import checks, epics, frontmatter, indexes  # noqa: E402
from maestro_cli.cli import main  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    epic_dir = tmp_path / "docs" / "epics"
    epic_dir.mkdir(parents=True)
    monkeypatch.setattr(epics, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(epics, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "EPIC_DIR", epic_dir)
    return epic_dir


def record(epic_dir, n):
    return next(epic_dir.glob(f"epic_{n:02d}_*.md"))


def fm_of(epic_dir, n):
    return yaml.safe_load(record(epic_dir, n).read_text().split("---\n")[1])


def log_of(epic_dir, n):
    return epics.log_entries(record(epic_dir, n).read_text().split("---\n", 2)[2])


def shaped(title):
    return f"{title} — 3 files — Done: pytest -q"


def refusal(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None)
    return str(e.value.code)


def two_epics(project, n_items=3):
    """Epic 1 with `n_items` todo rows, epic 2 with one."""
    main(["epic", "new", "--slug=source"])
    main(["epic", "new", "--slug=target"])
    for i in range(1, n_items + 1):
        main(["epic", "item", "--id=1", f"--add={shaped(f'row {i}')}"])
    main(["epic", "item", "--id=2", f"--add={shaped('already there')}"])


def close(n):
    main(["epic", "done-when", f"--id={n}", "--add=the thing", "--result=it held"])
    main(["epic", "close", f"--id={n}", "--outcome=delivered"])


def hand_close(epic_dir, n):
    """An epic closed under an older `close`, which still let todo rows stay behind."""
    path = record(epic_dir, n)
    _, fm_text, body = path.read_text().split("---\n", 2)
    fm = yaml.safe_load(fm_text)
    fm.update(status="done", closed="2026-09-20", outcome="delivered")
    path.write_text("---\n" + yaml.dump(fm, sort_keys=False) + "---\n" + body)


# ── --move-to ─────────────────────────────────────────────────────────────────

def test_move_to_adds_the_row_to_the_target_and_removes_it_from_the_source(project, capsys):
    two_epics(project)
    main(["epic", "item", "--id=1", "--item=2", "--blocked-by=waiting on the ADR"])
    main(["epic", "item", "--id=1", "--item=2", "--move-to=2"])
    assert "item 2 moved -> epic_2 item 2" in capsys.readouterr().out

    src = fm_of(project, 1)["items"]
    assert [it["id"] for it in src] == [1, 3]                 # the gap stays a gap
    tgt = fm_of(project, 2)["items"]
    assert [(it["id"], it["title"], it["status"]) for it in tgt] == [
        (1, shaped("already there"), "todo"), (2, shaped("row 2"), "todo")]
    assert tgt[1]["blocked_by"] == "waiting on the ADR"       # the flag travels

    assert log_of(project, 1)[-1].endswith(
        f"item 2 '{shaped('row 2')}' moved -> epic 2 item 2")
    assert log_of(project, 2)[-1].endswith("item 2 moved in from epic 1 item 2")
    # both files were written by the CLI, so both carry a valid stamp
    assert frontmatter.stamp_status(record(project, 1)) == "ok"
    assert frontmatter.stamp_status(record(project, 2)) == "ok"


def test_a_moved_out_id_is_never_reused(project):
    two_epics(project)
    main(["epic", "item", "--id=1", "--item=3", "--move-to=2"])
    main(["epic", "item", "--id=1", f"--add={shaped('new work')}"])
    assert [it["id"] for it in fm_of(project, 1)["items"]] == [1, 2, 4]


@pytest.mark.parametrize("status,extra", [("in_progress", []),
                                          ("done", ["--evidence=tests/test_x.py"])])
def test_only_a_todo_row_moves(project, status, extra):
    two_epics(project)
    main(["epic", "item", "--id=1", "--item=1", f"--status={status}", *extra])
    said = refusal(["epic", "item", "--id=1", "--item=1", "--move-to=2"])
    assert f"item 1 is {status}: only a todo row moves" in said
    assert len(fm_of(project, 1)["items"]) == 3 and len(fm_of(project, 2)["items"]) == 1


def test_move_into_a_closed_epic_is_refused(project):
    two_epics(project)
    main(["epic", "item", "--id=2", "--item=1", "--status=dropped", "--reason=superseded"])
    close(2)
    said = refusal(["epic", "item", "--id=1", "--item=1", "--move-to=2"])
    assert "epic_2 is closed" in said
    assert len(fm_of(project, 1)["items"]) == 3 and len(fm_of(project, 2)["items"]) == 1


def test_move_to_out_of_a_closed_epic_is_refused_and_names_moved_to(project):
    two_epics(project)
    hand_close(project, 1)
    said = refusal(["epic", "item", "--id=1", "--item=1", "--move-to=2"])
    assert "epic_1 is closed" in said and "--moved-to" in said


def test_move_to_refuses_the_same_epic_an_unknown_one_and_extra_flags(project):
    two_epics(project)
    assert "already in" in refusal(["epic", "item", "--id=1", "--item=1", "--move-to=1"])
    assert "epic_9 not found" in refusal(["epic", "item", "--id=1", "--item=1", "--move-to=9"])
    assert "does not combine" in refusal(
        ["epic", "item", "--id=1", "--item=1", "--move-to=2", "--status=done"])
    assert "one, not both" in refusal(
        ["epic", "item", "--id=1", "--item=1", "--move-to=2", "--moved-to=epic 2 item 1"])


def test_move_to_respects_the_target_size_cap(project):
    two_epics(project)
    for i in range(7):                      # target reaches max_open_items (8)
        main(["epic", "item", "--id=2", f"--add={shaped(f'filler {i}')}"])
    assert "open items" in refusal(["epic", "item", "--id=1", "--item=1", "--move-to=2"])
    assert len(fm_of(project, 1)["items"]) == 3


# ── --moved-to (a row already copied by hand) ─────────────────────────────────

def test_moved_to_removes_the_source_row_and_leaves_the_target_alone(project):
    two_epics(project)
    before = record(project, 2).read_text()
    main(["epic", "item", "--id=1", "--item=1", "--moved-to=epic 2 item 1"])
    assert [it["id"] for it in fm_of(project, 1)["items"]] == [2, 3]
    assert record(project, 2).read_text() == before
    assert log_of(project, 1)[-1].endswith(
        f"item 1 '{shaped('row 1')}' moved -> epic 2 item 1")


def test_moved_to_is_allowed_on_a_closed_source(project, capsys):
    two_epics(project)
    hand_close(project, 1)
    capsys.readouterr()
    main(["epic", "item", "--id=1", "--item=1", "--moved-to=epic 2 item 1"])
    fm = fm_of(project, 1)
    assert fm["status"] == "done" and [it["id"] for it in fm["items"]] == [2, 3]


def test_moved_to_needs_a_pointer_that_resolves(project):
    two_epics(project)
    assert "must read" in refusal(["epic", "item", "--id=1", "--item=1", "--moved-to=epic 2"])
    assert "epic_7 not found" in refusal(
        ["epic", "item", "--id=1", "--item=1", "--moved-to=epic 7 item 1"])
    assert "has no item 5" in refusal(
        ["epic", "item", "--id=1", "--item=1", "--moved-to=epic 2 item 5"])
    assert len(fm_of(project, 1)["items"]) == 3


def test_moved_to_refuses_a_row_that_is_not_todo(project):
    two_epics(project)
    main(["epic", "item", "--id=1", "--item=1", "--status=done", "--evidence=tests/x.py"])
    hand_close(project, 1)
    said = refusal(["epic", "item", "--id=1", "--item=1", "--moved-to=epic 2 item 1"])
    assert "only a todo row moves" in said


# ── counting: the board, close, and the checks ────────────────────────────────

def test_board_and_close_count_only_the_rows_left(project, capsys):
    two_epics(project)
    main(["epic", "item", "--id=1", "--item=1", "--status=done", "--evidence=tests/x.py"])
    main(["epic", "item", "--id=1", "--item=2", "--move-to=2"])
    main(["epic", "item", "--id=1", "--item=3", "--move-to=2"])
    board = (project / "INDEX.md").read_text()
    assert "items 1/1" in board                   # epic 1: two rows left for epic 2
    assert "items 0/3" in board                   # epic 2: one of its own + two in
    capsys.readouterr()
    close(1)
    out = capsys.readouterr().out
    assert "Closed epic_1" in out and "left todo" not in out


def test_k10_does_not_read_a_moved_title_as_a_claim(project):
    two_epics(project)
    main(["epic", "item", "--id=1", f"--add={shaped('the merged loader')}"])
    main(["epic", "item", "--id=1", "--item=4", "--move-to=2"])
    records = frontmatter.load(project, "epic")
    issues, _ = checks.kanban_findings(records)
    assert not [i for i in issues if "board never moved" in i]
