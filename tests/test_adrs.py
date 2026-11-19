"""Tests for the decision record kind — `maestro adr new|update`.

An ADR is amended in place and a folded one is archived (core rule 13,
tests/test_adr_amend.py). The older model — the old file left standing and pointed at
its replacement — stays valid for the projects that used it, and what is pinned here is
what that model needs to hold:

  * `superseded` refuses without the ADR that replaced it — a decision cannot be
    retired into thin air;
  * the replacement has to exist, and cannot be the record itself;
  * superseding leaves the old record on disk, with its own decision text intact;
  * the status vocabulary is closed, and the refusal names it.

Every case drives the real CLI entry point against a throwaway docs/adrs/.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import adrs, indexes  # noqa: E402
from maestro_cli.cli import main  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project whose docs/adrs/ the CLI writes into."""
    adr_dir = tmp_path / "docs" / "adrs"
    adr_dir.mkdir(parents=True)
    monkeypatch.setattr(adrs, "ADR_DIR", adr_dir)
    monkeypatch.setattr(adrs, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "ADR_DIR", adr_dir)
    return adr_dir


def record(adr_dir, n):
    return next(adr_dir.glob(f"adr_{n:02d}_*.md"))


def frontmatter_of(adr_dir, n):
    return yaml.safe_load(record(adr_dir, n).read_text().split("---\n")[1])


def refusal(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None), f"{argv} was expected to refuse"
    return str(e.value)


# ── new ──────────────────────────────────────────────────────────────────────

def test_new_scaffolds_a_proposed_record(project):
    main(["adr", "new", "--slug=one_instruction_file"])
    fm = frontmatter_of(project, 1)
    assert (fm["adr"], fm["status"], fm["date"]) == (1, "proposed", str(date.today()))
    assert record(project, 1).name == "adr_01_one_instruction_file.md"


def test_new_body_is_the_three_headings_a_decision_owes(project):
    main(["adr", "new", "--slug=one_instruction_file"])
    body = record(project, 1).read_text().split("---\n", 2)[2]
    assert [h for h in ("Context", "Decision", "Consequences") if f"**{h}**" in body] == \
        ["Context", "Decision", "Consequences"]


def test_new_numbers_from_the_records_on_disk(project):
    main(["adr", "new", "--slug=first"])
    (project / "adr_09_migrated.md").write_text("---\nadr: 9\nstatus: accepted\ntitle: m\n---\n")
    main(["adr", "new", "--slug=second"])
    assert record(project, 10).name == "adr_10_second.md"


def test_slug_is_reduced_to_a_filename_and_the_title_is_not(project):
    main(["adr", "new", "--slug=Two Co-equal Harnesses"])
    assert record(project, 1).name == "adr_01_two_co_equal_harnesses.md"
    assert frontmatter_of(project, 1)["title"] == "Two Co-equal Harnesses"


# ── update ───────────────────────────────────────────────────────────────────

def test_accepting_a_decision_records_the_one_liner_with_it(project):
    main(["adr", "new", "--slug=deterministic_grading"])
    main(["adr", "update", "--id=1", "--status=accepted",
          "--decision=verdicts are a function of stored bytes",
          "--tags=grading, method"])
    fm = frontmatter_of(project, 1)
    assert fm["status"] == "accepted"
    assert fm["decision"] == "verdicts are a function of stored bytes"
    assert fm["tags"] == ["grading", "method"]


def test_a_decision_longer_than_a_line_is_sent_to_the_body(project):
    main(["adr", "new", "--slug=long_winded"])
    msg = refusal(["adr", "update", "--id=1", "--decision=" + "x" * 301])
    assert "one-line".upper() in msg.upper() and "body" in msg.lower()


def test_unknown_status_names_the_allowed_values(project):
    main(["adr", "new", "--slug=a"])
    msg = refusal(["adr", "update", "--id=1", "--status=retired"])
    assert "proposed" in msg and "accepted" in msg and "superseded" in msg


def test_updating_a_missing_record_says_which_one(project):
    assert "adr_3" in refusal(["adr", "update", "--id=3", "--status=accepted"])


# ── supersession — the promise the kind exists for ───────────────────────────

def test_superseded_without_a_replacement_is_refused(project):
    main(["adr", "new", "--slug=old"])
    assert "--superseded-by" in refusal(["adr", "update", "--id=1", "--status=superseded"])


def test_the_replacement_has_to_exist(project):
    main(["adr", "new", "--slug=old"])
    assert "does not exist" in refusal(
        ["adr", "update", "--id=1", "--status=superseded", "--superseded-by=7"])


def test_a_decision_cannot_supersede_itself(project):
    """A self-pointing record retires a decision into a cycle: the reader following the
    pointer arrives back at the record that told them it was out of date."""
    main(["adr", "new", "--slug=old"])
    assert "itself" in refusal(
        ["adr", "update", "--id=1", "--status=superseded", "--superseded-by=1"])


def test_superseding_leaves_the_old_record_standing(project):
    main(["adr", "new", "--slug=old_way"])
    main(["adr", "update", "--id=1", "--status=accepted", "--decision=do it the old way"])
    main(["adr", "new", "--slug=new_way"])
    main(["adr", "update", "--id=1", "--status=superseded", "--superseded-by=2"])
    old = frontmatter_of(project, 1)
    assert old["status"] == "superseded" and old["superseded_by"] == 2
    # The decision it recorded is still readable — superseding is a pointer, not a delete.
    assert old["decision"] == "do it the old way"
    assert record(project, 2).exists()


def test_a_replacement_already_on_record_satisfies_the_status_change(project):
    """The requirement is that the record CARRIES the pointer, not that this call set it."""
    main(["adr", "new", "--slug=old"])
    main(["adr", "new", "--slug=new"])
    main(["adr", "update", "--id=1", "--superseded-by=2"])
    main(["adr", "update", "--id=1", "--status=superseded"])
    assert frontmatter_of(project, 1)["status"] == "superseded"


def test_the_index_carries_the_pointer_to_the_replacement(project):
    main(["adr", "new", "--slug=old"])
    main(["adr", "new", "--slug=new"])
    main(["adr", "update", "--id=1", "--status=superseded", "--superseded-by=2"])
    text = (project / "INDEX.md").read_text()
    assert "adr_2" in text.split("Superseded")[-1]


# ── retitle — the name changes, the number and date do not ───────────────────

def test_retitle_changes_title_and_scaffolded_heading_and_keeps_identity(project):
    main(["adr", "new", "--slug=old_name"])
    before = frontmatter_of(project, 1)
    main(["adr", "update", "--id=1", "--title=Data layout: raw and processed"])
    fm = frontmatter_of(project, 1)
    assert fm["title"] == "Data layout: raw and processed"
    assert (fm["adr"], fm["date"], fm["status"]) == (1, before["date"], before["status"])
    assert "# ADR 1 — Data layout: raw and processed\n" in record(project, 1).read_text()
    assert record(project, 1).name == "adr_01_old_name.md"   # no --slug, no rename


def test_retitle_leaves_a_hand_written_heading_alone(project):
    main(["adr", "new", "--slug=old_name"])
    p = record(project, 1)
    p.write_text(p.read_text().replace("# ADR 1 — old_name", "# ADR 1: my own heading"))
    main(["adr", "update", "--id=1", "--title=new name"])
    assert "# ADR 1: my own heading" in record(project, 1).read_text()


def test_retitle_leaves_a_valid_stamp(project):
    from maestro_cli import frontmatter
    main(["adr", "new", "--slug=old_name"])
    main(["adr", "update", "--id=1", "--title=new name", "--slug=new_name"])
    assert frontmatter.stamp_status(record(project, 1)) == "ok"


def test_slug_renames_the_file_and_the_index_follows(project):
    main(["adr", "new", "--slug=old_name"])
    main(["adr", "update", "--id=1", "--title=New Name", "--slug=New Name"])
    assert [p.name for p in project.glob("adr_*.md")] == ["adr_01_new_name.md"]
    assert frontmatter_of(project, 1)["adr"] == 1
    index = (project / "INDEX.md").read_text()
    assert "| 1 | New Name |" in index and "old_name" not in index


def test_slug_colliding_with_another_live_adr_is_refused(project):
    main(["adr", "new", "--slug=float"])
    main(["adr", "new", "--slug=layout"])
    msg = refusal(["adr", "update", "--id=2", "--slug=float"])
    assert "collides" in msg and "adr_01_float.md" in msg
    assert record(project, 2).name == "adr_02_layout.md"


def test_slug_whose_target_file_exists_is_refused(project):
    main(["adr", "new", "--slug=layout"])
    (project / "adr_01_taken.md").write_text("stray\n")
    assert "already exists" in refusal(["adr", "update", "--id=1", "--slug=taken"])
    assert (project / "adr_01_layout.md").exists()


def test_a_refused_update_does_not_move_the_file(project):
    main(["adr", "new", "--slug=layout"])
    refusal(["adr", "update", "--id=1", "--slug=renamed", "--status=retired"])
    assert [p.name for p in project.glob("adr_*.md")] == ["adr_01_layout.md"]


def test_empty_title_is_refused(project):
    main(["adr", "new", "--slug=layout"])
    assert "empty" in refusal(["adr", "update", "--id=1", "--title=  "])


def test_slug_rename_is_a_git_rename_when_tracked(project, tmp_path):
    import subprocess
    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True,
                                    capture_output=True, text=True).stdout
    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "0")
    main(["adr", "new", "--slug=layout"])
    git("add", "docs/adrs/adr_01_layout.md")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "1")
    main(["adr", "update", "--id=1", "--slug=data_layout"])
    status = git("status", "--short", "docs/adrs")
    assert "R  docs/adrs/adr_01_layout.md -> docs/adrs/adr_01_data_layout.md" in status


# ── the archive — history, whose numbers stay taken ─────────────────────────

def archive(project):
    d = project.parent / "archive" / "adrs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_new_never_reuses_an_archived_number(project):
    main(["adr", "new", "--slug=first"])
    (archive(project) / "adr_29_folded.md").write_text(
        "---\nadr: 29\nstatus: accepted\ntitle: folded\n---\n")
    main(["adr", "new", "--slug=next"])
    assert record(project, 30).name == "adr_30_next.md"


def test_highest_number_archived_with_no_live_record_above_it(project):
    main(["adr", "new", "--slug=a"])
    main(["adr", "new", "--slug=b"])
    main(["adr", "new", "--slug=c"])
    a = archive(project)
    record(project, 3).rename(a / record(project, 3).name)
    main(["adr", "new", "--slug=d"])
    assert record(project, 4).name == "adr_04_d.md"


def test_an_archived_file_without_frontmatter_still_holds_its_number(project):
    (archive(project) / "adr_12_legacy.md").write_text("# no frontmatter\n")
    main(["adr", "new", "--slug=x"])
    assert record(project, 13).name == "adr_13_x.md"


def test_archived_adrs_are_not_in_the_index(project):
    main(["adr", "new", "--slug=live"])
    (archive(project) / "adr_07_gone.md").write_text(
        "---\nadr: 7\nstatus: accepted\ntitle: gone\n---\n")
    main(["index", "render", "--kind=adr"])
    text = (project / "INDEX.md").read_text()
    assert "live" in text and "gone" not in text and "adr_07" not in text


def test_updating_an_archived_adr_says_it_is_archived(project):
    (archive(project) / "adr_07_gone.md").write_text(
        "---\nadr: 7\nstatus: accepted\ntitle: gone\n---\n")
    assert "archived" in refusal(["adr", "update", "--id=7", "--title=back"])
    assert "archived" in refusal(["adr", "show", "--id=7"])
