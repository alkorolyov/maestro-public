"""Tests for the dataset record kind — `maestro dataset new|update|verify`.

A dataset record exists to make rule 7 checkable: `data/raw/` is immutable, and a
"fix" is a new version rather than an edit. The sha256 is what turns that from a
convention into something a command can catch, so what is pinned here is the sha:

  * it is COMPUTED from the bytes, never supplied — and it matches the shared hasher
    the drift check re-verifies with;
  * `verify` separates the three ways a record and its bytes come apart — data edited
    in place (DRIFT), data not there (MISSING), record never hashed (NO-SHA) — and
    exits non-zero on any of them;
  * a record registered before its data lands is legal, with an empty sha and a note
    saying how to fill it;
  * a second `new` for the same name is refused, because a new release is a new
    version, not a new record.

Every case drives the real CLI entry point against a throwaway project.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import datasets, frontmatter, indexes  # noqa: E402
from maestro_cli.cli import main  # noqa: E402
from maestro_cli.hashing import hash_fileset  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project with docs/data/ and data/ — records here, bytes there."""
    docs = tmp_path / "docs" / "data"
    docs.mkdir(parents=True)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(datasets, "DATA_DIR", docs)
    # load_datasets() lives in frontmatter and reads ITS module global, so a record
    # written through datasets.DATA_DIR is only found again if both point at the same
    # place. In a real run they are the same object; here they are patched together.
    monkeypatch.setattr(frontmatter, "DATA_DIR", docs)
    monkeypatch.setattr(datasets, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(datasets, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "DATA_DIR", docs)
    return tmp_path


def seed(root, rel, **files):
    """Write a dataset's bytes under data/<rel>/ and return the directory."""
    d = root / "data" / rel
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text)
    return d


def frontmatter_of(root, name):
    text = (root / "docs" / "data" / f"{name}.md").read_text()
    return yaml.safe_load(text.split("---\n")[1])


def refusal(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None), f"{argv} was expected to refuse"
    return str(e.value)


# ── new: the sha comes from the bytes ────────────────────────────────────────

def test_sha_is_computed_from_the_files_on_disk(project):
    d = seed(project, "raw/wine", **{"wine.csv": "a,b\n1,2\n"})
    main(["dataset", "new", "--name=wine", "--source=uci", "--license=CC-BY"])
    fm = frontmatter_of(project, "wine")
    assert fm["sha256"] == hash_fileset(d)
    assert (fm["source"], fm["license"], fm["retrieved"]) == ("uci", "CC-BY", str(date.today()))


def test_a_version_selects_the_version_directory(project):
    seed(project, "raw/wine/v1", **{"wine.csv": "v1\n"})
    d2 = seed(project, "raw/wine/v2", **{"wine.csv": "v2\n"})
    main(["dataset", "new", "--name=wine", "--version=v2"])
    assert frontmatter_of(project, "wine")["sha256"] == hash_fileset(d2)


def test_an_explicit_path_wins_over_the_raw_default(project):
    seed(project, "raw/cohorts", **{"noise.csv": "ignored\n"})
    d = seed(project, "processed/cohorts", **{"trusted.csv": "kept\n"})
    main(["dataset", "new", "--name=cohorts", "--path=processed/cohorts"])
    fm = frontmatter_of(project, "cohorts")
    assert fm["path"] == "processed/cohorts"
    assert fm["sha256"] == hash_fileset(d)


def test_registering_before_the_data_lands_is_legal_and_says_so(project, capsys):
    main(["dataset", "new", "--name=pending"])
    assert frontmatter_of(project, "pending")["sha256"] == ""
    out = capsys.readouterr().out
    assert "sha256 empty" in out and "--rehash" in out


def test_a_second_record_for_the_same_name_is_refused(project):
    seed(project, "raw/wine", **{"wine.csv": "a\n"})
    main(["dataset", "new", "--name=wine"])
    msg = refusal(["dataset", "new", "--name=wine", "--version=v2"])
    assert "dataset update" in msg and "new version, not a new record" in msg


def test_the_name_keeps_its_case_so_it_matches_the_directory(project):
    """Unlike exp/adr/epic slugs, a dataset name IS the on-disk directory name."""
    d = seed(project, "raw/PAMPA_Trusted", **{"x.csv": "a\n"})
    main(["dataset", "new", "--name=PAMPA Trusted"])
    fm = frontmatter_of(project, "PAMPA_Trusted")
    assert fm["dataset"] == "PAMPA_Trusted" and fm["sha256"] == hash_fileset(d)


# ── update ───────────────────────────────────────────────────────────────────

def test_rehash_picks_up_new_files(project):
    d = seed(project, "raw/wine", **{"wine.csv": "a\n"})
    main(["dataset", "new", "--name=wine"])
    before = frontmatter_of(project, "wine")["sha256"]
    (d / "extra.csv").write_text("b\n")
    main(["dataset", "update", "--name=wine", "--rehash"])
    after = frontmatter_of(project, "wine")["sha256"]
    assert after != before and after == hash_fileset(d)


def test_rehash_with_nothing_to_hash_names_the_path_it_looked_at(project):
    main(["dataset", "new", "--name=ghost"])
    assert "raw/ghost" in refusal(["dataset", "update", "--name=ghost", "--rehash"])


def test_updating_an_unregistered_name_points_at_new(project):
    assert "dataset new" in refusal(["dataset", "update", "--name=nope", "--source=x"])


def test_repointing_the_path_rehashes_against_the_new_location(project):
    seed(project, "raw/wine", **{"wine.csv": "raw\n"})
    d = seed(project, "processed/wine", **{"wine.csv": "processed\n"})
    main(["dataset", "new", "--name=wine"])
    main(["dataset", "update", "--name=wine", "--path=processed/wine", "--rehash"])
    fm = frontmatter_of(project, "wine")
    assert fm["path"] == "processed/wine" and fm["sha256"] == hash_fileset(d)


# ── verify: the three ways a record and its bytes come apart ─────────────────

def test_verify_passes_when_nothing_moved(project, capsys):
    seed(project, "raw/wine", **{"wine.csv": "a\n"})
    main(["dataset", "new", "--name=wine"])
    main(["dataset", "verify"])
    assert "All dataset shas match" in capsys.readouterr().out


def test_an_edit_in_place_is_reported_as_drift(project, capsys):
    """Rule 7: raw data is immutable, so a changed sha is a broken promise, not an update."""
    d = seed(project, "raw/wine", **{"wine.csv": "a\n"})
    main(["dataset", "new", "--name=wine"])
    (d / "wine.csv").write_text("edited\n")
    msg = refusal(["dataset", "verify"])
    out = capsys.readouterr().out
    assert "DRIFT" in out and "new version" in out
    assert "1 dataset(s) need attention" in msg


def test_vanished_data_is_reported_as_missing(project, capsys):
    d = seed(project, "raw/wine", **{"wine.csv": "a\n"})
    main(["dataset", "new", "--name=wine"])
    (d / "wine.csv").unlink()
    d.rmdir()
    refusal(["dataset", "verify"])
    assert "MISSING" in capsys.readouterr().out


def test_a_record_that_was_never_hashed_is_reported_as_no_sha(project, capsys):
    main(["dataset", "new", "--name=pending"])          # registered before the data landed
    seed(project, "raw/pending", **{"x.csv": "a\n"})    # data arrives, record not refreshed
    refusal(["dataset", "verify"])
    out = capsys.readouterr().out
    assert "NO-SHA" in out and "--rehash" in out


def test_verify_counts_every_dataset_not_just_the_first(project, capsys):
    for name in ("a", "b"):
        d = seed(project, f"raw/{name}", **{"x.csv": "one\n"})
        main(["dataset", "new", f"--name={name}"])
        (d / "x.csv").write_text("two\n")
    assert "2 dataset(s)" in refusal(["dataset", "verify"])
    assert capsys.readouterr().out.count("DRIFT") == 2


def test_verify_with_no_records_is_not_a_failure(project, capsys):
    main(["dataset", "verify"])
    assert "No datasets to verify" in capsys.readouterr().out


# ── collecting: a pull that is still running ─────────────────────────────────
#
# Hashing a dataset whose bytes are still arriving records a moment nobody can
# reproduce, and every later check reads it as an edit in place. `--collecting` says
# "not yet"; `--complete` is the single moment the sha is stamped and rule 7 starts
# applying to those bytes.

def test_collecting_registers_without_hashing(project, capsys):
    seed(project, "raw/ticks", **{"2026-09-01.parquet": "day one\n"})   # pull already writing
    main(["dataset", "new", "--name=ticks", "--collecting"])
    fm = frontmatter_of(project, "ticks")
    assert fm["status"] == "collecting"
    assert fm["sha256"] == "pending"            # the bytes on disk were NOT hashed
    out = capsys.readouterr().out
    assert "collecting" in out and "--complete" in out


def test_new_without_collecting_records_status_complete(project):
    seed(project, "raw/wine", **{"wine.csv": "a\n"})
    main(["dataset", "new", "--name=wine"])
    assert frontmatter_of(project, "wine")["status"] == "complete"


def test_complete_stamps_the_sha_over_everything_the_pull_wrote(project):
    d = seed(project, "raw/ticks", **{"2026-09-01.parquet": "day one\n"})
    main(["dataset", "new", "--name=ticks", "--collecting"])
    (d / "2026-09-02.parquet").write_text("day two\n")                  # pull continues
    main(["dataset", "update", "--name=ticks", "--complete"])
    fm = frontmatter_of(project, "ticks")
    assert fm["status"] == "complete" and fm["sha256"] == hash_fileset(d)


def test_complete_with_nothing_on_disk_names_the_path_it_looked_at(project):
    main(["dataset", "new", "--name=ghost", "--collecting"])
    msg = refusal(["dataset", "update", "--name=ghost", "--complete"])
    assert "raw/ghost" in msg and "--complete" in msg


def test_status_collecting_walks_a_record_back_and_clears_the_sha(project):
    """Registered complete while the pull was still running — the stamped sha describes
    a half-arrived directory, so it goes back to pending rather than standing as truth."""
    seed(project, "raw/ticks", **{"2026-09-01.parquet": "day one\n"})
    main(["dataset", "new", "--name=ticks"])
    assert frontmatter_of(project, "ticks")["sha256"] != "pending"
    main(["dataset", "update", "--name=ticks", "--status=collecting"])
    fm = frontmatter_of(project, "ticks")
    assert fm["status"] == "collecting" and fm["sha256"] == "pending"


def test_rehash_on_a_collecting_record_is_refused_and_points_at_complete(project):
    seed(project, "raw/ticks", **{"2026-09-01.parquet": "day one\n"})
    main(["dataset", "new", "--name=ticks", "--collecting"])
    assert "--complete" in refusal(["dataset", "update", "--name=ticks", "--rehash"])


def test_complete_and_status_collecting_together_are_refused(project):
    seed(project, "raw/ticks", **{"x.parquet": "a\n"})
    main(["dataset", "new", "--name=ticks", "--collecting"])
    assert "opposite" in refusal(
        ["dataset", "update", "--name=ticks", "--complete", "--status=collecting"])


def test_verify_reports_a_collecting_dataset_without_failing(project, capsys):
    d = seed(project, "raw/ticks", **{"2026-09-01.parquet": "day one\n"})
    main(["dataset", "new", "--name=ticks", "--collecting"])
    (d / "2026-09-02.parquet").write_text("day two\n")    # the bytes SHOULD be moving
    main(["dataset", "verify"])                           # exits 0 — no SystemExit
    out = capsys.readouterr().out
    assert "collecting" in out and "DRIFT" not in out


def test_verify_catches_drift_again_once_the_pull_is_complete(project, capsys):
    d = seed(project, "raw/ticks", **{"2026-09-01.parquet": "day one\n"})
    main(["dataset", "new", "--name=ticks", "--collecting"])
    main(["dataset", "update", "--name=ticks", "--complete"])
    (d / "2026-09-01.parquet").write_text("rewritten\n")  # now this IS an edit in place
    refusal(["dataset", "verify"])
    assert "DRIFT" in capsys.readouterr().out


def test_a_record_with_no_status_field_is_treated_as_complete(project, capsys):
    """Every record written before the field existed describes a finished pull."""
    d = seed(project, "raw/wine", **{"wine.csv": "a\n"})
    main(["dataset", "new", "--name=wine"])
    rec = project / "docs" / "data" / "wine.md"
    rec.write_text("\n".join(l for l in rec.read_text().splitlines()
                             if not l.startswith("status:")) + "\n")
    assert "status" not in frontmatter_of(project, "wine")
    main(["dataset", "verify"])                       # complete + unchanged -> ok
    assert "ok" in capsys.readouterr().out
    (d / "wine.csv").write_text("edited\n")
    refusal(["dataset", "verify"])                    # complete + changed -> drift
    assert "DRIFT" in capsys.readouterr().out


# ── the advisory's wording ───────────────────────────────────────────────────

def test_the_note_says_since_when_and_how_to_end_it():
    note = datasets.collecting_note("ticks", {"version": "v1", "retrieved": "2026-09-10"},
                                    today=date(2026, 9, 11))
    assert "ticks v1" in note and "still collecting" in note and "2026-09-10" in note
    assert "--complete" in note


def test_a_collection_older_than_a_week_is_worded_as_stale():
    note = datasets.collecting_note("ticks", {"retrieved": "2026-08-01"},
                                    today=date(2026, 9, 11))
    assert "stale collection" in note and "41 days" in note


def test_a_note_for_a_record_with_an_unparseable_date_still_reads(project):
    note = datasets.collecting_note("ticks", {"retrieved": ""})
    assert "unrecorded date" in note and "stale" not in note


def test_status_complete_is_the_same_stamp_as_complete(project):
    d = seed(project, "raw/ticks", **{"d1.parquet": "day one\n"})
    main(["dataset", "new", "--name=ticks", "--collecting"])
    main(["dataset", "update", "--name=ticks", "--status=complete"])
    fm = frontmatter_of(project, "ticks")
    assert fm["status"] == "complete" and fm["sha256"] == hash_fileset(d)
