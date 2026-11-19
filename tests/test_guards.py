"""The pre-write path guard (tools/maestro_cli/guards.py) — the rule both harnesses run.

It guards exactly the CLI-owned surface (core rule 1): frontmatter and an epic's
`## Log` are the CLI's, bodies are hand-edited after scaffolding, INDEX.md is never
hand-edited. The first version of this guard blocked records wholesale, which blocked
the legitimate half too; these tests pin the corrected granularity, and pin it against
BOTH tool dialects — Claude Code's Write/Edit/MultiEdit and dsh's
write/edit/str_replace_editor — because the rule now serves both.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli.guards import verdict  # noqa: E402

_ADR_FM = "---\nadr: 7\ntitle: t\nstatus: accepted\ndate: '2026-09-01'\ntags: []\n---\n"
_ADR_BODY = "\n# ADR 7 — t\n\n**Context**: old prose here.\n\n**Decision**: body text.\n"

_EPIC_FM = "---\nepic: 5\ntitle: t\nstatus: todo\nitems: []\n---\n"
_EPIC_BODY = (
    "\n# Epic 5 — t\n\n**Why**: hand-written rationale.\n\n"
    "## Log\n\n- 2026-09-01 — opened.\n\n## Notes\n\nfree prose below the log.\n"
)


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _adr(tmp_path):
    return _write(tmp_path, "docs/adrs/adr_07_t.md", _ADR_FM + _ADR_BODY)


def _epic(tmp_path):
    return _write(tmp_path, "docs/epics/epic_05_t.md", _EPIC_FM + _EPIC_BODY)


def _edit(path, old, tool="Edit"):
    return verdict(tool, {"file_path": str(path), "old_string": old, "new_string": "x"})


# ── the granularity, on ADRs ─────────────────────────────────────────────────

def test_body_edit_is_allowed(tmp_path):
    assert _edit(_adr(tmp_path), "old prose here.") is None


def test_frontmatter_edit_is_denied(tmp_path):
    reason = _edit(_adr(tmp_path), "status: accepted")
    assert reason and "FRONTMATTER" in reason


def test_edit_spanning_the_boundary_is_denied(tmp_path):
    assert _edit(_adr(tmp_path), "---\n\n# ADR 7") is not None


def test_hand_creation_is_denied(tmp_path):
    missing = tmp_path / "docs" / "adrs" / "adr_09_new.md"
    reason = verdict("Write", {"file_path": str(missing), "content": "x"})
    assert reason and "scaffolded by the CLI" in reason


def test_write_with_identical_frontmatter_is_allowed(tmp_path):
    p = _adr(tmp_path)
    assert verdict("Write", {"file_path": str(p), "content": _ADR_FM + "\nnew body\n"}) is None


def test_write_changing_frontmatter_is_denied(tmp_path):
    p = _adr(tmp_path)
    changed = _ADR_FM.replace("accepted", "superseded")
    reason = verdict("Write", {"file_path": str(p), "content": changed + _ADR_BODY})
    assert reason and "FRONTMATTER" in reason


def test_multiedit_with_one_frontmatter_touch_is_denied(tmp_path):
    p = _adr(tmp_path)
    reason = verdict("MultiEdit", {"file_path": str(p), "edits": [
        {"old_string": "body text.", "new_string": "y"},
        {"old_string": "date: '2026-09-01'", "new_string": "date: '2026-09-02'"},
    ]})
    assert reason is not None


def test_experiment_records_get_the_same_granularity(tmp_path):
    p = _write(tmp_path, "docs/experiments/exp_03_probe.md",
               "---\nexp: 3\nstatus: running\n---\n\n## Method\n\nhand-written method.\n")
    assert _edit(p, "hand-written method.") is None
    assert _edit(p, "status: running") is not None


def test_unscopable_payload_fails_closed(tmp_path):
    reason = verdict("", {"file_path": str(_adr(tmp_path))})
    assert reason and "denied" in reason


def test_record_without_frontmatter_is_not_policed(tmp_path):
    p = _write(tmp_path, "docs/adrs/adr_08_odd.md", "no frontmatter at all\n")
    assert _edit(p, "no frontmatter") is None


def test_unrelated_files_are_untouched(tmp_path):
    p = _write(tmp_path, "docs/findings.md", "---\nx: 1\n---\nfindings prose")
    assert _edit(p, "x: 1") is None


# ── epics: the record kind the guards cover ──────────────────────────────────

def test_epic_frontmatter_edit_is_denied(tmp_path):
    reason = _edit(_epic(tmp_path), "status: todo")
    assert reason and "FRONTMATTER" in reason and "maestro epic" in reason


def test_epic_body_prose_is_allowed(tmp_path):
    p = _epic(tmp_path)
    assert _edit(p, "hand-written rationale.") is None
    assert _edit(p, "free prose below the log.") is None


def test_epic_log_is_cli_owned_and_denied(tmp_path):
    """The `## Log` is hashed by the stamp, so the pre-write guard must refuse it too —
    otherwise a hand-appended log line is allowed through and only breaks afterwards."""
    reason = _edit(_epic(tmp_path), "- 2026-09-01 — opened.")
    assert reason and "## Log" in reason and "--note" in reason


def test_epic_write_keeping_frontmatter_but_rewriting_the_log_is_denied(tmp_path):
    p = _epic(tmp_path)
    rewritten = _EPIC_BODY.replace("- 2026-09-01 — opened.", "- 2026-09-01 — opened; all done.")
    reason = verdict("Write", {"file_path": str(p), "content": _EPIC_FM + rewritten})
    assert reason and "## Log" in reason


def test_epic_write_touching_only_prose_is_allowed(tmp_path):
    p = _epic(tmp_path)
    rewritten = _EPIC_BODY.replace("hand-written rationale.", "a better rationale.")
    assert verdict("Write", {"file_path": str(p), "content": _EPIC_FM + rewritten}) is None


def test_epic_without_a_log_section_still_guards_its_frontmatter(tmp_path):
    p = _write(tmp_path, "docs/epics/epic_06_t.md", _EPIC_FM + "\n# Epic 6\n\nprose only.\n")
    assert _edit(p, "prose only.") is None
    assert _edit(p, "status: todo") is not None


def test_a_domain_doc_in_the_epics_dir_is_not_a_record(tmp_path):
    """A domain doc under docs/epics/ is not a record. It is not `epic_NN_*`,
    so it is hand-edited data, not a record."""
    p = _write(tmp_path, "docs/epics/fidelity_backlog_v2.md", "---\nkind: domain-doc\n---\nrows")
    assert _edit(p, "kind: domain-doc") is None


# ── the generated indexes ────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", [
    "docs/adrs/INDEX.md",
    "docs/experiments/INDEX.md",
    "docs/epics/INDEX.md",
    "docs/data/INDEX.md",
    "docs/kb/literature/INDEX.md",
])
def test_every_generated_index_is_fully_blocked(tmp_path, rel):
    reason = _edit(_write(tmp_path, rel, "generated"), "generated")
    assert reason and "GENERATED" in reason


def test_an_index_somewhere_else_is_not_ours(tmp_path):
    assert _edit(_write(tmp_path, "docs/kb/INDEX.md", "mine"), "mine") is None


# ── dataset records: creation only ───────────────────────────────────────────

def test_hand_creating_a_dataset_record_is_denied(tmp_path):
    missing = tmp_path / "docs" / "data" / "corpus.md"
    missing.parent.mkdir(parents=True)
    reason = verdict("Write", {"file_path": str(missing), "content": "x"})
    assert reason and "sha256" in reason


def test_editing_an_existing_dataset_description_is_allowed(tmp_path):
    p = _write(tmp_path, "docs/data/corpus.md", "---\nname: corpus\n---\ndescription")
    assert _edit(p, "description") is None


def test_a_data_artifact_outside_docs_is_not_a_dataset_record(tmp_path):
    p = _write(tmp_path, "data/raw/corpus/v1/notes.md", "raw notes")
    assert _edit(p, "raw notes") is None


# ── the dsh tool dialect ─────────────────────────────────────────────────────

def test_dsh_edit_uses_the_same_keys(tmp_path):
    p = _adr(tmp_path)
    assert verdict("edit", {"file_path": str(p), "old_string": "body text."}) is None
    assert verdict("edit", {"file_path": str(p), "old_string": "status: accepted"}) is not None


def test_str_replace_editor_path_and_old_str(tmp_path):
    p = _adr(tmp_path)
    base = {"path": str(p), "command": "str_replace"}
    assert verdict("str_replace_editor", {**base, "old_str": "body text."}) is None
    assert verdict("str_replace_editor", {**base, "old_str": "status: accepted"}) is not None


def test_str_replace_editor_create_is_a_whole_file_write(tmp_path):
    p = _adr(tmp_path)
    changed = _ADR_FM.replace("accepted", "superseded")
    reason = verdict("str_replace_editor",
                     {"path": str(p), "command": "create", "file_text": changed + _ADR_BODY})
    assert reason and "FRONTMATTER" in reason


def test_str_replace_editor_insert_fails_closed(tmp_path):
    """`insert` names no old text, so the guard cannot prove the line lands in the body."""
    reason = verdict("str_replace_editor",
                     {"path": str(_adr(tmp_path)), "command": "insert",
                      "insert_line": 3, "new_str": "status: draft"})
    assert reason and "denied" in reason


def test_a_view_is_not_a_write(tmp_path):
    assert verdict("str_replace_editor",
                   {"path": str(_adr(tmp_path)), "command": "view"}) is None


def test_a_call_with_no_path_has_no_opinion():
    assert verdict("bash", {"command": "ls"}) is None


def test_an_injected_reader_replaces_the_filesystem():
    """The rule takes the current file text from a reader, so an adapter can hand it
    sandboxed content and the rule never touches the disk itself."""
    reason = verdict("Edit", {"file_path": "docs/adrs/adr_01_x.md", "old_string": "status: draft"},
                     read=lambda p: _ADR_FM.replace("accepted", "draft") + _ADR_BODY)
    assert reason and "FRONTMATTER" in reason
