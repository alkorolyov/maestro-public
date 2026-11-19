"""Tests for `maestro docs check` as a whole — the parts not already pinned by
test_checks_kanban_adr9.py (K1-K3, A1-A4) and test_checks_dead_paths.py.

Covered here: the code-tier import rules, the hard size caps, forward-looking
sections, orphan docs, citation integrity, and — the distinction the whole design
rests on — which findings BLOCK and which only advise.

  * blocking (exit 2, stderr) is for a stored pointer that resolves to nothing, or a
    cap already breached: mechanical to fix, and dangerous to leave;
  * advisory (exit unchanged) is for a run dir that looks incomplete, because a crashed
    run, a tracker-backed project and a pre-ADR-3 dir all look identical from disk, and
    blocking there teaches people to delete evidence to silence the checker.

`--strict` is the escape hatch for a caller that wants a hard gate over both.
"""
from __future__ import annotations
import datetime as dt

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import checks, indexes  # noqa: E402


# ── the pure tier rules ──────────────────────────────────────────────────────

def tiers(root, src=None, scripts=None, experiments=None):
    """Lay out a three-tier project: {filename: source} per tier."""
    for tier, files in (("src", src), ("scripts", scripts), ("experiments", experiments)):
        if files is None:
            continue
        d = root / tier
        d.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (d / name).write_text(text)
    return root


def test_library_code_must_not_import_an_experiment(tmp_path):
    tiers(tmp_path, src={"model.py": "import experiments.exp_01_a\n"},
          experiments={"exp_01_a.py": ""})
    issue, = checks.layering_issues(tmp_path)
    assert "src/model.py" in issue and "library code" in issue


def test_library_code_must_not_import_a_script(tmp_path):
    tiers(tmp_path, src={"model.py": "from scripts import featurize\n"},
          scripts={"featurize.py": ""})
    assert len(checks.layering_issues(tmp_path)) == 1


def test_a_bare_sibling_import_counts_as_the_tier_it_names(tmp_path):
    """`python experiments/exp_02.py` resolves `import exp_01_a` to its sibling, so the
    package-root check alone would miss the copy rule 8 exists to prevent."""
    tiers(tmp_path, experiments={"exp_01_a.py": "", "exp_02_b.py": "import exp_01_a\n"})
    issue, = checks.layering_issues(tmp_path)
    assert "exp_02_b.py" in issue and "promote shared code to src/" in issue


def test_a_script_must_not_import_an_experiment(tmp_path):
    tiers(tmp_path, scripts={"sweep.py": "import exp_01_a\n"}, experiments={"exp_01_a.py": ""})
    issue, = checks.layering_issues(tmp_path)
    assert "production CLI" in issue


def test_an_experiment_may_use_the_tiers_below_it(tmp_path):
    tiers(tmp_path, src={"model.py": ""}, scripts={"featurize.py": ""},
          experiments={"exp_01_a.py": "import src.model\nimport scripts.featurize\n"})
    assert checks.layering_issues(tmp_path) == []


def test_an_experiment_importing_its_own_module_name_is_not_a_violation(tmp_path):
    tiers(tmp_path, experiments={"exp_01_a.py": "import exp_01_a\n"})
    assert checks.layering_issues(tmp_path) == []


def test_a_relative_import_stays_inside_its_package(tmp_path):
    tiers(tmp_path, src={"model.py": "from . import helpers\n"})
    assert checks.layering_issues(tmp_path) == []


def test_a_file_that_does_not_parse_is_skipped_not_fatal(tmp_path):
    tiers(tmp_path, src={"broken.py": "def (\n"})
    assert checks.layering_issues(tmp_path) == []


def test_run_dirs_are_ordered_numerically_not_lexically(tmp_path):
    for k in (1, 2, 10):
        (tmp_path / f"run_{k}").mkdir()
    (tmp_path / "v1").mkdir()               # a dataset version, not a run (ADR 3)
    assert [p.name for p in checks.run_dirs(tmp_path)] == ["run_1", "run_2", "run_10"]


# ── the whole check, over a throwaway project ────────────────────────────────

@pytest.fixture
def project(tmp_path, monkeypatch):
    """A minimal, clean maestro project that `check()` reports OK on."""
    for sub in ("docs/experiments", "docs/adrs", "docs/epics", "docs/data",
                "data/raw", "data/experiments"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text("# Project\n")
    (tmp_path / "maestro.toml").write_text('layers = ["discipline", "research"]\n')
    (tmp_path / "docs" / "progress.md").write_text("# Progress\n")
    (tmp_path / "docs" / "findings.md").write_text("# Findings\n")
    for mod, names in ((checks, ("ROOT", "EXP_DIR", "ADR_DIR", "EPIC_DIR", "DOCS_DIR",
                                 "RAW_DIR", "DATA_DIR", "EXPDATA_DIR")),
                       (indexes, ("ROOT", "EXP_DIR", "ADR_DIR", "EPIC_DIR", "DATA_DIR"))):
        for name in names:
            monkeypatch.setattr(mod, name, {
                "ROOT": tmp_path,
                "EXP_DIR": tmp_path / "docs" / "experiments",
                "ADR_DIR": tmp_path / "docs" / "adrs",
                "EPIC_DIR": tmp_path / "docs" / "epics",
                "DOCS_DIR": tmp_path / "docs",
                "DATA_DIR": tmp_path / "docs" / "data",
                "RAW_DIR": tmp_path / "data" / "raw",
                "EXPDATA_DIR": tmp_path / "data" / "experiments",
            }[name])
    return tmp_path


def exp_record(project, n=1, body="\n# Exp 1\n", **fields):
    fm = {"exp": n, "title": f"e{n}", "status": "done", "outcome": "confirmed",
          "takeaway": "it worked", "source_artifacts": [], **fields}
    lines = "\n".join(f"{k}: {v!r}" if isinstance(v, str) else f"{k}: {v}"
                      for k, v in fm.items())
    p = project / "docs" / "experiments" / f"exp_{n:02d}_e{n}.md"
    p.write_text(f"---\n{lines}\n---\n{body}")
    return p


def run(strict=False, verbose=False, report_only=False):
    return checks.check(strict=strict, verbose=verbose, report_only=report_only)


def test_a_clean_project_reports_ok(project, capsys):
    assert run() == 0
    assert "no drift detected" in capsys.readouterr().out


def test_an_over_cap_progress_file_blocks(project, capsys):
    (project / "docs" / "progress.md").write_text("\n".join(f"line {i}" for i in range(250)))
    assert run() == 2
    err = capsys.readouterr().err
    assert "docs/progress.md is 250 lines (cap 200)" in err and "DRIFT DETECTED" in err


def test_the_exp_cap_counts_prose_and_not_frontmatter(project, capsys):
    """A record's YAML is structured data — per-round metrics must not eat a prose cap."""
    big_fm = {"tags": [f"t{i}" for i in range(200)]}
    exp_record(project, 1, body="\n# Exp 1\n\nshort.\n", **big_fm)
    assert run() == 0
    exp_record(project, 2, body="\n".join(f"line {i}" for i in range(200)))
    assert run() == 2
    assert "(cap 150). Experiment is multiple" in capsys.readouterr().err


def test_an_oversized_claude_md_blocks_with_the_token_estimate(project, capsys):
    (project / "CLAUDE.md").write_text("x" * (checks.CLAUDE_TOKEN_CAP * checks.BYTES_PER_TOKEN + 400))
    assert run() == 2
    assert f"(cap {checks.CLAUDE_TOKEN_CAP})" in capsys.readouterr().err


@pytest.mark.parametrize("heading", ["## Next steps", "### TODO", "## Future work"])
def test_a_forward_looking_section_in_an_exp_blocks(project, capsys, heading):
    exp_record(project, 1, body=f"\n# Exp 1\n\n{heading}\n\n- do the thing\n")
    assert run() == 2
    assert "forward-looking section" in capsys.readouterr().err


def test_an_orphan_doc_names_both_ways_to_legitimise_it(project, capsys):
    (project / "docs" / "scratch.md").write_text("# Scratch\n")
    assert run() == 2
    err = capsys.readouterr().err
    assert "maestro adr new" in err and "domain-doc" in err


def test_a_doc_that_declares_itself_is_allowed(project):
    (project / "docs" / "schema.md").write_text("---\nkind: domain-doc\n---\n\n# Schema\n")
    assert run() == 0


def test_a_citation_to_a_missing_experiment_blocks(project, capsys):
    (project / "docs" / "findings.md").write_text("# Findings\n\n- **x**: y — Exp 4\n")
    assert run() == 2
    assert "references Exp 4" in capsys.readouterr().err


def test_a_citation_to_a_superseded_experiment_blocks(project, capsys):
    exp_record(project, 4, status="superseded")
    (project / "docs" / "findings.md").write_text("# Findings\n\n- **x**: y — Exp 4\n")
    assert run() == 2
    assert "which is superseded" in capsys.readouterr().err


def test_a_source_artifact_that_is_gone_blocks(project, capsys):
    exp_record(project, 1, source_artifacts=["data/experiments/exp_01_e1/run_1/metrics.json"])
    assert run() == 2
    assert "has lost its evidence" in capsys.readouterr().err


def test_a_best_run_pointing_at_nothing_blocks(project, capsys):
    (project / "data" / "experiments" / "exp_01_e1").mkdir()
    exp_record(project, 1, best_run="run_2")
    assert run() == 2
    assert "best_run=run_2" in capsys.readouterr().err


def test_raw_data_with_no_record_blocks_and_names_the_command(project, capsys):
    (project / "data" / "raw" / "wine").mkdir()
    (project / "data" / "raw" / "wine" / "wine.csv").write_text("a\n")
    assert run() == 2
    assert "maestro dataset new --name=wine" in capsys.readouterr().err


def test_an_incomplete_run_dir_only_advises(project, capsys):
    """A crashed run, a tracker-backed project and a pre-ADR-3 dir look identical here."""
    exp_record(project, 1)
    run_1 = project / "data" / "experiments" / "exp_01_e1" / "run_1"
    run_1.mkdir(parents=True)
    (run_1 / "run.log").write_text("started\n")          # no metrics.json
    assert run() == 0
    assert "no non-empty metrics.json" in capsys.readouterr().out


def test_strict_turns_an_advisory_into_a_failure(project):
    exp_record(project, 1)
    run_1 = project / "data" / "experiments" / "exp_01_e1" / "run_1"
    run_1.mkdir(parents=True)
    (run_1 / "run.log").write_text("started\n")
    assert run(strict=True) == 1


# ── non-actionable advisories are one summary line, unless --verbose ─────────

CLOSED_A5 = "states a result but cites no artifact (A5)"
SUMMARY = "suppressed (--verbose shows them)"


def closed_epic(project, n=1):
    """A closed epic whose outcome names a result and cites nothing: A5 on a CLOSED
    epic, the advisory the checker itself calls history rather than debt."""
    import yaml
    fm = {"epic": n, "title": f"epic {n}", "status": "done", "opened": "2026-09-01",
          "closed": "2026-09-02", "blocked_by": None,
          "done_when": [{"id": 1, "text": "it compiles", "result": "yes, verified: abc1234"}],
          "items": [], "options": [], "outcome": "0 errors"}
    p = project / "docs" / "epics" / f"epic_{n:02d}_e{n}.md"
    p.write_text("---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n# Epic\n\n## Log\n\n"
                 "- 2026-09-02 — closed.\n")
    return p


def live_advisory(project):
    """An actionable advisory on a live surface: a run dir with no metrics.json."""
    exp_record(project, 1)
    run_1 = project / "data" / "experiments" / "exp_01_e1" / "run_1"
    run_1.mkdir(parents=True)
    (run_1 / "run.log").write_text("started\n")


def test_closed_epic_advisories_fold_into_one_summary_line(project, capsys):
    closed_epic(project)
    live_advisory(project)
    assert run() == 0
    out = capsys.readouterr().out
    assert "no non-empty metrics.json" in out            # the live advisory still prints
    assert CLOSED_A5 not in out                          # the history does not
    assert "~ 1 advisory on closed epics / untouched files / legacy ADR text " + SUMMARY in out
    # The OK line still counts every advisory: the two above plus exp_1's A1, which stays
    # visible because the fixture is no git repo ("git could not say what changed").
    assert "3 advisory)." in out


def test_untouched_file_advisories_fold_into_the_same_line(project, capsys, monkeypatch):
    """An ADR 9 finding staged off a file untouched this session is the standing backlog."""
    (project / "docs" / "notes.md").write_text(
        "---\nkind: domain-doc\n---\n\n# Notes\n\nThe combat door is ported.\n")
    monkeypatch.setattr(checks, "touched_paths", lambda root, hours=None: set())
    assert run() == 0
    out = capsys.readouterr().out
    assert "status word 'ported'" not in out
    assert "~ 1 advisory on closed epics / untouched files / legacy ADR text " + SUMMARY in out


def test_verbose_prints_every_advisory_and_no_summary(project, capsys):
    closed_epic(project)
    live_advisory(project)
    assert run(verbose=True) == 0
    out = capsys.readouterr().out
    assert CLOSED_A5 in out and "no non-empty metrics.json" in out
    assert SUMMARY not in out


def test_a_project_with_only_live_advisories_prints_no_summary(project, capsys):
    live_advisory(project)
    assert run() == 0
    assert SUMMARY not in capsys.readouterr().out


def test_folding_changes_no_exit_code(project, capsys):
    """Suppressed advisories are still advisories: 0 by default, 1 under --strict, and the
    drift path stays 2 with the summary riding stderr beside the hard finding."""
    closed_epic(project)
    assert run() == 0
    capsys.readouterr()
    assert run(strict=True) == 1                         # counted, even when unprinted
    capsys.readouterr()
    (project / "docs" / "progress.md").write_text("\n".join(f"line {i}" for i in range(250)))
    assert run() == 2
    err = capsys.readouterr().err
    assert "- docs/progress.md is 250 lines" in err
    assert CLOSED_A5 not in err and SUMMARY in err


def test_output_ran_but_no_record_was_written_blocks(project, capsys):
    """The 'work ran, the record was never written' failure, in both its shapes."""
    d = project / "data" / "experiments" / "exp_07_ghost" / "run_1"
    d.mkdir(parents=True)
    (d / "run.log").write_text("epoch 1\n")
    assert run() == 2
    assert "work ran, the record was never written" in capsys.readouterr().err


def test_a_planned_record_with_output_blocks(project, capsys):
    exp_record(project, 1, status="planned", outcome="", takeaway="")
    d = project / "data" / "experiments" / "exp_01_e1" / "run_1"
    d.mkdir(parents=True)
    (d / "run.log").write_text("epoch 1\n")
    assert run() == 2
    assert "never written up" in capsys.readouterr().err


# ── datasets: a pull in progress is not drift ────────────────────────────────
#
# `docs check` runs as a Stop hook at the end of every agent turn. A dataset still
# being collected rewrites its own directory by design, so comparing shas reported
# "data changed in place (breaks immutability)" on every turn for something working
# exactly as intended. Collecting records skip the comparison and advise instead.

def dataset_record(project, name, sha, status=None, retrieved=None):
    # Yesterday, computed — not a literal. A literal "recent" date ages past
    # STALE_COLLECTING_DAYS and flips the advisory wording, so the fresh-collection
    # test starts failing on a calendar date rather than on a code change.
    retrieved = retrieved or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    fm = [f"dataset: {name}", "version: ''", "source: ''", "license: ''",
          f"retrieved: {retrieved}"]
    if status is not None:
        fm.append(f"status: {status}")
    fm += [f"sha256: {sha}", "used: ''", "tags: []"]
    p = project / "docs" / "data" / f"{name}.md"
    p.write_text("---\n" + "\n".join(fm) + "\n---\n\n# Dataset\n")
    return p


def raw_bytes(project, name, **files):
    d = project / "data" / "raw" / name
    d.mkdir(parents=True, exist_ok=True)
    for fname, text in files.items():
        (d / fname).write_text(text)
    return d


def test_a_collecting_dataset_advises_instead_of_reporting_drift(project, capsys):
    raw_bytes(project, "ticks", **{"d1.parquet": "day one\n", "d2.parquet": "day two\n"})
    dataset_record(project, "ticks", "pending", status="collecting")
    assert run() == 0
    out = capsys.readouterr()
    assert "still collecting" in out.out and "--complete" in out.out
    assert "drift" not in out.err.lower()


def test_a_long_running_collection_is_advisory_too_but_says_stale(project, capsys):
    raw_bytes(project, "ticks", **{"d1.parquet": "day one\n"})
    dataset_record(project, "ticks", "pending", status="collecting", retrieved="2026-01-01")
    assert run() == 0
    assert "stale collection" in capsys.readouterr().out


def test_a_complete_dataset_still_blocks_on_sha_drift(project, capsys):
    d = raw_bytes(project, "ticks", **{"d1.parquet": "day one\n"})
    dataset_record(project, "ticks", checks._dataset_sha("ticks", ""), status="complete")
    assert run() == 0
    (d / "d1.parquet").write_text("rewritten\n")
    assert run() == 2
    assert "sha drift" in capsys.readouterr().err


def test_a_record_with_no_status_field_is_checked_as_complete(project, capsys):
    """Records written before the field existed describe finished pulls."""
    d = raw_bytes(project, "ticks", **{"d1.parquet": "day one\n"})
    dataset_record(project, "ticks", checks._dataset_sha("ticks", ""))
    assert run() == 0
    (d / "d1.parquet").write_text("rewritten\n")
    assert run() == 2
    assert "sha drift" in capsys.readouterr().err


def test_strict_turns_the_collecting_advisory_into_a_failure(project):
    """The advisory is still a finding — a caller that wants a hard gate gets one."""
    raw_bytes(project, "ticks", **{"d1.parquet": "day one\n"})
    dataset_record(project, "ticks", "pending", status="collecting")
    assert run(strict=True) == 1


# ── --report-only: the same report, exit 0 whatever it found ─────────────────
#
# The Claude Code Stop hook treats ANY non-zero exit as "block": exit 2 forces another
# turn, every turn, for as long as a hard finding stands — and a normal branch state
# (an INDEX.md rendered on main, not yet on the feature branch) is such a finding. A
# drift report is information for the next turn, never a reason to refuse ending one.

def test_report_only_prints_the_hard_finding_and_exits_zero(project, capsys):
    (project / "docs" / "progress.md").write_text("\n".join(f"line {i}" for i in range(250)))
    assert run() == 2
    plain = capsys.readouterr()
    assert run(report_only=True) == 0
    report = capsys.readouterr()
    assert "DRIFT DETECTED" in report.err and "docs/progress.md is 250 lines" in report.err
    assert report.err == plain.err and report.out == plain.out   # same lines, same streams


def test_report_only_keeps_the_fold_and_verbose(project, capsys):
    closed_epic(project)
    (project / "docs" / "progress.md").write_text("\n".join(f"line {i}" for i in range(250)))
    assert run(report_only=True) == 0
    err = capsys.readouterr().err
    assert SUMMARY in err and CLOSED_A5 not in err
    assert run(report_only=True, verbose=True) == 0
    err = capsys.readouterr().err
    assert CLOSED_A5 in err and SUMMARY not in err


def test_report_only_on_a_clean_project_is_a_no_op(project, capsys):
    assert run() == 0
    plain = capsys.readouterr()
    assert run(report_only=True) == 0
    assert capsys.readouterr() == plain
    assert "no drift detected" in plain.out


def test_report_only_with_advisories_stays_zero(project, capsys):
    exp_record(project, 1)
    run_1 = project / "data" / "experiments" / "exp_01_e1" / "run_1"
    run_1.mkdir(parents=True)
    (run_1 / "run.log").write_text("started\n")
    assert run(strict=True) == 1
    capsys.readouterr()
    assert run(report_only=True) == 0
    assert "no non-empty metrics.json" in capsys.readouterr().out


def test_cli_refuses_report_only_with_strict(project, capsys):
    """Opposite intents — strict fails on advisories, report-only never fails."""
    from maestro_cli.cli import main
    with pytest.raises(SystemExit) as e:
        main(["docs", "check", "--report-only", "--strict"])
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "--report-only and --strict cannot be combined" in err


def test_cli_report_only_exits_zero_on_a_hard_finding(project, capsys):
    from maestro_cli.cli import main
    (project / "docs" / "progress.md").write_text("\n".join(f"line {i}" for i in range(250)))
    with pytest.raises(SystemExit) as e:
        main(["docs", "check"])
    assert e.value.code == 2
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        main(["docs", "check", "--report-only"])
    assert e.value.code == 0
    assert "DRIFT DETECTED" in capsys.readouterr().err


# ── docs/archive/adrs/ is history, not a live record set ─────────────────────

def test_archived_adrs_are_neither_listed_nor_checked_as_live(project, capsys, monkeypatch):
    """A consolidation folds ADRs into a survivor and `git mv`s them to docs/archive/adrs/.
    The archived files carry pointers and stamps that would be drift if they were live (a
    supersession pointing nowhere, a stale stamp); the survivor and CLAUDE.md cite their
    numbers. None of that may read as drift: the archive is history."""
    from maestro_cli import frontmatter
    for name in ("ROOT", "EXP_DIR", "ADR_DIR", "EPIC_DIR", "DATA_DIR"):
        monkeypatch.setattr(frontmatter, name, getattr(checks, name))
    arch = project / "docs" / "archive" / "adrs"
    arch.mkdir(parents=True)
    frontmatter.write(project / "docs" / "adrs" / "adr_01_data_layout.md",
                      {"adr": 1, "title": "data layout", "status": "accepted",
                       "date": "2026-09-28", "decision": "raw and processed", "tags": []},
                      "\n# ADR 1 — data layout\n\nFolds ADR 5; supersedes ADR 5 and replaces ADR 7.\n"
                      "\nHistory: folded ADR 5 and ADR 7 on 2026-09-28.\n")
    frontmatter.write(arch / "adr_05_old_layout.md",
                      {"adr": 5, "title": "old layout", "status": "superseded",
                       "superseded_by": 99, "date": "2026-09-11", "tags": []}, "\nold\n")
    (arch / "adr_07_hand_edited.md").write_text(
        "---\nadr: 7\ntitle: t\nstatus: accepted\nsig: 0000000000000000\n---\nbody\n")
    (arch / "README.md").write_text("| archived | survivor |\n|---|---|\n| 5 | 1 |\n| 7 | 1 |\n")
    (project / "CLAUDE.md").write_text("# Project\n\nLayout: ADR 1 (was ADR 5 and ADR 7).\n")
    indexes.render("adr")

    assert run(verbose=True) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert "adr_5" not in text and "adr_7" not in text and "archive" not in text
    assert "99" not in (project / "docs" / "adrs" / "INDEX.md").read_text()
    assert "old layout" not in (project / "docs" / "adrs" / "INDEX.md").read_text()
    assert checks.stamp_findings() == ([], [])
