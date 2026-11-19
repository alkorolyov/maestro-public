"""Epic records — docs/epics/epic_NN_<slug>.md (ADR 7, modules/kanban.md).

An epic is a standing goal that outlives one session. Its items are rows in the
record's own frontmatter — one item is one session, one branch — and the tasks below
them are commits, recorded nowhere else.

Three mechanics carry the whole design:

  * `blocked_by` is a FLAG, never a state. It is settable in any status and carries a
    reason; the status keeps saying where the work actually stands.
  * The WIP limits REFUSE. Two epics in progress per project, one item in progress per
    epic — a limit that can be passed by reflex is not a limit, so there is no --force.
  * `done_when` is the epic's own closing condition, in frontmatter rather than prose,
    and `close` refuses until every clause carries the result it MEASURED. The template
    always asked for a "Done when" paragraph; unchecked prose is how an epic closes on
    an activity report while its own condition sits three paragraphs up, unexamined.
"""
import re
import sys
from datetime import date

from .frontmatter import slugify, EPIC_DIR, FM_RE, ROOT, load, next_num, write


# review: waits for a person, no session picks it up. todo: approved, nobody on it, any
# session may take it. active: a session is on it NOW (a paused session is not active).
# Old records say `in_progress`; frontmatter.norm_epic reads it as `active`.
EPIC_STATUSES = ("review", "todo", "active", "done")
# An ITEM can also be `dropped`: measured and deliberately abandoned, with its reason.
# It is settled, like `done`, so neither the close nor any open-item count waits on it.
# An epic has no such state — an abandoned epic still closes, and its outcome says so.
ITEM_STATUSES = ("todo", "in_progress", "done", "dropped")
SETTLED_ITEM_STATUSES = ("done", "dropped")

# An item records WHEN it entered its state. The executor reads a clock but never
# NOTICES time passing, so ageing has to be written down by the tool rather than
# remembered by the agent — this is the flow half of Kanban (practice 3).
STALE_ITEM_DAYS = 7         # one item is one session; a week in_progress is a stall
STALE_BLOCK_DAYS = 14       # a flag nobody has cleared in a fortnight is not a flag

# Frontmatter every epic carries. `new` writes all of them; a record missing one was
# hand-written, which is what check K3 reports (rule 1 — records only via the CLI).
REQUIRED_KEYS = ("epic", "title", "status", "opened", "closed", "blocked_by",
                 "items", "options", "outcome")

# `arc` is optional frontmatter (a name from maestro.toml `[[arcs]]`), deliberately
# NOT in REQUIRED_KEYS: projects that declare no arcs never carry it.

# Canonical key order for a done_when clause. `check` is dropped when empty, so a
# clause carrying no command stays a two-line row rather than a row with a blank.
DONE_WHEN_KEYS = ("id", "text", "check", "result")

MAX_EPICS_IN_PROGRESS = 2   # per project (ADR 7); the default of policy [epics] max_in_progress
MAX_ITEMS_IN_PROGRESS = 1   # per epic — core rule 9 said as a WIP limit

LOG_HEADING = "## Log"
LOG_INTRO = ("_Append-only. One dated line per session; written by the CLI's "
                "`--note`, never by hand._")
# Reads accept the pre-2.15 heading too; append_log rewrites it to `## Log` on the next write.
LOG_RE = re.compile(r"^##\s+(?:Log|Ledger)\b[^\n]*\n", re.MULTILINE)
NEXT_H2_RE = re.compile(r"^##\s", re.MULTILINE)
LOG_DATE_RE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\b", re.MULTILINE)

# A hex run long enough to be a git sha and carrying BOTH a digit and an a-f letter.
# Both halves earn their place. Without the letter, an ordinary number in the same
# string ("2313000", an id, a date) would be resolved as a sha. Without the digit, an
# English word spelled from hex letters would be — "defaced" and "effaced" are seven
# letters each and would both be sent to `git rev-parse`. A real sha fails this test
# only when it happens to be all-digit or all-letter, which is roughly 1 in 1,400 for
# the 7-char short form and rarer as it lengthens; missing one is a silent pass, while
# a false positive REFUSES a correct record, so the trade runs this way on purpose.
# The boundaries also refuse anything sitting inside a PATH or a filename
# (`docs/archive/beefed01.md`), which is a citation already and not a sha to resolve.
# A sentence-ending full stop is still allowed: `.` counts as a boundary only when it is
# not followed by more word characters, so "…at 4779311c." reads as a sha and
# "beefed01.md" does not.
SHA_TOKEN_RE = re.compile(r"(?<![0-9A-Za-z/._-])"
                          r"(?=[0-9a-f]{7,40}(?![0-9A-Za-z/_-])(?!\.[0-9A-Za-z]))"
                          r"(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])"
                          r"[0-9a-f]+")


# ── pure helpers (no I/O — the CLI verbs and the checks share them) ───────────

def items_of(fm: dict) -> list:
    """The epic's item rows, always a list of dicts."""
    return [it for it in (fm.get("items") or []) if isinstance(it, dict)]


def item_label(item: dict) -> str:
    return f"item {item.get('id', '?')} \"{item.get('title', '')}\""


def items_in_progress(fm: dict) -> list:
    return [it for it in items_of(fm) if it.get("status") == "in_progress"]


def blocked_reason(card: dict) -> str:
    """The blocked flag's reason on an epic OR an item, '' when the card is not flagged."""
    return str(card.get("blocked_by") or "").strip()


def options_of(fm: dict) -> list:
    """The epic's OPTIONS — candidate work above the commitment point.

    An option is a line of text and nothing else: no id, no status, no owner, no age.
    That is the whole point. Kanban's commitment point separates things that MIGHT be
    done from work that IS being done, and an unlimited `todo` queue is what collapses
    the two — which is how a project ends up with a 272-row table wearing a status
    column. Pulling an option (`epic option --pull`) is the act of committing.
    """
    return [str(o) for o in (fm.get("options") or []) if str(o).strip()]


def done_when_of(fm: dict) -> list:
    """The epic's closing condition, always a list of clause dicts.

    A clause is `text` (the condition), an optional `check` (the command or artifact
    that answers it) and `result` (what that check actually SAID, filled in at close).
    Empty `result` means unanswered — the state `close` refuses to write over.
    """
    return [c for c in (fm.get("done_when") or []) if isinstance(c, dict)]


def clause_label(clause: dict) -> str:
    return f"clause {clause.get('id', '?')} \"{clause.get('text', '')}\""


def clause_result(clause: dict) -> str:
    """What the clause's check measured, '' while it is unanswered."""
    return str(clause.get("result") or "").strip()


def unanswered_clauses(fm: dict) -> list:
    return [c for c in done_when_of(fm) if not clause_result(c)]


def done_when_counts(fm: dict) -> tuple:
    """(answered, total) over the epic's done_when clauses."""
    clauses = done_when_of(fm)
    return sum(1 for c in clauses if clause_result(c)), len(clauses)


def normalise_done_when(fm: dict) -> list:
    """Every clause carries an id and an explicit `result` slot, in a stable key order.

    The empty slot is written out rather than omitted: an unanswered condition should be
    visible in the record, not inferred from a missing key.
    """
    out = []
    for i, clause in enumerate(done_when_of(fm), 1):
        row = {"id": int(clause.get("id") or i), "text": str(clause.get("text", "")).strip()}
        check = str(clause.get("check") or "").strip()
        if check:
            row["check"] = check
        row["result"] = clause_result(clause) or None
        out.append(row)
    return out


def item_age(item: dict, today=None) -> int:
    """Days the item has been in its current state, or -1 when it carries no stamp."""
    stamped = _as_date(item.get("since"))
    return ((today or date.today()) - stamped).days if stamped else -1


def block_age(item: dict, today=None) -> int:
    """Days the item has carried its blocked flag, or -1 when unstamped/unflagged."""
    stamped = _as_date(item.get("blocked_since"))
    return ((today or date.today()) - stamped).days if stamped else -1


def _as_date(value):
    """A frontmatter date as a date object, or None when it is not one."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def normalise_items(fm: dict) -> list:
    """Every item carries `since`. Written on each save, so the stamp cannot be skipped.

    Records predating the stamp are dated from the epic's `opened` — honest, because the
    item cannot have entered its state before the epic existed, and it never invents a
    date closer to today than the truth.
    """
    fallback = str(fm.get("opened") or date.today())
    out = []
    for it in items_of(fm):
        row = dict(it)
        row.setdefault("since", fallback)
        if blocked_reason(row):
            row.setdefault("blocked_since", fallback)
        else:
            row.pop("blocked_since", None)
        out.append(row)
    return out


def item_counts(fm: dict) -> tuple:
    """(done, total) over the epic's items."""
    items = items_of(fm)
    return sum(1 for it in items if it.get("status") == "done"), len(items)


def items_dropped(fm: dict) -> int:
    """How many of the epic's items were dropped — settled, but not done."""
    return sum(1 for it in items_of(fm) if it.get("status") == "dropped")


def counts_text(fm: dict) -> str:
    """The board's item count: `items 3/5 done`, plus `, 1 dropped` when any were."""
    done, total = item_counts(fm)
    dropped = items_dropped(fm)
    return f"items {done}/{total} done" + (f", {dropped} dropped" if dropped else "")


def _log_section(body: str) -> str:
    """The text of the body's ## Log section, '' when there is none."""
    m = LOG_RE.search(body)
    if not m:
        return ""
    tail = NEXT_H2_RE.search(body, m.end())
    return body[m.end():tail.start() if tail else len(body)]


def log_dates(body: str) -> list:
    """Every ISO date opening a line of the body's ## Log section, in file order."""
    return LOG_DATE_RE.findall(_log_section(body))


def log_entries(body: str) -> list:
    """Every log entry as one string, in file order.

    An entry starts at a `- YYYY-MM-DD` line and runs until the next one, so the
    indented continuation lines a long note wraps onto stay with their date.
    """
    section = _log_section(body)
    starts = [m.start() for m in LOG_DATE_RE.finditer(section)]
    return [section[a:b].strip() for a, b in zip(starts, starts[1:] + [len(section)])]


# A note that opens with today's date repeats the prefix append_log adds: the model
# types "2026-01-04 items cut …" and the log reads "2026-01-04 — 2026-01-04 items cut …"
# (the model types the date and the CLI adds it again). The CLI owns the date; that one
# is dropped. Any OTHER date is content and stays.
_OWN_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*(?:[—–-]|:)?\s*")


def strip_own_date(note: str) -> str:
    """`note` without a leading today's-date prefix (see _OWN_DATE_RE)."""
    m = _OWN_DATE_RE.match(note)
    if m and m.group(1) == str(date.today()):
        return note[m.end():]
    return note


def append_log(body: str, line: str) -> str:
    """Append `line` to the body's ## Log section, creating the section if absent.

    Append-only: nothing already in the section (or anywhere else in the body) moves.
    """
    m = LOG_RE.search(body)
    if not m:
        return body.rstrip("\n") + f"\n\n{LOG_HEADING}\n\n{LOG_INTRO}\n\n{line}\n"
    tail = NEXT_H2_RE.search(body, m.end())
    end = tail.start() if tail else len(body)
    section = body[m.end():end].rstrip("\n")
    rest = "\n" + body[end:] if tail else ""
    heading = f"{LOG_HEADING}\n"            # a legacy `## Ledger` heading migrates here
    return body[:m.start()] + heading + section + f"\n{line}\n" + rest


# ── moving an item between epics ─────────────────────────────────────────────
#
# When an epic is split, a row that goes elsewhere LEAVES this epic: it is deleted from
# `items:` and the log keeps the one line that says where it went. There is no `moved`
# state — a moved row is not work of this epic, so it must not sit in any count. The
# precedent this replaces was a `todo` row re-titled "MOVED -> epic N item M", which the
# board read as unfinished work forever (13 rows moved out, yet the board still said
# "items 7/20 done" and a close listed all 13 as "left todo").
#
# Item ids are stable: the rows that stay keep theirs and the gap stays a gap. A new row
# never reuses a moved-out id either — the log line below is the high-water mark, so a
# later "item 20" can never be confused with a moved-out item 20.

MOVE_OUT_RE = re.compile(r"^-\s+\d{4}-\d{2}-\d{2}\s+—\s+item\s+(\d+)\s.*"
                         r"\smoved -> epic \d+ item \d+\s*$", re.DOTALL)
MOVE_IN_RE = re.compile(r"^-\s+\d{4}-\d{2}-\d{2}\s+—\s+item\s+\d+\s+moved in from "
                        r"epic \d+ item \d+\s*$")
MOVED_TO_RE = re.compile(r"^\s*epic\s+(\d+)\s+item\s+(\d+)\s*$", re.I)


# The line a drop or a re-open writes. It quotes the reason, whose words can be anything
# ("measured, not merged"), so like a move line it is bookkeeping, never a work claim.
DROP_LINE_RE = re.compile(r"^-\s+\d{4}-\d{2}-\d{2}\s+—\s+item\s+\d+\s+"
                          r"(?:dropped|re-opened) — ")


def is_move_line(entry: str) -> bool:
    """True for a log entry written by a move (either side) — bookkeeping, not work."""
    return bool(MOVE_OUT_RE.match(entry) or MOVE_IN_RE.match(entry))


def is_drop_line(entry: str) -> bool:
    """True for a log entry written by a drop or a re-open — bookkeeping, not work."""
    return bool(DROP_LINE_RE.match(entry))


def moved_out_ids(body: str) -> list:
    """Ids the log says left this epic, in log order."""
    return [int(m.group(1)) for m in map(MOVE_OUT_RE.match, log_entries(body)) if m]


def next_item_id(items: list, body: str) -> int:
    """The id a new row gets: past every row present AND every row that moved out."""
    ids = [int(it.get("id", 0)) for it in items] + moved_out_ids(body)
    return max(ids, default=0) + 1


def move_out_line(item: dict, target: int, target_item: int) -> str:
    return (f"- {date.today()} — item {item.get('id')} '{item.get('title', '')}' "
            f"moved -> epic {target} item {target_item}")


def move_in_line(new_id: int, source: int, source_item: int) -> str:
    return f"- {date.today()} — item {new_id} moved in from epic {source} item {source_item}"


# ── the item shape (the lane controls) ───────────────────────────────────────
#
# An item title is a CONTRACT, not a label. One item read "port the remaining read
# sites", was held by a single planner for days, and turned out to cover far more files —
# a number nobody knew at the time, because the title never said. It was never one
# session, so the WIP limit that exists to keep it to one never fired; the brief written
# from it named no file list; and dozens of children were spawned against a scope that
# had never been stated. `maestro epic option` is where an
# unscoped idea lives (that is what the intake is FOR). Crossing the commitment point
# means answering two questions, so `--add` now refuses a title that answers neither:
#
#   the done-test   `Done:` or `Done-test:` — the command or artifact that ends the item
#   the scope       `N files` / `N sites`   — how wide it reaches, counted before the brief
#
# The scope count is then judged by SHAPE, not by size. A wide count is not the problem
# in itself — a large compiler-driven rename is one mechanical pass, and cutting
# it into child units is exactly how it should be run. What cannot be wide is a DESIGN
# item: one seam, one decision, one judgement call per session. So above
# `[items] max_files` (policy.py) a title is accepted when it declares the plan —
# `N files in K units` — and refused when it does not, with the split named rather than
# the number complained about.
#
# The third refusal is about certainty rather than size: a title carrying TBD, "to be
# decided", "decide whether" or "open question" is a QUESTION, and a question cannot be
# closed with evidence (rule 2). The decision is its own small item — an ADR, or a step-0
# measurement — and the work that depends on it follows once it has an answer.
#
# The two caps at the end are the same rule applied to LENGTH: a board line is an index
# entry, and prose belongs in the record body or an ADR.

DONE_TEST_RE = re.compile(r"\bdone(?:-test)?\s*:", re.I)
SCOPE_RE = re.compile(r"\b(\d+)\s+(files?|sites?)\b", re.I)
# The plan that makes a wide item legal: "N files in K units".
UNIT_PLAN_RE = re.compile(r"\bin\s+(\d+)\s+units?\b", re.I)
# A title that is still a question. `TBD` takes word boundaries — the phrases do not
# need them, and would only be weakened by them.
OPEN_DECISION_RE = re.compile(r"\btbd\b|to be decided|decide whether|open question", re.I)

ITEM_SHAPE = ('maestro epic item --id=<N> --add="<what changes> — 12 files — '
              'Done: cargo nextest run -p engine_core"')


def scope_counts(title: str) -> list:
    """Every `N files` / `N sites` the title states, as (count, unit)."""
    return [(int(n), unit.lower()) for n, unit in SCOPE_RE.findall(title or "")]


def item_shape_refusal(title: str, root=None) -> str:
    """Why this item title is not a contract, or '' when it is one.

    Refused rather than warned, for the reason `--evidence` is refused rather than
    warned: an item nobody can size is an item nobody can close, and by the time the
    scope is visible the session that would have split it is long gone.

    The size limit judges SHAPE: over `max_files` a MECHANICAL pass is legal once it
    declares its plan (`N files in K units`), a DESIGN item never is.
    """
    from . import policy

    text = (title or "").strip()
    if not text:
        return "--add cannot be empty: an item with no title is not a card."

    root = ROOT if root is None else root
    missing = []
    if not DONE_TEST_RE.search(text):
        missing.append("a done-test marker (`Done:` or `Done-test:`) — the command or "
                       "artifact that ENDS the item")
    if not scope_counts(text):
        missing.append("a scope marker (`N files` or `N sites`) — how wide it reaches, "
                       "counted before the brief is written")
    if missing:
        return ("An item title is a CONTRACT, and this one is missing "
                + " and ".join(missing) + ".\nExpected shape:\n  " + ITEM_SHAPE
                + "\nNot scoped yet? That is what the intake is for — "
                "`maestro epic option --id=<N> --add=\"...\"` parks it above the "
                "commitment point until it can state both.")

    if OPEN_DECISION_RE.search(text):
        return ("an item is not a question; record the decision (ADR / step-0 "
                "measurement) as its own small item first. This title still carries an "
                f"open decision ({OPEN_DECISION_RE.search(text).group(0)}), and a "
                "question cannot be closed with evidence — whatever the item does, the "
                "answer arrives mid-session and re-scopes it. Decide first, in a card "
                "whose done-test is the ADR or the measurement; the work that depends on "
                "the answer is the item after it.")

    max_files = policy.setting(root, "items", "max_files")
    widest, unit = max(scope_counts(text))
    if widest > max_files and not UNIT_PLAN_RE.search(text):
        return (f"split it before the brief: {widest} {unit} > max_files {max_files} "
                f"({policy.FILENAME} [items] max_files). Over max_files an item must be a "
                "MECHANICAL pass — a compiler-driven sweep the planner cuts into child "
                f"units — and must declare it as \"{widest} {unit} in K units\". A DESIGN "
                "item (one seam, one decision) is never this wide: split it off first and "
                "give it its own done-test.")

    cap = policy.setting(root, "board", "max_title_chars")
    if len(text) > cap:
        return (f"--add is {len(text)} chars and the cap is {cap} ({policy.FILENAME} "
                "[board] max_title_chars): the board line is an index entry; the "
                "reasoning belongs in the record body / ADR.")
    return ""


def open_items(fm: dict) -> list:
    """The epic's items still to do — `todo` or `in_progress`. Settled ones (done,
    dropped) do not crowd."""
    return [it for it in items_of(fm) if it.get("status") not in SETTLED_ITEM_STATUSES]


def epic_size_refusal(epic_id: int, fm: dict, root=None) -> str:
    """Why no further item can be added to this epic, or '' when there is room.

    The WIP limit above (one item in_progress) governs what is being WORKED; this one
    governs what is COMMITTED. An epic that keeps accepting items becomes the 272-row
    table modules/kanban.md describes: a queue nobody re-reads, whose items are pulled by
    whichever session happens to be running rather than by a plan. One dsh session runs
    one epic, so the epic has to be a session's worth of work.
    """
    from . import policy

    cap = policy.setting(ROOT if root is None else root, "epics", "max_open_items")
    count = len(open_items(fm))
    if count < cap:
        return ""
    return (f"epic {epic_id} has {count} open items (max_open_items {cap}): one dsh "
            "session runs one epic — split it: `maestro epic new --slug=...` and move "
            f"items with `maestro epic item --id={epic_id} --item=<k> --move-to=<new>`, "
            "blocked_by the first half")


def note_refusal(note, root=None, flag="--note") -> str:
    """Why this `--note` (or a dropped item's `--reason`, which is logged too) cannot go
    on the board, or '' when it fits.

    Same rule as the title cap, one line down: the log is a dated index of what happened,
    and a 1,200-character note is a record body that landed in the wrong file — it also
    hides the command that follows it when a guard quotes the call back.
    """
    from . import policy

    text = str(note or "")
    cap = policy.setting(ROOT if root is None else root, "board", "max_note_chars")
    if len(text) <= cap:
        return ""
    return (f"{flag} is {len(text)} chars and the cap is {cap} ({policy.FILENAME} "
            "[board] max_note_chars): the board line is an index entry; the reasoning "
            "belongs in the record body / ADR.")


def _epic_wip_refusal(records: dict, epic_id: int, root=None) -> str:
    """Message refusing a move to in_progress, or '' when a slot is free."""
    from . import policy
    cap = policy.setting(ROOT if root is None else root, "epics", "max_in_progress")
    holders = [(n, fm) for n, (_, fm) in sorted(records.items())
               if n != epic_id and fm.get("status") == "active"]
    if len(holders) < cap:
        return ""
    named = ", ".join(f'epic_{n} "{fm.get("title", "")}"' for n, fm in holders)
    first = holders[0][0]
    return (f"epic_{epic_id} cannot move to active: {len(holders)} epics already are, "
            f"and the limit is {cap} per project ({policy.FILENAME} [epics] max_in_progress). "
            f"{named} hold the slots. "
            f"Free one first — `maestro epic close --id={first} --outcome=\"...\"` or "
            f"`maestro epic update --id={first} --status=todo`.")


def _item_wip_refusal(epic_id: int, fm: dict) -> str:
    """Message refusing to write an epic whose items break the one-in-progress limit."""
    running = items_in_progress(fm)
    if len(running) <= MAX_ITEMS_IN_PROGRESS:
        return ""
    ids = ", ".join(str(it.get("id", "?")) for it in running)
    return (f"epic_{epic_id} has {len(running)} items in_progress (items {ids}) and the limit is "
            f"{MAX_ITEMS_IN_PROGRESS} per epic — one session, one branch. "
            f"{item_label(running[0])} holds the slot; set the others back to todo, or finish "
            f"them, before updating this epic.")


def _done_when_refusal(epic_id: int, fm: dict) -> str:
    """Message refusing a close whose condition is absent or unmeasured, or ''.

    Same contract as `--evidence` on an item: `done` is the claim that gates everything
    downstream (rule 2), so it is refused bare rather than warned about.
    """
    clauses = done_when_of(fm)
    if not clauses:
        return (f"epic_{epic_id} cannot close: it has no done_when clause, so nothing in "
                f"the record says what done MEANS. State the closing condition first — "
                f"`maestro epic done-when --id={epic_id} --add=\"...\" --check=\"...\"` — then "
                f"record what the check measured. An epic that cannot state its closing "
                f"condition has not finished; it has stopped.")
    missing = unanswered_clauses(fm)
    if not missing:
        return ""
    answered, total = done_when_counts(fm)
    named = "; ".join(clause_label(c) for c in missing)
    first = missing[0].get("id", "?")
    return (f"epic_{epic_id} cannot close: {len(missing)} of {total} done_when clauses have "
            f"no measured result ({named}). Run each clause's check and record what it said "
            f"— `maestro epic done-when --id={epic_id} --clause={first} --result=\"...\"`. "
            f"--outcome states the capability delivered; the clause results are the "
            f"measurements behind it, and {answered}/{total} is not an answer.")


def unlink_exp(n: int) -> list[int]:
    """Remove experiment `n` from every epic's `exps` list; returns the epics changed.

    Goes through the same `write` as `epic update`, so each record's stamp stays valid.
    """
    changed = []
    for num, (path, fm) in sorted(load(EPIC_DIR, "epic").items()):
        have = _as_ints(fm.get("exps"))
        if n not in have:
            continue
        body = FM_RE.sub("", path.read_text())
        fm["exps"] = [x for x in have if x != n]
        body = append_log(body, f"- {date.today()} — unlinked exp {n} (record deleted)")
        write(path, fm, body)
        changed.append(num)
    return changed


def _render():
    """Rebuild the board after a write (imported late: indexes reads this module)."""
    from . import indexes
    indexes.render("epic")


def unresolvable_shas(evidence: str, root=None) -> list:
    """The sha-shaped tokens in `evidence` that git cannot stand behind. [] when fine.

    Evidence may legitimately be a merge sha, a test name, or an artifact path, so only
    the SHA-SHAPED tokens are judged and everything else is left alone. A token fails on
    one of two counts, and they are different failures:

      * it resolves to no commit at all — a typo, or a sha from another repo. The record
        then cites nothing, which is rule 2's failure exactly.
      * it resolves, but no branch or tag contains it — an ORPHAN. This is the one that
        actually happens: an executor commits, is asked to reword, and the first commit
        is stranded; the branch is deleted at merge and the sha the record kept is now
        reachable from nothing and dies at the next `git gc`. A tag can point at exactly
        such a commit, and only a human read of the reflog catches it before it enters the
        board.

    Returns [] — never a complaint — when git cannot answer (no git, not a repo, no
    commits yet). A guard that fires on a broken toolchain teaches people to bypass it.
    """
    import subprocess

    tokens = list(dict.fromkeys(SHA_TOKEN_RE.findall(evidence or "")))
    if not tokens:
        return []

    def git(*args):
        try:
            r = subprocess.run(["git", "-C", str(root or ROOT), *args],
                               capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    if git("rev-parse", "HEAD") is None:
        return []

    bad = []
    for tok in tokens:
        if git("rev-parse", "--verify", "--quiet", f"{tok}^{{commit}}") is None:
            bad.append((tok, "resolves to no commit in this repo"))
        elif not (git("branch", "--contains", tok) or git("tag", "--contains", tok)):
            bad.append((tok, "is an orphan — no branch or tag contains it, so it is "
                             "unreachable and the next `git gc` deletes it"))
    return bad


# ── links to experiments and ADRs ─────────────────────────────────────────────

def _as_ints(values) -> list[int]:
    """An epic's `exps` / `adrs` list as ints; a non-int entry written by hand is kept out."""
    out = []
    for v in values or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _link_numbers(field: str, flag: str, raw: str):
    """Parse `--exps=147,148` / `--adrs=31` into sorted unique ints that name records.

    Returns (numbers, refusal). A number is linkable only when its record exists under
    docs/experiments/ (exp_<NN>_*.md) or docs/adrs/ (adr_<NN>_*.md) — an epic that points
    at a record nobody wrote is a dangling link, not a trace.
    """
    nums = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            n = int(tok)
        except ValueError:
            return [], f"--{flag}={raw!r}: {tok!r} is not a record number (comma-separated ints)."
        if n < 0:
            return [], f"--{flag}={raw!r}: {n} is not a record number."
        nums.append(n)
    if not nums:
        return [], f"--{flag} needs at least one number, e.g. --{flag}=12,13."
    nums = sorted(set(nums))
    kind, sub = ("exp", "experiments") if field == "exps" else ("adr", "adrs")
    folder = ROOT / "docs" / sub
    missing = [n for n in nums
               if not any(folder.glob(f"{kind}_{n:02d}_*.md"))
               and not any(folder.glob(f"{kind}_{n}_*.md"))]
    if missing:
        which = ", ".join(str(n) for n in missing)
        return [], (f"--{flag}: no {kind} record for {which} under docs/{sub}/ "
                    f"(looked for {kind}_<NN>_*.md). Link only records that exist.")
    return nums, None


# ── verbs ─────────────────────────────────────────────────────────────────────

def declared_arcs(root=None) -> tuple:
    """Arc names declared in maestro.toml, () when none (or no readable declaration)."""
    from . import declaration
    try:
        decl = declaration.load(root or ROOT)
    except declaration.DeclarationError:
        return ()
    return decl.arc_names if decl else ()


def arc_refusal(name, root=None) -> str:
    """Refusal text when arcs are declared and `name` is not one of them."""
    arcs = declared_arcs(root)
    if name and arcs and name not in arcs:
        return (f"--arc={name!r} is not a declared arc ({', '.join(arcs)}). Arcs are declared "
                "in maestro.toml `[[arcs]]`.")
    return ""


def epic_new(args):
    EPIC_DIR.mkdir(parents=True, exist_ok=True)
    records = load(EPIC_DIR, "epic")
    n = next_num(records, EPIC_DIR, "epic")
    slug = slugify(args.slug)
    if not slug:
        sys.exit(f"--slug={args.slug!r} has no word characters to name a file with.")
    title = args.title or args.slug
    arc = (getattr(args, "arc", None) or "").strip()
    refusal = arc_refusal(arc)
    if refusal:
        sys.exit(refusal)
    today = str(date.today())
    path = EPIC_DIR / f"epic_{n:02d}_{slug}.md"
    fm = {
        "epic": n,
        "title": title,
        "status": "todo",
        "opened": today,
        "closed": None,
        "blocked_by": None,
        "done_when": [],
        "items": [],
        "options": [],
        "outcome": None,
        "exps": [],
        "adrs": [],
        "tags": [],
    }
    if arc:
        fm["arc"] = arc
    # No "**Done when**" paragraph: the closing condition is frontmatter now
    # (`epic done-when`), and two homes for one claim is how they drift apart.
    body = (f"\n# Epic {n} — {title}\n\n"
            "**Why**: \n\n"
            "**Out of scope**: \n\n"
            f"{LOG_HEADING}\n\n{LOG_INTRO}\n\n"
            f"- {today} — opened.\n")
    write(path, fm, body)
    _render()
    print(f"Created {path.relative_to(ROOT)} (status=todo)")


def epic_update(args):
    refusal = note_refusal(getattr(args, "note", None))
    if refusal:
        sys.exit(refusal)

    records = load(EPIC_DIR, "epic")
    if args.id not in records:
        sys.exit(f"epic_{args.id} not found.")
    path, fm = records[args.id]
    body = FM_RE.sub("", path.read_text())

    refusal = _item_wip_refusal(args.id, fm)
    if refusal:
        sys.exit(refusal)

    links = {}
    for field, flag in (("exps", "exps"), ("adrs", "adrs")):
        raw = getattr(args, field, None)
        if raw is None:
            continue
        nums, refusal = _link_numbers(field, flag, raw)
        if refusal:
            sys.exit(refusal)
        links[field] = nums

    if not (args.status or args.blocked_by is not None or args.title is not None
            or (args.note and args.note.strip()) or links
            or getattr(args, "arc", None) is not None
            or getattr(args, "runner", None) is not None):
        sys.exit("Nothing to do: `epic update` needs one of --status, --blocked-by, "
                 "--title, --arc, --runner, --note, --exps or --adrs.")

    updates, traces = {}, []
    if args.status:
        if args.status not in EPIC_STATUSES:
            sys.exit(f"--status must be one of: {', '.join(EPIC_STATUSES)}")
        if args.status == "done":
            sys.exit(f"--status=done is set by `maestro epic close --id={args.id} "
                     "--outcome=\"...\"`, which records what the epic delivered.")
        if args.status == "active" and fm.get("status") != "active":
            refusal = _epic_wip_refusal(records, args.id)
            if refusal:
                sys.exit(refusal)
        updates["status"] = args.status
        if args.status != "active" and fm.get("runner"):
            updates["runner"] = None        # nobody is on it any more
            traces.append(f"runner cleared — was: {fm.get('runner')}")
    runner_arg = getattr(args, "runner", None)
    if runner_arg is not None and "runner" not in updates:
        new_runner = runner_arg.strip()
        if new_runner != str(fm.get("runner") or ""):
            updates["runner"] = new_runner or None
            traces.append(f"runner set to {new_runner}" if new_runner
                          else f"runner cleared — was: {fm.get('runner')}")
    if args.blocked_by is not None:
        # A FLAG, not a state: setting or clearing it never touches `status`.
        # An empty value clears the flag.
        updates["blocked_by"] = args.blocked_by.strip() or None
    if args.title is not None:
        # Re-titling is a CORRECTION, so it leaves a revision trace (rule 1 — the same
        # contract as `epic item --title`): the old wording goes to the log, never vanishes.
        new_title = args.title.strip()
        if not new_title:
            sys.exit("--title cannot be empty: an epic with no title is not a record.")
        was = str(fm.get("title", "")).strip()
        if new_title == was:
            sys.exit(f"epic_{args.id} already carries that title.")
        updates["title"] = new_title
        traces.append(f"epic re-titled — was: {was}")
        # The body heading was written from the title when the record was scaffolded.
        # Move it in the same pass, or the frontmatter and the body drift apart and the
        # board renders one word while the record reads another.
        old_head = f"# Epic {args.id} — {was}"
        if old_head in body:
            body = body.replace(old_head, f"# Epic {args.id} — {new_title}", 1)

    if getattr(args, "arc", None) is not None:
        new_arc = args.arc.strip()
        refusal = arc_refusal(new_arc)
        if refusal:
            sys.exit(refusal)
        was_arc = str(fm.get("arc") or "")
        if new_arc != was_arc:
            updates["arc"] = new_arc or None
            traces.append(f"arc set to {new_arc}" if new_arc else f"arc cleared — was: {was_arc}")

    linked = {}
    for field, nums in links.items():
        have = _as_ints(fm.get(field))
        added = [n for n in nums if n not in have]
        if added:
            updates[field] = sorted(set(have) | set(added))
            linked[field] = added
            traces.append(f"linked {field} {', '.join(str(n) for n in added)}")

    for trace in traces:
        body = append_log(body, f"- {date.today()} — {trace}")

    note = strip_own_date(args.note.strip()) if args.note else ""
    if note:
        body = append_log(body, f"- {date.today()} — {note}")

    old_status = fm.get("status")
    fm.update(updates)
    if "arc" in updates and not updates["arc"]:
        fm.pop("arc", None)
    if "runner" in updates and not updates["runner"]:
        fm.pop("runner", None)
    write(path, fm, body)

    said = [f"status: {old_status} → {fm.get('status')}"]
    if "blocked_by" in updates:
        said.append("blocked flag " + ("set" if updates["blocked_by"] else "cleared"))
    if "title" in updates:
        said.append("re-titled")
    if "runner" in updates:
        said.append("runner " + (f"set to {updates['runner']}" if updates["runner"]
                                 else "cleared"))
    if "arc" in updates:
        said.append("arc " + (f"set to {updates['arc']}" if updates["arc"] else "cleared"))
    for field in links:
        if field in linked:
            said.append(f"linked {field} {', '.join(str(n) for n in linked[field])}")
        else:
            said.append(f"{field} already linked")
    if traces:
        said.append("revision trace appended")
    if note:
        said.append("log line appended")
    print(f"Updated epic_{args.id} ({'; '.join(said)}).")
    _render()


def epic_item(args):
    """Add an item row, or change one — the frontmatter is never hand-edited (rule 1)."""
    # The CALL is judged before the record is opened: a malformed item title is refused
    # the same way whatever epic it was aimed at, and the refusal that matters is the one
    # about the title, not "epic_999 not found".
    if args.add and args.item is not None:
        sys.exit("--add creates a new row; --item targets an existing one. Pass one, not both.")
    if args.add and args.title:
        sys.exit("--add already carries the title; --title re-titles an EXISTING item (--item).")
    if not args.add and args.item is None:
        sys.exit("Nothing to do: pass --add=\"title\" or --item=<id> with "
                 "--status/--title/--blocked-by/--move-to/--moved-to.")
    if getattr(args, "reason", None) is not None and args.status != "dropped":
        sys.exit("--reason says why an item was dropped; it goes with --status=dropped only.")
    move_to = getattr(args, "move_to", None)
    moved_to = getattr(args, "moved_to", None)
    if move_to is not None or moved_to is not None:
        _item_move(args, move_to, moved_to)
        return
    if args.add:
        refusal = item_shape_refusal(args.add)
        if refusal:
            sys.exit(refusal)
    refusal = note_refusal(getattr(args, "note", None))
    if refusal:
        sys.exit(refusal)

    records = load(EPIC_DIR, "epic")
    if args.id not in records:
        sys.exit(f"epic_{args.id} not found.")
    path, fm = records[args.id]
    body = FM_RE.sub("", path.read_text())
    today = str(date.today())

    items = normalise_items(fm)
    said, traces = [], []

    if args.add:
        refusal = epic_size_refusal(args.id, fm)
        if refusal:
            sys.exit(refusal)
        new_id = next_item_id(items, body)
        items.append({"id": new_id, "title": args.add.strip(),
                      "status": "todo", "since": today})
        said.append(f"item {new_id} added (todo)")
    else:
        row = next((it for it in items if it.get("id") == args.item), None)
        if row is None:
            have = ", ".join(str(it.get("id", "?")) for it in items) or "none"
            sys.exit(f"epic_{args.id} has no item {args.item} (items: {have}).")
        if args.status is None and args.blocked_by is None and args.title is None:
            sys.exit(f"--item={args.item} needs --status, --title, --blocked-by, --move-to "
                     "or --moved-to.")

        if args.title is not None:
            # Re-titling is a CORRECTION, so it leaves a revision trace (rule 1 — the same
            # contract as `exp revise`): the old wording goes to the log, never vanishes.
            new_title = args.title.strip()
            if not new_title:
                sys.exit("--title cannot be empty: an item with no title is not a card.")
            was = str(row.get("title", "")).strip()
            if new_title == was:
                sys.exit(f"item {args.item} already carries that title.")
            row["title"] = new_title
            said.append(f"item {args.item} re-titled")
            traces.append(f"item {args.item} re-titled — was: {was}")

        if args.status:
            if args.status not in ITEM_STATUSES:
                sys.exit(f"--status must be one of: {', '.join(ITEM_STATUSES)}")
            old = row.get("status")
            # A dropped item leaves only by re-opening, and a done one is dropped only
            # after re-opening: both moves pass through todo, so neither the evidence nor
            # the reason is ever silently swapped for the other.
            if old == "dropped" and args.status != "todo":
                sys.exit(f"item {args.item} is dropped: re-open it first "
                         f"(`maestro epic item --id={args.id} --item={args.item} "
                         "--status=todo`).")
            if old == "done" and args.status == "dropped":
                sys.exit(f"item {args.item} is done: a done item is not dropped. Re-open it "
                         f"first (`maestro epic item --id={args.id} --item={args.item} "
                         "--status=todo`), then drop it with its reason.")
            # An item closes with EVIDENCE, exactly as an epic closes with an outcome.
            # A status word is a claim (rule 2 / ADR 9) and `done` is the claim that gates
            # everything downstream, so the CLI refuses it bare rather than warning: moving
            # a card is the activity that FEELS like progress while what is underneath goes
            # unexamined, and that is the failure the board was built to stop.
            if args.status == "done":
                evidence = (args.evidence or "").strip()
                if not evidence:
                    sys.exit(
                        f"item {args.item} cannot go done without --evidence: name the "
                        "merge sha, the test, or the artifact path that shows it. "
                        "Nothing to point at yet? Then it is not done.")
                # An unresolvable sha is evidence in form only. Refused rather than
                # warned, for the same reason `done` is refused bare: the board is what
                # everything downstream is checked against, and a citation nothing can
                # follow is worse than none — it reads as proof.
                bad = unresolvable_shas(evidence)
                if bad:
                    named = "; ".join(f"`{t}` {why}" for t, why in bad)
                    sys.exit(
                        f"item {args.item} cannot go done on evidence git cannot follow: "
                        f"{named}. Cite the sha that survives on the trunk — usually the "
                        "MERGE commit, not the branch commit that went into it.")
                row["evidence"] = evidence
            elif old == "done":
                row.pop("evidence", None)        # reopened — the old evidence no longer holds
            # A dropped item is SETTLED, so it carries its reason the way a done one
            # carries its evidence — refused bare for the same reason: without it the
            # row is indistinguishable from work nobody finished.
            if args.status == "dropped":
                reason = (args.reason or "").strip()
                if not reason:
                    sys.exit(
                        f"item {args.item} cannot go dropped without --reason: say what was "
                        "measured and why it falls below the bar.")
                refusal = note_refusal(reason, flag="--reason")
                if refusal:
                    sys.exit(refusal)
                row["reason"] = reason
                traces.append(f"item {args.item} dropped — {reason}")
            elif old == "dropped":
                was = str(row.pop("reason", "") or "").strip()
                traces.append(f"item {args.item} re-opened — was dropped: {was}")
            if args.status != old:
                row["since"] = today             # the clock the agent cannot feel
            row["status"] = args.status
            said.append(f"item {args.item} status: {old} → {args.status}")

        if args.blocked_by is not None:
            # A FLAG, not a state (same contract as the epic-level flag). Empty clears —
            # by removing the key, so K2 never sees a reasonless flag.
            if args.blocked_by.strip():
                row["blocked_by"] = args.blocked_by.strip()
                row["blocked_since"] = today
                said.append(f"item {args.item} blocked flag set")
            else:
                row.pop("blocked_by", None)
                row.pop("blocked_since", None)
                said.append(f"item {args.item} blocked flag cleared")

    fm["items"] = items
    fm.setdefault("options", [])
    refusal = _item_wip_refusal(args.id, fm)
    if refusal:
        sys.exit(refusal)

    for trace in traces:
        body = append_log(body, f"- {date.today()} — {trace}")
    if traces:
        said.append("revision trace appended")

    note = strip_own_date(args.note.strip()) if getattr(args, "note", None) else ""
    if note:
        body = append_log(body, f"- {date.today()} — {note}")
        said.append("log line appended")

    write(path, fm, body)
    print(f"Updated epic_{args.id} ({'; '.join(said)}).")
    _render()


def _item_move(args, move_to, moved_to):
    """`--move-to=<epic>` moves a row; `--moved-to="epic N item M"` records a hand copy.

    Both take the row OUT of the source epic (see "moving an item" above) and leave one
    log line naming the other side. `--move-to` also writes the new todo row into the
    target; `--moved-to` is for a row already copied there, so it only verifies the
    pointer and writes nothing to the target.
    """
    if move_to is not None and moved_to is not None:
        sys.exit("--move-to moves the row; --moved-to records a row already copied by "
                 "hand. Pass one, not both.")
    flag = "--move-to" if move_to is not None else "--moved-to"
    if args.add or args.status or args.title is not None or args.blocked_by is not None:
        sys.exit(f"{flag} takes the row out of this epic; it does not combine with "
                 "--add, --status, --title or --blocked-by.")
    refusal = note_refusal(getattr(args, "note", None))
    if refusal:
        sys.exit(refusal)

    records = load(EPIC_DIR, "epic")
    if args.id not in records:
        sys.exit(f"epic_{args.id} not found.")
    path, fm = records[args.id]
    body = FM_RE.sub("", path.read_text())
    items = normalise_items(fm)
    row = next((it for it in items if it.get("id") == args.item), None)
    if row is None:
        have = ", ".join(str(it.get("id", "?")) for it in items) or "none"
        sys.exit(f"epic_{args.id} has no item {args.item} (items: {have}).")
    status = row.get("status")
    if status != "todo":
        sys.exit(f"item {args.item} is {status}: only a todo row moves. A done or dropped "
                 "row is history of THIS epic and stays here; an in_progress row is being worked "
                 f"— finish it, or set it back to todo "
                 f"(`maestro epic item --id={args.id} --item={args.item} --status=todo`) "
                 "first.")

    if move_to is not None:
        # A move creates work in the target, so a CLOSED source is refused: its leftover
        # rows are bookkeeping, recorded with --moved-to once they exist elsewhere.
        if fm.get("status") == "done":
            sys.exit(f"epic_{args.id} is closed: --move-to cannot take work out of it. "
                     f"Add the row to the new epic (`maestro epic item --id=<new> --add=...`), "
                     f"then record it here with `--moved-to=\"epic <new> item <k>\"`.")
        if move_to == args.id:
            sys.exit(f"--move-to={move_to} is the epic the row is already in.")
        if move_to not in records:
            sys.exit(f"--move-to: epic_{move_to} not found.")
        t_path, t_fm = records[move_to]
        if t_fm.get("status") == "done":
            sys.exit(f"epic_{move_to} is closed: a closed epic takes no new work. Move the "
                     "row to an open epic, or open a new one (`maestro epic new`).")
        refusal = epic_size_refusal(move_to, t_fm)
        if refusal:
            sys.exit(refusal)
        t_body = FM_RE.sub("", t_path.read_text())
        t_items = normalise_items(t_fm)
        new_id = next_item_id(t_items, t_body)
        new_row = {"id": new_id, "title": row.get("title", ""), "status": "todo",
                   "since": str(date.today())}
        if blocked_reason(row):                  # the flag travels with the work
            new_row["blocked_by"] = blocked_reason(row)
            new_row["blocked_since"] = row.get("blocked_since") or str(date.today())
        t_items.append(new_row)
        t_fm["items"] = t_items
        t_fm.setdefault("options", [])
        t_body = append_log(t_body, move_in_line(new_id, args.id, args.item))
        target, target_item = move_to, new_id
    else:
        m = MOVED_TO_RE.match(moved_to or "")
        if not m:
            sys.exit(f"--moved-to={moved_to!r} must read \"epic <N> item <M>\" — the row "
                     "the work now lives in.")
        target, target_item = int(m.group(1)), int(m.group(2))
        if target == args.id:
            sys.exit(f"--moved-to names epic_{target}, the epic the row is already in.")
        # A pointer nothing can follow is a claim from memory (rule 2): it must resolve.
        if target not in records:
            sys.exit(f"--moved-to: epic_{target} not found.")
        if not any(it.get("id") == target_item for it in items_of(records[target][1])):
            have = ", ".join(str(it.get("id", "?"))
                             for it in items_of(records[target][1])) or "none"
            sys.exit(f"--moved-to: epic_{target} has no item {target_item} (items: {have}). "
                     f"Add it there first, or use --move-to={target} to move the row.")

    fm["items"] = [it for it in items if it.get("id") != args.item]
    fm.setdefault("options", [])
    body = append_log(body, move_out_line(row, target, target_item))
    note = strip_own_date(args.note.strip()) if getattr(args, "note", None) else ""
    if note:
        body = append_log(body, f"- {date.today()} — {note}")

    if move_to is not None:
        write(t_path, t_fm, t_body)              # the target first: never lose the row
    write(path, fm, body)
    where = f"epic_{target} item {target_item}"
    said = (f"item {args.item} moved -> {where}" if move_to is not None
            else f"item {args.item} removed; recorded as moved -> {where}")
    print(f"Updated epic_{args.id} ({said}" + ("; log line appended" if note else "") + ").")
    _render()


def epic_option(args):
    """The intake above the commitment point: add, pull into an item, or drop.

    Options are not cards. They have no status, no owner and no age, so nothing here
    reports as stalled and nothing accumulates a stale verdict — the two failure modes
    an unlimited `todo` queue produces.
    """
    records = load(EPIC_DIR, "epic")
    if args.id not in records:
        sys.exit(f"epic_{args.id} not found.")
    path, fm = records[args.id]
    body = FM_RE.sub("", path.read_text())
    options = options_of(fm)
    given = [x for x in (args.add, args.pull, args.drop) if x is not None]
    if len(given) != 1:
        sys.exit("Pass exactly one of --add=\"text\", --pull=<n>, --drop=<n>.")

    if args.add is not None:
        text = args.add.strip()
        if not text:
            sys.exit("--add cannot be empty.")
        options.append(text)
        said = f"option {len(options)} added"
    else:
        which = args.pull if args.pull is not None else args.drop
        if not 1 <= which <= len(options):
            listing = "; ".join(f"{i}: {o}" for i, o in enumerate(options, 1)) or "none"
            sys.exit(f"epic_{args.id} has no option {which} (options: {listing}).")
        text = options.pop(which - 1)
        if args.pull is not None:
            # Pulling an option CREATES an item, so it is held to the same epic size as
            # `item --add`: the commitment point is the same act either way.
            refusal = epic_size_refusal(args.id, fm)
            if refusal:
                sys.exit(refusal)
            items = normalise_items(fm)
            new_id = next_item_id(items, body)
            items.append({"id": new_id, "title": text, "status": "todo",
                          "since": str(date.today())})
            fm["items"] = items
            said = f"option {which} pulled → item {new_id} (todo)"
            body = append_log(
                body, f"- {date.today()} — committed to option {which}: {text}")
        else:
            said = f"option {which} dropped"
            body = append_log(
                body, f"- {date.today()} — dropped option {which}: {text}")

    fm["options"] = options
    fm.setdefault("items", [])
    write(path, fm, body)
    print(f"Updated epic_{args.id} ({said}).")
    _render()


def epic_done_when(args):
    """Write the epic's closing condition, or record what a clause's check measured.

    The clause is the contract; `--result` is the reading taken against it. Keeping the
    two apart is the point: a condition written at open and a measurement taken at close
    cannot be the same edit, and an epic that closes without the second has only stopped.
    """
    records = load(EPIC_DIR, "epic")
    if args.id not in records:
        sys.exit(f"epic_{args.id} not found.")
    path, fm = records[args.id]
    body = FM_RE.sub("", path.read_text())

    if args.add and args.clause is not None:
        sys.exit("--add creates a new clause; --clause targets an existing one. "
                 "Pass one, not both.")
    if args.add and args.text:
        sys.exit("--add already carries the wording; --text re-words an EXISTING clause "
                 "(--clause).")
    if not args.add and args.clause is None:
        sys.exit("Nothing to do: pass --add=\"condition\" or --clause=<n> with "
                 "--result/--text/--check/--drop.")

    clauses = normalise_done_when(fm)
    said, traces = [], []

    if args.add:
        text = args.add.strip()
        if not text:
            sys.exit("--add cannot be empty: a clause with no condition closes nothing.")
        new_id = max((int(c.get("id", 0)) for c in clauses), default=0) + 1
        row = {"id": new_id, "text": text}
        if args.check and args.check.strip():
            row["check"] = args.check.strip()
        row["result"] = args.result.strip() if (args.result or "").strip() else None
        clauses.append(row)
        said.append(f"clause {new_id} added" + ("" if row["result"] else " (unanswered)"))
    else:
        row = next((c for c in clauses if c.get("id") == args.clause), None)
        if row is None:
            have = ", ".join(str(c.get("id", "?")) for c in clauses) or "none"
            sys.exit(f"epic_{args.id} has no clause {args.clause} (clauses: {have}).")
        if args.drop:
            clauses = [c for c in clauses if c.get("id") != args.clause]
            said.append(f"clause {args.clause} dropped")
            traces.append(f"done_when clause {args.clause} dropped — was: "
                          f"{row.get('text', '')}")
        else:
            if args.text is None and args.check is None and args.result is None:
                sys.exit(f"--clause={args.clause} needs --result, --text, --check or --drop.")
            if args.text is not None:
                # Re-wording is a CORRECTION and leaves a revision trace, the same
                # contract `exp revise` and `epic item --title` carry (rule 1): a closing
                # condition quietly reworded to match what happened proves nothing.
                new_text = args.text.strip()
                if not new_text:
                    sys.exit("--text cannot be empty: drop the clause instead (--drop).")
                was = str(row.get("text", "")).strip()
                if new_text == was:
                    sys.exit(f"clause {args.clause} already reads that way.")
                row["text"] = new_text
                said.append(f"clause {args.clause} re-worded")
                traces.append(f"done_when clause {args.clause} re-worded — was: {was}")
            if args.check is not None:
                check = args.check.strip()
                if check:
                    row["check"] = check
                    said.append(f"clause {args.clause} check set")
                else:
                    row.pop("check", None)
                    said.append(f"clause {args.clause} check cleared")
            if args.result is not None:
                result = args.result.strip()
                row["result"] = result or None
                said.append(f"clause {args.clause} "
                            + ("answered" if result else "result cleared"))

    fm["done_when"] = clauses
    fm.setdefault("items", [])
    fm.setdefault("options", [])

    for trace in traces:
        body = append_log(body, f"- {date.today()} — {trace}")
    if traces:
        said.append("revision trace appended")
    note = strip_own_date(args.note.strip()) if getattr(args, "note", None) else ""
    if note:
        body = append_log(body, f"- {date.today()} — {note}")
        said.append("log line appended")

    write(path, fm, body)
    answered, total = done_when_counts(fm)
    print(f"Updated epic_{args.id} ({'; '.join(said)}; done_when {answered}/{total} answered).")
    _render()


def epic_close(args):
    records = load(EPIC_DIR, "epic")
    if args.id not in records:
        sys.exit(f"epic_{args.id} not found.")
    path, fm = records[args.id]
    body = FM_RE.sub("", path.read_text())

    unsettled = open_items(fm)
    if unsettled:
        named = "; ".join(f"{item_label(it)} ({it.get('status')})" for it in unsettled)
        sys.exit(f"epic_{args.id} cannot close while {len(unsettled)} item(s) are not "
                 f"settled: {named}. Close each with its evidence (--status=done "
                 "--evidence=...), drop it with its reason (--status=dropped --reason=...), "
                 f"or move it to another epic (--move-to=<N>).")

    refusal = _done_when_refusal(args.id, fm)
    if refusal:
        sys.exit(refusal)

    fm["status"] = "done"
    fm["closed"] = str(date.today())
    fm["outcome"] = args.outcome
    fm["items"] = normalise_items(fm)
    fm["done_when"] = normalise_done_when(fm)
    fm.setdefault("options", [])
    answered, total = done_when_counts(fm)
    said = [f"{answered}/{total} done_when clauses answered", f"outcome: {args.outcome}"]

    learned = (getattr(args, "learned", None) or "").strip()
    if learned:
        # Kanban's operations review, in its smallest honest form: --outcome says what the
        # work delivered, --learned says what the work taught us about how we work. The
        # second has no other home — adr records a decision, findings records a
        # measurement, and neither is a claim about the process itself.
        said.append(f"retro line → {_append_retro(learned, args.id).relative_to(ROOT)}")

    dropped = items_dropped(fm)
    if dropped:
        said.append(f"{dropped} item(s) dropped")

    write(path, fm, body)
    print(f"Closed epic_{args.id} ({'; '.join(said)}).")
    _render()


RETRO_HEADING = "# Retrospectives"
RETRO_INTRO = ("_What each closed epic taught us about HOW we work — not what it "
               "delivered (that is the epic's outcome). Append-only, written by "
               "`maestro epic close --learned`._")


def _append_retro(text: str, epic_id: int):
    """Append one dated line to docs/retro.md, creating the file on first use."""
    retro = ROOT / "docs" / "retro.md"
    retro.parent.mkdir(parents=True, exist_ok=True)
    if not retro.exists():
        retro.write_text(f"{RETRO_HEADING}\n\n{RETRO_INTRO}\n\n")
    with retro.open("a") as fh:
        fh.write(f"- {date.today()} — **epic {epic_id}**: {text}\n")
    return retro


def epic_show(args):
    records = load(EPIC_DIR, "epic")
    if args.id not in records:
        sys.exit(f"epic_{args.id} not found.")
    path, fm = records[args.id]
    print(f"epic: {fm['epic']}  status: {fm.get('status', '')}  title: {fm.get('title', '')}")
    print(f"opened: {fm.get('opened') or '—'}  closed: {fm.get('closed') or '—'}  "
          f"{counts_text(fm)}")
    if blocked_reason(fm):
        print(f"blocked_by: {blocked_reason(fm)}")
    answered, total = done_when_counts(fm)
    if total:
        print(f"done when: {answered}/{total} answered")
        for c in done_when_of(fm):
            got = clause_result(c)
            print(f"  [{'x' if got else ' '}] {c.get('id', '?')}. {c.get('text', '')}")
            if c.get("check"):
                print(f"        check:  {c['check']}")
            print(f"        result: {got or '— unanswered'}")
    else:
        print("done when: — no clause (close will refuse)")
    if fm.get("outcome"):
        print(f"outcome: {fm['outcome']}")
    for field in ("exps", "adrs", "tags"):
        if fm.get(field):
            print(f"{field}: {', '.join(str(x) for x in fm[field])}")
    for it in items_of(fm):
        reason = blocked_reason(it)
        flag = f"   blocked: {reason}" if reason else ""
        why = f"   reason: {it.get('reason') or '—'}" if it.get("status") == "dropped" else ""
        print(f"  item {str(it.get('id', '?')):>3}  {str(it.get('status', '')):12s}  "
              f"{it.get('title', '')}{flag}{why}")
    dates = log_dates(FM_RE.sub("", path.read_text()))
    if dates:
        print(f"log: {len(dates)} line(s), newest {max(dates)}")


def epic_list(args):
    records = load(EPIC_DIR, "epic")
    for n, (_, fm) in sorted(records.items()):
        if args.status and fm.get("status") != args.status:
            continue
        reason = blocked_reason(fm)
        if args.blocked and not reason:
            continue
        flag = f"  blocked: {reason}" if reason else ""
        print(f"{n:3d}  {fm.get('status', ''):12s}  {str(fm.get('title', '')):40s}  "
              f"{counts_text(fm)}{flag}")
