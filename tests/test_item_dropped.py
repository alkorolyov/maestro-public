"""Dropping an item: `epic item --status=dropped --reason=...`.

A dropped item was measured and deliberately abandoned. It is SETTLED, like done, so
the close and every open-item count stop waiting on it — but it is not done, so the
board says so. Pinned here:

  * --reason is required for dropped (as --evidence is for done), is stored on the row,
    and lands in the epic's log;
  * todo / in_progress -> dropped; dropped -> todo re-opens (the reason leaves the row,
    the log keeps it); done -> dropped and dropped -> anything but todo are refused;
  * close accepts a mix of done and dropped, and refuses while any item is todo;
  * the board, `epic list` and `epic show` count dropped items distinctly;
  * a dropped row does not crowd max_open_items and does not move;
  * K4 blocks a dropped row with no reason (a hand edit).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import checks, epics, indexes  # noqa: E402
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


def item(epic_dir, n, k):
    return next(it for it in fm_of(epic_dir, n)["items"] if it["id"] == k)


def shaped(title):
    return f"{title} — 3 files — Done: pytest -q"


def refusal(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None)
    return str(e.value.code)


def one_epic(n_items=3):
    main(["epic", "new", "--slug=probe"])
    for i in range(1, n_items + 1):
        main(["epic", "item", "--id=1", f"--add={shaped(f'row {i}')}"])
    main(["epic", "done-when", "--id=1", "--add=the thing", "--result=it held"])


def drop(k, reason="0.80x, below the 0.9x bar"):
    main(["epic", "item", "--id=1", f"--item={k}", "--status=dropped", f"--reason={reason}"])


def finish(k):
    main(["epic", "item", "--id=1", f"--item={k}", "--status=done",
          "--evidence=tests/test_item_dropped.py"])


# ── the reason ────────────────────────────────────────────────────────────────

def test_dropped_requires_a_reason(project, capsys):
    one_epic()
    msg = refusal(["epic", "item", "--id=1", "--item=1", "--status=dropped"])
    assert "--reason" in msg
    assert item(project, 1, 1)["status"] == "todo"
    assert "--reason" in refusal(["epic", "item", "--id=1", "--item=1", "--status=dropped",
                                  "--reason=  "])


def test_reason_without_dropped_is_refused(project, capsys):
    one_epic()
    msg = refusal(["epic", "item", "--id=1", "--item=1", "--status=in_progress",
                   "--reason=why not"])
    assert "--status=dropped" in msg
    assert item(project, 1, 1)["status"] == "todo"


def test_drop_stores_the_reason_on_the_row_and_logs_it(project, capsys):
    one_epic()
    main(["epic", "item", "--id=1", "--item=2", "--status=in_progress"])
    drop(2)
    row = item(project, 1, 2)
    assert row["status"] == "dropped"
    assert row["reason"] == "0.80x, below the 0.9x bar"
    assert "evidence" not in row
    assert any("item 2 dropped — 0.80x, below the 0.9x bar" in e for e in log_of(project, 1))


def test_an_overlong_reason_is_refused_at_the_note_cap(project, capsys):
    one_epic()
    msg = refusal(["epic", "item", "--id=1", "--item=1", "--status=dropped",
                   "--reason=" + "x" * 2000])
    assert msg.startswith("--reason is 2000 chars")


# ── transitions ───────────────────────────────────────────────────────────────

def test_reopen_moves_dropped_back_to_todo_and_the_log_keeps_the_reason(project, capsys):
    one_epic()
    drop(1)
    main(["epic", "item", "--id=1", "--item=1", "--status=todo"])
    row = item(project, 1, 1)
    assert row["status"] == "todo"
    assert "reason" not in row
    assert any("item 1 re-opened — was dropped: 0.80x, below the 0.9x bar" in e
               for e in log_of(project, 1))


def test_done_cannot_be_dropped_directly(project, capsys):
    one_epic()
    finish(1)
    msg = refusal(["epic", "item", "--id=1", "--item=1", "--status=dropped", "--reason=r"])
    assert "--status=todo" in msg
    assert item(project, 1, 1)["status"] == "done"


@pytest.mark.parametrize("to", ["done", "in_progress", "dropped"])
def test_dropped_leaves_only_by_reopening(project, capsys, to):
    one_epic()
    drop(1)
    argv = ["epic", "item", "--id=1", "--item=1", f"--status={to}"]
    argv += {"done": ["--evidence=tests/x.py"], "dropped": ["--reason=again"]}.get(to, [])
    assert "re-open it first" in refusal(argv)
    assert item(project, 1, 1)["reason"] == "0.80x, below the 0.9x bar"


def test_a_dropped_row_does_not_move(project, capsys):
    one_epic()
    main(["epic", "new", "--slug=other"])
    drop(1)
    msg = refusal(["epic", "item", "--id=1", "--item=1", "--move-to=2"])
    assert "only a todo row moves" in msg


def test_epic_status_has_no_dropped(project, capsys):
    one_epic()
    assert "review, todo, active, done" in refusal(
        ["epic", "update", "--id=1", "--status=dropped"])


# ── close ─────────────────────────────────────────────────────────────────────

def test_close_accepts_a_mix_of_done_and_dropped(project, capsys):
    one_epic()
    finish(1)
    drop(2)
    finish(3)
    capsys.readouterr()
    main(["epic", "close", "--id=1", "--outcome=two landed; one below the bar"])
    out = capsys.readouterr().out
    assert "Closed epic_1" in out and "1 item(s) dropped" in out
    assert fm_of(project, 1)["status"] == "done"


def test_close_refuses_while_a_todo_item_is_left(project, capsys):
    one_epic()
    finish(1)
    drop(2)
    msg = refusal(["epic", "close", "--id=1", "--outcome=x"])
    assert 'item 3 "' in msg and "(todo)" in msg
    assert "--status=dropped" in msg and "--move-to" in msg
    assert fm_of(project, 1)["status"] != "done"


# ── counts and the board ──────────────────────────────────────────────────────

def test_dropped_items_do_not_crowd_max_open_items(project, capsys):
    main(["epic", "new", "--slug=probe"])
    for i in range(1, 9):                         # the default cap is 8
        main(["epic", "item", "--id=1", f"--add={shaped(f'row {i}')}"])
    assert "max_open_items" in refusal(["epic", "item", "--id=1",
                                        f"--add={shaped('row 9')}"])
    drop(1)
    main(["epic", "item", "--id=1", f"--add={shaped('row 9')}"])
    assert len(epics.open_items(fm_of(project, 1))) == 8


def test_board_list_and_show_count_dropped_distinctly(project, capsys):
    one_epic()
    finish(1)
    drop(2)
    main(["index", "render", "--kind=epic"])
    board = (project / "INDEX.md").read_text()
    assert "items 1/3" in board
    capsys.readouterr()

    main(["epic", "list"])
    assert "items 1/3 done, 1 dropped" in capsys.readouterr().out
    main(["epic", "show", "--id=1"])
    out = capsys.readouterr().out
    assert "items 1/3 done, 1 dropped" in out
    assert "dropped" in out and "reason: 0.80x, below the 0.9x bar" in out


def test_board_says_nothing_about_dropped_when_none_were(project, capsys):
    one_epic()
    main(["index", "render", "--kind=epic"])
    board = (project / "INDEX.md").read_text()
    assert "items 0/3" in board and "dropped" not in board


# ── checks ────────────────────────────────────────────────────────────────────

def test_k4_blocks_a_dropped_row_with_no_reason(project, capsys):
    one_epic()
    drop(1)
    path = record(project, 1)
    head, fm_text, body = path.read_text().split("---\n", 2)
    fm = yaml.safe_load(fm_text)
    fm["items"][0].pop("reason")
    path.write_text("---\n" + yaml.dump(fm, sort_keys=False) + "---\n" + body)

    issues, _ = checks.kanban_findings(epics.load(project, "epic"))
    assert any("item 1" in i and "dropped with no reason" in i for i in issues)


def test_k10_does_not_fire_once_an_item_is_dropped(project, capsys):
    one_epic(n_items=2)
    drop(1, reason="measured, not merged: below the bar")
    issues, _ = checks.kanban_findings(epics.load(project, "epic"))
    assert not any("board never moved" in i for i in issues)
