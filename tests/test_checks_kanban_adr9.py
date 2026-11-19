"""Tests for the seven new drift checks: K1-K3 (ADR 7) and A1-A4 (ADR 9).

The ADR 9 four are STAGED (ADR 9, step 2): a finding hard-fails only when its file was
touched since HEAD, so an existing backlog stays advisory and cannot turn the checker
into something people switch off. That gating is the part with teeth, so it is tested
against a real git repo as well as through the pure helper.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402
import yaml  # noqa: E402

from maestro_cli import checks  # noqa: E402


def write_record(path: Path, fm: dict, body: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False) + "---\n" + body)
    return path


def epic_fm(n=1, **over):
    # done_when defaults to one ANSWERED clause: K8 (closed with an unanswered clause)
    # and K9 (no clause at all) are both silent, so these fixtures still test one check
    # each. The K8/K9 cases below override it.
    fm = {"epic": n, "title": f"epic {n}", "status": "todo", "opened": str(date.today()),
          "closed": None, "blocked_by": None,
          "done_when": [{"id": 1, "text": "the port compiles", "result": "0 errors"}],
          "items": [], "options": [], "outcome": None}
    fm.update(over)
    return fm


# ── K1: an in_progress epic whose log has gone quiet ──────────────────────

def _log(day):
    return f"\n# Epic 1\n\n## Log\n\n- {day} — opened.\n"


def test_k1_flags_a_stalled_in_progress_epic_as_advisory(tmp_path):
    old = date.today() - timedelta(days=30)
    p = write_record(tmp_path / "epic_01_x.md", epic_fm(status="active"), _log(old))
    issues, notes = checks.kanban_findings({1: (p, epic_fm(status="active"))})
    assert issues == []
    assert len(notes) == 1
    assert "active for 30 days" in notes[0]


def test_k1_silent_on_a_fresh_log_line(tmp_path):
    recent = date.today() - timedelta(days=3)
    p = write_record(tmp_path / "epic_01_x.md", epic_fm(status="active"), _log(recent))
    issues, notes = checks.kanban_findings({1: (p, epic_fm(status="active"))})
    assert (issues, notes) == ([], [])


def test_k1_ignores_epics_that_are_not_in_progress(tmp_path):
    old = date.today() - timedelta(days=99)
    p = write_record(tmp_path / "epic_01_x.md", epic_fm(status="todo"), _log(old))
    issues, notes = checks.kanban_findings({1: (p, epic_fm(status="todo"))})
    assert (issues, notes) == ([], [])


def test_k1_falls_back_to_the_opened_date_with_no_log(tmp_path):
    old = str(date.today() - timedelta(days=40))
    fm = epic_fm(status="active", opened=old)
    p = write_record(tmp_path / "epic_01_x.md", fm, "\n# Epic 1\n")
    _, notes = checks.kanban_findings({1: (p, fm)})
    assert "40 days" in notes[0]


# ── K10: the log says it landed, the board never moved ────────────────────

def _items(*statuses):
    return [{"id": i + 1, "title": f"item {i + 1}", "status": st, "since": str(date.today())}
            for i, st in enumerate(statuses)]


def _log_with(*lines):
    body = "\n# Epic 1\n\n## Log\n\n"
    return body + "".join(f"- {date.today()} — {ln}\n" for ln in lines)


def test_k10_blocks_a_merged_claim_over_an_all_todo_board(tmp_path):
    # 8 units merged, log written by hand, every item still todo.
    fm = epic_fm(status="todo", items=_items("todo", "todo"))
    body = _log_with("opened.",
                        "EXECUTION COMPLETE (session): 8 subagent work units, all merged\n"
                        "  to main. 30 of 36 rows closed.")
    p = write_record(tmp_path / "epic_01_x.md", fm, body)
    issues, notes = checks.kanban_findings({1: (p, fm)})
    assert notes == []
    assert len(issues) == 1
    assert "board never moved" in issues[0] and "'COMPLETE'" in issues[0]


def test_k10_silent_once_an_item_moved(tmp_path):
    fm = epic_fm(status="active", items=_items("done", "todo"))
    fm["items"][0]["evidence"] = "abc123"
    p = write_record(tmp_path / "epic_01_x.md", fm, _log_with("opened.", "unit 1 merged."))
    issues, _ = checks.kanban_findings({1: (p, fm)})
    assert issues == []


def test_k10_silent_on_a_plain_opened_line(tmp_path):
    fm = epic_fm(status="todo", items=_items("todo"))
    p = write_record(tmp_path / "epic_01_x.md", fm, _log_with("opened."))
    assert checks.kanban_findings({1: (p, fm)}) == ([], [])


def test_k10_reads_only_the_newest_line(tmp_path):
    # An old "merged" note followed by a newer neutral one is history, not a live claim.
    fm = epic_fm(status="todo", items=_items("todo"))
    p = write_record(tmp_path / "epic_01_x.md", fm,
                     _log_with("opened.", "unit 1 merged.", "re-planned; nothing pulled yet."))
    assert checks.kanban_findings({1: (p, fm)}) == ([], [])


def test_k10_ignores_a_closed_epic(tmp_path):
    fm = epic_fm(status="done", items=_items("todo"))
    p = write_record(tmp_path / "epic_01_x.md", fm, _log_with("opened.", "all merged."))
    issues, _ = checks.kanban_findings({1: (p, fm)})
    assert not any("board never moved" in i for i in issues)


def test_log_entries_keeps_continuation_lines_with_their_date():
    from maestro_cli import epics
    body = "## Log\n\n- 2026-09-02 — opened.\n- 2026-09-02 — long note\n  wraps here.\n"
    entries = epics.log_entries(body)
    assert len(entries) == 2
    assert entries[1] == "- 2026-09-02 — long note\n  wraps here."


# ── K11: an item title that is a list of tasks ───────────────────────────────

LONG_ITEM_TITLE = ("Rule-text reader door — unknown conditionals must resolve faithfully, "
                "not fail-closed: unique-dsl-unknown-conditionals, promotion-inert-conditionals, "
                "promotion-non-strength-effects-inert, promotion-availability-clauses (judge "
                "vs data), solar-nuclear-conditional-unknown, improvement-unique-filters")


def test_k11_advises_on_an_item_title_that_lists_tasks(tmp_path):
    fm = epic_fm(status="todo", items=[{"id": 1, "title": LONG_ITEM_TITLE, "status": "todo",
                                        "since": str(date.today())}])
    p = write_record(tmp_path / "epic_01_x.md", fm, _log_with("opened."))
    issues, notes = checks.kanban_findings({1: (p, fm)})
    assert issues == []
    assert len(notes) == 1 and "tasks written into an item" in notes[0]
    assert "lists 4 identifiers" in notes[0]


def test_k11_on_a_closed_epic_is_advisory_but_non_actionable(tmp_path):
    """Same finding, same text — but a closed epic's title is history, so the note is
    the kind `check()` folds into the summary line instead of re-printing each turn."""
    item = {"id": 1, "title": LONG_ITEM_TITLE, "status": "done", "evidence": "abc1234",
            "since": str(date.today())}
    open_fm = epic_fm(status="active", items=[item])
    closed_fm = epic_fm(status="done", closed=str(date.today()), outcome="done", items=[item])
    p = write_record(tmp_path / "epic_01_x.md", open_fm, _log_with("opened."))
    _, open_notes = checks.kanban_findings({1: (p, open_fm)})
    _, closed_notes = checks.kanban_findings({1: (p, closed_fm)})
    assert [str(n) for n in open_notes] == [str(n) for n in closed_notes]
    assert not isinstance(open_notes[0], checks.NonActionable)
    assert isinstance(closed_notes[0], checks.NonActionable)


@pytest.mark.parametrize("title", [
    "sea: naval movement (4 tasks)",
    "refactor the loader, then the writer, then the index",
    "a, b",
])
def test_k11_silent_on_prose_and_short_lists(tmp_path, title):
    fm = epic_fm(status="todo", items=[{"id": 1, "title": title, "status": "todo",
                                        "since": str(date.today())}])
    p = write_record(tmp_path / "epic_01_x.md", fm, _log_with("opened."))
    assert checks.kanban_findings({1: (p, fm)}) == ([], [])


# ── K8/K9: the closing condition ─────────────────────────────────────────────

def test_k9_flags_an_open_epic_with_no_closing_condition_as_advisory(tmp_path):
    fm = epic_fm(status="active", done_when=[])
    p = write_record(tmp_path / "epic_01_x.md", fm, _log(date.today()))
    issues, notes = checks.kanban_findings({1: (p, fm)})
    # Advisory, not blocking: an epic with no stated condition is a fact about work in
    # flight, not a malformed record — and it is raised NOW, while stating the condition
    # is still a decision rather than a rationalisation.
    assert issues == []
    assert len(notes) == 1 and "has no done_when clause" in notes[0]
    assert "rationalisation" in notes[0]


def test_k9_is_silent_once_a_clause_exists_even_unanswered(tmp_path):
    fm = epic_fm(status="todo", done_when=[{"id": 1, "text": "0 OPEN rows", "result": None}])
    p = write_record(tmp_path / "epic_01_x.md", fm)
    assert checks.kanban_findings({1: (p, fm)}) == ([], [])


def test_k9_does_not_nag_a_legacy_closed_epic(tmp_path):
    # Records closed before the field existed carry no clause; re-litigating them buys
    # nothing, so K9 only speaks about epics that can still act on it.
    fm = epic_fm(status="done", closed=str(date.today()), outcome="shipped", done_when=[])
    p = write_record(tmp_path / "epic_01_x.md", fm)
    assert checks.kanban_findings({1: (p, fm)}) == ([], [])


def test_k8_blocks_a_closed_epic_whose_clause_was_never_measured(tmp_path):
    fm = epic_fm(status="done", closed=str(date.today()), outcome="shipped", done_when=[
        {"id": 1, "text": "0 OPEN rows", "result": "0 OPEN, 274 rows"},
        {"id": 2, "text": "the suite stays green", "result": None},
    ])
    p = write_record(tmp_path / "epic_01_x.md", fm)
    issues, _ = checks.kanban_findings({1: (p, fm)})
    # `epic close` refuses this, so the record can only have got here by hand.
    assert len(issues) == 1
    assert "closed with 1 of 2 done_when clause(s) unanswered" in issues[0]
    assert "hand-edited" in issues[0]
    assert "--clause=<k> --result=" in issues[0]


# ── K2: a blocked flag with no reason ────────────────────────────────────────

@pytest.mark.parametrize("value", ["", "   "])
def test_k2_blocks_an_empty_blocked_flag(tmp_path, value):
    fm = epic_fm(blocked_by=value)
    p = write_record(tmp_path / "epic_01_x.md", fm)
    issues, _ = checks.kanban_findings({1: (p, fm)})
    assert any("blocked_by is set but empty" in i for i in issues)


def test_k2_accepts_a_cleared_flag(tmp_path):
    fm = epic_fm(blocked_by=None)
    p = write_record(tmp_path / "epic_01_x.md", fm)
    issues, _ = checks.kanban_findings({1: (p, fm)})
    assert issues == []


def test_k2_covers_item_rows_too(tmp_path):
    fm = epic_fm(items=[{"id": 2, "title": "Extract physics", "status": "todo", "blocked_by": " "}])
    p = write_record(tmp_path / "epic_01_x.md", fm)
    issues, _ = checks.kanban_findings({1: (p, fm)})
    assert any('item 2 "Extract physics"' in i for i in issues)


# ── K3: frontmatter the CLI did not write ────────────────────────────────────

def test_k3_blocks_a_hand_written_record_missing_keys(tmp_path):
    fm = {"epic": 1, "title": "hand rolled", "status": "active"}
    p = write_record(tmp_path / "epic_01_x.md", fm, _log(date.today()))
    issues, _ = checks.kanban_findings({1: (p, fm)})
    assert any("missing required key(s)" in i for i in issues)
    assert any("opened" in i and "blocked_by" in i for i in issues)


def test_k3_silent_on_a_cli_written_record(tmp_path):
    fm = epic_fm()
    p = write_record(tmp_path / "epic_01_x.md", fm)
    issues, _ = checks.kanban_findings({1: (p, fm)})
    assert issues == []


# ── A1 / A2: a result with no artifact behind it ─────────────────────────────

def _exps(tmp_path, fm):
    p = write_record(tmp_path / "docs" / "experiments" / "exp_01_x.md", fm)
    return {1: (p, fm)}


def test_a1_flags_a_takeaway_with_no_source_artifacts(tmp_path):
    found = checks.adr9_findings(tmp_path, _exps(tmp_path, {"exp": 1, "takeaway": "it worked"}))
    assert len(found) == 1
    rel, msg = found[0]
    assert rel == "docs/experiments/exp_01_x.md"
    assert "source_artifacts is empty" in msg


def test_a1_silent_when_the_takeaway_is_cited(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "metrics.json").write_text("{}")
    found = checks.adr9_findings(tmp_path, _exps(tmp_path, {
        "exp": 1, "takeaway": "it worked", "source_artifacts": ["data/metrics.json"]}))
    assert found == []


def test_a2_flags_a_source_artifact_that_is_gone(tmp_path):
    found = checks.adr9_findings(tmp_path, _exps(tmp_path, {
        "exp": 1, "takeaway": "it worked", "source_artifacts": ["data/gone.csv"]}))
    assert len(found) == 1
    assert "has lost its evidence" in found[0][1]


def test_a2_defers_to_the_check_that_already_reported_the_path(tmp_path):
    exps = _exps(tmp_path, {"exp": 1, "takeaway": "it worked",
                            "source_artifacts": ["data/gone.csv"]})
    found = checks.adr9_findings(tmp_path, exps, already_reported={(1, "data/gone.csv")})
    assert found == []


# ── A3: a status word with no evidence marker ────────────────────────────────

def _docs(tmp_path, name, text):
    d = tmp_path / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return tmp_path


def test_a3_flags_a_bare_status_row(tmp_path):
    _docs(tmp_path, "conformance.md", "# Rows\n\nG8-16 reachable: no\n")
    found = checks.adr9_findings(tmp_path, {})
    assert len(found) == 1
    assert "docs/conformance.md:3" in found[0][1]
    assert "reachable:" in found[0][1]


@pytest.mark.parametrize("line", [
    "G8-16 reachable: no — verified: a1b2c3d",
    "G8-16 reachable: no (unverified)",
])
def test_a3_accepts_a_marked_row(tmp_path, line):
    _docs(tmp_path, "conformance.md", f"# Rows\n\n{line}\n")
    assert checks.adr9_findings(tmp_path, {}) == []


@pytest.mark.parametrize("line", [
    "A status row such as `G8-16 reachable: no` is a claim about code.",
    'A status row such as "the module is CONFORMANT" is a claim about code.',
])
def test_a3_ignores_a_quoted_or_backticked_mention(tmp_path, line):
    """Discussing a status word is not asserting one — that is how the ADRs read."""
    _docs(tmp_path, "notes.md", f"# Notes\n\n{line}\n")
    assert checks.adr9_findings(tmp_path, {}) == []


def test_a3_ignores_fenced_code_and_frontmatter(tmp_path):
    _docs(tmp_path, "notes.md",
          "---\nkind: reference\nsummary: unported rows live here\n---\n\n"
          "```\nstatus word   G8-16 reachable: no\n```\n")
    assert checks.adr9_findings(tmp_path, {}) == []


def test_a3_ignores_derived_words(tmp_path):
    _docs(tmp_path, "notes.md", "# Notes\n\nThe run was reported and fully supported.\n")
    assert checks.adr9_findings(tmp_path, {}) == []


def test_a3_caps_the_report_per_file(tmp_path):
    rows = "\n".join(f"G{i} reachable: no" for i in range(10))
    _docs(tmp_path, "conformance.md", f"# Rows\n\n{rows}\n")
    found = checks.adr9_findings(tmp_path, {})
    assert len(found) == checks.A3_MAX_PER_FILE + 1
    assert "further unmarked status word(s)" in found[-1][1]


# ── A4: a rule-bearing docs file nothing triggers ────────────────────────────

RULES_DOC = "# House rules\n\n" + "\n".join(
    [f"- Rule {i}: you MUST do the thing." for i in range(6)]) + "\n" * 20


def test_a4_flags_an_untriggered_rules_doc(tmp_path):
    _docs(tmp_path, "house_rules.md", RULES_DOC)
    (tmp_path / "CLAUDE.md").write_text("# Project\n\nSee the docs.\n")
    found = checks.adr9_findings(tmp_path, {})
    assert len(found) == 1
    assert "reads as rule-bearing" in found[0][1]


def test_a4_silent_when_a_claude_md_table_row_triggers_it(tmp_path):
    _docs(tmp_path, "house_rules.md", RULES_DOC)
    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n\n| Situation | Load |\n|---|---|\n| Writing code | `docs/house_rules.md` |\n")
    assert checks.adr9_findings(tmp_path, {}) == []


def test_a4_ignores_a_prose_mention(tmp_path):
    """Rule 12: a doc named only in prose is loaded by no harness, so it is still dead."""
    _docs(tmp_path, "house_rules.md", RULES_DOC)
    (tmp_path / "CLAUDE.md").write_text("# Project\n\nRules live in docs/house_rules.md.\n")
    assert len(checks.adr9_findings(tmp_path, {})) == 1


def test_a4_ignores_prose_without_rules(tmp_path):
    _docs(tmp_path, "background.md", "# Background\n\n" + "Prose line.\n" * 40)
    assert checks.adr9_findings(tmp_path, {}) == []


def test_a4_ignores_records_and_framework_files(tmp_path):
    for name in ("progress.md", "findings.md"):
        _docs(tmp_path, name, RULES_DOC)
    (tmp_path / "docs" / "experiments").mkdir(parents=True)
    (tmp_path / "docs" / "experiments" / "exp_01_x.md").write_text(RULES_DOC)
    assert checks.adr9_findings(tmp_path, {}) == []


# ── the staging gate itself ──────────────────────────────────────────────────

def test_stage_hard_fails_a_touched_file_and_only_advises_on_the_rest():
    issues, notes = [], []
    checks.stage_adr9([("docs/new.md", "new debt"), ("docs/old.md", "old debt")],
                      touched={"docs/new.md"}, issues=issues, notes=notes)
    assert issues == ["new debt"]
    assert len(notes) == 1 and notes[0].startswith("old debt")
    assert "unchanged since HEAD" in notes[0]


def test_stage_degrades_to_advisory_when_git_cannot_answer():
    issues, notes = [], []
    checks.stage_adr9([("docs/new.md", "new debt")], touched=None, issues=issues, notes=notes)
    assert issues == []
    assert "git could not say what changed" in notes[0]


def test_stage_marks_only_the_untouched_backlog_non_actionable():
    """The untouched-file advisory is the standing backlog and is folded away by default;
    a git failure is an anomaly and stays visible."""
    issues, notes = [], []
    checks.stage_adr9([("docs/old.md", "old debt")], touched=set(), issues=issues, notes=notes)
    assert isinstance(notes[0], checks.NonActionable)
    issues, notes = [], []
    checks.stage_adr9([("docs/old.md", "old debt")], touched=None, issues=issues, notes=notes)
    assert not isinstance(notes[0], checks.NonActionable)


def test_closed_epic_evidence_sweep_is_non_actionable(tmp_path):
    """A5 on a CLOSED epic says so in its own text ("history, not debt to repair"); the
    marker makes that classification something `check()` can act on."""
    fm = epic_fm(status="done", closed=str(date.today()), outcome="the port compiles",
                 done_when=[{"id": 1, "text": "compiles", "result": "0 errors"}])
    p = write_record(tmp_path / "docs" / "epics" / "epic_01_x.md", fm, _log_with("closed."))
    notes = checks.evidence_sha_notes(tmp_path, {1: (p, fm)})
    assert len(notes) == 2 and all("The epic is CLOSED" in n for n in notes)
    assert all(isinstance(n, checks.NonActionable) for n in notes)


def test_uncommitted_paths_returns_none_outside_a_repo(tmp_path):
    assert checks.uncommitted_paths(tmp_path) is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_uncommitted_paths_sees_modified_and_untracked_files(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                       capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "committed.md").write_text("one\n")
    git("add", "-A")
    git("-c", "commit.gpgsign=false", "commit", "-qm", "first")

    assert checks.uncommitted_paths(tmp_path) == set()
    (tmp_path / "committed.md").write_text("two\n")
    (tmp_path / "fresh.md").write_text("new file\n")
    assert checks.uncommitted_paths(tmp_path) == {"committed.md", "fresh.md"}


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_the_gate_end_to_end_committed_is_advisory_touched_is_blocking(tmp_path):
    """The same uncited takeaway: advisory once committed, blocking once edited."""
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                       capture_output=True, text=True)

    fm = {"exp": 1, "takeaway": "it worked"}
    exps = _exps(tmp_path, fm)
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("add", "-A")
    git("-c", "commit.gpgsign=false", "commit", "-qm", "first")

    findings = checks.adr9_findings(tmp_path, exps)
    issues, notes = [], []
    checks.stage_adr9(findings, checks.uncommitted_paths(tmp_path), issues, notes)
    assert issues == [] and len(notes) == 1        # committed backlog: advisory

    write_record(exps[1][0], {**fm, "takeaway": "it worked, edited"})
    issues, notes = [], []
    checks.stage_adr9(checks.adr9_findings(tmp_path, exps),
                      checks.uncommitted_paths(tmp_path), issues, notes)
    assert notes == [] and len(issues) == 1        # touched this session: blocking


# ── INDEX staleness is decided on content, not mtime ─────────────────────────


def _adr_index_mismatch(indexes, adr_dir):
    """The content comparison check 1 performs, isolated from the full drift run."""
    idx = adr_dir / "INDEX.md"
    records = indexes.load_kind(adr_dir, "adr")
    if not (idx.exists() and records):
        return False
    return indexes.build_adr_index(records).strip() != idx.read_text().strip()


def test_index_staleness_ignores_mtime_and_catches_content(tmp_path, monkeypatch):
    """git does not preserve mtimes, so a checkout, clone or branch switch made a
    byte-correct INDEX look stale -- and a check that cries wolf is a check people
    disable. Touching a record must stay silent; changing the INDEX bytes must not.
    """
    from maestro_cli import indexes

    adr_dir = tmp_path / "docs" / "adrs"
    adr_dir.mkdir(parents=True)
    (adr_dir / "adr_01_a_decision.md").write_text(
        "---\nadr: 1\ntitle: a_decision\nstatus: accepted\ndate: '2026-01-01'\n"
        "decision: 'Do the thing'\ntags: []\n---\n\n# ADR 1\n")
    index = adr_dir / "INDEX.md"
    index.write_text(indexes.build_adr_index(indexes.load_kind(adr_dir, "adr")))

    assert _adr_index_mismatch(indexes, adr_dir) is False

    # a pure mtime bump on the record: still a match
    os.utime(adr_dir / "adr_01_a_decision.md", (2 ** 31, 2 ** 31))
    assert _adr_index_mismatch(indexes, adr_dir) is False

    # a real content change: no longer a match
    index.write_text(index.read_text().replace("a_decision", "a_decisionX", 1))
    assert _adr_index_mismatch(indexes, adr_dir) is True


# ── the session window: committing is not a way out of the gate ──────────────
#
# "Touched this session" used to mean "differs from HEAD" alone. Writing the claim and
# committing it in the same bash call therefore cleared the gate: by the time the Stop
# hook ran, the file matched HEAD and the finding printed as an advisory nobody had to
# act on (a metric written into progress.md). A commit inside the
# session window now counts as touched too.

def _repo(tmp_path):
    def git(*args, env=None):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "commit.gpgsign=false", *args],
                       check=True, capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    return git


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_a_file_committed_inside_the_window_still_counts_as_touched(tmp_path):
    git = _repo(tmp_path)
    _docs(tmp_path, "conformance.md", "# Rows\n\nG8-16 reachable: no\n")
    git("add", "-A")
    git("commit", "-qm", "rows")

    assert checks.uncommitted_paths(tmp_path) == set()      # the loophole, as it looked
    assert "docs/conformance.md" in checks.touched_paths(tmp_path)

    issues, notes = [], []
    checks.stage_adr9(checks.adr9_findings(tmp_path, {}), checks.touched_paths(tmp_path),
                      issues, notes)
    assert len(issues) == 1 and notes == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_a_file_committed_before_the_window_stays_advisory(tmp_path):
    """The ratchet's other half: yesterday's backlog must not start blocking."""
    git = _repo(tmp_path)
    _docs(tmp_path, "conformance.md", "# Rows\n\nG8-16 reachable: no\n")
    old = "2026-01-02T03:04:05+00:00"
    git("add", "-A")
    git("commit", "-qm", "rows", env={"GIT_AUTHOR_DATE": old, "GIT_COMMITTER_DATE": old})

    assert checks.touched_paths(tmp_path) == set()

    issues, notes = [], []
    checks.stage_adr9(checks.adr9_findings(tmp_path, {}), checks.touched_paths(tmp_path),
                      issues, notes)
    assert issues == [] and len(notes) == 1
    assert "untouched by a commit in the session window" in notes[0]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_the_window_is_configurable(tmp_path):
    git = _repo(tmp_path)
    _docs(tmp_path, "conformance.md", "# Rows\n\nG8-16 reachable: no\n")
    stale = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    git("add", "-A")
    git("commit", "-qm", "rows", env={"GIT_AUTHOR_DATE": stale, "GIT_COMMITTER_DATE": stale})

    assert checks.touched_paths(tmp_path, hours=12) == {"docs/conformance.md"}
    assert checks.touched_paths(tmp_path, hours=1) == set()


def test_touched_paths_returns_none_outside_a_repo(tmp_path):
    """No git, no window — the ADR 9 gate degrades to advisory, it never crashes."""
    assert checks.touched_paths(tmp_path) is None
    assert checks.recently_committed_paths(tmp_path) is None


# ── A3's remedy is per-file: progress.md holds no numbers to mark ────────────

def test_a3_on_progress_md_says_to_link_the_record_not_to_mark_the_line(tmp_path):
    _docs(tmp_path, "progress.md", "# Plan\n\nG8-16 reachable: no\n")
    (rel, msg), = checks.adr9_findings(tmp_path, {})
    assert rel == "docs/progress.md"
    assert "progress.md holds no metric values or status words (rule 10)" in msg
    assert "replace the number with a link to the record that holds it" in msg
    assert "verified:" not in msg          # rule 10 forbids the value being there at all


def test_a3_elsewhere_keeps_the_evidence_marker_remedy(tmp_path):
    _docs(tmp_path, "conformance.md", "# Rows\n\nG8-16 reachable: no\n")
    (_, msg), = checks.adr9_findings(tmp_path, {})
    assert "`verified: <sha|date>` on the line, or write it `unverified`" in msg


# ── A3 (rule 10): progress.md holds no result counts ─────────────────────────

@pytest.mark.parametrize("line", [
    "Item 5 re-synced the client suite (suite 735/735).",
    "`packages/ruleset` is DELETED (1938 LOC).",
    "the wire is pinned by 12 byte goldens",
    "full gate: 2313 passed, 1 skipped",
])
def test_a3_flags_a_result_count_in_progress(tmp_path, line):
    _docs(tmp_path, "progress.md", f"# Progress\n\n## Current\n\n{line}\n")
    found = checks.adr9_findings(tmp_path, {})
    assert len(found) == 1
    assert "docs/progress.md:5" in found[0][1] and "rule 10" in found[0][1]


@pytest.mark.parametrize("line", [
    "epics 6/8 logs hold theirs",                       # an ordinal, not a total
    "closed with 6/6 items, 4/4 done_when",             # a board tally — the INDEX's
    "items 10/10 done on the board",
    "12 of the options remain; see the record",
    "`suite 735/735` is what the record says",          # discussed, not asserted
    "Epic 9 CLOSED 2026-09-04 — see the record",
])
def test_a3_leaves_ordinals_board_tallies_and_quotes_alone(tmp_path, line):
    _docs(tmp_path, "progress.md", f"# Progress\n\n## Current\n\n{line}\n")
    assert checks.adr9_findings(tmp_path, {}) == []


def test_a3_count_rule_is_progress_only(tmp_path):
    _docs(tmp_path, "notes.md", "# Notes\n\nthe suite is 735/735 and 1938 LOC went\n")
    assert checks.adr9_findings(tmp_path, {}) == []


# ── A6: a scratch path is not evidence ───────────────────────────────────────

def _epic(tmp_path, result, status="active"):
    (tmp_path / "docs" / "epics").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "docs" / "epics" / "epic_09_t.md"
    path.touch()
    fm = {"status": status,
          "done_when": [{"id": 1, "text": "gate is one command", "result": result}]}
    return path, fm


@pytest.mark.parametrize("cited", [
    ".tmp/final_gate.log", "/tmp/demo_gate_recon.md", "rust/target/gate/run.log",
    "packages/client/dist/index.js", "tmp/x.txt", "src/__pycache__/x.pyc",
])
def test_a6_flags_a_scratch_path_while_the_epic_is_open(tmp_path, cited):
    path, fm = _epic(tmp_path, f"green at 0d9e69c9 — per-step times in {cited}")
    out = [m for _, m in checks.adr9_findings(tmp_path, {}, epic_records={9: (path, fm)})]
    assert any(cited in m and "scratch" in m and "--clause=1" in m for m in out)
    assert not any("cites no artifact" in m for m in out)     # the sha still counts (A5)


@pytest.mark.parametrize("cited", [
    "data/experiments/exp_03_gate/run_1/gate.log",     # the run dir — rule 4's home
    "docs/archive/gate_runs.log",
    ".github/workflows/ci.yml",                        # a tracked dot-dir is fine
    "tools/build/render.py",                           # `build/` is not in the set
])
def test_a6_accepts_a_kept_artifact(tmp_path, cited):
    path, fm = _epic(tmp_path, f"green — {cited}")
    for d in ("data", "docs", "tools"):
        (tmp_path / d).mkdir(exist_ok=True)
    out = [m for _, m in checks.adr9_findings(tmp_path, {}, epic_records={9: (path, fm)})]
    assert not any("scratch" in m for m in out)


def test_a6_is_an_advisory_on_a_closed_epic(tmp_path):
    path, fm = _epic(tmp_path, "green at 0d9e69c9 (.tmp/final_gate.log)", status="done")
    assert checks.adr9_findings(tmp_path, {}, epic_records={9: (path, fm)}) == []
    notes = checks.evidence_sha_notes(tmp_path, {9: (path, fm)})
    assert len(notes) == 1 and ".tmp/final_gate.log" in notes[0] and "A6" in notes[0]
