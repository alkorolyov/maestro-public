"""Tests for `maestro exp delete` — removing an experiment record whose results are invalid.

Contracts: the number is tombstoned and never reallocated; epics stop listing the exp (with a
valid stamp); a finding or another record's lineage that still cites it blocks the delete;
`--purge` removes the script and run dirs, and without it they are left and named.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import epics, experiments, frontmatter, indexes  # noqa: E402
from maestro_cli.cli import main  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    exp_dir = tmp_path / "docs" / "experiments"
    epic_dir = tmp_path / "docs" / "epics"
    exp_dir.mkdir(parents=True)
    epic_dir.mkdir(parents=True)
    for mod in (experiments, epics):
        monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(experiments, "EXP_DIR", exp_dir)
    monkeypatch.setattr(experiments, "FINDINGS", tmp_path / "docs" / "findings.md")
    monkeypatch.setattr(epics, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(indexes, "EXP_DIR", exp_dir)
    monkeypatch.setattr(indexes, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(frontmatter, "ROOT", tmp_path)
    return tmp_path


def new_exp(slug):
    main(["exp", "new", f"--slug={slug}"])


def delete(n, *extra):
    main(["exp", "delete", f"--id={n}", "--reason=wrong labels", *extra])


def exp_files(root):
    return sorted(p.name for p in (root / "docs" / "experiments").glob("exp_*.md"))


def test_tombstoned_number_is_never_reallocated(project):
    new_exp("a")
    new_exp("b")
    delete(2, "--by=agent")
    tomb = (project / "docs" / "archive" / "experiments" / "deleted.md").read_text()
    assert "- exp 2 | b |" in tomb and "| agent | wrong labels" in tomb
    new_exp("c")
    assert exp_files(project) == ["exp_01_a.md", "exp_03_c.md"]


def test_index_no_longer_lists_deleted_exp(project):
    new_exp("a")
    new_exp("gone")
    delete(2)
    assert "gone" not in (project / "docs" / "experiments" / "INDEX.md").read_text()


def test_epic_unlink_keeps_stamp_valid(project):
    new_exp("a")
    new_exp("b")
    epic_dir = project / "docs" / "epics"
    frontmatter.write(epic_dir / "epic_01_x.md",
                      {"epic": 1, "title": "X", "status": "todo", "exps": [1, 2]},
                      "\n# Epic 1 — X\n\n## Log\n\n")
    delete(2)
    path = epic_dir / "epic_01_x.md"
    fm = frontmatter.load(epic_dir, "epic")[1][1]
    assert fm["exps"] == [1]
    assert "unlinked exp 2" in path.read_text()
    text = path.read_text()
    fm_text, body = text.split("---\n", 2)[1:]
    stamp_line = [ln for ln in fm_text.splitlines() if ln.startswith(frontmatter.STAMP_KEY + ":")][0]
    bare = fm_text.replace(stamp_line + "\n", "")
    assert stamp_line.split(": ")[1] == frontmatter.stamp_of(bare, body)


def test_refuses_when_findings_cite_it(project, capsys):
    new_exp("a")
    (project / "docs" / "findings.md").write_text("- **x**: it works — Exp 1\n")
    with pytest.raises(SystemExit) as e:
        delete(1)
    assert "docs/findings.md" in str(e.value)
    assert exp_files(project) == ["exp_01_a.md"]


def test_findings_citation_does_not_match_longer_number(project):
    new_exp("a")
    (project / "docs" / "findings.md").write_text("- **x**: it works — Exp 12\n")
    delete(1)
    assert exp_files(project) == []


def test_refuses_when_another_exp_has_it_as_parent(project):
    new_exp("a")
    new_exp("b")
    main(["exp", "update", "--id=2", "--parent=1"])
    with pytest.raises(SystemExit) as e:
        delete(1)
    assert "exp_02_b.md" in str(e.value)
    assert len(exp_files(project)) == 2


def test_purge_removes_script_and_run_dirs_else_keeps_them(project, capsys):
    new_exp("a")
    new_exp("b")
    for n, slug in ((1, "a"), (2, "b")):
        (project / "experiments").mkdir(exist_ok=True)
        (project / "experiments" / f"exp_{n:02d}_{slug}.py").write_text("")
        run = project / "data" / "experiments" / f"exp_{n:02d}_{slug}" / "run_1"
        run.mkdir(parents=True)
    delete(1)
    out = capsys.readouterr().out
    assert "Kept experiments/exp_01_a.py" in out
    assert "Kept data/experiments/exp_01_a" in out
    assert (project / "experiments" / "exp_01_a.py").exists()
    delete(2, "--purge")
    assert not (project / "experiments" / "exp_02_b.py").exists()
    assert not (project / "data" / "experiments" / "exp_02_b").exists()
    assert (project / "data" / "experiments" / "exp_01_a").exists()
