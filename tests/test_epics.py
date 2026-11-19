"""Tests for the epic record kind (ADR 7 / modules/kanban.md).

The three mechanics that are easy to get wrong, and are therefore pinned here:

  * the WIP limits REFUSE (two epics per project, one item per epic) — no --force;
  * `blocked_by` is a FLAG, so setting or clearing it never moves `status`;
  * the log is APPEND-ONLY — new lines land at the end, nothing above them moves.

Every case drives the real CLI entry point against a throwaway project dir, so the
flag names are exercised alongside the behaviour.
"""
from __future__ import annotations

from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import epics, indexes  # noqa: E402
from maestro_cli.cli import main  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project whose docs/epics/ the CLI writes into."""
    epic_dir = tmp_path / "docs" / "epics"
    epic_dir.mkdir(parents=True)
    monkeypatch.setattr(epics, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(epics, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "EPIC_DIR", epic_dir)
    return epic_dir


def record(epic_dir, n):
    return next(epic_dir.glob(f"epic_{n:02d}_*.md"))


def frontmatter_of(epic_dir, n):
    text = record(epic_dir, n).read_text()
    return yaml.safe_load(text.split("---\n")[1])


def body_of(epic_dir, n):
    return record(epic_dir, n).read_text().split("---\n", 2)[2]


def set_items(epic_dir, n, items):
    """Seed item rows by hand — stage B has no `item` verb yet."""
    path = record(epic_dir, n)
    head, fm_text, body = path.read_text().split("---\n", 2)
    fm = yaml.safe_load(fm_text)
    fm["items"] = items
    path.write_text("---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False) + "---\n" + body)


def answer_condition(n=1, text="the suite stays green", result="2144 pass, 0 fail"):
    """Give epic `n` a closing condition and the reading against it, so `close` is legal."""
    main(["epic", "done-when", f"--id={n}", f"--add={text}", f"--result={result}"])


def shaped(title: str, files: int = 3, done: str = "pytest -q") -> str:
    """An item title in the shape `epic item --add` now requires: scope + done-test."""
    return f"{title} — {files} files — Done: {done}"


def refusal(argv):
    """Run the CLI expecting a refusal; return the message it exited with."""
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None), "a refused command must exit non-zero"
    return str(e.value.code)


# ── WIP limits ────────────────────────────────────────────────────────────────

def test_epic_wip_limit_is_raised_per_project_by_policy(project, capsys):
    (project.parent.parent / "maestro.toml").write_text("[epics]\nmax_in_progress = 3\n")
    for slug in ("first", "second", "third", "fourth"):
        main(["epic", "new", f"--slug={slug}"])
    for n in (1, 2, 3):
        main(["epic", "update", f"--id={n}", "--status=active"])
    capsys.readouterr()

    msg = refusal(["epic", "update", "--id=4", "--status=active"])
    assert "the limit is 3 per project" in msg
    assert "[epics] max_in_progress" in msg


def test_third_epic_in_progress_is_refused_and_names_the_holders(project, capsys):
    main(["epic", "new", "--slug=first", "--title=Split the engine god file"])
    main(["epic", "new", "--slug=second", "--title=Port the combat rules"])
    main(["epic", "new", "--slug=third"])
    main(["epic", "update", "--id=1", "--status=active"])
    main(["epic", "update", "--id=2", "--status=active"])
    capsys.readouterr()

    msg = refusal(["epic", "update", "--id=3", "--status=active"])
    assert "epic_3 cannot move to active" in msg
    assert "the limit is 2 per project" in msg
    # The message names WHICH epics hold the slots, and how to free one.
    assert 'epic_1 "Split the engine god file"' in msg
    assert 'epic_2 "Port the combat rules"' in msg
    assert "maestro epic close --id=1" in msg
    # Refused means unwritten: epic 3 is still todo.
    assert frontmatter_of(project, 3)["status"] == "todo"


def test_second_item_in_progress_is_refused_and_names_the_item(project, capsys):
    main(["epic", "new", "--slug=first"])
    set_items(project, 1, [
        {"id": 1, "title": "Extract the renderer", "status": "in_progress"},
        {"id": 2, "title": "Extract physics", "status": "in_progress"},
    ])
    capsys.readouterr()

    msg = refusal(["epic", "update", "--id=1", "--note=anything"])
    assert "2 items in_progress (items 1, 2)" in msg
    assert "the limit is 1 per epic" in msg
    assert 'item 1 "Extract the renderer" holds the slot' in msg


def test_two_epics_in_progress_is_allowed(project, capsys):
    main(["epic", "new", "--slug=first"])
    main(["epic", "new", "--slug=second"])
    main(["epic", "update", "--id=1", "--status=active"])
    main(["epic", "update", "--id=2", "--status=active"])
    capsys.readouterr()
    assert frontmatter_of(project, 1)["status"] == "active"
    assert frontmatter_of(project, 2)["status"] == "active"


# ── blocked_by is a flag, never a state ───────────────────────────────────────

def test_blocked_by_does_not_touch_status(project, capsys):
    main(["epic", "new", "--slug=first"])
    main(["epic", "update", "--id=1", "--status=active"])
    main(["epic", "update", "--id=1", "--blocked-by=upstream API change has not landed"])
    capsys.readouterr()
    fm = frontmatter_of(project, 1)
    assert fm["blocked_by"] == "upstream API change has not landed"
    assert fm["status"] == "active"   # the flag did not eat the state


def test_empty_blocked_by_clears_the_flag_and_keeps_the_status(project, capsys):
    main(["epic", "new", "--slug=first"])
    main(["epic", "update", "--id=1", "--status=active"])
    main(["epic", "update", "--id=1", "--blocked-by=waiting on the renderer PR"])
    main(["epic", "update", "--id=1", "--blocked-by="])
    capsys.readouterr()
    fm = frontmatter_of(project, 1)
    assert fm["blocked_by"] is None
    assert fm["status"] == "active"


def test_blocked_epic_can_be_listed_by_the_flag(project, capsys):
    main(["epic", "new", "--slug=first"])
    main(["epic", "new", "--slug=second"])
    main(["epic", "update", "--id=2", "--blocked-by=upstream API change has not landed"])
    capsys.readouterr()
    main(["epic", "list", "--blocked"])
    out = capsys.readouterr().out
    assert "second" in out
    assert "first" not in out


# ── the log is append-only ─────────────────────────────────────────────────

def test_notes_append_in_order_and_move_nothing(project, capsys):
    main(["epic", "new", "--slug=first"])
    before = body_of(project, 1)
    for note in ("renderer extracted", "physics extracted", "entry points deleted"):
        main(["epic", "update", "--id=1", f"--note={note}"])
    capsys.readouterr()
    after = body_of(project, 1)

    # Everything that was there is still there, in place, untouched.
    assert after.startswith(before.rstrip("\n"))
    positions = [after.index(n) for n in ("renderer extracted", "physics extracted",
                                          "entry points deleted")]
    assert positions == sorted(positions)
    assert after.count("## Log") == 1
    assert "opened." in after


def test_append_log_creates_the_section_when_absent():
    body = "\n# Epic 1 — x\n\n**Why**: because\n"
    out = epics.append_log(body, "- 2026-08-24 — first line")
    assert "**Why**: because" in out
    assert out.rstrip().endswith("- 2026-08-24 — first line")
    assert out.count("## Log") == 1


def test_append_log_keeps_a_following_section_last():
    body = "## Log\n\n- 2026-08-01 — opened.\n\n## Notes\n\ntail prose\n"
    out = epics.append_log(body, "- 2026-08-24 — moved")
    assert out.index("- 2026-08-24 — moved") < out.index("## Notes")
    assert out.rstrip().endswith("tail prose")


# ── closing ───────────────────────────────────────────────────────────────────

def test_close_is_refused_while_an_item_is_in_progress(project, capsys):
    main(["epic", "new", "--slug=first"])
    set_items(project, 1, [
        {"id": 1, "title": "Extract the renderer", "status": "done"},
        {"id": 2, "title": "Extract physics", "status": "in_progress"},
    ])
    capsys.readouterr()

    msg = refusal(["epic", "close", "--id=1", "--outcome=renderer extracted"])
    assert 'item 2 "Extract physics"' in msg
    assert frontmatter_of(project, 1)["status"] != "done"


def test_close_requires_an_outcome(project, capsys):
    main(["epic", "new", "--slug=first"])
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        main(["epic", "close", "--id=1"])
    assert e.value.code == 2
    assert "--outcome" in capsys.readouterr().err
    assert frontmatter_of(project, 1)["status"] == "todo"


def test_close_allows_a_dropped_item_and_refuses_a_todo_one(project, capsys):
    main(["epic", "new", "--slug=first"])
    set_items(project, 1, [
        {"id": 1, "title": "Extract the renderer", "status": "done"},
        {"id": 2, "title": "Delete the old entry points", "status": "todo"},
    ])
    answer_condition(1)
    msg = refusal(["epic", "close", "--id=1", "--outcome=renderer extracted"])
    assert 'item 2 "Delete the old entry points" (todo)' in msg
    main(["epic", "item", "--id=1", "--item=2", "--status=dropped",
          "--reason=entry points still have two callers"])
    main(["epic", "close", "--id=1", "--outcome=renderer extracted; entry points dropped"])
    capsys.readouterr()
    fm = frontmatter_of(project, 1)
    assert fm["status"] == "done"
    assert fm["outcome"] == "renderer extracted; entry points dropped"
    assert fm["closed"]


def test_done_via_update_is_refused_and_points_at_close(project, capsys):
    main(["epic", "new", "--slug=first"])
    capsys.readouterr()
    msg = refusal(["epic", "update", "--id=1", "--status=done"])
    assert "maestro epic close --id=1" in msg


# ── the board ─────────────────────────────────────────────────────────────────

def test_board_renders_one_line_per_epic_by_status(project, capsys):
    main(["epic", "new", "--slug=done_one", "--title=Split the engine: god file"])
    main(["epic", "new", "--slug=running_one"])
    main(["epic", "new", "--slug=waiting_one"])
    answer_condition(1)
    main(["epic", "close", "--id=1", "--outcome=all 12 conformance gaps closed"])
    main(["epic", "update", "--id=2", "--status=active", "--runner=dsh"])
    set_items(project, 2, [{"id": 1, "title": "Extract physics", "status": "done"},
                           {"id": 2, "title": "Extract sound", "status": "todo"}])
    main(["epic", "update", "--id=3", "--blocked-by=upstream API change has not landed"])
    main(["index", "render", "--kind=epic"])
    capsys.readouterr()

    board = (project / "INDEX.md").read_text()
    assert "Do not edit by hand" in board
    for heading in ("## Active", "## Todo", "## Review", "## Done"):
        assert heading in board
    assert "## Blocked" not in board and "## Options" not in board
    active = board.split("## Active")[1].split("## Todo")[0]
    todo = board.split("## Todo")[1].split("## Review")[0]
    done = board.split("## Done")[1]
    assert "epic 2 \u2014 running_one \u00b7 active \u00b7 dsh \u00b7 items 1/2" in active
    assert "epic 3 \u2014 waiting_one \u00b7 todo \u00b7 items 0/0 \u00b7 blocked" in todo
    assert "done: 1 Split the engine" in done and "god file" not in done


def test_epic_runner_set_cleared_and_auto_cleared(project):
    main(["epic", "new", "--slug=a"])
    main(["epic", "update", "--id=1", "--status=active", "--runner=claude"])
    assert frontmatter_of(project, 1)["runner"] == "claude"
    main(["epic", "update", "--id=1", "--status=todo"])
    assert "runner" not in frontmatter_of(project, 1)
    main(["epic", "update", "--id=1", "--runner=dsh"])
    main(["epic", "update", "--id=1", "--runner="])
    assert "runner" not in frontmatter_of(project, 1)


def test_old_in_progress_epic_reads_as_active(project):
    main(["epic", "new", "--slug=a"])
    p = next((project).glob("epic_01_*.md"))
    text = p.read_text().replace("status: todo", "status: in_progress")
    p.write_text(text)
    from maestro_cli import frontmatter as fmod
    assert fmod.load(project, "epic")[1][1]["status"] == "active"
    main(["index", "render", "--kind=epic"])
    assert "epic 1 \u2014 a \u00b7 active" in (project / "INDEX.md").read_text()


# ── done_when — the closing condition, written at open and answered at close ──

def test_a_new_epic_is_born_with_an_empty_condition_and_no_prose_twin(project):
    main(["epic", "new", "--slug=port"])
    assert frontmatter_of(project, 1)["done_when"] == []
    # The condition lives in frontmatter ONLY. Two homes for one claim is how they drift.
    assert "**Done when**" not in body_of(project, 1)
    assert "**Why**" in body_of(project, 1)


def test_close_refuses_with_no_clause_and_says_what_done_would_mean(project, capsys):
    main(["epic", "new", "--slug=port"])
    capsys.readouterr()
    msg = refusal(["epic", "close", "--id=1", "--outcome=shipped it"])
    assert "has no done_when clause" in msg
    assert "maestro epic done-when --id=1 --add=" in msg
    assert frontmatter_of(project, 1)["status"] == "todo"   # refused means unwritten


def test_close_refuses_while_a_clause_is_unanswered_and_names_it(project, capsys):
    main(["epic", "new", "--slug=port"])
    main(["epic", "done-when", "--id=1", "--add=OPEN rows: 36 -> 0",
          "--check=python tools/ledger_summary.py --check"])
    main(["epic", "done-when", "--id=1", "--add=the cargo suite stays green",
          "--result=2144 pass, 0 fail"])
    capsys.readouterr()

    msg = refusal(["epic", "close", "--id=1", "--outcome=shipped it"])
    assert "1 of 2 done_when clauses have no measured result" in msg
    assert 'clause 1 "OPEN rows: 36 -> 0"' in msg
    assert "the cargo suite stays green" not in msg      # the ANSWERED one is not nagged
    assert "--clause=1 --result=" in msg
    assert frontmatter_of(project, 1)["status"] == "todo"


def test_close_records_the_answered_count_once_every_clause_is_measured(project, capsys):
    main(["epic", "new", "--slug=port"])
    main(["epic", "done-when", "--id=1", "--add=OPEN rows: 36 -> 0", "--result=0 OPEN, 274 rows"])
    main(["epic", "close", "--id=1", "--outcome=the log can be trusted unread"])
    out = capsys.readouterr().out
    assert "1/1 done_when clauses answered" in out
    fm = frontmatter_of(project, 1)
    assert fm["status"] == "done"
    assert fm["done_when"][0]["result"] == "0 OPEN, 274 rows"


def test_add_can_carry_its_own_result_and_keeps_the_check(project, capsys):
    main(["epic", "new", "--slug=port"])
    main(["epic", "done-when", "--id=1", "--add=suite green", "--check=cargo nextest run",
          "--result=2144 pass"])
    capsys.readouterr()
    clause = frontmatter_of(project, 1)["done_when"][0]
    assert clause == {"id": 1, "text": "suite green", "check": "cargo nextest run",
                      "result": "2144 pass"}


def test_an_unanswered_clause_writes_an_explicit_empty_slot(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "done-when", "--id=1", "--add=suite green"])
    # The empty slot is WRITTEN, not omitted: an unanswered condition is visible in the
    # record rather than inferred from a missing key.
    assert frontmatter_of(project, 1)["done_when"][0]["result"] is None


def test_result_can_be_cleared_back_to_unanswered_and_close_refuses_again(project, capsys):
    main(["epic", "new", "--slug=port"])
    main(["epic", "done-when", "--id=1", "--add=suite green", "--result=2144 pass"])
    main(["epic", "done-when", "--id=1", "--clause=1", "--result="])
    capsys.readouterr()
    assert frontmatter_of(project, 1)["done_when"][0]["result"] is None
    assert "no measured result" in refusal(["epic", "close", "--id=1", "--outcome=x"])


def test_rewording_a_clause_keeps_a_revision_trace(project, capsys):
    main(["epic", "new", "--slug=port"])
    main(["epic", "done-when", "--id=1", "--add=no file over 1500 lines"])
    main(["epic", "done-when", "--id=1", "--clause=1", "--text=no file over 1000 lines"])
    capsys.readouterr()
    # A closing condition quietly reworded to match what happened proves nothing, so the
    # old wording goes to the log (the `exp revise` contract, rule 1).
    body = body_of(project, 1)
    assert "done_when clause 1 re-worded — was: no file over 1500 lines" in body
    assert frontmatter_of(project, 1)["done_when"][0]["text"] == "no file over 1000 lines"


def test_dropping_a_clause_traces_its_wording_and_frees_no_id(project, capsys):
    main(["epic", "new", "--slug=port"])
    main(["epic", "done-when", "--id=1", "--add=first condition"])
    main(["epic", "done-when", "--id=1", "--add=second condition"])
    main(["epic", "done-when", "--id=1", "--clause=1", "--drop"])
    main(["epic", "done-when", "--id=1", "--add=third condition"])
    capsys.readouterr()
    clauses = frontmatter_of(project, 1)["done_when"]
    assert [c["id"] for c in clauses] == [2, 3]          # ids never get reused
    assert "done_when clause 1 dropped — was: first condition" in body_of(project, 1)


def test_check_can_be_set_and_cleared(project, capsys):
    main(["epic", "new", "--slug=port"])
    main(["epic", "done-when", "--id=1", "--add=suite green", "--check=cargo test"])
    main(["epic", "done-when", "--id=1", "--clause=1", "--check="])
    capsys.readouterr()
    assert "check" not in frontmatter_of(project, 1)["done_when"][0]


def test_done_when_argument_shapes_are_refused(project, capsys):
    main(["epic", "new", "--slug=port"])
    main(["epic", "done-when", "--id=1", "--add=suite green"])
    capsys.readouterr()
    assert "Pass one, not both" in refusal(
        ["epic", "done-when", "--id=1", "--add=x", "--clause=1"])
    assert "--text re-words an EXISTING clause" in refusal(
        ["epic", "done-when", "--id=1", "--add=x", "--text=y"])
    assert "Nothing to do" in refusal(["epic", "done-when", "--id=1"])
    assert "needs --result, --text, --check or --drop" in refusal(
        ["epic", "done-when", "--id=1", "--clause=1"])
    assert "has no clause 9" in refusal(
        ["epic", "done-when", "--id=1", "--clause=9", "--result=x"])
    assert "already reads that way" in refusal(
        ["epic", "done-when", "--id=1", "--clause=1", "--text=suite green"])
    assert "drop the clause instead" in refusal(
        ["epic", "done-when", "--id=1", "--clause=1", "--text= "])
    assert "closes nothing" in refusal(["epic", "done-when", "--id=1", "--add= "])


def test_board_shows_a_missing_condition_and_an_answered_one(project, capsys):
    main(["epic", "new", "--slug=closed_one"])
    main(["epic", "new", "--slug=open_one"])
    answer_condition(1)
    main(["epic", "close", "--id=1", "--outcome=the suite is trustworthy"])
    main(["index", "render", "--kind=epic"])
    capsys.readouterr()

    board = (project / "INDEX.md").read_text()
    assert "epic 2 \u2014 open_one \u00b7 todo" in board
    assert "done: 1 closed_one" in board


# ── epic item — the frontmatter is never hand-edited (rule 1) ─────────────────

def test_item_add_assigns_next_id_and_todo(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('first thing')}"])
    main(["epic", "item", "--id=1", f"--add={shaped('second thing')}"])
    items = frontmatter_of(project, 1)["items"]
    assert [(it["id"], it["status"]) for it in items] == [(1, "todo"), (2, "todo")]
    assert items[1]["title"] == shaped("second thing")


def test_item_status_flip(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('only thing')}"])
    main(["epic", "item", "--id=1", "--item=1", "--status=done", "--evidence=merge abc1234"])
    assert frontmatter_of(project, 1)["items"][0]["status"] == "done"


def test_item_wip_limit_refuses_second_in_progress(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('a')}"])
    main(["epic", "item", "--id=1", f"--add={shaped('b')}"])
    main(["epic", "item", "--id=1", "--item=1", "--status=in_progress"])
    with pytest.raises(SystemExit, match="limit"):
        main(["epic", "item", "--id=1", "--item=2", "--status=in_progress"])
    # the refused write must not have landed
    statuses = [it["status"] for it in frontmatter_of(project, 1)["items"]]
    assert statuses == ["in_progress", "todo"]


def test_item_blocked_flag_set_and_clear_never_touches_status(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('a')}"])
    main(["epic", "item", "--id=1", "--item=1", "--blocked-by=waiting on data drop"])
    row = frontmatter_of(project, 1)["items"][0]
    assert row["blocked_by"] == "waiting on data drop" and row["status"] == "todo"
    main(["epic", "item", "--id=1", "--item=1", "--blocked-by="])
    row = frontmatter_of(project, 1)["items"][0]
    assert "blocked_by" not in row          # cleared by removal — K2 never fires on it


def test_item_add_and_item_are_mutually_exclusive(project):
    main(["epic", "new", "--slug=port"])
    with pytest.raises(SystemExit, match="one, not both"):
        main(["epic", "item", "--id=1", "--add=x", "--item=1", "--status=done"])


def test_item_missing_target_and_missing_action_refuse(project):
    main(["epic", "new", "--slug=port"])
    with pytest.raises(SystemExit, match="Nothing to do"):
        main(["epic", "item", "--id=1"])
    with pytest.raises(SystemExit, match="no item 9"):
        main(["epic", "item", "--id=1", "--item=9", "--status=done"])


def test_item_note_lands_in_log(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('a')}", "--note=seeded the plan"])
    assert "seeded the plan" in record(project, 1).read_text()


# ── an epic re-title is a correction: traced, and the heading moves with it ───

def test_epic_retitle_traces_the_old_wording_and_moves_the_heading(project):
    main(["epic", "new", "--slug=route_arc", "--title=Theme 1: v6 as the harness"])
    main(["epic", "update", "--id=1", "--title=Arc 1: v6 as the harness"])
    fm = frontmatter_of(project, 1)
    assert fm["title"] == "Arc 1: v6 as the harness"
    assert fm["status"] == "todo"                  # a re-title is not a state change
    text = record(project, 1).read_text()
    # rule 1: the correction leaves a trace, so the old wording is never simply gone
    assert "was: Theme 1: v6 as the harness" in text
    # the body heading was written from the title at scaffold time and must follow it,
    # or the board renders one word while the record reads another
    assert "# Epic 1 — Arc 1: v6 as the harness" in text
    assert "# Epic 1 — Theme 1: v6 as the harness" not in text


def test_epic_retitle_refuses_empty_and_noop(project):
    main(["epic", "new", "--slug=port", "--title=a real title"])
    with pytest.raises(SystemExit, match="cannot be empty"):
        main(["epic", "update", "--id=1", "--title=  "])
    with pytest.raises(SystemExit, match="already carries that title"):
        main(["epic", "update", "--id=1", "--title=a real title"])
    assert frontmatter_of(project, 1)["title"] == "a real title"


def test_epic_retitle_does_not_touch_the_blocked_flag_or_status(project, capsys):
    main(["epic", "new", "--slug=port", "--title=old"])
    main(["epic", "update", "--id=1", "--status=active"])
    main(["epic", "update", "--id=1", "--blocked-by=waiting on the renderer PR"])
    main(["epic", "update", "--id=1", "--title=new"])
    capsys.readouterr()
    fm = frontmatter_of(project, 1)
    assert fm["title"] == "new"
    assert fm["status"] == "active"
    assert fm["blocked_by"] == "waiting on the renderer PR"


def test_item_retitle_keeps_a_revision_trace(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('single-owner the table path')}"])
    main(["epic", "item", "--id=1", "--item=1", "--title=cite the log by row id"])
    row = frontmatter_of(project, 1)["items"][0]
    assert row["title"] == "cite the log by row id"
    assert row["status"] == "todo"                       # a re-title is not a state change
    # rule 1: the correction leaves a trace, so the old wording is never simply gone
    assert f"was: {shaped('single-owner the table path')}" in record(project, 1).read_text()


def test_item_retitle_refuses_empty_noop_and_add(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('a real title')}"])
    with pytest.raises(SystemExit, match="cannot be empty"):
        main(["epic", "item", "--id=1", "--item=1", "--title=  "])
    with pytest.raises(SystemExit, match="already carries that title"):
        main(["epic", "item", "--id=1", "--item=1", f"--title={shaped('a real title')}"])
    with pytest.raises(SystemExit, match="re-titles an EXISTING item"):
        main(["epic", "item", "--id=1", "--add=new row", "--title=nope"])
    assert frontmatter_of(project, 1)["items"][0]["title"] == shaped("a real title")


def test_item_retitle_alone_satisfies_the_action_check(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('old')}"])
    main(["epic", "item", "--id=1", "--item=1", "--title=new"])   # no --status, no --blocked-by
    assert frontmatter_of(project, 1)["items"][0]["title"] == "new"


# ── the flow layer: dates, exit evidence, options, retro ─────────────────────

def _age_item(epic_dir, n, since):
    """Back-date item 1's stamp. The CLI writes the clock, so a test must plant the past."""
    path = record(epic_dir, n)
    text = path.read_text()
    head, fm_text, body = text.split("---\n", 2)
    fm = yaml.safe_load(fm_text)
    fm["items"][0]["since"] = since
    path.write_text(f"{head}---\n{yaml.safe_dump(fm, sort_keys=False)}---\n{body}")


def test_item_carries_a_since_stamp_from_birth(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('a')}"])
    assert frontmatter_of(project, 1)["items"][0]["since"] == str(date.today())


def test_status_change_restamps_since_but_a_retitle_does_not(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('a')}"])
    _age_item(project, 1, since="2020-01-01")         # pretend it has sat a while
    main(["epic", "item", "--id=1", "--item=1", "--title=b"])
    assert frontmatter_of(project, 1)["items"][0]["since"] == "2020-01-01"
    main(["epic", "item", "--id=1", "--item=1", "--status=in_progress"])
    assert frontmatter_of(project, 1)["items"][0]["since"] == str(date.today())


def test_done_refuses_without_evidence_and_records_it_with(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('a')}"])
    with pytest.raises(SystemExit, match="cannot go done without --evidence"):
        main(["epic", "item", "--id=1", "--item=1", "--status=done"])
    assert frontmatter_of(project, 1)["items"][0]["status"] == "todo"
    main(["epic", "item", "--id=1", "--item=1", "--status=done", "--evidence=merge deadbeef"])
    row = frontmatter_of(project, 1)["items"][0]
    assert row["status"] == "done" and row["evidence"] == "merge deadbeef"


def test_reopening_a_done_item_drops_its_evidence(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('a')}"])
    main(["epic", "item", "--id=1", "--item=1", "--status=done", "--evidence=merge deadbeef"])
    main(["epic", "item", "--id=1", "--item=1", "--status=in_progress"])
    assert "evidence" not in frontmatter_of(project, 1)["items"][0]


def test_blocked_flag_is_dated_and_the_date_goes_when_it_clears(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "item", "--id=1", f"--add={shaped('a')}"])
    main(["epic", "item", "--id=1", "--item=1", "--blocked-by=waiting on the data drop"])
    assert frontmatter_of(project, 1)["items"][0]["blocked_since"] == str(date.today())
    main(["epic", "item", "--id=1", "--item=1", "--blocked-by="])
    row = frontmatter_of(project, 1)["items"][0]
    assert "blocked_since" not in row and "blocked_by" not in row


def test_an_option_is_not_a_card(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "option", "--id=1", "--add=maybe port the renderer"])
    fm = frontmatter_of(project, 1)
    assert fm["options"] == ["maybe port the renderer"]
    assert fm["items"] == []                          # no status, no id, no age


def test_pulling_an_option_commits_it_and_leaves_the_list(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "option", "--id=1", "--add=first"])
    main(["epic", "option", "--id=1", "--add=second"])
    main(["epic", "option", "--id=1", "--pull=1"])
    fm = frontmatter_of(project, 1)
    assert fm["options"] == ["second"]
    assert [(i["id"], i["title"], i["status"]) for i in fm["items"]] == [(1, "first", "todo")]
    assert "committed to option 1: first" in record(project, 1).read_text()


def test_dropping_an_option_says_so_in_the_log(project):
    main(["epic", "new", "--slug=port"])
    main(["epic", "option", "--id=1", "--add=never mind"])
    main(["epic", "option", "--id=1", "--drop=1"])
    assert frontmatter_of(project, 1)["options"] == []
    assert "dropped option 1: never mind" in record(project, 1).read_text()


def test_option_verb_refuses_a_bad_index_and_two_actions(project):
    main(["epic", "new", "--slug=port"])
    with pytest.raises(SystemExit, match="no option 4"):
        main(["epic", "option", "--id=1", "--pull=4"])
    with pytest.raises(SystemExit, match="exactly one of"):
        main(["epic", "option", "--id=1", "--add=x", "--drop=1"])


def test_close_learned_writes_the_retro_line(project):
    main(["epic", "new", "--slug=port"])
    answer_condition(1)
    main(["epic", "close", "--id=1", "--outcome=shipped",
          "--learned=one item per session was too coarse for a sweep"])
    retro = (project.parent / "retro.md").read_text()
    assert "**epic 1**: one item per session was too coarse for a sweep" in retro
    assert str(date.today()) in retro


def test_a_legacy_ledger_heading_is_read_and_migrated_on_the_next_write(project):
    main(["epic", "new", "--slug=port"])
    path = record(project, 1)
    path.write_text(path.read_text().replace("## Log", "## Ledger"))
    assert epics.log_dates(body_of(project, 1))                  # still read under the old heading
    main(["epic", "update", "--id=1", "--note=moved"])
    body = body_of(project, 1)
    assert "## Log\n" in body and "## Ledger" not in body     # heading migrated, nothing else moved
    assert body.count("opened.") == 1 and "moved" in body


def test_a_note_that_repeats_todays_date_is_not_double_dated(project, capsys):
    from datetime import date
    main(["epic", "new", "--slug=first"])
    today = str(date.today())
    main(["epic", "update", "--id=1", f"--note={today} items cut"])
    main(["epic", "update", "--id=1", "--note=2026-08-18 ruling recorded"])   # content
    capsys.readouterr()
    body = body_of(project, 1)
    assert f"- {today} — items cut" in body
    assert f"- {today} — {today}" not in body
    assert f"- {today} — 2026-08-18 ruling recorded" in body


def test_new_never_reuses_an_archived_epic_number(project):
    """An archived epic is history, but its number stays taken (docs/archive/epics/)."""
    main(["epic", "new", "--slug=first"])
    arch = project.parent / "archive" / "epics"
    arch.mkdir(parents=True)
    (arch / "epic_05_retired.md").write_text("---\nepic: 5\ntitle: r\nstatus: done\n---\n")
    main(["epic", "new", "--slug=second"])
    assert record(project, 6).name == "epic_06_second.md"


# ── linking experiments and ADRs ──────────────────────────────────────────────

def seed_records(root, exps=(), adrs=()):
    """Stub record files so the link check has something to find."""
    (root / "docs" / "experiments").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "adrs").mkdir(parents=True, exist_ok=True)
    for n in exps:
        (root / "docs" / "experiments" / f"exp_{n:02d}_stub.md").write_text("---\n---\n")
    for n in adrs:
        (root / "docs" / "adrs" / f"adr_{n:02d}_stub.md").write_text("---\n---\n")


def test_exps_and_adrs_are_added_sorted_and_logged(project, capsys):
    seed_records(project.parent.parent, exps=(7, 147, 148), adrs=(31,))
    main(["epic", "new", "--slug=first"])
    main(["epic", "update", "--id=1", "--exps=148,147", "--adrs=31"])
    main(["epic", "update", "--id=1", "--exps=7"])
    out = capsys.readouterr().out
    fm = frontmatter_of(project, 1)
    assert fm["exps"] == [7, 147, 148]
    assert fm["adrs"] == [31]
    assert fm["status"] == "todo"          # linking moves no state
    body = body_of(project, 1)
    assert "linked exps 147, 148" in body
    assert "linked adrs 31" in body
    assert "linked exps 7" in body
    assert "linked exps 7" in out


def test_linking_an_already_linked_number_dedupes(project, capsys):
    seed_records(project.parent.parent, exps=(147, 148))
    main(["epic", "new", "--slug=first"])
    main(["epic", "update", "--id=1", "--exps=147"])
    main(["epic", "update", "--id=1", "--exps=147,148,148"])
    capsys.readouterr()
    assert frontmatter_of(project, 1)["exps"] == [147, 148]
    body = body_of(project, 1)
    assert body.count("linked exps 147") == 1
    assert "linked exps 148" in body


def test_linking_an_unknown_number_is_refused_and_writes_nothing(project, capsys):
    seed_records(project.parent.parent, exps=(147,), adrs=(31,))
    main(["epic", "new", "--slug=first"])
    capsys.readouterr()
    before = record(project, 1).read_text()
    msg = refusal(["epic", "update", "--id=1", "--exps=147,999"])
    assert "no exp record for 999" in msg
    msg = refusal(["epic", "update", "--id=1", "--adrs=32"])
    assert "no adr record for 32" in msg
    msg = refusal(["epic", "update", "--id=1", "--exps=abc"])
    assert "not a record number" in msg
    assert record(project, 1).read_text() == before


def test_update_with_nothing_to_do_names_the_link_flags(project, capsys):
    main(["epic", "new", "--slug=first"])
    capsys.readouterr()
    msg = refusal(["epic", "update", "--id=1"])
    assert "needs one of" in msg
    assert "--exps" in msg and "--adrs" in msg
