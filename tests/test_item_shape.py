"""The item-shape check on `maestro epic item --add`, and the two board caps.

WHY these refusals exist: one item read "port the remaining read sites", was held by a
single planner for days, and covered hundreds of files — a number the title never
stated, so nothing could refuse it, split it, or size the brief written from it. A title now has to answer two questions (what ends this, and how wide is it),
and the scope it states is held to a per-project limit.

What is pinned here is the REFUSAL: which halves of the shape are named when they are
missing, that the size limit judges SHAPE (a wide MECHANICAL pass is legal once it
declares `N files in K units`; a design item never is), that a title still carrying an
open decision is refused at any size, that an epic stops accepting items once its open
ones reach the cap, and that every limit comes from `maestro.toml` with the framework
default standing when the file is absent or unusable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import epics, indexes, policy  # noqa: E402
from maestro_cli.cli import main  # noqa: E402

GOOD = "port the mission planner — 12 files — Done: cargo nextest run -p policy_core"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project the CLI writes into, with one epic already open."""
    epic_dir = tmp_path / "docs" / "epics"
    epic_dir.mkdir(parents=True)
    monkeypatch.setattr(epics, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(epics, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "EPIC_DIR", epic_dir)
    main(["epic", "new", "--slug=port"])
    return tmp_path


def items_of(project):
    path = next((project / "docs" / "epics").glob("epic_01_*.md"))
    return yaml.safe_load(path.read_text().split("---\n")[1])["items"] or []


def refusal(argv) -> str:
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None), "a refused command must exit non-zero"
    return str(e.value.code)


def declare_policy(project, text: str):
    (project / policy.FILENAME).write_text(text)


# ── the two halves of the shape ──────────────────────────────────────────────

def test_a_title_stating_both_is_added(project):
    main(["epic", "item", "--id=1", f"--add={GOOD}"])
    assert [(it["id"], it["title"]) for it in items_of(project)] == [(1, GOOD)]


def test_a_missing_done_test_is_named_and_the_shape_is_shown(project):
    said = refusal(["epic", "item", "--id=1", "--add=port the planner — 12 files"])
    assert "done-test marker" in said
    assert "scope marker" not in said          # the half that IS there is not complained about
    assert "Done: cargo nextest run" in said   # the expected shape, spelled out
    assert items_of(project) == []


def test_a_missing_scope_is_named(project):
    said = refusal(["epic", "item", "--id=1", "--add=port the planner — Done: cargo test"])
    assert "scope marker" in said and "done-test marker" not in said
    assert "maestro epic option" in said       # where an unscoped idea goes instead


def test_a_title_missing_both_names_both(project):
    said = refusal(["epic", "item", "--id=1", "--add=x"])
    assert "done-test marker" in said and "scope marker" in said


@pytest.mark.parametrize("title", [
    "port the planner — 12 files — Done: cargo test",
    "port the planner — 12 FILES — done-test: cargo test",
    "split view.rs — 1 file — Done-test: make gate",
    "re-cite the table — 30 sites — Done: python3 tools/ledger_summary.py --check",
])
def test_every_accepted_spelling_of_the_two_markers(project, title):
    main(["epic", "item", "--id=1", f"--add={title}"])
    assert len(items_of(project)) == 1


def test_the_shape_is_judged_before_the_epic_is_looked_up(project):
    """The refusal that matters is the one about the title. `--id=999` names an epic that
    does not exist, and the old order answered with that instead."""
    assert "done-test marker" in refusal(["epic", "item", "--id=999", "--add=x"])


def test_a_re_title_is_not_held_to_the_shape(project):
    """`--title` corrects an EXISTING row and leaves a revision trace; only the act of
    ADDING a card crosses the commitment point."""
    main(["epic", "item", "--id=1", f"--add={GOOD}"])
    main(["epic", "item", "--id=1", "--item=1", "--title=port the mission planner"])
    assert items_of(project)[0]["title"] == "port the mission planner"


# ── the scope limit ──────────────────────────────────────────────────────────

def test_a_wide_item_that_declares_no_unit_plan_is_refused(project):
    said = refusal(["epic", "item", "--id=1",
                    "--add=port the read sites — 255 files — Done: make gate"])
    assert "split it before the brief: 255 files > max_files 40" in said
    assert "maestro.toml [items] max_files" in said
    # the refusal names the two shapes, rather than complaining about the number
    assert "MECHANICAL pass" in said and '255 files in K units' in said
    assert "DESIGN item (one seam, one decision)" in said
    assert items_of(project) == []


def test_a_wide_mechanical_pass_that_declares_its_units_is_accepted(project):
    """Size is not the rule — shape is. A compiler-driven sweep cut into child units is
    one legitimate item; the plan has to be on the card."""
    main(["epic", "item", "--id=1",
          "--add=rename the tile axes — 223 files in 9 units — Done: make gate"])
    assert len(items_of(project)) == 1


@pytest.mark.parametrize("title", [
    "rename — 223 files in 9 units — Done: make gate",
    "rename — 223 files IN 9 UNITS — Done: make gate",
    "rename — 223 files in 1 unit — Done: make gate",
])
def test_every_spelling_of_the_unit_plan(project, title):
    main(["epic", "item", "--id=1", f"--add={title}"])
    assert len(items_of(project)) == 1


def test_a_unit_plan_does_not_excuse_a_missing_done_test(project):
    """The two shape markers are not negotiable — the unit plan only answers the size
    question, and a mechanical pass still has to say what ends it."""
    assert "done-test marker" in refusal(
        ["epic", "item", "--id=1", "--add=rename — 223 files in 9 units"])


# ── a title that is still a question ─────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "port the planner (approach TBD) — 6 files — Done: make gate",
    "port the planner — approach to be decided — 6 files — Done: make gate",
    "decide whether to keep the facade — 6 files — Done: make gate",
    "port the planner — open question: which seam — 6 files — Done: make gate",
    "rename — 223 files in 9 units — Done: make gate — naming TBD",
])
def test_an_open_decision_is_refused_at_any_size(project, title):
    said = refusal(["epic", "item", "--id=1", f"--add={title}"])
    assert said.startswith("an item is not a question; record the decision "
                           "(ADR / step-0 measurement) as its own small item first")
    assert items_of(project) == []


def test_a_decided_title_with_the_same_words_apart_is_fine(project):
    main(["epic", "item", "--id=1",
          "--add=open the question log to the board — 4 files — Done: make gate"])
    assert len(items_of(project)) == 1


def test_the_limit_is_the_one_the_project_declares(project):
    declare_policy(project, "[items]\nmax_files = 8\n")
    assert "255 files > max_files 8" in refusal(
        ["epic", "item", "--id=1", "--add=port — 255 files — Done: make gate"])
    assert "12 files > max_files 8" in refusal(["epic", "item", "--id=1", f"--add={GOOD}"])
    main(["epic", "item", "--id=1", "--add=port one — 8 files — Done: make gate"])
    assert len(items_of(project)) == 1


def test_a_site_count_is_held_to_the_same_limit_and_says_so_in_its_own_unit(project):
    assert "80 sites > max_files 40" in refusal(
        ["epic", "item", "--id=1", "--add=re-cite — 80 sites — Done: make gate"])


def test_the_widest_count_in_a_title_is_the_one_measured(project):
    assert "255 files > max_files 40" in refusal(
        ["epic", "item", "--id=1", "--add=3 files here, 255 files there — Done: make gate"])


# ── the policy file: defaults, declarations, and a file that will not parse ──

def test_the_defaults_are_what_a_project_declaring_nothing_gets(project):
    assert not (project / policy.FILENAME).exists()
    assert policy.setting(project, "items", "max_files") == 40
    assert policy.setting(project, "board", "max_note_chars") == 500
    assert policy.setting(project, "board", "max_title_chars") == 700
    assert policy.setting(project, "agents.dsh", "root_writes_code") is False


def test_a_declared_value_wins(project):
    declare_policy(project, "[items]\nmax_files = 5\n\n[board]\nmax_note_chars = 90\n"
                      "max_title_chars = 120\n\n[agents.dsh]\nroot_writes_code = true\n")
    assert policy.setting(project, "items", "max_files") == 5
    assert policy.setting(project, "board", "max_note_chars") == 90
    assert policy.setting(project, "board", "max_title_chars") == 120
    assert policy.setting(project, "agents.dsh", "root_writes_code") is True


@pytest.mark.parametrize("text", [
    "[items]\nmax_files = not a number\n",     # wrong type
    "[items]\nmax_files = 0\n",                # a limit that would refuse everything
    "[items]\nmax_files = -3\n",
    "[items\nmax_files = 5\n",                 # will not parse at all
    "",                                        # empty
    "max_files = 5\n",                         # declared outside its section
])
def test_an_unusable_declaration_leaves_the_default_standing(project, text):
    declare_policy(project, text)
    assert policy.setting(project, "items", "max_files") == 40


def test_the_policy_tables_share_maestro_toml_with_the_declaration(project):
    """One file, two readers: the declaration keeps its keys, the policy its tables."""
    from maestro_cli import declaration
    declare_policy(project, 'layers = ["discipline"]\n\n[[shape]]\nname = "other"\n'
                            'since = "2026-09-14"\n\n[[arcs]]\nname = "core"\n\n'
                            "[branching]\nmode = \"strict\"\n\n[items]\nmax_files = 12\n\n"
                            "[agents.dsh]\nroot_writes_code = true\n")
    assert policy.setting(project, "items", "max_files") == 12
    assert policy.setting(project, "agents.dsh", "root_writes_code") is True
    decl = declaration.load(project)
    assert decl.layers == ("discipline",)
    assert [s.name for s in decl.shapes] == ["other"]
    assert decl.arc_names == ("core",)


def test_a_non_bool_opt_out_is_not_an_opt_out(project):
    declare_policy(project, '[agents]\nroot_writes_code = "yes"\n')
    assert policy.setting(project, "agents.dsh", "root_writes_code") is False


# ── the board caps ───────────────────────────────────────────────────────────

def test_a_note_over_the_cap_is_refused_on_both_verbs(project):
    note = "why this took two days: " + "reasoning. " * 60
    for argv in (["epic", "item", "--id=1", f"--add={GOOD}", f"--note={note}"],
                 ["epic", "update", "--id=1", f"--note={note}"]):
        said = refusal(argv)
        assert f"--note is {len(note)} chars and the cap is 500" in said
        assert "the board line is an index entry" in said
    assert items_of(project) == []             # the refused --add never landed either


def test_a_note_under_the_cap_lands(project):
    main(["epic", "item", "--id=1", f"--add={GOOD}", "--note=cut the branch"])
    assert "cut the branch" in next(
        (project / "docs" / "epics").glob("epic_01_*.md")).read_text()


def test_the_note_cap_is_the_declared_one(project):
    declare_policy(project, "[board]\nmax_note_chars = 20\n")
    assert "cap is 20" in refusal(
        ["epic", "update", "--id=1", "--note=a note that is comfortably over twenty chars"])


def test_a_title_over_the_cap_is_refused_even_when_it_states_both(project):
    declare_policy(project, "[board]\nmax_title_chars = 60\n")
    title = "port the planner " + "and everything it touches " * 5 + "— 3 files — Done: make gate"
    said = refusal(["epic", "item", "--id=1", f"--add={title}"])
    assert f"--add is {len(title)} chars and the cap is 60" in said
    assert "the reasoning belongs in the record body / ADR" in said


def test_an_empty_title_is_still_refused_as_an_empty_title(project):
    assert "cannot be empty" in refusal(["epic", "item", "--id=1", "--add=   "])


# ── epic size: one dsh session runs one epic ─────────────────────────────────

def fill(project, n):
    """`n` open items on epic 1, added straight into the record (the CLI's own cap is
    what is under test, so the seeding cannot go through it)."""
    path = next((project / "docs" / "epics").glob("epic_01_*.md"))
    head, fm_text, body = path.read_text().split("---\n", 2)
    fm = yaml.safe_load(fm_text)
    fm["items"] = [{"id": i, "title": f"item {i} — 2 files — Done: make gate",
                    "status": "todo", "since": "2026-09-12"} for i in range(1, n + 1)]
    path.write_text("---\n" + yaml.dump(fm, sort_keys=False) + "---\n" + body)


def test_an_epic_at_the_cap_refuses_the_next_item(project):
    fill(project, 8)
    said = refusal(["epic", "item", "--id=1", f"--add={GOOD}"])
    assert said == ("epic 1 has 8 open items (max_open_items 8): one dsh session runs one "
                    "epic — split it: `maestro epic new --slug=...` and move items with "
                    "`maestro epic item --id=1 --item=<k> --move-to=<new>`, blocked_by the "
                    "first half")
    assert len(items_of(project)) == 8


def test_an_epic_under_the_cap_still_accepts(project):
    fill(project, 7)
    main(["epic", "item", "--id=1", f"--add={GOOD}"])
    assert len(items_of(project)) == 8


def test_only_OPEN_items_crowd_an_epic(project):
    """A closed item is history, not queue. Eight done ones leave the epic empty."""
    fill(project, 8)
    path = next((project / "docs" / "epics").glob("epic_01_*.md"))
    path.write_text(path.read_text().replace("status: todo", "status: done"))
    main(["epic", "item", "--id=1", f"--add={GOOD}"])
    assert len(items_of(project)) == 9


def test_the_cap_is_the_one_the_project_declares(project):
    declare_policy(project, "[epics]\nmax_open_items = 3\n")
    fill(project, 3)
    assert "has 3 open items (max_open_items 3)" in refusal(
        ["epic", "item", "--id=1", f"--add={GOOD}"])


def test_an_unusable_cap_leaves_the_default_standing(project):
    declare_policy(project, "[epics]\nmax_open_items = 0\n")
    assert policy.setting(project, "epics", "max_open_items") == 8
    fill(project, 7)
    main(["epic", "item", "--id=1", f"--add={GOOD}"])      # 7 < the default 8
    assert len(items_of(project)) == 8


def test_pulling_an_option_is_held_to_the_same_cap(project):
    """`option --pull` creates an item, so it crosses the same commitment point."""
    main(["epic", "option", "--id=1", "--add=maybe port the renderer"])
    fill(project, 8)
    assert "has 8 open items" in refusal(["epic", "option", "--id=1", "--pull=1"])
    # the option is still there to pull once the epic has room
    path = next((project / "docs" / "epics").glob("epic_01_*.md"))
    assert "maybe port the renderer" in path.read_text()
