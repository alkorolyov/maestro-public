"""Evidence has to be something git can still follow, and a result has to cite something.

Two halves of the same rule-2 failure:

  * an executor committed, was asked to reword, and the FIRST commit was stranded. Its
    sha was still quoted as proof. `git branch --contains` finds nothing, and the next
    `git gc` deletes it — evidence in form only. `epic item --status=done` now refuses it.
  * the epic closed on "full GATE green ... 2313 passed / 1 skipped" with no path, no sha
    and no marker anywhere in the clause. A3 reads prose and skips frontmatter, so the
    one place an epic states its results was the one place nothing looked. That is A5.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import checks, epics, indexes  # noqa: E402
from maestro_cli.cli import main  # noqa: E402


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=check).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A throwaway project that is also a real git repo, with one commit on main."""
    epic_dir = tmp_path / "docs" / "epics"
    epic_dir.mkdir(parents=True)
    monkeypatch.setattr(epics, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(epics, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "EPIC_DIR", epic_dir)

    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "seed.txt").write_text("seed\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def orphan_sha(root):
    """A real commit that no branch or tag contains — the shape that actually happens."""
    git(root, "switch", "-q", "-c", "tmp")
    (root / "stranded.txt").write_text("x\n")
    # `add -A` would sweep the untracked epic record onto this branch, and deleting the
    # branch would then take the record with it — stage only the file this commit is for.
    git(root, "add", "stranded.txt")
    git(root, "commit", "-q", "-m", "stranded")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-q", "main")
    git(root, "branch", "-q", "-D", "tmp")
    return sha


def open_epic_with_item(title="a thing — 3 files — Done: pytest -q"):
    main(["epic", "new", "--slug=t", "--title=T"])
    main(["epic", "update", "--id=1", "--status=active"])
    main(["epic", "item", "--id=1", f"--add={title}"])
    main(["epic", "item", "--id=1", "--item=1", "--status=in_progress"])


def refusal(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None), "a refused command must exit non-zero"
    return str(e.value.code)


# ── the write-time guard ──────────────────────────────────────────────────────

def test_a_reachable_sha_is_accepted(repo):
    open_epic_with_item()
    head = git(repo, "rev-parse", "HEAD")
    main(["epic", "item", "--id=1", "--item=1", "--status=done", f"--evidence={head}"])
    fm = yaml.safe_load(next(repo.glob("docs/epics/epic_01_*.md")).read_text().split("---\n")[1])
    assert fm["items"][0]["evidence"] == head


def test_an_orphaned_sha_is_refused_and_named(repo):
    open_epic_with_item()
    sha = orphan_sha(repo)
    msg = refusal(["epic", "item", "--id=1", "--item=1", "--status=done", f"--evidence={sha}"])
    assert sha in msg and "orphan" in msg
    # and the refusal LEFT the row alone — a refused write must not half-apply
    fm = yaml.safe_load(next(repo.glob("docs/epics/epic_01_*.md")).read_text().split("---\n")[1])
    assert fm["items"][0]["status"] == "in_progress"
    assert "evidence" not in fm["items"][0]


def test_a_sha_that_resolves_to_nothing_is_refused(repo):
    open_epic_with_item()
    msg = refusal(["epic", "item", "--id=1", "--item=1", "--status=done",
                   "--evidence=deadb33f"])
    assert "deadb33f" in msg and "no commit" in msg


def test_evidence_that_is_not_a_sha_is_left_alone(repo):
    """Evidence may be a test or an artifact path — only sha-shaped tokens are resolved."""
    open_epic_with_item()
    main(["epic", "item", "--id=1", "--item=1", "--status=done",
          "--evidence=tests/test_thing.py::test_case, docs/archive/beefed01.md"])
    fm = yaml.safe_load(next(repo.glob("docs/epics/epic_01_*.md")).read_text().split("---\n")[1])
    assert fm["items"][0]["status"] == "done"


def test_no_git_means_no_opinion(tmp_path, monkeypatch):
    """A guard that fires on a broken toolchain teaches people to bypass it."""
    epic_dir = tmp_path / "docs" / "epics"
    epic_dir.mkdir(parents=True)
    monkeypatch.setattr(epics, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(epics, "ROOT", tmp_path)
    monkeypatch.setattr(indexes, "EPIC_DIR", epic_dir)
    open_epic_with_item()
    main(["epic", "item", "--id=1", "--item=1", "--status=done", "--evidence=deadb33f"])
    fm = yaml.safe_load(next(tmp_path.glob("docs/epics/epic_01_*.md")).read_text().split("---\n")[1])
    assert fm["items"][0]["evidence"] == "deadb33f"


# ── the sweep over what was recorded before the guard ─────────────────────────

def test_sweep_reports_a_rotted_sha_as_advisory(repo):
    open_epic_with_item()
    sha = orphan_sha(repo)
    path = next(repo.glob("docs/epics/epic_01_*.md"))
    head, fm_text, body = path.read_text().split("---\n", 2)
    fm = yaml.safe_load(fm_text)
    fm["items"][0].update(status="done", evidence=sha)      # as a pre-guard record has it
    path.write_text("---\n" + yaml.dump(fm, sort_keys=False) + "---\n" + body)

    notes = checks.evidence_sha_notes(repo, {1: (path, fm)})
    assert len(notes) == 1 and sha in notes[0] and "orphan" in notes[0]


def test_sweep_is_quiet_on_a_reachable_sha(repo):
    open_epic_with_item()
    path = next(repo.glob("docs/epics/epic_01_*.md"))
    fm = yaml.safe_load(path.read_text().split("---\n")[1])
    fm["items"][0].update(status="done", evidence=git(repo, "rev-parse", "HEAD"))
    assert checks.evidence_sha_notes(repo, {1: (path, fm)}) == []


# ── A5: an epic's own results cite something ──────────────────────────────────

def a5_messages(root, fm, path=None):
    path = path or (root / "docs" / "epics" / "epic_01_t.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return [m for _, m in checks.adr9_findings(root, {}, epic_records={1: (path, fm)})
            if "cites no artifact" in m]


def test_a_done_when_result_with_no_artifact_is_flagged(tmp_path):
    (tmp_path / "docs").mkdir()
    fm = {"done_when": [{"id": 1, "text": "the suite stays green",
                         "result": "2313 passed, 1 skipped on every merge"}]}
    out = a5_messages(tmp_path, fm)
    assert len(out) == 1 and "done_when 1" in out[0]


def test_a_result_that_names_a_path_or_a_sha_or_a_marker_passes(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "data").mkdir()
    for answer in ("2313 passed — data/experiments/exp_01_x/run_1/metrics.json",
                   "2313 passed at 4779311c",
                   "2313 passed. verified: 2026-09-04"):
        fm = {"done_when": [{"id": 1, "text": "t", "result": answer}]}
        assert a5_messages(tmp_path, fm) == [], answer


def test_an_unanswered_clause_is_not_an_a5(tmp_path):
    """A5 judges an ANSWER. An empty result is `close`'s business, not evidence debt."""
    (tmp_path / "docs").mkdir()
    fm = {"done_when": [{"id": 1, "text": "t", "result": None}]}
    assert a5_messages(tmp_path, fm) == []


def test_an_outcome_with_no_artifact_is_flagged(tmp_path):
    (tmp_path / "docs").mkdir()
    fm = {"outcome": "the crate is rules-only now and the split is complete"}
    out = a5_messages(tmp_path, fm)
    assert len(out) == 1 and "outcome" in out[0]
    # the remedy must not tell anyone to rewrite a closed record
    assert "done-when" not in out[0]


def test_a_closed_epic_is_history_not_debt(tmp_path):
    """A closed epic's answers are dated, and `outcome` has no CLI path to correct."""
    (tmp_path / "docs" / "epics").mkdir(parents=True)
    path = tmp_path / "docs" / "epics" / "epic_01_t.md"
    path.touch()
    fm = {"status": "done", "outcome": "the split is complete",
          "done_when": [{"id": 1, "text": "t", "result": "2313 passed"}], "items": []}
    assert a5_messages(tmp_path, fm, path) == []            # not staged to blocking
    notes = checks.evidence_sha_notes(tmp_path, {1: (path, fm)})
    assert len(notes) == 2 and all("CLOSED" in n for n in notes)
