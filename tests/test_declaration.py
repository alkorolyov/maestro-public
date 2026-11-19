"""The declaration (maestro.toml): membership, rule layers, the dated shape history — and
what the checker, the hooks and `init` do with it (design.md → "Shape declaration").

The contract under test:
  * a record is judged under the shape valid at its date; one dated before the first
    declared shape is history — its citations are not checked and not repointed;
  * evidence is a path on disk OR a well-formed `table:<schema>.<name>@<snapshot>`;
  * under `other` no data citation and no dataset sha is judged; only `tiers` is policed;
  * an infra run leaves a log, not a metric;
  * the research layer switches the exp/run/raw/tier checks off, the discipline stays;
  * an undeclared project is still checked this release, with one advisory;
  * `init` writes the declaration once and never rewrites it; `shape add` only appends.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import checks, declaration, guards, indexes, init as init_mod  # noqa: E402
from maestro_cli.cli import main as cli_main  # noqa: E402

DECL = 'layers = ["discipline", "research"]\n'


def write_decl(root, text=DECL):
    (root / "maestro.toml").write_text(text)


# ── the loader ───────────────────────────────────────────────────────────────

def test_nothing_declared_is_none(tmp_path):
    assert declaration.load(tmp_path) is None
    assert not declaration.is_declared(tmp_path)


def test_maestro_toml_is_read_in_full(tmp_path):
    write_decl(tmp_path, 'layers = ["discipline", "research"]\ntracker = "none"\n'
                         '[[shape]]\nname = "tiers"\nsince = "2026-09-11"\n'
                         '[[shape]]\nname = "other"\nsince = "2026-09-14"\n')
    d = declaration.load(tmp_path)
    assert d.layers == ("discipline", "research") and d.research and d.tracker == "none"
    assert [s.name for s in d.shapes] == ["tiers", "other"]
    assert d.first_line == date(2026, 9, 11)
    assert d.shape_at(date(2026, 9, 12)).name == "tiers"
    assert d.shape_at(date(2026, 9, 14)).name == "other"
    assert d.shape_at(date(2026, 9, 1)) is None and d.legacy(date(2026, 9, 1))
    assert d.line == date(2026, 9, 14)
    assert d.legacy(date(2026, 9, 11))            # under tiers, a layout that is gone
    assert not d.legacy(date(2026, 9, 14)) and not d.legacy(None)
    assert d.shape_at(None).name == "other" and d.current.name == "other"
    assert not d.polices_data


def test_only_tiers_is_policed_and_old_shape_names_are_refused(tmp_path):
    write_decl(tmp_path, DECL + '[[shape]]\nname = "tiers"\nsince = "2026-09-11"\n')
    assert declaration.load(tmp_path).polices_data
    write_decl(tmp_path, DECL)                                   # declared, no shape: tiers
    assert declaration.load(tmp_path).polices_data
    for old in ("lake", "catalog"):
        write_decl(tmp_path, DECL + f'[[shape]]\nname = "{old}"\nsince = "2026-09-14"\n')
        with pytest.raises(declaration.DeclarationError, match="needs `name`"):
            declaration.load(tmp_path)


def test_pyproject_tool_maestro_is_the_alias(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[tool.maestro]\ntracker = "none"\nlayers = ["discipline"]\n'
        '[[tool.maestro.shape]]\nname = "tiers"\nsince = "2026-01-01"\n')
    d = declaration.load(tmp_path)
    assert d.source.name == "pyproject.toml" and not d.research
    assert d.shapes[0].since == date(2026, 1, 1)
    # maestro.toml wins when both are there
    write_decl(tmp_path)
    assert declaration.load(tmp_path).source.name == "maestro.toml"


def test_no_shapes_means_no_history_line(tmp_path):
    write_decl(tmp_path)
    d = declaration.load(tmp_path)
    assert d.shapes == () and d.first_line is None and d.shape_at(date(2020, 1, 1)) is None
    assert not d.legacy(date(2020, 1, 1))


@pytest.mark.parametrize("text, fragment", [
    ('layers = ["ml"]\n', "layers must be"),
    ('layers = ["research"]\n', "discipline layer is not optional"),
    ('layers = []\n', "layers must be"),
    ('[[shape]]\nname = "cloud"\nsince = "2026-01-01"\n', "needs `name`"),
    ('[[shape]]\nname = "tiers"\nsince = "yesterday"\n', "not a YYYY-MM-DD"),
    ('[[shape]]\nname = "tiers"\nsince = "2026-02-01"\n[[shape]]\nname = "other"\nsince = "2026-01-01"\n',
     "not after the previous"),
    ('layers = [\n', "cannot parse"),
])
def test_a_declaration_that_cannot_be_acted_on_raises(tmp_path, text, fragment):
    write_decl(tmp_path, text)
    with pytest.raises(declaration.DeclarationError, match=fragment):
        declaration.load(tmp_path)


def test_record_date_reads_whichever_key_the_kind_carries():
    assert declaration.record_date({"date": "2026-09-01"}) == date(2026, 9, 1)
    assert declaration.record_date({"opened": date(2026, 9, 2)}) == date(2026, 9, 2)
    assert declaration.record_date({"retrieved": "2026-09-03"}) == date(2026, 9, 3)
    assert declaration.record_date({"date": "not a date"}) is None
    assert declaration.record_date({}) is None


def test_render_round_trips_and_append_only_goes_forward(tmp_path):
    write_decl(tmp_path, declaration.render(("discipline",), "tiers", date(2026, 9, 1)))
    d = declaration.load(tmp_path)
    assert d.layers == ("discipline",) and d.shapes[0] == declaration.Shape("tiers", date(2026, 9, 1))
    path = tmp_path / "maestro.toml"
    declaration.append_shape(path, "other", date(2026, 9, 14))
    assert [s.name for s in declaration.load(tmp_path).shapes] == ["tiers", "other"]
    with pytest.raises(declaration.DeclarationError, match="not after"):
        declaration.append_shape(path, "tiers", date(2026, 9, 14))
    with pytest.raises(declaration.DeclarationError, match="one of"):
        declaration.append_shape(path, "cloud", date(2027, 1, 1))


def test_table_reference_form():
    ok = declaration.TABLE_REF.match
    assert ok("table:gold.daily_bars@42") and ok("table:silver.bars_1m")
    assert not ok("table:daily_bars") and not ok("table:gold.daily bars@1") and not ok("gold.x@1")


# ── the checker ──────────────────────────────────────────────────────────────

@pytest.fixture
def project(tmp_path, monkeypatch):
    for sub in ("docs/experiments", "docs/adrs", "docs/epics", "docs/data",
                "data/raw", "data/experiments"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text("# Project\n")
    (tmp_path / "docs" / "progress.md").write_text("# Progress\n")
    (tmp_path / "docs" / "findings.md").write_text("# Findings\n")
    paths = {"ROOT": tmp_path, "EXP_DIR": tmp_path / "docs" / "experiments",
             "ADR_DIR": tmp_path / "docs" / "adrs", "EPIC_DIR": tmp_path / "docs" / "epics",
             "DOCS_DIR": tmp_path / "docs", "DATA_DIR": tmp_path / "docs" / "data",
             "RAW_DIR": tmp_path / "data" / "raw", "EXPDATA_DIR": tmp_path / "data" / "experiments"}
    for mod, names in ((checks, tuple(paths)), (indexes, ("ROOT", "EXP_DIR", "ADR_DIR", "EPIC_DIR", "DATA_DIR"))):
        for name in names:
            monkeypatch.setattr(mod, name, paths[name])
    monkeypatch.setattr(checks, "touched_paths", lambda root, hours=None: set())
    return tmp_path


def exp_record(project, n=1, **fields):
    fm = {"exp": n, "title": f"e{n}", "status": "done", "outcome": "confirmed",
          "takeaway": "it worked", "source_artifacts": [], "date": "2026-09-15", **fields}
    lines = "\n".join(f"{k}: {v!r}" if isinstance(v, str) else f"{k}: {v}" for k, v in fm.items())
    p = project / "docs" / "experiments" / f"exp_{n:02d}_e{n}.md"
    p.write_text(f"---\n{lines}\n---\n\n# Exp {n}\n")
    return p


def run_dir(project, n=1, k=1, slug=None, files=("run.log", "metrics.json")):
    d = project / "data" / "experiments" / f"exp_{n:02d}_{slug or f'e{n}'}" / f"run_{k}"
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_text("x\n")
    return d


def report(capsys):
    out = capsys.readouterr()
    return out.out + out.err


def test_undeclared_is_checked_as_before_with_one_advisory(project, capsys):
    assert checks.check() == 0
    text = report(capsys)
    assert "membership is inferred" in text and "OK (" in text


def test_an_unreadable_declaration_blocks(project, capsys):
    write_decl(project, 'layers = ["ml"]\n')
    assert checks.check() == 2
    assert "layers must be" in report(capsys)


def test_a_record_before_the_first_shape_is_history(project, capsys):
    write_decl(project, DECL + '[[shape]]\nname = "tiers"\nsince = "2026-09-14"\n')
    exp_record(project, 1, date="2026-09-10", consumes=["data/raw/gone/v1"],
               source_artifacts=["data/raw/gone/v1/manifest.json"])
    run_dir(project, 1, files=())                      # empty run dir, no run.log either
    exp_record(project, 2, date="2026-09-15", consumes=["data/raw/also_gone/v1"])
    assert checks.check(verbose=True) == 2
    text = report(capsys)
    assert "exp_1" not in text.replace("1 record(s)", "")   # nothing about the legacy record
    assert "exp_2: consumes 'data/raw/also_gone/v1'" in text
    assert "1 record(s) dated before the current shape's line (tiers since 2026-09-14) are history" in text


def test_under_other_the_checker_does_not_judge_data_citations(project, capsys):
    write_decl(project, DECL + '[[shape]]\nname = "tiers"\nsince = "2026-09-01"\n'
                               '[[shape]]\nname = "other"\nsince = "2026-09-14"\n')
    exp_record(project, 1, date="2026-09-11", consumes=["data/raw/migrated_away/v1"])
    exp_record(project, 2, date="2026-09-15", consumes=["data/lake/gold/gone.parquet", "table:daily_bars"],
               source_artifacts=["table:gold.daily_bars@12", "docs/kb/missing.md"])
    assert checks.check(verbose=True) == 2
    text = report(capsys)
    assert "migrated_away" not in text and "gone.parquet" not in text and "table:daily_bars" not in text
    assert "exp_2: source_artifacts 'docs/kb/missing.md' does not exist" in text   # not a data path
    assert "1 record(s) dated before the current shape's line (other since 2026-09-14)" in text


def test_a_table_reference_is_evidence_under_tiers_and_a_malformed_one_is_not(project, capsys):
    write_decl(project, DECL + '[[shape]]\nname = "tiers"\nsince = "2026-09-01"\n')
    exp_record(project, 1, consumes=["table:silver.bars_1d@12"],
               source_artifacts=["table:gold.daily_bars@12"])
    exp_record(project, 2, consumes=["table:daily_bars"])
    assert checks.check() == 2
    text = report(capsys)
    assert "exp_1" not in text
    assert "exp_2: consumes 'table:daily_bars' but file is missing" in text


def test_an_infra_run_needs_no_metrics_and_a_confirmed_one_does(project, capsys):
    write_decl(project)
    exp_record(project, 1, outcome="infra")
    run_dir(project, 1, files=("run.log",))
    exp_record(project, 2)
    run_dir(project, 2, files=("run.log",))
    checks.check()
    text = report(capsys)
    assert "exp_01_e1/run_1/ has no non-empty metrics.json" not in text
    assert "exp_02_e2/run_1/ has no non-empty metrics.json" in text


def test_under_other_no_dataset_sha_is_checked(project, capsys):
    write_decl(project, DECL + '[[shape]]\nname = "other"\nsince = "2026-09-01"\n')
    (project / "docs" / "data" / "bars.md").write_text(
        "---\ndataset: bars\nversion: ''\npath: lake/bronze/massive/bars\nretrieved: '2026-09-15'\n"
        "status: complete\nsha256: deadbeef\n---\n# bars\n")
    (project / "data" / "lake" / "bronze" / "massive" / "bars").mkdir(parents=True)
    (project / "data" / "lake" / "bronze" / "massive" / "bars" / "a.parquet").write_bytes(b"1")
    assert checks.check(verbose=True) == 0
    text = report(capsys)
    assert "sha drift" not in text
    assert "1 dataset record(s) not sha-checked: the declared shape is `other`" in text


def test_under_other_a_raw_dir_without_a_record_is_the_projects_business(project, capsys):
    write_decl(project, DECL + '[[shape]]\nname = "other"\nsince = "2026-09-01"\n')
    (project / "data" / "raw" / "nyse").mkdir()
    assert checks.check() == 0
    assert "has no dataset record" not in report(capsys)


def test_an_epic_log_is_not_a_claim(tmp_path):
    (tmp_path / "docs" / "epics").mkdir(parents=True)
    (tmp_path / "docs" / "epics" / "epic_01_x.md").write_text(
        "# Epic 1 — x\n\n## Goal\n\nthe loader is ported\n\n## Log\n\n"
        "- 2026-09-16 — item 6 re-titled — was: ported from build\n")
    found = [msg for _, msg in checks.adr9_findings(tmp_path, {})]
    assert any("epic_01_x.md:5: status word 'ported'" in m for m in found)   # the Goal line
    assert not any("epic_01_x.md:9" in m for m in found)                     # the Log line


def test_without_the_research_layer_the_data_tier_checks_are_off(project, capsys):
    write_decl(project, 'layers = ["discipline"]\n')
    (project / "data" / "raw" / "unrecorded").mkdir()
    (project / "data" / "experiments" / "exp_07_orphan" / "run_1").mkdir(parents=True)
    (project / "data" / "experiments" / "exp_07_orphan" / "run_1" / "run.log").write_text("ran\n")
    (project / "src").mkdir()
    (project / "src" / "lib.py").write_text("import scripts.tool\n")   # a tier violation
    assert checks.check() == 0
    text = report(capsys)
    assert "has no dataset record" not in text and "exp_07" not in text and "src/" not in text
    write_decl(project)                                                  # research on
    assert checks.check() == 2
    assert "has no dataset record" in report(capsys)


# ── membership for the hooks ─────────────────────────────────────────────────

def test_a_declaration_alone_makes_a_maestro_project(tmp_path):
    assert not guards.is_maestro_project(tmp_path)
    write_decl(tmp_path)
    assert guards.is_maestro_project(tmp_path)


def test_the_records_dir_inference_survives_this_release(tmp_path):
    (tmp_path / "docs" / "adrs").mkdir(parents=True)
    assert guards.is_maestro_project(tmp_path)


# ── init and the shape verbs ─────────────────────────────────────────────────

@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "maestro"
    (repo / "templates").mkdir(parents=True)
    (repo / "global" / "hooks").mkdir(parents=True)
    for name in ("CLAUDE.md", "progress.md", "findings.md", "setup.md", "data.md", "pre-commit"):
        (repo / "templates" / name).write_text(f"# {name}\n")
    (repo / "core.md").write_text("# core\n")
    return repo


def test_init_writes_the_declaration_once(tmp_path, checkout):
    project = tmp_path / "p"
    project.mkdir()
    init_mod.init_project(path=project, repo=checkout, shape="other", layers=["discipline"])
    d = declaration.load(project)
    assert d.layers == ("discipline",) and d.shapes[0].name == "other"
    assert d.shapes[0].since == date.today()
    plan = init_mod.init_project(path=project, repo=checkout, shape="tiers")
    assert declaration.load(project).shapes[0].name == "other"         # never rewritten
    assert any("maestro.toml exists" in line for _, line in plan.lines)


def test_init_refuses_a_layer_or_shape_it_does_not_know(tmp_path, checkout):
    project = tmp_path / "p"
    project.mkdir()
    with pytest.raises(init_mod.InitError, match="--layers"):
        init_mod.init_project(path=project, repo=checkout, layers=["research"])
    with pytest.raises(init_mod.InitError, match="--shape"):
        init_mod.init_project(path=project, repo=checkout, shape="cloud")


def test_shape_add_and_show_through_the_cli(tmp_path, monkeypatch, capsys):
    from maestro_cli import frontmatter
    monkeypatch.setattr(frontmatter, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="no maestro.toml"):
        cli_main(["shape", "add", "--name=other", "--since=2026-09-14"])
    write_decl(tmp_path, declaration.render(("discipline", "research"), "tiers", date(2026, 9, 1)))
    cli_main(["shape", "add", "--name=other", "--since=2026-09-14"])
    assert "Appended shape other since 2026-09-14" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="not after"):
        cli_main(["shape", "add", "--name=tiers", "--since=2026-09-10"])
    cli_main(["shape", "show"])
    out = capsys.readouterr().out
    assert "tiers since 2026-09-01, other since 2026-09-14" in out


def test_init_cli_passes_layers_and_shape(tmp_path, checkout, monkeypatch):
    project = tmp_path / "p"
    project.mkdir()
    monkeypatch.chdir(project)
    cli_main(["init", f"--repo={checkout}", "--layers=discipline,research", "--shape=other"])
    assert declaration.load(project).shapes[0].name == "other"
    with pytest.raises(SystemExit, match="project-mode flag"):
        cli_main(["init", "--harness", f"--repo={checkout}", "--shape=other"])


# ── kb_raw: where the kb's downloaded sources live ───────────────────────────

def test_kb_raw_defaults_to_the_old_path(tmp_path):
    write_decl(tmp_path)
    assert declaration.load(tmp_path).kb_raw == declaration.DEFAULT_KB_RAW
    assert declaration.kb_raw_dir(tmp_path) == tmp_path / "docs/kb/literature/raw"
    assert declaration.kb_raw_dir(tmp_path / "undeclared") == tmp_path / "undeclared/docs/kb/literature/raw"


def test_kb_raw_is_relative_to_the_root_or_absolute(tmp_path):
    write_decl(tmp_path, DECL + 'kb_raw = "data/raw/kb/literature/raw"\n')
    assert declaration.kb_raw_dir(tmp_path) == tmp_path / "data/raw/kb/literature/raw"
    write_decl(tmp_path, DECL + 'kb_raw = "/srv/kb/raw"\n')
    assert declaration.kb_raw_dir(tmp_path) == Path("/srv/kb/raw")


def test_kb_raw_expands_variables_and_defaults(tmp_path):
    write_decl(tmp_path, DECL + 'kb_raw = "${DATA_X:-data}/raw/kb"\n')
    assert declaration.kb_raw_dir(tmp_path, env={}) == tmp_path / "data/raw/kb"
    assert declaration.kb_raw_dir(tmp_path, env={"DATA_X": "/mnt/d"}) == Path("/mnt/d/raw/kb")
    write_decl(tmp_path, DECL + 'kb_raw = "$DATA_X/raw/kb"\n')
    with pytest.raises(declaration.DeclarationError, match="DATA_X"):
        declaration.kb_raw_dir(tmp_path, env={})


def test_kb_raw_must_be_a_path_string(tmp_path):
    write_decl(tmp_path, DECL + 'kb_raw = ""\n')
    with pytest.raises(declaration.DeclarationError, match="kb_raw"):
        declaration.load(tmp_path)
