"""`maestro board render` — the epic board as ONE self-contained HTML file (ADR 7).

ADR 7 rules out a daemon, a port, a database and auth: status lives in git and the
board is a file you double-click. So this module writes a single page with its CSS
inline, no script, no network reference — it renders identically from `file://`.

Two shapes carry over from the markdown board in `indexes.py`:

  * `blocked_by` is a FLAG, never a state. A blocked epic stays in the column of the
    state it is blocked IN; there is no fourth column. The Blocked strip below the
    columns REPEATS those cards (and names blocked items, which have no card of their
    own) together with the state they are stuck in.
  * every value shown is read back from record frontmatter, so the page can be thrown
    away and rebuilt at any time.

`--scan` sweeps sibling projects one or two levels below a directory. That sweep is
strictly READ-ONLY across projects: the only path this module ever writes is --output.
"""
import html
import os
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .epics import blocked_reason, counts_text, items_of
from .frontmatter import EPIC_DIR, ROOT
from .indexes import load_epics

STATES = (("review", "REVIEW"), ("todo", "TODO"), ("active", "ACTIVE"), ("done", "DONE"))

# How deep below a --scan root a project may sit. Projects live at <scan>/<project>
# or <scan>/<org>/<project>; deeper is a checkout inside a checkout, not a project.
SCAN_DEPTHS = (1, 2)


# ── collecting cards ─────────────────────────────────────────────────────────

class Card:
    """One epic, plus where it came from and how to link to it."""

    def __init__(self, fm, project, path):
        self.fm = fm
        self.project = project
        self.path = path

    @property
    def number(self):
        return self.fm.get("epic")

    @property
    def status(self):
        return str(self.fm.get("status") or "todo")


def _epic_dirs(scan_root):
    """Every `<project>/docs/epics` one or two levels below `scan_root`.

    Skips what it cannot read, and refuses to leave the tree: a symlinked project
    whose real location is outside `scan_root` is not scanned.
    """
    root = Path(scan_root).expanduser()
    try:
        real_root = root.resolve(strict=True)
    except OSError:
        return []

    found = []
    level = [root]
    for depth in range(1, max(SCAN_DEPTHS) + 1):
        nxt = []
        for parent in level:
            try:
                children = sorted(p for p in parent.iterdir() if p.is_dir())
            except OSError:
                continue                      # unreadable directory: skip, never fail
            for child in children:
                try:
                    real = child.resolve()
                except OSError:
                    continue
                if real != real_root and real_root not in real.parents:
                    continue                  # symlink pointing out of the scanned tree
                nxt.append(child)
                if depth in SCAN_DEPTHS:
                    d = child / "docs" / "epics"
                    try:
                        if d.is_dir() and any(d.glob("epic_*.md")):
                            found.append(d)
                    except OSError:
                        continue              # no permission to look: skip, never fail
        level = nxt
    return found


def _real(path):
    """Identity of a directory for de-duplication, symlinks resolved."""
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def _project_name(epic_dir):
    """The project a `<project>/docs/epics` directory belongs to."""
    return epic_dir.parent.parent.name


def collect(epic_dir=None, scan=None):
    """(cards, skipped, projects) for the current project and any scanned ones.

    `skipped` is [(path, why)] — a record that would not parse is reported on the page,
    never crashed on.
    """
    epic_dir = Path(epic_dir) if epic_dir is not None else EPIC_DIR
    dirs, seen = [epic_dir], {_real(epic_dir)}
    if scan:
        for d in _epic_dirs(scan):
            if _real(d) not in seen:
                seen.add(_real(d))
                dirs.append(d)

    cards, skipped, projects = [], [], []
    for d in dirs:
        name = _project_name(d)
        if name not in projects:
            projects.append(name)
        errors = []
        try:
            records = load_epics(d, errors=errors)
        except OSError as exc:                # unreadable directory mid-scan
            skipped.append((d, str(exc)))
            continue
        skipped += errors
        for fm in records:
            cards.append(Card(fm, name, d / f"{fm['_slug']}.md"))
    return cards, skipped, projects


# ── rendering ────────────────────────────────────────────────────────────────

def _e(value):
    """Every record-derived value goes through here: titles, reasons and outcomes are
    free text and do contain `&`, `<` and quotes."""
    return html.escape(str(value), quote=True)


def _href(path, out_dir):
    """A relative link that resolves under `file://` from the written page."""
    try:
        rel = os.path.relpath(str(path), str(out_dir))
    except ValueError:                        # different drive (Windows): fall back
        rel = str(path)
    return quote(rel.replace(os.sep, "/"))


CSS = """
:root {
  color-scheme: light dark;
  --bg: #f4f5f7;
  --panel: #ffffff;
  --card: #ffffff;
  --ink: #1b1f24;
  --ink-dim: #5c6672;
  --line: #d8dde3;
  --accent: #2b6cb0;
  --blocked: #b03a2e;
  --blocked-bg: #fdeceb;
  --done: #2f7a4d;
  --shadow: 0 1px 2px rgba(20, 25, 32, .10);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171c;
    --panel: #1b1f26;
    --card: #222831;
    --ink: #e7ebf0;
    --ink-dim: #9aa5b1;
    --line: #333c47;
    --accent: #7fb2e5;
    --blocked: #f08a7c;
    --blocked-bg: #3a2320;
    --done: #7fc99b;
    --shadow: 0 1px 2px rgba(0, 0, 0, .45);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 1.5rem clamp(.75rem, 3vw, 2.5rem) 3rem;
  background: var(--bg);
  color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
h1 { font-size: 1.4rem; margin: 0 0 .25rem; letter-spacing: .01em; }
h2 { font-size: .8rem; margin: 0; text-transform: uppercase; letter-spacing: .09em; }
h3 { font-size: .98rem; margin: .15rem 0 .4rem; line-height: 1.35; }
a { color: inherit; text-decoration: none; }
.meta { margin: 0; color: var(--ink-dim); font-size: .82rem; }
.meta code { font-size: .8rem; }
header { border-bottom: 1px solid var(--line); padding-bottom: .9rem; margin-bottom: 1.2rem; }
.board {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 17rem), 1fr));
  gap: 1rem;
  align-items: start;
}
.column {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: .8rem .8rem 1rem;
  min-width: 0;
}
.column-head {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: .5rem; color: var(--ink-dim); margin-bottom: .7rem;
}
.count { font-size: .78rem; color: var(--ink-dim); }
.card {
  display: block;
  background: var(--card);
  border: 1px solid var(--line);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: .55rem .7rem .6rem;
  margin-bottom: .6rem;
  box-shadow: var(--shadow);
  overflow-wrap: anywhere;
}
.card:last-child { margin-bottom: 0; }
.card:hover { border-color: var(--accent); }
.card.is-blocked { border-left-color: var(--blocked); }
.card.is-done { border-left-color: var(--done); }
.tagline { display: flex; flex-wrap: wrap; gap: .4rem; align-items: baseline;
           font-size: .72rem; color: var(--ink-dim); letter-spacing: .04em; }
.project { text-transform: uppercase; font-weight: 600; }
.num { font-variant-numeric: tabular-nums; }
.counts { margin: 0; font-size: .78rem; color: var(--ink-dim); font-variant-numeric: tabular-nums; }
.outcome { margin: .4rem 0 0; font-size: .8rem; color: var(--ink-dim); }
.outcome b { color: var(--done); font-weight: 600; }
.flag {
  margin: .45rem 0 0; padding: .3rem .45rem;
  background: var(--blocked-bg); color: var(--blocked);
  border-radius: 4px; font-size: .78rem;
}
.flag b { letter-spacing: .06em; }
.panel {
  margin-top: 1.4rem; background: var(--panel);
  border: 1px solid var(--line); border-radius: 8px; padding: .9rem 1rem 1rem;
}
.panel h2 { margin-bottom: .6rem; color: var(--ink-dim); }
.wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .84rem; }
th, td { text-align: left; padding: .35rem .6rem .35rem 0; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--ink-dim); font-weight: 600; font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; }
tr:last-child td { border-bottom: 0; }
.empty { color: var(--ink-dim); font-style: italic; font-size: .85rem; margin: 0; }
footer { margin-top: 2rem; color: var(--ink-dim); font-size: .78rem;
         border-top: 1px solid var(--line); padding-top: .8rem; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
       background: var(--bg); padding: .05rem .3rem; border-radius: 3px; }
"""


def _card_html(card, out_dir, show_project):
    reason = blocked_reason(card.fm)
    classes = ["card"]
    if reason:
        classes.append("is-blocked")
    if card.status == "done":
        classes.append("is-done")

    tags = []
    if show_project:
        tags.append(f'<span class="project">{_e(card.project)}</span>')
    tags.append(f'<span class="num">epic {_e(card.number)}</span>')

    parts = [f'<a class="{" ".join(classes)}" href="{_href(card.path, out_dir)}">',
             f'  <div class="tagline">{"".join(tags)}</div>',
             f'  <h3>{_e(card.fm.get("title") or card.path.stem)}</h3>',
             f'  <p class="counts">{_e(counts_text(card.fm))}</p>']
    if reason:
        parts.append(f'  <p class="flag"><b>BLOCKED</b> — {_e(reason)}</p>')
    if card.status == "done" and card.fm.get("outcome"):
        parts.append(f'  <p class="outcome"><b>Outcome:</b> {_e(card.fm["outcome"])}</p>')
    parts.append("</a>")
    return "\n".join(parts)


def _blocked_rows(cards, show_project):
    """Every blocked epic AND blocked item, with the state it is blocked IN.

    A repeat of the flagged cards, not a move: the columns above still hold them.
    """
    rows = []
    for card in cards:
        who = f"epic {_e(card.number)}"
        if show_project:
            who = f"{_e(card.project)} · {who}"
        if blocked_reason(card.fm):
            rows.append((f"{who} — {_e(card.fm.get('title', ''))}",
                         _e(card.status), _e(blocked_reason(card.fm))))
        for it in items_of(card.fm):
            reason = blocked_reason(it)
            if reason:
                rows.append((f"{who} / item {_e(it.get('id', '?'))} — {_e(it.get('title', ''))}",
                             _e(it.get("status", "")), _e(reason)))
    return rows


def build_html(cards, skipped, projects, out_path, now=None):
    """The whole page: one string, no external reference of any kind."""
    out_dir = Path(out_path).parent
    show_project = len(projects) > 1
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    where = ", ".join(_e(p) for p in projects) or "—"
    n_blocked = sum(1 for c in cards if blocked_reason(c.fm))

    head = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Epic board — {where}</title>",
        f"<style>{CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        "<h1>Epic Board</h1>",
        f'<p class="meta">{where} · {len(cards)} epic(s) · {n_blocked} blocked · '
        f"generated {stamp}</p>",
        "</header>",
        '<main class="board">',
    ]

    body = []
    for state, heading in STATES:
        rows = [c for c in cards if c.status == state]
        body.append('<section class="column">')
        body.append('<div class="column-head">'
                    f"<h2>{heading}</h2><span class=\"count\">{len(rows)}</span></div>")
        if rows:
            body += [_card_html(c, out_dir, show_project) for c in rows]
        else:
            body.append('<p class="empty">nothing here</p>')
        body.append("</section>")
    body.append("</main>")

    blocked = _blocked_rows(cards, show_project)
    body += ['<section class="panel">', "<h2>Blocked</h2>",
             '<p class="empty">A flag, not a state — every card below is still counted in '
             "its own column above.</p>"]
    if blocked:
        body += ['<div class="wrap">', "<table>",
                 "<tr><th>Card</th><th>State</th><th>Reason</th></tr>"]
        for who, state, reason in blocked:
            body.append(f"<tr><td>{who}</td><td>{state}</td><td>{reason}</td></tr>")
        body += ["</table>", "</div>"]
    else:
        body.append('<p class="empty">Nothing blocked.</p>')
    body.append("</section>")

    if skipped:
        body += ['<section class="panel">', "<h2>Skipped records</h2>",
                 '<div class="wrap">', "<table>",
                 "<tr><th>Path</th><th>Why</th></tr>"]
        for path, why in skipped:
            body.append(f"<tr><td><code>{_e(path)}</code></td><td>{_e(why)}</td></tr>")
        body += ["</table>", "</div>", "</section>"]

    foot = ["<footer>",
            "Generated file — do not edit by hand; every value is read back from "
            "<code>docs/epics/epic_*.md</code> frontmatter. "
            "Rebuild with <code>maestro board render</code>.",
            "</footer>", "</body>", "</html>"]

    return "\n".join(head + body + foot) + "\n"


# ── verb ─────────────────────────────────────────────────────────────────────

def board_render(args):
    out = Path(getattr(args, "output", None) or (ROOT / "docs" / "epics" / "board.html"))
    out = out.expanduser()
    cards, skipped, projects = collect(scan=getattr(args, "scan", None))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(cards, skipped, projects, out), encoding="utf-8")

    said = f"Wrote {out} — {len(cards)} epic(s) across {len(projects)} project(s)"
    if skipped:
        said += f", {len(skipped)} record(s) skipped"
    print(said + ".")

    if getattr(args, "open", False):
        try:                                  # best-effort: a headless box has no browser
            webbrowser.open(out.resolve().as_uri())
        except Exception as exc:
            print(f"(could not open a browser: {exc})")
