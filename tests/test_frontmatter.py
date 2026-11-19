"""Tests for the shared record I/O — `frontmatter.py`, and the layout printer over it.

Every record kind reads and writes through this module, so a change here moves all of
them at once. What is pinned:

  * `load` returns only well-formed records of the kind asked for, and silently skips
    the rest — an unparseable file must not take a whole command down;
  * `next_num` follows the highest number on disk, so deleting a record never hands
    its number to the next one;
  * `write` round-trips, in the field order it was given (frontmatter is read by people
    too, and yaml's default is alphabetical);
  * `slugify` reduces a title to something safe to put in a path;
  * ROOT resolution: the env override wins, then the nearest project ancestor of the
    CALLER's directory — a machine-level CLI must resolve the caller's project,
    never its own checkout;
  * `maestro info show` prints the layout from those constants rather than repeating it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import frontmatter as fm  # noqa: E402
from maestro_cli import info  # noqa: E402


def seed(d, name, text):
    (d / name).write_text(text)


# ── load ─────────────────────────────────────────────────────────────────────

def test_load_keys_records_by_their_number(tmp_path):
    seed(tmp_path, "exp_01_a.md", "---\nexp: 1\ntitle: a\n---\nbody\n")
    seed(tmp_path, "exp_02_b.md", "---\nexp: 2\ntitle: b\n---\nbody\n")
    records = fm.load(tmp_path, "exp")
    assert sorted(records) == [1, 2]
    path, meta = records[2]
    assert path.name == "exp_02_b.md" and meta["title"] == "b"


def test_a_file_without_frontmatter_is_skipped_not_fatal(tmp_path):
    seed(tmp_path, "exp_01_a.md", "---\nexp: 1\n---\n")
    seed(tmp_path, "exp_02_notes.md", "# just prose, no frontmatter\n")
    assert list(fm.load(tmp_path, "exp")) == [1]


def test_a_record_missing_its_kind_key_is_skipped(tmp_path):
    """`exp: N` is what makes a file an experiment record; without it there is no key."""
    seed(tmp_path, "exp_01_a.md", "---\ntitle: orphan\n---\n")
    assert fm.load(tmp_path, "exp") == {}


def test_load_of_a_missing_directory_is_empty_not_an_error(tmp_path):
    assert fm.load(tmp_path / "nope", "exp") == {}


def test_load_ignores_other_kinds_in_the_same_directory(tmp_path):
    seed(tmp_path, "exp_01_a.md", "---\nexp: 1\n---\n")
    seed(tmp_path, "adr_01_a.md", "---\nadr: 1\n---\n")
    assert list(fm.load(tmp_path, "adr")) == [1]


# ── next_num ─────────────────────────────────────────────────────────────────

def test_next_num_starts_at_one(tmp_path):
    assert fm.next_num({}) == 1


def test_next_num_follows_the_highest_not_the_count(tmp_path):
    """A deleted record's number is never reissued — records are cited by number."""
    assert fm.next_num({1: None, 7: None}) == 8


# ── write ────────────────────────────────────────────────────────────────────

def test_write_round_trips_through_load(tmp_path):
    path = tmp_path / "exp_01_a.md"
    fm.write(path, {"exp": 1, "title": "a", "tags": ["x", "y"]}, "\n# body\n")
    _, meta = fm.load(tmp_path, "exp")[1]
    meta.pop("sig")                       # the CLI's stamp rides along as the last key
    assert meta == {"exp": 1, "title": "a", "tags": ["x", "y"]}
    assert path.read_text().endswith("\n# body\n")


def test_field_order_is_preserved_for_the_human_reading_it(tmp_path):
    path = tmp_path / "exp_01_a.md"
    fm.write(path, {"exp": 1, "title": "a", "status": "done", "date": "2026-08-29"})
    block = path.read_text().split("---\n")[1]
    assert [ln.split(":")[0] for ln in block.strip().splitlines()] == \
        ["exp", "title", "status", "date", "sig"]      # the stamp is always last


def test_a_multiline_value_survives_the_round_trip(tmp_path):
    """Takeaways are prose and routinely wrap — yaml must give back what it was given."""
    path = tmp_path / "exp_01_a.md"
    long = "a takeaway that runs on, with a colon: and a — dash, over one line"
    fm.write(path, {"exp": 1, "takeaway": long})
    assert yaml.safe_load(path.read_text().split("---\n")[1])["takeaway"] == long


# ── slugify ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Depth Sweep", "depth_sweep"),
    ("batch-size sweep", "batch_size_sweep"),
    ("nested/dir", "nested_dir"),
    ("../escape", "escape"),
    ("__trailing__", "trailing"),
    ("v2.1 rerun", "v2_1_rerun"),
    ("///", ""),
])
def test_slugify(raw, expected):
    assert fm.slugify(raw) == expected


# ── rel ──────────────────────────────────────────────────────────────────────

def test_rel_is_relative_inside_the_project_and_absolute_outside(monkeypatch, tmp_path):
    monkeypatch.setattr(fm, "ROOT", tmp_path)
    assert fm.rel(tmp_path / "docs" / "experiments") == "docs/experiments"
    assert fm.rel(Path("/etc/hosts")) == "/etc/hosts"


# ── ROOT resolution (ADR 10: the caller's project, not the CLI's checkout) ────

def test_the_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("MAESTRO_ROOT", str(tmp_path))
    assert fm._find_root() == tmp_path.resolve()


def test_the_nearest_project_ancestor_of_the_caller_wins(monkeypatch, tmp_path):
    monkeypatch.delenv("MAESTRO_ROOT", raising=False)
    project = tmp_path / "outer" / "project"
    (project / "docs").mkdir(parents=True)
    deep = project / "src" / "pkg"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert fm._find_root() == project.resolve()


def test_a_pyproject_marks_a_project_too(monkeypatch, tmp_path):
    monkeypatch.delenv("MAESTRO_ROOT", raising=False)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)
    assert fm._find_root() == tmp_path.resolve()


# ── info show: the layout is printed from the constants, not retyped ─────────

def test_info_prints_the_directories_the_cli_actually_writes_to(capsys):
    info.info()
    out = capsys.readouterr().out
    for d in (fm.EXP_DIR, fm.ADR_DIR, fm.DATA_DIR, fm.KB_LIT_DIR):
        assert fm.rel(d) in out
    assert str(fm.ROOT) in out


def test_info_names_the_cli_as_the_only_way_to_write_a_record(capsys):
    info.info()
    out = capsys.readouterr().out
    assert "maestro exp new" in out and "never hand-author" in out.lower()


# ── next_num and the archive ─────────────────────────────────────────────────

def test_next_num_counts_the_archive_only_when_asked(tmp_path):
    live = tmp_path / "docs" / "adrs"
    arch = tmp_path / "docs" / "archive" / "adrs"
    live.mkdir(parents=True)
    arch.mkdir(parents=True)
    seed(live, "adr_02_a.md", "---\nadr: 2\n---\n")
    seed(arch, "adr_29_b.md", "---\nadr: 29\n---\n")
    records = fm.load(live, "adr")
    assert fm.next_num(records) == 3
    assert fm.next_num(records, live, "adr") == 30
    assert fm.next_num({}, live, "adr") == 30


def test_archived_records_are_not_record_files(tmp_path, monkeypatch):
    """The stamp check walks record_files(); the archive is history, not checked as live."""
    live = tmp_path / "docs" / "adrs"
    arch = tmp_path / "docs" / "archive" / "adrs"
    live.mkdir(parents=True)
    arch.mkdir(parents=True)
    seed(live, "adr_01_a.md", "---\nadr: 1\n---\n")
    seed(arch, "adr_02_b.md", "---\nadr: 2\n---\n")
    monkeypatch.setattr(fm, "ADR_DIR", live)
    assert [p.name for p in fm.record_files() if p.name.startswith("adr_")] == ["adr_01_a.md"]


# ── next_num across branches and worktrees ───────────────────────────────────

def _git(repo, *args):
    import subprocess
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(repo), "PATH": "/usr/bin:/bin"})


def test_next_num_steps_past_a_number_another_branch_and_worktree_hold(tmp_path):
    """Two parallel sessions each saw only their own docs/ and both allocated exp 159.
    A number committed on any local branch, or sitting uncommitted in another
    worktree, is taken."""
    repo = tmp_path / "repo"
    exps = repo / "docs" / "experiments"
    exps.mkdir(parents=True)
    seed(exps, "exp_01_a.md", "---\nexp: 1\n---\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "side")
    seed(exps, "exp_05_side.md", "---\nexp: 5\n---\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "side")
    _git(repo, "checkout", "-q", "main")
    other = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(other), "-b", "wt")
    seed(other / "docs" / "experiments", "exp_07_draft.md", "---\nexp: 7\n---\n")

    records = fm.load(exps, "exp")
    assert set(records) == {1}
    assert fm.next_num(records, exps, "exp") == 8


def test_next_num_outside_git_counts_only_the_tree(tmp_path):
    exps = tmp_path / "docs" / "experiments"
    exps.mkdir(parents=True)
    seed(exps, "exp_03_a.md", "---\nexp: 3\n---\n")
    assert fm.next_num(fm.load(exps, "exp"), exps, "exp") == 4
