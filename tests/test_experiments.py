"""Tests for the experiment record kind — `maestro exp new|update|revise|set_body`.

`_append_finding` has its own file; this one covers the record contract around it,
which core rule 1 and rule 2 rest on:

  * `update` FILLS IN results; `revise` CORRECTS a wrong one and keeps the original —
    the two are not interchangeable, and revise refuses when there is nothing to revise;
  * closing a record (`--status=done`) refuses without the outcome AND the takeaway that
    make the closure a claim rather than a state change;
  * a comparative outcome (improved/parity/regression) refuses without the track and
    metric it is comparative ON;
  * lineage never dangles: `--parent`/`--related` are checked against records on disk;
  * `set_body` rewrites prose and leaves the CLI-owned frontmatter byte-identical.

Every case drives the real CLI entry point against a throwaway docs/experiments/, so the
flag names are exercised alongside the behaviour.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import experiments, indexes  # noqa: E402
from maestro_cli.cli import main  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project whose docs/experiments/ the CLI writes into."""
    exp_dir = tmp_path / "docs" / "experiments"
    exp_dir.mkdir(parents=True)
    monkeypatch.setattr(experiments, "EXP_DIR", exp_dir)
    monkeypatch.setattr(experiments, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "EXP_DIR", exp_dir)
    return exp_dir


def record(exp_dir, n):
    return next(exp_dir.glob(f"exp_{n:02d}_*.md"))


def frontmatter_of(exp_dir, n):
    return yaml.safe_load(record(exp_dir, n).read_text().split("---\n")[1])


def body_of(exp_dir, n):
    return record(exp_dir, n).read_text().split("---\n", 2)[2]


def refusal(argv):
    """Run the CLI expecting a clean stop, and return what it told the caller."""
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None), f"{argv} was expected to refuse"
    return str(e.value)


def done(exp_dir, n, **extra):
    """Close a record the way the CLI demands: outcome and takeaway together."""
    argv = ["exp", "update", f"--id={n}", "--status=done", "--outcome=confirmed",
            "--takeaway=it worked"]
    argv += [f"--{k.replace('_', '-')}={v}" for k, v in extra.items()]
    main(argv)


# ── new ──────────────────────────────────────────────────────────────────────

def test_new_scaffolds_a_planned_record(project):
    main(["exp", "new", "--slug=rf_baseline"])
    fm = frontmatter_of(project, 1)
    assert (fm["exp"], fm["status"], fm["date"]) == (1, "planned", str(date.today()))
    assert record(project, 1).name == "exp_01_rf_baseline.md"


def test_new_numbers_from_the_records_on_disk(project):
    main(["exp", "new", "--slug=first"])
    main(["exp", "new", "--slug=second"])
    # 07 exists but 02-06 do not: the next number follows the HIGHEST, never the count.
    (project / "exp_07_gap.md").write_text("---\nexp: 7\nstatus: done\n---\n")
    main(["exp", "new", "--slug=third"])
    assert record(project, 8).name == "exp_08_third.md"


def test_new_body_is_the_four_headings_a_record_owes(project):
    main(["exp", "new", "--slug=rf_baseline"])
    body = body_of(project, 1)
    assert [h for h in ("Goal", "Method", "Results", "Takeaway") if f"**{h}**" in body] == \
        ["Goal", "Method", "Results", "Takeaway"]


# ── update: what a result must carry ─────────────────────────────────────────

def test_done_without_an_outcome_is_refused(project):
    main(["exp", "new", "--slug=rf"])
    assert "--outcome" in refusal(["exp", "update", "--id=1", "--status=done",
                                   "--takeaway=it worked"])


def test_done_without_a_takeaway_is_refused(project):
    main(["exp", "new", "--slug=rf"])
    assert "--takeaway" in refusal(["exp", "update", "--id=1", "--status=done",
                                    "--outcome=confirmed"])


def test_an_outcome_already_on_record_satisfies_the_close(project):
    """The requirement is that the record CARRIES them, not that this call supplied them."""
    main(["exp", "new", "--slug=rf"])
    main(["exp", "update", "--id=1", "--outcome=confirmed", "--takeaway=it worked"])
    main(["exp", "update", "--id=1", "--status=done"])
    assert frontmatter_of(project, 1)["status"] == "done"


def test_unknown_outcome_names_the_allowed_values(project):
    main(["exp", "new", "--slug=rf"])
    msg = refusal(["exp", "update", "--id=1", "--outcome=great"])
    assert "confirmed" in msg and "inconclusive" in msg


@pytest.mark.parametrize("outcome", ["improved", "parity", "regression"])
def test_a_comparative_outcome_needs_what_it_compares_on(project, outcome):
    main(["exp", "new", "--slug=rf"])
    assert "--track" in refusal(["exp", "update", "--id=1", f"--outcome={outcome}",
                                 "--takeaway=better"])
    assert "--metric" in refusal(["exp", "update", "--id=1", f"--outcome={outcome}",
                                  "--takeaway=better", "--track=wine"])


def test_a_non_comparative_outcome_needs_neither(project):
    main(["exp", "new", "--slug=rf"])
    done(project, 1)
    assert frontmatter_of(project, 1)["outcome"] == "confirmed"


def test_updating_a_missing_record_says_which_one(project):
    assert "exp_4" in refusal(["exp", "update", "--id=4", "--status=running"])


# ── update: metrics are parsed, not stored as prose ──────────────────────────

def test_metric_values_are_numbers(project):
    main(["exp", "new", "--slug=rf"])
    main(["exp", "update", "--id=1", "--metric=accuracy=0.84"])
    assert frontmatter_of(project, 1)["metric"] == {"accuracy": 0.84}


def test_spread_becomes_its_own_key(project):
    main(["exp", "new", "--slug=rf"])
    main(["exp", "update", "--id=1", "--metric=auc=0.84±0.02"])
    assert frontmatter_of(project, 1)["metric"] == {"auc": 0.84, "auc_sd": 0.02}


@pytest.mark.parametrize("sep", ["±", "+/-", "+-"])
def test_every_spread_separator_reads_the_same(project, sep):
    main(["exp", "new", "--slug=rf"])
    main(["exp", "update", "--id=1", f"--metric=auc=0.84{sep}0.02"])
    assert frontmatter_of(project, 1)["metric"]["auc_sd"] == 0.02


def test_repeated_flags_and_comma_pairs_accumulate(project):
    main(["exp", "new", "--slug=rf"])
    main(["exp", "update", "--id=1", "--metric=acc=0.84,f1=0.80", "--metric=auc=0.9"])
    assert frontmatter_of(project, 1)["metric"] == {"acc": 0.84, "f1": 0.80, "auc": 0.9}


def test_a_non_numeric_metric_is_kept_as_written(project):
    """NA is a legal value (rule 2: missing is NA, never an estimate) — it must survive."""
    main(["exp", "new", "--slug=rf"])
    main(["exp", "update", "--id=1", "--metric=accuracy=NA"])
    assert frontmatter_of(project, 1)["metric"] == {"accuracy": "NA"}


# ── update: lineage never dangles ────────────────────────────────────────────

def test_parent_must_exist(project):
    main(["exp", "new", "--slug=child"])
    assert "does not exist" in refusal(["exp", "update", "--id=1", "--parent=9"])


def test_a_superseded_parent_is_refused_as_dangling(project):
    main(["exp", "new", "--slug=parent"])
    main(["exp", "new", "--slug=child"])
    main(["exp", "update", "--id=1", "--status=superseded"])
    assert "dangling" in refusal(["exp", "update", "--id=2", "--parent=1"])


def test_related_is_deduplicated_and_sorted(project):
    for slug in ("a", "b", "c"):
        main(["exp", "new", f"--slug={slug}"])
    main(["exp", "update", "--id=1", "--related=3,2,3"])
    assert frontmatter_of(project, 1)["related"] == [2, 3]


def test_related_cannot_include_self(project):
    main(["exp", "new", "--slug=a"])
    assert "self" in refusal(["exp", "update", "--id=1", "--related=1"])


def test_unknown_review_flag_names_the_allowed_set(project):
    main(["exp", "new", "--slug=a"])
    msg = refusal(["exp", "update", "--id=1", "--flags=looks_odd"])
    assert "single_seed" in msg


# ── revise: the correction keeps what it corrected ───────────────────────────

def test_revise_keeps_the_original_takeaway(project):
    main(["exp", "new", "--slug=rf"])
    done(project, 1)
    main(["exp", "revise", "--id=1", "--reason=misread the run dir",
          "--new-takeaway=it did not work"])
    fm = frontmatter_of(project, 1)
    assert fm["takeaway"] == "it did not work"
    assert len(fm["revisions"]) == 1
    rev = fm["revisions"][0]
    assert rev["previous_takeaway"] == "it worked"
    assert rev["reason"] == "misread the run dir"
    assert rev["by"] == "user"
    assert rev["date"] == str(date.today())


def test_revisions_accumulate_rather_than_replace(project):
    main(["exp", "new", "--slug=rf"])
    done(project, 1)
    main(["exp", "revise", "--id=1", "--reason=first", "--new-takeaway=second reading"])
    main(["exp", "revise", "--id=1", "--reason=second", "--new-takeaway=third reading",
          "--by=agent"])
    revs = frontmatter_of(project, 1)["revisions"]
    assert [r["previous_takeaway"] for r in revs] == ["it worked", "second reading"]
    assert [r["by"] for r in revs] == ["user", "agent"]


def test_revise_with_nothing_to_revise_points_at_update(project):
    """`revise` corrects a wrong result; filling in a first one is `update` (rule 1)."""
    main(["exp", "new", "--slug=rf"])
    assert "maestro exp update" in refusal(
        ["exp", "revise", "--id=1", "--reason=none yet", "--new-takeaway=first"])


def test_revise_to_the_same_takeaway_is_refused(project):
    main(["exp", "new", "--slug=rf"])
    done(project, 1)
    assert "identical" in refusal(["exp", "revise", "--id=1", "--reason=no change",
                                   "--new-takeaway= it worked "])


# ── set_body: prose is rewritten, frontmatter is not ─────────────────────────

def test_set_body_leaves_the_frontmatter_byte_identical(project, tmp_path):
    main(["exp", "new", "--slug=rf"])
    done(project, 1, metric="acc=0.84")
    before = record(project, 1).read_text().split("---\n")[1]
    src = tmp_path / "body.md"
    src.write_text("\n# Exp 1 — rf\n\n**Goal**: condensed.\n")
    main(["exp", "set_body", "--id=1", f"--from-file={src}"])
    assert record(project, 1).read_text().split("---\n")[1] == before
    assert "condensed." in body_of(project, 1)


def test_a_body_carrying_its_own_frontmatter_is_refused(project, tmp_path):
    main(["exp", "new", "--slug=rf"])
    src = tmp_path / "body.md"
    src.write_text("---\nexp: 1\nstatus: done\n---\n\n# Exp 1\n")
    msg = refusal(["exp", "set_body", "--id=1", f"--from-file={src}"])
    assert "frontmatter is preserved" in msg
    # The record still holds the frontmatter the CLI wrote, not the one offered.
    assert frontmatter_of(project, 1)["status"] == "planned"


def test_a_missing_source_file_names_the_path(project, tmp_path):
    main(["exp", "new", "--slug=rf"])
    missing = tmp_path / "nope.md"
    assert str(missing) in refusal(["exp", "set_body", "--id=1", f"--from-file={missing}"])


def test_over_cap_body_warns_but_still_writes(project, tmp_path, capsys):
    main(["exp", "new", "--slug=rf"])
    src = tmp_path / "body.md"
    src.write_text("\n".join(f"line {i}" for i in range(experiments.EXP_LINE_CAP + 20)))
    main(["exp", "set_body", "--id=1", f"--from-file={src}"])
    out = capsys.readouterr().out
    assert "over the" in out and str(experiments.EXP_LINE_CAP) in out
    assert "line 5" in body_of(project, 1)


# ── the INDEX every write regenerates ────────────────────────────────────────

def test_a_record_without_a_title_renders_instead_of_crashing(project):
    """Malformed frontmatter is what `docs check` REPORTS — it must survive rendering.

    The exp and adr tables read `title` directly, so one hand-written record with the
    key missing took `maestro index render` down with a KeyError, and with it every
    command that re-renders after a write.
    """
    (project / "exp_04_handwritten.md").write_text("---\nexp: 4\nstatus: done\n---\n")
    main(["exp", "new", "--slug=rf"])
    row = [ln for ln in (project / "INDEX.md").read_text().splitlines() if ln.startswith("| 4 ")]
    assert row and row[0].split("|")[2].strip() == "—"


def test_a_pipe_in_a_title_does_not_break_the_row(project):
    import re as _re
    main(["exp", "new", "--slug=a|b sweep"])
    row = next(ln for ln in (project / "INDEX.md").read_text().splitlines()
               if ln.startswith("| 1 "))
    assert r"a\|b" in row                           # escaped, so the cell holds it
    cells = _re.split(r"(?<!\\)\|", row)[1:-1]      # and the row is still 6 columns
    assert len(cells) == 6


# ── the slug becomes a path, so it is filtered ───────────────────────────────

@pytest.mark.parametrize("slug,expected", [
    ("Depth Sweep", "depth_sweep"),
    ("a|b sweep", "a_b_sweep"),
    ("../escape", "escape"),
    ("nested/dir", "nested_dir"),
    ("trailing__", "trailing"),
])
def test_slug_is_reduced_to_a_filename(project, slug, expected):
    main(["exp", "new", f"--slug={slug}"])
    assert record(project, 1).name == f"exp_01_{expected}.md"


def test_the_title_keeps_the_wording_the_slug_dropped(project):
    """The slug names the file; the title is prose and is not mangled to match it."""
    main(["exp", "new", "--slug=Depth Sweep"])
    assert frontmatter_of(project, 1)["title"] == "Depth Sweep"


def test_a_slug_with_nothing_to_name_a_file_with_is_refused(project):
    assert "no word characters" in refusal(["exp", "new", "--slug=///"])
    assert list(project.glob("exp_*.md")) == []


def test_run_count_finds_the_dirs_a_prose_title_names(project, tmp_path, monkeypatch):
    """`_count_runs` derives the run dir from the title, so it has to slugify it too.

    Run counts are derived, never stored (rule 2 / rule 4). The derivation read the
    title raw, so an experiment titled "Depth Sweep" was looked up under
    `data/experiments/exp_01_Depth Sweep/` — a directory the CLI never creates — and
    reported no runs however many it had.
    """
    monkeypatch.setattr(indexes, "ROOT", tmp_path)
    main(["exp", "new", "--slug=Depth Sweep"])
    for k in (1, 2):
        (tmp_path / "data" / "experiments" / "exp_01_depth_sweep" / f"run_{k}").mkdir(parents=True)
    # best_run puts the record in the External Pointers table, which is where runs are counted.
    main(["exp", "update", "--id=1", "--best-run=exp_01_depth_sweep__base__s0"])
    pointers = (project / "INDEX.md").read_text().split("## External Pointers")[1]
    row = next(ln for ln in pointers.splitlines() if ln.startswith("| 1 "))
    assert row.split("|")[3].strip() == "2"


# ── exp finding: the line that lands in findings.md ──────────────────────────

def test_a_finding_is_labelled_and_linked_to_its_experiment(project, tmp_path, monkeypatch):
    findings = tmp_path / "docs" / "findings.md"
    findings.write_text("# Findings\n\n## Positive findings (what works)\n\n")
    monkeypatch.setattr(experiments, "FINDINGS", findings)
    main(["exp", "new", "--slug=rf_baseline"])
    main(["exp", "finding", "--id=1", "--text=accuracy holds at 0.84 on cv5"])
    assert "- **rf_baseline**: accuracy holds at 0.84 on cv5 — Exp 1" in findings.read_text()


def test_a_finding_survives_a_record_with_no_title(project, tmp_path, monkeypatch):
    """Rule 5 wants the finding recorded; a malformed record is not a reason to lose it."""
    findings = tmp_path / "docs" / "findings.md"
    findings.write_text("# Findings\n\n")
    monkeypatch.setattr(experiments, "FINDINGS", findings)
    (project / "exp_04_handwritten.md").write_text("---\nexp: 4\nstatus: done\n---\n")
    main(["exp", "finding", "--id=4", "--negative", "--text=it does not hold"])
    text = findings.read_text()
    assert "- **exp_4**: it does not hold — Exp 4" in text
    assert "## Negative findings" in text          # the section is created on demand


def test_a_finding_for_a_missing_record_is_refused(project):
    assert "exp_9" in refusal(["exp", "finding", "--id=9", "--text=x"])


def test_new_never_reuses_an_archived_experiment_number(project):
    """An archived record is history, but its number stays taken (docs/archive/experiments/)."""
    main(["exp", "new", "--slug=first"])
    arch = project.parent / "archive" / "experiments"
    arch.mkdir(parents=True)
    (arch / "exp_08_retired.md").write_text("---\nexp: 8\ntitle: r\nstatus: done\n---\n")
    main(["exp", "new", "--slug=second"])
    assert record(project, 9).name == "exp_09_second.md"
