"""The live-ADR model (core rule 13): `maestro adr amend`, and what `docs check` expects.

One live ADR per decision area, amended in place. `adr amend` rewrites the frontmatter
decision and appends a dated entry to the body's single final `History:` line, naming the
git sha that still holds the prior text. A folded ADR moves to docs/archive/adrs/.

The checker accepts both models: a live record that another ADR says it folds in is an
advisory (4b) whose remedy is the archive, and a legacy `superseded_by` may point at an
archived number.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from maestro_cli import adrs, indexes  # noqa: E402
from maestro_cli.cli import main  # noqa: E402

TODAY = str(date.today())


@pytest.fixture
def project(tmp_path, monkeypatch):
    adr_dir = tmp_path / "docs" / "adrs"
    adr_dir.mkdir(parents=True)
    monkeypatch.setattr(adrs, "ADR_DIR", adr_dir)
    monkeypatch.setattr(adrs, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "ADR_DIR", adr_dir)
    main(["adr", "new", "--slug=data_layer"])
    main(["adr", "update", "--id=1", "--status=accepted", "--decision=raw then processed"])
    return adr_dir


def _record(adr_dir):
    return next(adr_dir.glob("adr_01_*.md"))


def _fm(adr_dir):
    return yaml.safe_load(_record(adr_dir).read_text().split("---\n")[1])


def _body(adr_dir):
    return _record(adr_dir).read_text().split("---\n", 2)[2]


def refusal(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None)
    return str(e.value)


def test_amend_rewrites_the_decision_and_starts_the_history_line(project):
    main(["adr", "amend", "--id=1", "--decision=raw, processed, no lake", "--note=lake deleted"])
    assert _fm(project)["decision"] == "raw, processed, no lake"
    body = _body(project)
    assert body.rstrip().endswith(f"History: amended {TODAY}: lake deleted.")
    assert body.count("History:") == 1


def test_amend_appends_to_the_existing_history_line(project):
    p = _record(project)
    p.write_text(p.read_text().rstrip("\n")
                 + "\n\nHistory: folds in ADR 3, 12; prior text in git\ne01864f.\n")
    main(["adr", "amend", "--id=1", "--decision=d2", "--note=partitions by month"])
    body = _body(project)
    assert body.count("History:") == 1
    assert body.rstrip().endswith(
        f"prior text in git\ne01864f; amended {TODAY}: partitions by month.")


def test_amend_keeps_the_stamp_valid(project):
    main(["adr", "amend", "--id=1", "--decision=d2", "--note=n"])
    from maestro_cli import frontmatter
    assert frontmatter.stamp_status(_record(project)) == "ok"


def test_amend_names_the_commit_holding_the_prior_text(project, tmp_path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x"}
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "adr"]):
        subprocess.run(["git", "-C", str(tmp_path), *cmd], check=True, capture_output=True, env=env)
    sha = subprocess.run(["git", "-C", str(tmp_path), "log", "-1", "--format=%h"],
                         capture_output=True, text=True, check=True).stdout.strip()
    main(["adr", "amend", "--id=1", "--decision=d2", "--note=n"])
    assert f"amended {TODAY}: n (prior text in git {sha})." in _body(project)


@pytest.mark.parametrize("argv, words", [
    (["adr", "amend", "--id=9", "--decision=d", "--note=n"], "not found"),
    (["adr", "amend", "--id=1", "--decision= ", "--note=n"], "--decision is empty"),
    (["adr", "amend", "--id=1", "--decision=" + "x" * 301, "--note=n"], "ONE-LINE"),
    (["adr", "amend", "--id=1", "--decision=d", "--note= "], "--note is empty"),
])
def test_amend_refuses(project, argv, words):
    assert words in refusal(argv)


def test_amend_refuses_a_superseded_record(project):
    main(["adr", "new", "--slug=other"])
    main(["adr", "update", "--id=1", "--status=superseded", "--superseded-by=2"])
    assert "adr_2" in refusal(["adr", "amend", "--id=1", "--decision=d", "--note=n"])


def test_amend_refuses_an_archived_number(project):
    archive = project.parent / "archive" / "adrs"
    archive.mkdir(parents=True)
    _record(project).rename(archive / _record(project).name)
    assert "archived" in refusal(["adr", "amend", "--id=1", "--decision=d", "--note=n"])


# ── docs check under the live-ADR model ─────────────────────────────────────

def _cli(cwd: Path, *args):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "tools"), "MAESTRO_ROOT": str(cwd)}
    return subprocess.run([sys.executable, "-m", "maestro_cli.cli", *args], cwd=str(cwd),
                          capture_output=True, text=True, env=env, timeout=60)


@pytest.fixture
def two_adrs(tmp_path):
    (tmp_path / "docs").mkdir()
    for slug in ("folded_area", "live_area"):
        assert _cli(tmp_path, "adr", "new", f"--slug={slug}").returncode == 0
    live = next((tmp_path / "docs" / "adrs").glob("adr_02_*.md"))
    live.write_text(live.read_text() + "\nHistory: folds in ADR 1; prior text in git abc1234.\n")
    return tmp_path


def test_a_live_record_another_adr_folds_in_is_flagged(two_adrs):
    out = _cli(two_adrs, "docs", "check")
    assert out.returncode == 0
    assert "adr_1 is still live" in out.stdout and "docs/archive/adrs/" in out.stdout


def test_an_archived_folded_record_is_not_flagged(two_adrs):
    adr_dir = two_adrs / "docs" / "adrs"
    archive = two_adrs / "docs" / "archive" / "adrs"
    archive.mkdir(parents=True)
    old = next(adr_dir.glob("adr_01_*.md"))
    old.rename(archive / old.name)
    assert _cli(two_adrs, "index", "render", "--kind=all").returncode == 0
    out = _cli(two_adrs, "docs", "check")
    assert out.returncode == 0, out.stderr
    assert "adr_1 is still live" not in out.stdout


def test_a_legacy_superseded_by_may_name_an_archived_number(two_adrs):
    adr_dir = two_adrs / "docs" / "adrs"
    assert _cli(two_adrs, "adr", "new", "--slug=legacy").returncode == 0
    assert _cli(two_adrs, "adr", "update", "--id=3", "--status=superseded",
                "--superseded-by=1").returncode == 0
    archive = two_adrs / "docs" / "archive" / "adrs"
    archive.mkdir(parents=True)
    old = next(adr_dir.glob("adr_01_*.md"))
    old.rename(archive / old.name)
    assert _cli(two_adrs, "index", "render", "--kind=all").returncode == 0
    out = _cli(two_adrs, "docs", "check")
    assert out.returncode == 0, out.stderr
    assert "superseded_by=1 does not exist" not in out.stderr + out.stdout
