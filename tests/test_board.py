"""Tests for `maestro board render` — the HTML kanban board (ADR 7).

What is pinned here is what the ADR would be contradicted by:

  * a blocked epic stays in the column of the state it is blocked IN — the flag never
    becomes a fourth column;
  * the page is SELF-CONTAINED (no http(s) reference, no <script>), because the whole
    point is a file you double-click with no server, no daemon and no port;
  * free text out of a record is escaped, and a record that will not parse is reported
    as a skipped card instead of crashing the render.
"""
from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import board  # noqa: E402
from maestro_cli.cli import main  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def write_epic(epic_dir, n, title, status="todo", blocked_by=None, outcome=None,
               items=(), slug=None):
    epic_dir.mkdir(parents=True, exist_ok=True)
    slug = slug or f"epic_{n:02d}_e{n}"
    lines = ["---", f"epic: {n}", f"title: {title!r}", f"status: {status}"]
    lines.append(f"blocked_by: {blocked_by!r}" if blocked_by else "blocked_by: null")
    lines.append(f"outcome: {outcome!r}" if outcome else "outcome: null")
    if items:
        lines.append("items:")
        for it in items:
            lines.append(f"- id: {it['id']}")
            lines.append(f"  title: {it.get('title', '')!r}")
            lines.append(f"  status: {it.get('status', 'todo')}")
            if it.get("blocked_by"):
                lines.append(f"  blocked_by: {it['blocked_by']!r}")
    else:
        lines.append("items: []")
    lines += ["---", "", f"# Epic {n} — {title}", ""]
    path = epic_dir / f"{slug}.md"
    path.write_text("\n".join(lines))
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project whose docs/epics/ the board reads."""
    epic_dir = tmp_path / "proj" / "docs" / "epics"
    epic_dir.mkdir(parents=True)
    monkeypatch.setattr(board, "EPIC_DIR", epic_dir)
    monkeypatch.setattr(board, "ROOT", tmp_path / "proj")
    return epic_dir


def render(out, scan=None, extra=()):
    argv = ["board", "render", f"--output={out}"]
    if scan:
        argv.append(f"--scan={scan}")
    main(argv + list(extra))
    return Path(out).read_text()


class Wellformed(HTMLParser):
    """Minimal well-formedness check: every non-void tag closes, in order."""

    VOID = {"meta", "br", "hr", "img", "input", "link", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.problems = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"</{tag}> closes {self.stack[-1:] or ['nothing']}")
            return
        self.stack.pop()


def parse_ok(text):
    p = Wellformed()
    p.feed(text)
    p.close()
    assert not p.problems, p.problems
    assert not p.stack, f"unclosed: {p.stack}"


# ── the board itself ─────────────────────────────────────────────────────────

def test_one_card_per_state(project, tmp_path):
    write_epic(project, 1, "first", status="done", outcome="shipped the thing")
    write_epic(project, 2, "second", status="active")
    write_epic(project, 3, "third", status="todo", items=[
        {"id": 1, "title": "a", "status": "done"},
        {"id": 2, "title": "b", "status": "todo"},
    ])
    out = tmp_path / "board.html"
    text = render(out)
    parse_ok(text)

    for title in ("first", "second", "third"):
        assert text.count(f">{title}</h3>") == 1
    assert "TODO" in text and "ACTIVE" in text and "DONE" in text
    assert "items 1/2" in text                    # counts come off the item rows
    assert "shipped the thing" in text            # outcome shown on a done card
    # Each card links to its own record, relatively (the page sits beside them or not).
    assert 'href="epic_01_e1.md"' in text or "epic_01_e1.md" in text


def test_blocked_card_keeps_its_state_column(project, tmp_path):
    write_epic(project, 1, "unblocked", status="active")
    write_epic(project, 2, "stuck", status="todo", blocked_by="upstream API not landed")
    out = tmp_path / "board.html"
    text = render(out)
    parse_ok(text)

    # The blocked epic sits inside the TODO column, not in a column of its own.
    todo = text.split("TODO")[1].split("ACTIVE")[0]
    assert ">stuck</h3>" in todo
    assert "upstream API not landed" in todo
    assert "BLOCKED" in todo
    # There are exactly four columns — no fourth for the flag.
    assert text.count('<section class="column') == 4
    # The flag is repeated below WITH the state it is blocked in, never moved there.
    assert text.count("upstream API not landed") == 2
    assert "<td>todo</td>" in text


def test_blocked_item_named_with_its_epic(project, tmp_path):
    write_epic(project, 1, "epic one", status="active", items=[
        {"id": 1, "title": "port the loader", "status": "in_progress",
         "blocked_by": "waiting on schema v2"},
    ])
    text = render(tmp_path / "board.html")
    parse_ok(text)
    assert "item 1" in text and "waiting on schema v2" in text


def test_free_text_is_escaped(project, tmp_path):
    nasty = 'a <script>alert("x")</script> & "quoted" title'
    write_epic(project, 1, nasty, status="todo", blocked_by='needs <b>&</b> "review"')
    text = render(tmp_path / "board.html")
    parse_ok(text)

    assert "<script" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;" in text
    assert "&quot;quoted&quot;" in text or "&#x27;" in text or "quoted" in text
    assert '<b>&</b>' not in text


def test_self_contained(project, tmp_path):
    write_epic(project, 1, "only", status="todo")
    text = render(tmp_path / "board.html")
    assert "http://" not in text
    assert "https://" not in text
    assert "<script" not in text
    assert "<style>" in text                 # CSS inline, not linked
    assert "<link" not in text


def test_empty_project_still_renders(project, tmp_path):
    text = render(tmp_path / "board.html")
    parse_ok(text)
    assert "Epic Board" in text
    assert text.count('<section class="column') == 4
    assert "Nothing blocked." in text


def test_malformed_record_is_skipped_not_fatal(project, tmp_path):
    write_epic(project, 1, "healthy", status="todo")
    (project / "epic_02_broken.md").write_text("---\nepic: 2\ntitle: [unclosed\n---\nbody\n")
    text = render(tmp_path / "board.html")
    parse_ok(text)

    assert ">healthy</h3>" in text
    assert "Skipped records" in text
    assert "epic_02_broken.md" in text


# ── --scan across projects ───────────────────────────────────────────────────

def test_scan_finds_projects_one_and_two_levels_deep(project, tmp_path):
    write_epic(project, 1, "home epic", status="todo")

    tree = tmp_path / "tree"
    shallow = tree / "alpha" / "docs" / "epics"
    deep = tree / "org" / "beta" / "docs" / "epics"
    write_epic(shallow, 1, "alpha epic", status="active")
    write_epic(deep, 1, "beta epic", status="done", outcome="closed out")
    write_epic(deep, 2, "beta blocked", status="todo", blocked_by="no reviewer")
    # Too deep to be a project, and a directory with no epic records at all.
    write_epic(tree / "a" / "b" / "c" / "docs" / "epics", 1, "too deep")
    (tree / "empty" / "docs" / "epics").mkdir(parents=True)

    text = render(tmp_path / "board.html", scan=tree)
    parse_ok(text)

    for title in ("home epic", "alpha epic", "beta epic", "beta blocked"):
        assert text.count(f">{title}</h3>") == 1, title
    assert ">too deep</h3>" not in text
    # In scan mode each card is labelled with its project.
    assert "alpha" in text and "beta" in text and "proj" in text


def test_scan_does_not_write_into_other_projects(project, tmp_path):
    tree = tmp_path / "tree"
    other = tree / "alpha" / "docs" / "epics"
    write_epic(other, 1, "alpha epic", status="todo")
    before = sorted(p.name for p in other.iterdir())

    render(tmp_path / "board.html", scan=tree)
    assert sorted(p.name for p in other.iterdir()) == before


def test_scan_skips_symlinks_out_of_the_tree(project, tmp_path):
    tree = tmp_path / "tree"
    (tree).mkdir()
    outside = tmp_path / "outside" / "docs" / "epics"
    write_epic(outside, 1, "outsider", status="todo")
    try:
        (tree / "link").symlink_to(tmp_path / "outside", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    text = render(tmp_path / "board.html", scan=tree)
    parse_ok(text)
    assert ">outsider</h3>" not in text


def test_unreadable_directory_is_skipped(project, tmp_path):
    tree = tmp_path / "tree"
    good = tree / "alpha" / "docs" / "epics"
    write_epic(good, 1, "alpha epic", status="todo")
    locked = tree / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        text = render(tmp_path / "board.html", scan=tree)
    finally:
        locked.chmod(0o755)
    parse_ok(text)
    assert ">alpha epic</h3>" in text


def test_single_project_omits_the_project_label(project, tmp_path):
    write_epic(project, 1, "solo", status="todo")
    text = render(tmp_path / "board.html")
    assert '<span class="project">' not in text


def test_open_is_best_effort(project, tmp_path, monkeypatch, capsys):
    """A headless box has no browser; --open must not turn a written board into a failure."""
    write_epic(project, 1, "only", status="todo")

    def boom(_uri):
        raise RuntimeError("no display")

    monkeypatch.setattr(board.webbrowser, "open", boom)
    out = tmp_path / "board.html"
    render(out, extra=["--open"])
    assert out.exists()
    assert "could not open a browser" in capsys.readouterr().out
