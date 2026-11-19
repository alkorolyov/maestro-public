"""Project-level options — candidate work that belongs to no epic yet.

`epic option` is the intake below a goal; this is the intake above all of them. An idea
arrives mid-session and there is exactly one thing to do with it: park it in one command
and keep working. Without that, a one-thread-per-session limit does not produce focus, it
produces either a context switch or amnesia.

An option here is what an option is anywhere in maestro (modules/kanban.md): a line of
text with no status, no owner and no age — except that the CLI stamps the DATE it was
written, because the executor cannot feel time pass and an idea from June should not read
like one from this morning.

They live in `docs/progress.md` under `## Up next`, which core rule 10 already reserves
for candidate work. No new file and no new record kind: an option is not a record, it is
a line somebody might one day commit to.
"""
import re
import sys
from datetime import date

from .frontmatter import ROOT


PROGRESS = ROOT / "docs" / "progress.md"
UP_NEXT = "## Up next"
UP_NEXT_RE = re.compile(r"^##\s+Up next[^\n]*\n", re.MULTILINE)
NEXT_H2_RE = re.compile(r"^##\s", re.MULTILINE)
# A parked line: "- 2026-01-01 — text", or a bare "- text" written before this verb
# existed. The placeholder the template ships with is not one of them.
BULLET_RE = re.compile(r"^-\s+(?:(\d{4}-\d{2}-\d{2})\s+—\s+)?(.+?)\s*$", re.MULTILINE)
PLACEHOLDER = re.compile(r"^\{.*\}$")


def _section_span(text):
    """(start, end) character offsets of the ## Up next body, or (None, None)."""
    found = UP_NEXT_RE.search(text)
    if not found:
        return None, None
    tail = NEXT_H2_RE.search(text, found.end())
    return found.end(), (tail.start() if tail else len(text))


def parse(text):
    """The parked options under ## Up next, in file order, as (date, text) pairs."""
    start, end = _section_span(text)
    if start is None:
        return []
    return [(when, what) for when, what in BULLET_RE.findall(text[start:end])
            if what.strip() and not PLACEHOLDER.match(what.strip())]


def _rewrite(text, rows):
    """`text` with the ## Up next bullets replaced by `rows`, prose around them kept.

    Only the bullet lines move. The section's own explanatory paragraph — and every
    other section of the file — is byte-identical afterwards.
    """
    start, end = _section_span(text)
    if start is None:
        raise KeyError(UP_NEXT)
    body = text[start:end]
    kept = [ln for ln in body.splitlines()
            if not (ln.lstrip().startswith("- ") and BULLET_RE.match(ln.strip()))]
    while kept and not kept[-1].strip():
        kept.pop()
    lines = [f"- {when} — {what}" if when else f"- {what}" for when, what in rows]
    rebuilt = "\n".join(kept + ([""] if kept else []) + lines) or ""
    return text[:start] + rebuilt.rstrip("\n") + "\n\n" + text[end:]


def _load():
    if not PROGRESS.is_file():
        sys.exit(f"{PROGRESS.relative_to(ROOT)} does not exist — `maestro init` scaffolds "
                 "it, and project options live in its `## Up next` section.")
    text = PROGRESS.read_text()
    if _section_span(text)[0] is None:
        sys.exit(f'{PROGRESS.relative_to(ROOT)} has no "{UP_NEXT}" section, which is where '
                 "project options live (core rule 10). Add the heading, or re-scaffold "
                 "from templates/progress.md.")
    return text


def _show(rows, prefix="", stream=None):
    stream = stream or sys.stdout
    if not rows:
        print(f"{prefix}no options parked.", file=stream)
        return
    for i, (when, what) in enumerate(rows, 1):
        print(f"{prefix}{i:3d}. {when or '—':10s}  {what}", file=stream)


def option(args):
    """Add, drop or list the project's options. Exactly one action per call."""
    given = [x for x in (args.add, args.drop) if x is not None]
    if len(given) > 1 or (given and args.list):
        sys.exit('Pass exactly one of --add="text", --drop=<n>, --list.')

    text = _load()
    rows = parse(text)

    if args.list or not given:
        _show(rows)
        return

    if args.add is not None:
        what = args.add.strip()
        if not what:
            sys.exit("--add cannot be empty.")
        rows.append((str(date.today()), what))
        said = f"option {len(rows)} parked"
    else:
        if not 1 <= args.drop <= len(rows):
            print("Current options:", file=sys.stderr)
            _show(rows, prefix="  ", stream=sys.stderr)
            sys.exit(f"no option {args.drop} (there are {len(rows)}).")
        when, what = rows.pop(args.drop - 1)
        # No log line: progress.md is the live plan, not a record, and an option
        # above the commitment point is deliberately trace-light. An idea worth a trace
        # is worth an epic (`maestro epic new`), which has a log of its own.
        said = f'option {args.drop} dropped — "{what}"'

    PROGRESS.write_text(_rewrite(text, rows))
    print(f"{said} ({len(rows)} parked).")
