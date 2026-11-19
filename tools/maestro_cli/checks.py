"""Drift detector — run by the pre-commit gate (`--staged`) or by hand.

Checks:
- INDEX.md files are not stale
- findings.md / CLAUDE.md cite only existing, non-superseded exps
- exp parent: references exist and are not superseded
- exp consumes: file paths exist on disk
- adr superseded_by: references exist; superseded adrs have superseded_by set
- W1 an ADR cites epics, epic items or the plan (blocking for text dated 2026-09-27 on;
  older text one folded legacy advisory per ADR)
- docs/ root has no orphan files outside the framework structure
- hard size caps hold (progress/findings/CLAUDE.md, per-exp files)
- datasets under data/raw/ have a docs/data/<name>.md record, and its sha matches the bytes
  (a record whose `status:` is `collecting` is exempt until `dataset update --complete`
  stamps the sha — one advisory instead, so a running pull is not reported as drift)
- experiment output under data/experiments/ has a record, and that record is written up
- run dirs (exp_NN_*/run_<K>/) agree with their record: best_run resolves and
  source_artifacts paths exist; run-dir completeness (run.log + metrics.json) is advisory
- exp files carry no forward-looking sections (Next Steps / Action Items / v2 plan / ...)
- code-tier import layering holds (src/ ⊀ scripts//experiments/; exp ⊀ another exp)
- the kanban layer holds (ADR 7): K1 a stalled in_progress epic, K2 a blocked flag with
  no reason, K3 epic frontmatter that the CLI did not write, K4 a done item with no
  evidence or a dropped item with no reason, K10 a log line that says
  the work landed over a board where every item is still todo, K11 an item title that
  lists identifiers (tasks written into an item; advisory)
- the CLI wrote what it owns (rule 1, enforced by a stamp): S1 a record whose frontmatter
  or epic log was edited by hand (blocking), S2 records not yet stamped (one advisory)
- results are cited, not recalled (ADR 9): A1 a takeaway with no source_artifacts, A2 a
  source_artifacts path missing on disk, A3 a status word with no verified/unverified
  marker, A4 a rule-bearing docs file no CLAUDE.md triggers, A5 an epic done_when result
  or outcome that cites no artifact at all
- an item's recorded evidence is a sha git can still follow — one that resolves to no
  commit, or an orphan no branch or tag contains (advisory; `epic item` refuses new ones)

Two severities. `issues` BLOCK (exit 2, report on stderr). `notes` are ADVISORY: they
ride along in the same report, prefixed `~` instead of `-`, and never change the exit
code — for conditions that are usually drift but have honest exceptions, where blocking
would train people to work around the checker instead of fixing the drift.

Exit codes: 0 = clean (one-line summary on stdout) · 2 = drift found (report on STDERR).
A Claude Code Stop hook would read exit 2 as 'block the turn', and every real project
has some drift, so it would block every turn-end. Never wire it as one.
"""
import ast
import os
import re
import subprocess
import sys
import yaml
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import declaration, epics, frontmatter, gitstate
from .datasets import collecting_note, is_collecting
from .hashing import dataset_sha_rel

# Default to the project root; CHECK_DRIFT_ROOT overrides it so the checks can be
# exercised against a sandbox tree.
ROOT = Path(os.environ.get("CHECK_DRIFT_ROOT") or frontmatter.ROOT)
EXP_DIR = ROOT / "docs" / "experiments"
ADR_DIR = ROOT / "docs" / "adrs"
EPIC_DIR = ROOT / "docs" / "epics"
DOCS_DIR = ROOT / "docs"
FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
EXP_REF = re.compile(r"\bExp\s*(\d+)\b")

# Standard top-level docs/ files — anything else is an orphan
KNOWN_DOCS = {"progress.md", "findings.md", "data.md", "setup.md", "retro.md"}
# Known subdirectories — unexpected subdirs are silently allowed
KNOWN_SUBDIRS = {"experiments", "adrs", "epics", "kb", "archive"}

# Hard size caps (core.md → Hard size caps). (path relative to ROOT, cap, over-hint)
SIZE_CAPS = [
    ("docs/progress.md", 200, "Archive completed sprints to docs/archive/progress_{YYYY-QN}.md."),
    ("docs/findings.md", 300, "Move overturned to '## Superseded findings'; archive oldest year."),
]
EXP_LINE_CAP = 150         # docs/experiments/exp_*.md
# core.md house rules: CLAUDE.md is capped in TOKENS, not lines — dense prose carries
# ~2.5x the tokens of sparse prose at equal line count. Estimated as bytes/4; that is a
# proxy, not a tokenizer, so the cap is deliberately round.
CLAUDE_TOKEN_CAP = 8000     # CLAUDE.md at any tier
BYTES_PER_TOKEN = 4
# Forward-looking section headings forbidden in exp files (core.md → File ownership).
FORBIDDEN_EXP_HEADING = re.compile(
    r"^#{1,6}\s*(next steps?|next up|action items?|future work|road\s?map|to-?do|v2 plan|plan for v2)\b",
    re.IGNORECASE | re.MULTILINE,
)
RAW_DIR = ROOT / "data" / "raw"
DATA_DIR = ROOT / "docs" / "data"
EXPDATA_DIR = ROOT / "data" / "experiments"
DIR_EXP_NUM = re.compile(r"^exp_(\d+)")
RUN_DIR_RE = re.compile(r"^run_(\d+)$")   # ADR 3 — v<N>/ stays reserved for datasets



def _load_datasets():
    """Dataset records, keyed by name: docs/data/<name>.md → {name: (path, fm)}."""
    records = {}
    if not DATA_DIR.exists():
        return records
    for p in DATA_DIR.glob("*.md"):
        if p.name == "INDEX.md":
            continue
        m = FM_RE.match(p.read_text())
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        if "dataset" in fm:
            records[fm["dataset"]] = (p, fm)
    return records


def _dataset_sha(name, version, path=""):
    """sha256 of a dataset file-set (shared impl — see hashing.py).
    `path` (relative to data/) locates the bytes; absent → raw/<name>[/<version>]."""
    return dataset_sha_rel(ROOT / "data", name, version, path)


def _data_rel(name, version, path=""):
    if path:
        return path
    return f"raw/{name}/{version}" if version else f"raw/{name}"


def load_kind(directory, kind):
    records = {}
    if not directory.exists():
        return records
    for p in directory.glob(f"{kind}_*.md"):
        m = FM_RE.match(p.read_text())
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        if kind in fm:
            records[fm[kind]] = (p, fm)
    return records


def _imported_roots(path):
    """Top-level module name of every absolute import in a .py file (AST, best-effort)."""
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return set()
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                roots.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])   # relative (level>0) imports stay in-package
    return roots


def run_dirs(d):
    """The exp data dir's run_<K>/ subdirs (ADR 3), ordered by K."""
    return sorted((p for p in d.iterdir() if p.is_dir() and RUN_DIR_RE.match(p.name)),
                  key=lambda p: int(RUN_DIR_RE.match(p.name).group(1)))


def _run_dir_rel(n, best, d):
    """The repo-relative path of exp n's run dir `best`. With no exp data dir here (a
    linked worktree without data/), the main checkout's name for it, if it has one."""
    if d is not None:
        return str((d / best).relative_to(ROOT))
    main = gitstate.main_checkout(str(ROOT.resolve()))
    if main is not None:
        for cand in sorted((main / "data" / "experiments").glob(f"exp_{n:02d}_*/{best}")):
            return str(cand.relative_to(main))
    return f"data/experiments/exp_{n:02d}/{best}"


def exp_data_dir(n):
    """data/experiments/exp_NN_<slug>/ for experiment n, or None."""
    if not EXPDATA_DIR.is_dir():
        return None
    return next((p for p in sorted(EXPDATA_DIR.glob(f"exp_{n:02d}_*")) if p.is_dir()), None)


def layering_issues(root):
    """3-tier import-layering violations (core.md → 'Code lives in 3 tiers').

    src/ must not import scripts/ or experiments/; scripts/ must not import
    experiments/; an experiment must not import another experiment (each is one-off —
    shared code belongs in src/). Tiers are matched by package root ('experiments',
    'scripts') and by bare module stem (how `python experiments/foo.py` resolves a
    sibling import). Returns a list of issue strings.
    """
    out = []
    src, scripts, exps_dir = root / "src", root / "scripts", root / "experiments"
    exp_stems = {p.stem for p in exps_dir.glob("*.py")} if exps_dir.exists() else set()
    script_stems = {p.stem for p in scripts.glob("*.py")} if scripts.exists() else set()
    layering = "violates 3-tier layering (core.md → Code lives in 3 tiers)."

    def scan(d, forbidden, label):
        if not d.exists():
            return
        for p in d.rglob("*.py"):
            bad = _imported_roots(p) & forbidden
            if bad:
                out.append(f"{p.relative_to(root)}: {label} imports {sorted(bad)} — {layering}")

    scan(src, {"experiments", "scripts"} | exp_stems | script_stems, "library code")
    scan(scripts, {"experiments"} | exp_stems, "production CLI")
    if exps_dir.exists():                          # experiments may use src/scripts, not each other
        for p in exps_dir.glob("*.py"):
            bad = (_imported_roots(p) & ({"experiments"} | exp_stems)) - {p.stem}
            if bad:
                out.append(f"{p.relative_to(root)}: experiment imports another experiment "
                           f"{sorted(bad)} — each exp is one-off; promote shared code to src/.")
    return out


# ── the kanban layer (ADR 7 / modules/kanban.md) ─────────────────────────────

class NonActionable(str):
    """An advisory the checker itself classifies as nothing this session can act on.

    Two classes: a finding on a CLOSED epic (history, not debt to repair — the record has
    no CLI path to correct) and an ADR 9 finding staged off a file untouched since HEAD and
    by no commit in the session window (the existing backlog, which can only shrink).
    Still a str — every caller that reads notes reads it unchanged, `--strict` still counts
    it — but `check()` folds these into one summary line unless `--verbose` asks for them.
    A Stop hook that re-prints 16 identical lines it calls non-actionable on every turn
    trains the reader to skip the whole advisory block.
    """


def _note(text, quiet):
    return NonActionable(text) if quiet else text


STALE_EPIC_DAYS = 14        # K1 — an in_progress epic nobody has written a log line for

# K10 — words a log line uses to say the work HAPPENED. A newest line carrying one
# while every item still reads `todo` means the log and the board disagree, and one
# of them is wrong. \b keeps "merged" from matching "submerged"; "closed" is deliberately
# absent because a re-title trace can quote an old title that contains it.
# K11 — an item title that is a list. Three or more comma-separated segments that are
# each ONE token (no spaces) read as identifiers, not prose: tasks written into an item.
LIST_ITEM_MIN = 3


def title_list_count(title) -> int:
    """How many comma-separated single-token segments an item title carries."""
    return sum(1 for seg in str(title or "").split(",")
               if seg.strip() and " " not in seg.strip())


LOG_CLAIM_RE = re.compile(
    r"\b(complete|completed|merged|landed|shipped|delivered|finished)\b", re.IGNORECASE)


def _as_date(value):
    """A frontmatter date as a date object, or None when it is not one."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# W1 — an ADR records a decision and its evidence, never the work plan around it
# (modules/kanban.md: plans leak into whatever record is open). Dated: text written on
# or after W1_SINCE blocks; older text is history, reported once per ADR and folded.
W1_SINCE = date(2026, 9, 27)
# What counts as a work reference. Deliberately narrow, because a false positive here
# trains people to switch the check off:
# - `epic 7`, `Epics 2`, `epic_07`, `docs/epics/` — the word followed by its number, or
#   the record path; "epic" as plain prose ("an epic effort") carries no number and passes.
# - `item 15` ONLY in a sentence that also names an epic — a bare "item 3" is as often a
#   numbered list entry of the decision itself.
# - `Up next` and `maestro option` — the progress.md intake. A bare "options:" is NOT
#   matched: an ADR's considered alternatives are its proper content.
W1_EPIC_RE = re.compile(r"\bepics?\s*\d+|\bepic_\d+|docs/epics\b", re.IGNORECASE)
W1_ITEM_RE = re.compile(r"\bitems?\s+\d+", re.IGNORECASE)
W1_PLAN_RE = re.compile(r"\bup next\b|\bmaestro (?:epic )?option\b", re.IGNORECASE)
# An amendment carries its own date up to the next marker (the base text: `date:`).
AMENDMENT_RE = re.compile(r"\*\*Amendment \((\d{4}-\d{2}-\d{2})")
# A sentence: split at . ! ? ; followed by whitespace, or at a blank line. A single
# newline is a hard wrap inside a sentence, so "epic\n2" still reads as one reference.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n\s*\n")


def work_refs(text):
    """The work-tracking references in `text`, in order, de-duplicated (W1's pattern)."""
    found = []
    for sentence in SENTENCE_SPLIT_RE.split(text):
        hits = [m.group(0) for m in W1_EPIC_RE.finditer(sentence)]
        if hits:
            hits += [m.group(0) for m in W1_ITEM_RE.finditer(sentence)]
        hits += [m.group(0) for m in W1_PLAN_RE.finditer(sentence)]
        for h in hits:
            h = re.sub(r"\s+", " ", h)
            if h.lower() not in (f.lower() for f in found):
                found.append(h)
    return found


def dated_segments(fm, body):
    """[(date|None, text)]: the base text under the frontmatter `date`, then each
    `**Amendment (YYYY-MM-DD` paragraph under its own date, up to the next marker."""
    base_date = _as_date(fm.get("date"))
    # ADRs that keep their prose in frontmatter fields (decision/context/...) count it
    # as base text: it was written with the record.
    fm_prose = "\n\n".join(str(v) for k, v in fm.items() if isinstance(v, str) and k != "date")
    marks = list(AMENDMENT_RE.finditer(body))
    segs = [(base_date, fm_prose + "\n\n" + body[:marks[0].start() if marks else len(body)])]
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        segs.append((_as_date(m.group(1)), body[m.start():end]))
    return segs


def adr_work_ref_findings(adrs, since=W1_SINCE):
    """W1 over the ADR records ({n: (path, fm)}). Returns (issues, notes).

    Text dated on/after `since` that names an epic, an epic item or the plan BLOCKS;
    older text is one folded advisory per ADR (history is not rewritten). Text with no
    readable date is judged as new — an undated record cannot claim to be history.
    """
    issues, notes = [], []

    def fmt(segs):
        return "; ".join(f"{d or 'undated'}: {', '.join(r)}" for d, r in segs)

    for n, (path, fm) in sorted(adrs.items()):
        body = FM_RE.sub("", path.read_text(), count=1)
        new, old = [], []
        for d, text in dated_segments(fm, body):
            refs = work_refs(text)
            if refs:
                (old if d is not None and d < since else new).append((d, refs))
        rel = frontmatter.rel(path)
        if new:
            issues.append(                                                  # W1
                f"{rel}: cites work tracking ({fmt(new)}) — an ADR records a decision and "
                "its evidence (exp records, artifacts), never epics, items or the plan "
                "(modules/kanban.md, W1). Cite the exp or artifact instead; the work "
                "belongs on the epic.")
        if old:
            notes.append(NonActionable(                                     # W1, legacy
                f"{rel}: cites work tracking in text dated before {since} ({fmt(old)}) — "
                "legacy, left as written (W1)."))
    return issues, notes


def kanban_findings(records, today=None, arcs=()):
    """K1-K11 over the epic records. Returns (issues, notes).

    K1 is ADVISORY: a stalled epic is a fact about the world, not a malformed record,
    and the only way to silence it is to write a log line — blocking on that would
    buy fake notes. K2 and K3 BLOCK: both mean the record itself is wrong, and both are
    fixed by one CLI call. K10 BLOCKS for the same reason: a log line that says
    "merged"/"complete" over a board where every item is still todo is a record
    contradicting itself (a session can close rows and write the log by hand without
    moving any item; the board is the contract the log is checked against).
    """
    issues, notes = [], []
    today = today or date.today()
    for n, (path, fm) in sorted(records.items()):
        closed = fm.get("status") == "done"   # its advisories are history, not debt
        missing = [k for k in epics.REQUIRED_KEYS if k not in fm]
        if missing:                                                    # K3
            issues.append(
                f"epic_{n}: frontmatter is missing required key(s) {', '.join(missing)} — epic "
                "records are written by the CLI (rule 1), not by hand. Add the key(s), or "
                "re-create the record with `maestro epic new`.")

        if fm.get("blocked_by") is not None and not epics.blocked_reason(fm):
            issues.append(                                              # K2
                f"epic_{n}: blocked_by is set but empty — a flag with no reason blocks nothing "
                f"and cannot be unblocked. Give the reason (`maestro epic update --id={n} "
                f'--blocked-by="..."`) or clear the flag (`--blocked-by=`).')
        for it in epics.items_of(fm):
            if it.get("blocked_by") is not None and not epics.blocked_reason(it):
                issues.append(                                          # K2, on an item
                    f"epic_{n}: {epics.item_label(it)} has blocked_by set but empty — give the "
                    "reason or remove the key.")

            if it.get("status") == "dropped" and not str(it.get("reason") or "").strip():
                issues.append(                                          # K4, dropped
                    f"epic_{n}: {epics.item_label(it)} is dropped with no reason — a dropped "
                    "item is settled, and the reason is what tells it apart from work nobody "
                    "finished. Re-open it (`--status=todo`), then drop it with "
                    f"`maestro epic item --id={n} --item={it.get('id')} --status=dropped "
                    '--reason="..."`.')

            if it.get("status") == "done" and not str(it.get("evidence") or "").strip():
                issues.append(                                          # K4
                    f"epic_{n}: {epics.item_label(it)} is done with no evidence — `done` is a "
                    "claim and rule 2 governs it. Re-close it with "
                    f"`maestro epic item --id={n} --item={it.get('id')} --status=done "
                    '--evidence="<sha|test|artifact>"`.')

            listed = title_list_count(it.get("title"))
            if listed >= LIST_ITEM_MIN:
                notes.append(_note(                                     # K11
                    f"epic_{n}: {epics.item_label(it)} title lists {listed} identifiers — "
                    "that is tasks written into an item. An item is one branch; its tasks "
                    "live in commits or the project's task-level record, never in the "
                    "title (kanban.md → vocabulary). Re-title it: "
                    f"`maestro epic item --id={n} --item={it.get('id')} --title=\"...\"`.", closed))

            if not it.get("since"):
                notes.append(_note(                                     # K5
                    f"epic_{n}: {epics.item_label(it)} carries no `since` stamp, so nothing "
                    "can tell how long it has sat. Any CLI write to this epic stamps it.", closed))

            age = epics.item_age(it, today)
            if it.get("status") == "in_progress" and age > epics.STALE_ITEM_DAYS:
                notes.append(_note(                                     # K6 — ageing WIP
                    f"epic_{n}: {epics.item_label(it)} has been in_progress {age} days "
                    f"(cap {epics.STALE_ITEM_DAYS}). One item is one session — either it is "
                    "several items wearing one title, or it stalled and nobody said so.", closed))

            blocked = epics.block_age(it, today)
            if epics.blocked_reason(it) and blocked > epics.STALE_BLOCK_DAYS:
                notes.append(_note(                                     # K7 — ageing block
                    f"epic_{n}: {epics.item_label(it)} has been blocked {blocked} days "
                    f"(cap {epics.STALE_BLOCK_DAYS}) on: {epics.blocked_reason(it)}. A flag "
                    "nobody can clear is a decision waiting to be made.", closed))

        answered, clauses = epics.done_when_counts(fm)
        if fm.get("status") == "done" and clauses and answered < clauses:
            issues.append(                                              # K8
                f"epic_{n} is closed with {clauses - answered} of {clauses} done_when "
                "clause(s) unanswered — `epic close` refuses that, so this record was "
                "hand-edited. Record what each check measured: "
                f'`maestro epic done-when --id={n} --clause=<k> --result="..."`.')

        if fm.get("status") != "done" and not clauses:
            notes.append(                                               # K9
                f"epic_{n} has no done_when clause, so nothing in the record says what done "
                "MEANS, and `epic close` will refuse it. State the closing condition now "
                f'(`maestro epic done-when --id={n} --add="..." --check="..."`), while it is '
                "still a decision rather than a rationalisation of whatever happened.")

        body = FM_RE.sub("", path.read_text())
        items = epics.items_of(fm)
        entries = epics.log_entries(body)
        board_unmoved = (fm.get("status") == "todo"
                         or (items and all(it.get("status") == "todo" for it in items)))
        # A move or drop line is bookkeeping: it quotes a moved title or a drop reason,
        # and those words ("…merged…") are no claim that work happened here.
        if (fm.get("status") != "done" and board_unmoved and entries
                and not epics.is_move_line(entries[-1])
                and not epics.is_drop_line(entries[-1])):
            claim = LOG_CLAIM_RE.search(entries[-1])
            if claim:                                                   # K10
                issues.append(
                    f"epic_{n}: the newest log line says the work happened "
                    f"('{claim.group(0)}') but the board never moved — every item is still "
                    "todo. The log and the board disagree, so one of them is wrong. If the "
                    "work landed, close each item with its evidence (`maestro epic item "
                    f"--id={n} --item=<k> --status=done --evidence=\"<sha>\"`) and diff what "
                    "closed against what each item's title owns; if it did not, the line is "
                    "a claim from memory (rule 2).")

        if arcs:                                                        # arcs declared
            arc = fm.get("arc")
            if arc and arc not in arcs:
                issues.append(
                    f"epic_{n}: arc {arc!r} is not declared in maestro.toml ({', '.join(arcs)}) — "
                    f"fix with `maestro epic update --id={n} --arc=<name>`.")
            elif not arc and not closed:
                issues.append(
                    f"epic_{n}: no arc, and maestro.toml declares arcs ({', '.join(arcs)}) — "
                    f"`maestro epic update --id={n} --arc=<name>`.")

        if fm.get("status") != "active":
            continue
        stamps = [d for d in (_as_date(s) for s in epics.log_dates(body)) if d]
        newest = max(stamps) if stamps else _as_date(fm.get("opened"))
        if newest is None:
            continue
        age = (today - newest).days
        if age > STALE_EPIC_DAYS:                                       # K1
            notes.append(
                f"epic_{n} has been active for {age} days with nothing new in its log "
                f"(newest line {newest}, cap {STALE_EPIC_DAYS} days). Either it moved and nobody "
                f'wrote it down (`maestro epic update --id={n} --note="..."`), or it is really '
                "todo wearing a costume.")
    return issues, notes


# ── the stamp: the CLI wrote what it owns (rule 1, enforced) ─────────────────

STAMP_CLI = {"exp": "maestro exp update|revise", "adr": "maestro adr ...",
             "epic": "maestro epic update|item|done-when|close (log: --note)",
             "dataset": "maestro dataset ..."}


def _record_kind(path) -> str:
    n = path.name
    return ("exp" if n.startswith("exp_") else "adr" if n.startswith("adr_")
            else "epic" if n.startswith("epic_") else "dataset")


def stamp_findings(root=None):
    """S1 (BLOCKING): a record whose CLI-owned surface no longer matches its stamp.
    S2 (ADVISORY, one line): records that carry no stamp yet.

    S1 blocks because the record was edited by hand — any tool, any harness, any
    shell — and the fix is one CLI call (or, for a deliberate hand fix, an explicit
    `maestro docs stamp --accept`). S2 is one line, not one per file: a legacy record
    is stamped by its next CLI write, and `--accept` stamps everything at adoption.
    """
    issues, notes = [], []
    unstamped = 0
    merged = 0
    for p in frontmatter.record_files():
        st = frontmatter.stamp_status(p)
        if st == "mismatch" and _taken_from_a_merge_side(p):
            merged += 1                                                 # S3
        elif st == "mismatch":
            issues.append(                                              # S1
                f"{frontmatter.rel(p)}: edited by hand — its frontmatter"
                f"{' or ## Log' if _record_kind(p) == 'epic' else ''} no longer matches "
                f"the CLI's stamp (rule 1). Revert the edit and make the change through "
                f"`{STAMP_CLI[_record_kind(p)]}`; a deliberate hand fix is blessed with "
                "`maestro docs stamp --accept`.")
        elif st == "unstamped":
            unstamped += 1
    if unstamped:
        notes.append(                                                   # S2
            f"{unstamped} record(s) carry no stamp yet — each is stamped by its next CLI "
            "write, or all at once with `maestro docs stamp --accept`.")
    if merged:
        notes.append(                                                   # S3
            f"{merged} record(s) differ from their stamp but carry one merge side's "
            "CLI-owned surface verbatim — a merge resolution, not a hand edit. "
            "`maestro docs stamp --accept` re-signs them once the merge is committed.")
    return issues, notes


def _taken_from_a_merge_side(path) -> bool:
    """S3: during a merge, the record's frontmatter (and epic log) equals one side's.

    Picking a side is how a conflict is resolved; it is not the hand edit S1 exists to
    catch (tools/maestro_cli/gitstate.py). Only asked for a mismatching record, so a
    clean tree never pays for the git calls.
    """
    kind = "epic" if _record_kind(path) == "epic" else "record"
    from .guards import _owned_text
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return False
    return gitstate.taken_from_a_side(path, text, lambda t: _owned_text(t, kind))


# ── results are cited, not recalled (ADR 9) ──────────────────────────────────

# Status words about CODE. They gate future work exactly as a metric does, so each one
# carries `verified: <sha|date>` or is written `unverified` (ADR 9). Case matters:
# CONFORMANT is the verdict, and \b keeps "reported"/"supported" from matching "ported".
STATUS_WORD_RE = re.compile(r"\b(CONFORMANT|unported|ported|reachable:)")
EVIDENCE_RE = re.compile(r"\bunverified\b|\bverified:")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
QUOTED_RE = re.compile(r"\"[^\"]*\"|'[^']*'|“[^”]*”")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
# A4 — "rule-bearing" is deliberately narrow: a doc that tells someone what they MUST or
# must NEVER do, on at least this many separate lines. Prose that merely mentions a rule
# once does not qualify, because a false positive here trains people to disable the check.
RULE_MODAL_RE = re.compile(r"\b(MUST|NEVER|ALWAYS|must|never|always|do not|don't)\b")
A4_MIN_RULE_LINES = 3
A4_MIN_LINES = 20
# Record dirs and generated files are never "rule-bearing docs": records state facts,
# kb states what someone else found, archive is dead by definition.
A4_SKIP_DIRS = ("experiments", "adrs", "epics", "data", "kb", "archive")
# CLAUDE.md files that are fixtures or templates, not this project's live instructions.
TRIGGER_SKIP_DIRS = ("data", "tests", "templates")
A3_MAX_PER_FILE = 3


def uncommitted_paths(root):
    """Repo-relative paths whose content differs from HEAD, plus untracked files.

    ADR 9 step 2 (RATCHET) hard-fails only on what this session touched. Returns None —
    meaning "git cannot say" — when git is missing, the tree is not a repo, or there is
    no HEAD yet; every ADR 9 finding then degrades to advisory rather than crashing.
    """
    def git(*args):
        try:
            r = subprocess.run(["git", "-C", str(root), *args],
                               capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if r.returncode == 0 else None

    changed = git("diff", "--name-only", "HEAD")
    if changed is None:
        return None
    # An uncited claim in a BRAND-NEW file is the commonest shape of new debt, and a new
    # file never shows in `git diff HEAD`, so untracked files count as touched too.
    untracked = git("ls-files", "--others", "--exclude-standard") or ""
    return {ln.strip() for ln in (changed + untracked).splitlines() if ln.strip()}


# How far back a commit still counts as "this session". A session-state-free proxy: the
# checker holds no session id, and the harness gives it none, so time is the only signal
# both a Stop hook and a pre-commit run can read. 12 h is longer than a working session
# and shorter than a night, so yesterday's backlog stays advisory.
SESSION_HOURS = float(os.environ.get("MAESTRO_SESSION_HOURS") or 12)


def recently_committed_paths(root, hours=None):
    """Repo-relative paths written by a commit inside the session window.

    Without this, "touched this session" means "differs from HEAD", and committing IS the
    way out of the gate: an agent wrote metric values into progress.md and
    committed in the same bash call, so by the time the Stop hook ran the file matched
    HEAD and the ADR 9 finding printed as an advisory nobody had to clear.

    Rejected: the branch's last `checkout` reflog entry as the session boundary. On a
    long-lived checkout (this repo, `main` for weeks) that entry is weeks back, so every
    file the branch ever touched would count as touched this session — the ratchet
    inverted. A wall-clock window is coarser but cannot swing that way.

    Returns None on the same "git cannot say" conditions as uncommitted_paths.
    """
    hours = SESSION_HOURS if hours is None else hours

    def git(*args):
        try:
            r = subprocess.run(["git", "-C", str(root), *args],
                               capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if r.returncode == 0 else None

    # An ABSOLUTE cutoff, not "--since=12 hours ago": git rejects a fractional
    # "12.0 hours ago" and, being a revision-limiting option, answers an unparsable one
    # with an empty list and exit 0 — the gate would silently pass everything.
    # --all: work committed on a feature branch counts even after a switch back.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = git("log", "--all", f"--since={cutoff.isoformat()}", "--name-only", "--format=")
    if out is None:
        return None
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def touched_paths(root, hours=None):
    """Everything ADR 9's ratchet treats as this session's work: uncommitted changes,
    untracked files, and anything a commit inside the session window rewrote."""
    uncommitted = uncommitted_paths(root)
    if uncommitted is None:
        return None
    return uncommitted | (recently_committed_paths(root, hours) or set())


def _prose(line):
    """The line with inline code and quoted spans removed.

    A status word inside backticks or quotes is being DISCUSSED (an ADR explaining the
    rule, a note quoting someone else's row), not asserted. Only bare prose asserts.
    """
    return QUOTED_RE.sub(" ", INLINE_CODE_RE.sub(" ", line))


def _docs_markdown(docs_dir):
    """Every docs/*.md worth scanning: no generated INDEX, no archived docs."""
    if not docs_dir.is_dir():
        return []
    out = []
    for p in sorted(docs_dir.rglob("*.md")):
        parts = p.relative_to(docs_dir).parts
        if p.name == "INDEX.md" or "archive" in parts:
            continue
        out.append(p)
    return out


def _trigger_rows(root):
    """Every docs path named in a TABLE ROW of a live CLAUDE.md — the load triggers.

    Rule 12: a rules doc earns a row in a "when to load" table. A prose mention is not a
    trigger, so only lines that are table rows count.
    """
    named = set()
    for p in sorted(root.rglob("CLAUDE.md")):
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or rel.parts[0] in TRIGGER_SKIP_DIRS:
            continue
        for line in p.read_text().splitlines():
            if not line.lstrip().startswith("|"):
                continue
            for m in re.finditer(r"([A-Za-z0-9_./-]*docs/[A-Za-z0-9_./-]+\.md)", line):
                path = m.group(1)
                named.add(path)
                named.add(path.split("/")[-1])
    return named


# ── dead references: a cited path that does not exist (G0a) ──────────────────

# A path is only judged when it is cited as one — in backticks, or as a link target.
# Bare prose is too ambiguous, and a check that cries wolf gets disabled (see check 1).
_CITE_RE = re.compile(r"`([^`\n]+)`|\]\(([^)\s]+)\)")
# Template and glob forms name a SHAPE, not a file: exp_NN_<slug>.md, docs/**, ${VAR}.
_PLACEHOLDER_RE = re.compile(r"[<>*{}$]|\bNN\b|\bXX\b")
# A cite may carry a line ref or an anchor: combat.rs:412, replay_format.md#v2.
_CITE_TRIM_RE = re.compile(r"[:#].*$")
_SKIP_PREFIXES = ("http://", "https://", "mailto:", "~", "/", "#", ".")
# Record dirs are HISTORICAL: an ADR is a dated decision and an exp record a dated run, so
# a path in one describes the tree AS IT WAS. Judging those paths against today's tree is
# the same category error as editing data/raw/ (rule 7) — the citation is a fact, not a
# pointer. Most hits of that kind are correct: an ADR may cite an engine that was
# deliberately deleted at a tag.
_HISTORICAL_DOC_DIRS = ("adrs", "experiments", "data", "kb", "archive")
# Advisories are capped per file, like A3: one doc written before a big deletion can carry
# dozens of dead paths, and a report nobody reads to the end is a report nobody acts on.
# The BLOCKING list is never capped — every dead path in CLAUDE.md has to go.
_DEAD_PATH_MAX_PER_FILE = 3


def _repo_paths_cited(text, top_dirs):
    """Repo-relative paths a markdown file cites → the first line each appears on."""
    out = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in _CITE_RE.finditer(line):
            raw = (m.group(1) or m.group(2) or "").strip()
            if not raw or raw.startswith(_SKIP_PREFIXES) or _PLACEHOLDER_RE.search(raw):
                continue
            cand = _CITE_TRIM_RE.sub("", raw).rstrip("/.,;)").strip()
            # First segment must be a real top-level dir, so prose like "and/or" is out.
            if "/" not in cand or cand.split("/", 1)[0] not in top_dirs:
                continue
            out.setdefault(cand, lineno)
    return out


def dead_path_findings(root):
    """A live doc cites a repo path that does not exist. Returns (issues, notes).

    Written after three dead references turned up in one session: a CLAUDE.md line
    naming an archive path that was never created, a fixtures README describing files
    that had been removed from the repo, and a docs list pointing at a superseded file.
    All three read as authoritative; none resolved. The existing checks already refuse a
    dead exp number (check 2) and a dead `consumes` path (check 3) — a dead DOC path was
    the one citation nothing verified, and the rule-12 scan even had `exists()` in hand
    and used it to SKIP the file rather than report it.

    CLAUDE.md is BLOCKING: it is the instruction file, so a path that does not resolve is
    a false statement the next session will act on. Other live docs are advisory.
    """
    issues, notes = [], []
    if not root.is_dir():
        return issues, notes
    top_dirs = {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    if not top_dirs:
        return issues, notes

    targets = [(p, True) for p in sorted(root.rglob("CLAUDE.md"))
               if not any(part.startswith(".") for part in p.relative_to(root).parts)
               and p.relative_to(root).parts[0] not in TRIGGER_SKIP_DIRS]
    docs_dir = root / "docs"
    targets += [(p, False) for p in _docs_markdown(docs_dir)
                if p.relative_to(docs_dir).parts[0] not in _HISTORICAL_DOC_DIRS]

    for path, blocking in targets:
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root)
        shown = 0
        elsewhere = {}
        dead = []
        for c, n in _repo_paths_cited(text, top_dirs).items():
            if (root / c).exists() or (path.parent / c).exists():
                continue
            why = gitstate.worktree_absence(root, c)
            if why:
                elsewhere[c] = why
            else:
                dead.append((c, n))
        if not blocking and len(dead) > _DEAD_PATH_MAX_PER_FILE:
            notes.append(
                f"{rel} cites {len(dead)} paths that do not exist (showing "
                f"{_DEAD_PATH_MAX_PER_FILE}). A doc this far out of date is usually a dated "
                "one-off that belongs in docs/archive/ (rule 10), not a doc to repair.")
        for cand, lineno in _repo_paths_cited(text, top_dirs).items():
            # A markdown link inside docs/ may be relative to its OWN directory
            # (docs/progress.md → `experiments/INDEX.md`), which is valid and common.
            # Judge a path dead only when NEITHER reading resolves.
            if (root / cand).exists() or (path.parent / cand).exists():
                continue
            if cand in elsewhere:
                notes.append(f"{rel}:{lineno}: {elsewhere[cand]}")
                continue
            if not blocking:
                shown += 1
                if shown > _DEAD_PATH_MAX_PER_FILE:
                    continue
            (issues if blocking else notes).append(
                f"{rel}:{lineno} cites `{cand}`, which does not exist. A cited path is a "
                "claim like any other (rule 2) — fix the path, or drop the citation.")
    return issues, notes


def evidence_sha_notes(root, records):
    """Recorded evidence whose sha git can no longer follow. Returns notes (advisory).

    ADVISORY on purpose, and it is the same ratchet ADR 9 uses: `epic item` now REFUSES
    an unresolvable sha at write time, so new debt cannot enter, while what is already on
    the board is reported and can only shrink. Blocking a whole project's checks on a
    branch someone deleted last month would get the checker switched off, and the fix is
    often no longer available — the commit is gone.
    """
    notes = []
    top_dirs = {d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")}
    for n, (path, fm) in sorted(dict(records).items()):
        rel = path.relative_to(root)
        if fm.get("status") == "done":
            answers = [(f"done_when {c.get('id')}", epics.clause_result(c))
                       for c in epics.done_when_of(fm)]
            answers.append(("outcome", str(fm.get("outcome") or "").strip()))
            for what, text in answers:
                if text and not _cites_an_artifact(text, top_dirs):
                    notes.append(NonActionable(
                        f"{rel}: {what} states a result but cites no artifact (A5) — no path, "
                        "no sha, no `verified:` marker. The epic is CLOSED, so this is history, "
                        "not debt to repair: the citation belongs in whatever cites this result "
                        "next (rule 2 / ADR 9)."))
                for tok in _scratch_paths_cited(text or ""):
                    notes.append(NonActionable(
                        f"{rel}: {what} cites `{tok}` (A6) — a scratch or build path, gone by "
                        "the next session. The epic is CLOSED, so this is history: whatever "
                        "cites this result next re-reads the number from a kept artifact, "
                        "or writes it `unverified` (rule 2 / ADR 9)."))
        for item in epics.items_of(fm):
            bad = epics.unresolvable_shas(str(item.get("evidence") or ""), root)
            for tok, why in bad:
                notes.append(_note(
                    f"{rel}: item {item.get('id', '?')} cites evidence `{tok}`, which {why}. "
                    "The board's evidence is what every downstream claim rests on (rule 2) — "
                    "repoint it at the merge commit that carries the work.",
                    fm.get("status") == "done"))
    return notes


def _a3_remedy(path):
    """What to DO about an unmarked status word — which is not the same everywhere.

    Anywhere else, the fix is to mark the claim. In progress.md there is nothing to mark:
    rule 10 says the file holds no metric values and no experiment status at all, so
    "add `verified: <sha>`" would talk an agent into a second rule violation dressed as a
    fix. The record is where the number lives; progress.md links it.
    """
    if path.name == "progress.md":
        return ("progress.md holds no metric values or status words (rule 10): replace the "
                "number with a link to the record that holds it.")
    return "Add `verified: <sha|date>` on the line, or write it `unverified`."


# A5 reads FRONTMATTER, where a path is written bare far more often than in backticks,
# so it cannot reuse `_repo_paths_cited` (which wants a code span or a markdown link).
# Bare is safe to accept here because the first segment still has to be a real top-level
# directory: "and/or" is not a citation, "data/experiments/exp_01/run_1/" is.
_BARE_PATH_RE = re.compile(r"(?<![\w/])([A-Za-z_][\w.-]*)/[\w./*-]+")


def _cites_an_artifact(text, top_dirs):
    """Does this answer point at something a reader can go and open?

    Three forms count, and nothing else: a repo path, a sha-shaped token, or the
    `verified:` / `unverified` marker A3 already speaks. A command is deliberately NOT
    enough — "cargo nextest … 72/72 pass" names how the number was made but not the run
    that made it, and a number nobody can re-open at the commit it came from is the
    recalled result rule 2 exists to stop.
    """
    if EVIDENCE_RE.search(text) or epics.SHA_TOKEN_RE.search(text):
        return True
    return any(m.group(1) in top_dirs for m in _BARE_PATH_RE.finditer(text))


# A6 — a citation into a scratch or build directory is not evidence. The file is real
# while the session lasts and gone, or overwritten, by the next one, and it lives on one
# machine: /tmp, .tmp/, target/, node_modules/, dist/, .cache/. Rule 4 already says "never
# /tmp" for a run's outputs; the log a done_when quotes is the same kind of thing.
# A clause that cites a gitignored log can quote numbers from another run: it was typed
# while that log was still being written, and nothing could catch it once the file was gone.
# Segments, not prefixes, so `rust/target/…` and `packages/client/dist/…` count too.
# `build/` is deliberately absent: too many projects track a directory of that name.
SCRATCH_SEGMENTS = frozenset({".tmp", "tmp", "target", "node_modules", "dist", ".cache",
                              "__pycache__"})
_PATH_TOKEN_RE = re.compile(r"(?<![\w-])(/?[\w.-]+(?:/[\w.*-]+)+)")


def _scratch_paths_cited(text):
    """Every path-shaped token in `text` whose directory part enters a scratch dir."""
    out = []
    for m in _PATH_TOKEN_RE.finditer(text):
        tok = m.group(1)
        dirs = tok.split("/")[:-1]
        if tok.startswith("/tmp/") or any(d in SCRATCH_SEGMENTS for d in dirs):
            out.append(tok)
    return out


# Rule 10 in numbers. A3 catches status WORDS; progress.md also collects the COUNTS —
# a suite total `735/735`, `1938 LOC`, `12 goldens`, `2313 passed` — and those are the
# values that go stale unnoticed (a gate that knows only the words lets counts reach
# `## Current`). A fraction is a count only in
# pass/total shape: numerator ≤ denominator and denominator ≥ 10, so ordinals and board
# positions ("epics 6/8", "item 3/6") pass, and a board tally ("items 10/10", "4/4
# done_when") is the INDEX's business, not a metric. There is nothing to mark in
# progress.md — the fix is the link to the record that holds the number.
PROGRESS_COUNT_RE = re.compile(
    r"\b(\d+)\s*/\s*(\d+)\b"
    r"|\b\d[\d,]*\s*(?:[a-z]+\s+)?(?:LOC|tests?|passed|failed|goldens?)\b")
PROGRESS_COUNT_MIN_TOTAL = 10
# A fraction next to one of these is a board tally ("items 10/10", "4/4 done_when").
_BOARD_WORDS = frozenset({"item", "items", "done_when", "clause", "clauses", "epic", "epics",
                          "option", "options"})
_WORD_BEFORE_RE = re.compile(r"(\w+)\W*$")
_WORD_AFTER_RE = re.compile(r"^\W*(\w+)")


def _progress_counts(line):
    """The result counts a progress.md line asserts (see PROGRESS_COUNT_RE)."""
    prose = _prose(line)
    found = []
    for m in PROGRESS_COUNT_RE.finditer(prose):
        if m.group(1) is not None:
            num, den = int(m.group(1)), int(m.group(2))
            if not (num <= den and den >= PROGRESS_COUNT_MIN_TOTAL):
                continue
            before = _WORD_BEFORE_RE.search(prose[:m.start()])
            after = _WORD_AFTER_RE.search(prose[m.end():])
            if any(w and w.group(1).lower() in _BOARD_WORDS for w in (before, after)):
                continue
        found.append(m.group(0))
    return found


def adr9_findings(root, exps, already_reported=(), epic_records=()):
    """A1-A5. Returns [(repo-relative path, message)] — the caller stages the severity.

    A2 defers to the unconditional run-dir check above: a path it already reported is
    skipped so the same dead artifact is never named twice.

    A5 is A1's twin on the other record kind. A1 catches an exp whose takeaway names no
    source_artifacts; A5 catches an EPIC whose done_when result or outcome asserts what
    the work achieved and points at nothing. That half went unchecked for a reason worth
    writing down: A3 reads prose and deliberately skips frontmatter, but an epic's
    results are IN the frontmatter — so the one place an epic states its outcomes was the
    one place no evidence check ever looked (an epic can close on a "full gate green"
    claim with no path, sha or marker in the clause, while the logs behind it sit in a
    gitignored build dir and `docs check` stays green).
    """
    out = []

    for n, (path, fm) in sorted(exps.items()):
        rel = str(path.relative_to(root))
        if str(fm.get("takeaway") or "").strip() and not (fm.get("source_artifacts") or []):
            out.append((rel,                                              # A1
                f"exp_{n}: takeaway is written but source_artifacts is empty — a result is cited, "
                f"not recalled (rule 2 / ADR 9). Name the file it was read back from: "
                f"`maestro exp update --id={n} --source-artifacts=data/experiments/...`."))
        for s in fm.get("source_artifacts") or []:
            if (n, s) in already_reported or (root / s).exists():
                continue
            if gitstate.worktree_absence(root, str(s)):
                continue          # in the main checkout; this worktree lacks the ignored dir
            out.append((rel,                                              # A2
                f"exp_{n}: source_artifacts '{s}' does not exist — the recorded result has lost "
                "its evidence (rule 2 / ADR 9)."))

    docs = _docs_markdown(root / "docs")
    for p in docs:
        rel = str(p.relative_to(root))
        text = p.read_text(errors="replace")
        lines = text.splitlines()
        in_fence = False
        in_fm = lines[:1] == ["---"]
        in_log = False        # an epic's `## Log` is the CLI's own trace, not a claim
        hits = 0
        for i, line in enumerate(lines, 1):
            if in_fm:
                in_fm = line.strip() != "---" or i == 1
                continue
            if FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if line.startswith("## "):
                in_log = p.parent.name == "epics" and line.strip() == "## Log"
            if in_fence or in_log or EVIDENCE_RE.search(line):
                continue
            m = STATUS_WORD_RE.search(_prose(line))
            counts = _progress_counts(line) if p.name == "progress.md" else []
            if not m and not counts:
                continue
            hits += 1
            if hits > A3_MAX_PER_FILE:
                continue
            if m:
                out.append((rel,                                          # A3
                    f"{rel}:{i}: status word '{m.group(1)}' is asserted with no evidence "
                    "marker — a status word about code gates work the way a metric does "
                    f"(rule 2 / ADR 9). {_a3_remedy(p)}"))
            else:
                out.append((rel,                                          # A3 (rule 10)
                    f"{rel}:{i}: holds a result count '{counts[0]}' — a test total, a LOC "
                    "count or a pass count is a metric value, and progress.md carries none "
                    f"(rule 10): it goes stale unnoticed. {_a3_remedy(p)}"))
        if hits > A3_MAX_PER_FILE:
            out.append((rel, f"{rel}: {hits - A3_MAX_PER_FILE} further unmarked status word(s) "
                             "on later lines (first 3 listed above)."))

    triggered = _trigger_rows(root)
    for p in docs:
        rel_parts = p.relative_to(root / "docs").parts
        if rel_parts[0] in A4_SKIP_DIRS or p.name in KNOWN_DOCS:
            continue
        lines = p.read_text().splitlines()
        if len(lines) < A4_MIN_LINES:
            continue
        rule_lines = sum(1 for ln in lines if RULE_MODAL_RE.search(ln))
        if rule_lines < A4_MIN_RULE_LINES:
            continue
        rel = str(p.relative_to(root))
        if rel in triggered or p.name in triggered:
            continue
        out.append((rel,                                                  # A4
            f"{rel} reads as rule-bearing ({rule_lines} lines say must/never/always) but no "
            "CLAUDE.md has a 'when to load' row for it — no harness auto-loads docs/*.md, so "
            "those rules are dead (core rule 12 / ADR 9). Add a trigger row, inline the rules, "
            "or move the file to docs/archive/."))

    top_dirs = {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    for n, (p, fm) in sorted(dict(epic_records).items()):
        # A CLOSED epic is a dated record: its answers describe what was measured then,
        # and `outcome` has no CLI path to correct at all. Those go to the advisory sweep
        # instead (evidence_sha_notes) — a check whose only remedy is rewriting history
        # is a check people learn to switch off. Blocking bites while the epic is OPEN,
        # which is the whole window in which the citation can still be added honestly.
        if fm.get("status") == "done":
            continue
        rel = str(p.relative_to(root))
        answers = [(f"done_when {c.get('id')}", epics.clause_result(c))
                   for c in epics.done_when_of(fm)]
        answers.append(("outcome", str(fm.get("outcome") or "").strip()))
        for what, text in answers:
            if not text or _cites_an_artifact(text, top_dirs):
                continue
            clause = what.split()[-1] if what.startswith("done_when") else None
            remedy = (f"`maestro epic done-when --id={n} --clause={clause} --result=...` "
                      "rewrites it." if clause else
                      "The outcome is set at close; a follow-up log line can carry the "
                      "citation without rewriting a closed record.")
            out.append((rel,                                              # A5
                f"epic_{n}: {what} states a result but cites no artifact — no path, no sha, "
                "no `verified:` marker. A result is read back from something, not recalled "
                f"(rule 2 / ADR 9): name the file, run dir or merge sha it came from. {remedy}"))
        for what, text in answers:
            for tok in _scratch_paths_cited(text):
                clause = what.split()[-1] if what.startswith("done_when") else None
                out.append((rel,                                          # A6
                    f"epic_{n}: {what} cites `{tok}` — a scratch or build path is gone by the "
                    "next session and lives on one machine, so it is not evidence (rule 2; rule 4 "
                    "says never /tmp). Copy the log under data/experiments/<exp>/run_<K>/ or "
                    "docs/archive/ and cite that path"
                    + (f" (`maestro epic done-when --id={n} --clause={clause} --result=...`)."
                       if clause else ".")))
    return out


def stage_adr9(findings, touched, issues, notes):
    """ADR 9 step 2 — the RATCHET. Hard-fail a finding only when its file was touched.

    A hard fail on day one against an existing backlog does not produce verification, it
    produces a disabled check. So the debt is advisory and can only shrink, while
    anything edited in this session blocks.
    """
    for rel, message in findings:
        if touched is None:
            notes.append(message + " [advisory: git could not say what changed, so ADR 9's "
                                   "gate cannot fire]")
        elif rel in touched:
            issues.append(message)
        else:
            notes.append(NonActionable(
                message + " [advisory: file unchanged since HEAD and untouched by a commit in "
                          "the session window — ADR 9 stages the hard fail to files touched "
                          "this session]"))


def staged_paths(root=None):
    """Repo-relative paths git has staged for the next commit, as a set.

    An empty set when the call fails or nothing is staged — callers treat that as
    "scope to nothing", which is the safe direction for a commit gate: no staged
    file means no commit to gate.
    """
    root = Path(root or ROOT)
    try:
        out = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--name-only"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def scope_to(findings, paths):
    """The findings that name one of `paths`.

    A finding leads with the repo-relative path it is about (`docs/progress.md:9: ...`),
    so a substring test is enough and needs no per-check plumbing. A finding that names
    no path at all is DROPPED here by design: `--staged` answers "does this commit add
    drift", and a project-wide observation is not this commit's to answer.
    """
    return [f for f in findings if any(p in f for p in paths)]


def check(strict=False, staged=False, verbose=False, report_only=False):
    """Run every check. Returns the process exit code (0 clean, 2 drift).

    `strict` also fails on advisories, for callers that want a hard gate — every advisory,
    the non-actionable ones included, so the exit code does not depend on `verbose`.
    `report_only` prints the SAME report (same lines, same streams, same fold) but returns
    0 whatever it found. It is for a consumer that turns any non-zero exit into a refusal
    — a Stop hook, which on exit 2 forces another turn, every turn, for as long as a hard
    finding stands. A generated INDEX.md that is on `main` but not yet on the feature
    branch is normal branch state, and must not block a turn-end.
    A drift report is information for the next turn, never a reason to refuse ending one;
    the `--staged` pre-commit gate keeps its exit codes. `strict` and `report_only` are
    opposite intents — the CLI refuses the pair; here `report_only` simply wins.
    `verbose` prints the NonActionable advisories too; by default they are folded into
    one summary line, since nothing in them changes between turns or asks for a fix.
    `staged` narrows the report to findings about files staged for commit — the
    pre-commit gate, which must block NEW drift without holding a commit hostage to
    drift that was already there (a domain doc can carry many such lines, which would
    block every unrelated docs commit).
    """
    issues = []   # blocking  — exit 2
    notes = []    # advisory  — reported, exit code unchanged

    exps = load_kind(EXP_DIR, "exp")
    adrs = load_kind(ADR_DIR, "adr")
    epic_records = load_kind(EPIC_DIR, "epic")

    # 0. The declaration (design.md → "Shape declaration"). maestro.toml says whether
    #    this is a maestro project, which rule layers apply and what the data shape has
    #    been over time; the checks below read it instead of assuming one shape.
    try:
        decl = declaration.load(ROOT)
    except declaration.DeclarationError as exc:
        issues.append(f"{exc} — a declaration that cannot be read is the one state nothing "
                      "can reason about; fix maestro.toml (or `[tool.maestro]`) first.")
        decl = None
    if decl is None:
        # Transition: an undeclared project is still checked as before, with this one
        # advisory. The release that drops the inference makes this an exit-0 no-op.
        notes.append(
            f"membership is inferred from docs/ record dirs — no {declaration.DECLARATION_FILE}. "
            "The inference polices projects that never adopted maestro (one abandoned ADR stub "
            "is enough) and goes in the next release; `maestro init` writes the declaration.")
    research = decl is None or decl.research
    legacy_records = 0

    def legacy(fm):
        """A record dated before the current shape's line — written under a layout that
        is gone, or before adoption: history, checked under nothing."""
        return decl is not None and decl.legacy(declaration.record_date(fm))

    # Under `tiers` (or no declaration at all, the transition default) data paths are the
    # checker's business; under `other` the project owns its layout and a data citation
    # is taken as written.
    data_checked = decl is None or decl.polices_data

    def evidence_ok(ref):
        """A cited artifact resolves: a path on disk, or a well-formed catalog table
        reference (`table:<schema>.<name>@<snapshot>`). A data citation under `other`
        is not judged."""
        ref = str(ref)
        if not data_checked and (ref.startswith("data/") or ref.startswith("table:")):
            return True
        if ref.startswith("table:"):
            return declaration.TABLE_REF.match(ref) is not None
        return (ROOT / ref).exists()

    def elsewhere(ref):
        """A missing, gitignored path this linked worktree lacks but the main checkout
        holds: a warning, not drift (gitstate.worktree_absence). None otherwise."""
        ref = str(ref)
        if ref.startswith("table:"):
            return None
        return gitstate.worktree_absence(ROOT, ref)

    # 1. INDEX.md staleness, decided on CONTENT rather than mtime.
    #    git does not preserve mtimes, so a checkout, clone or branch switch used to
    #    report a byte-correct INDEX as stale. A check that cries wolf gets disabled.
    #    The builders take indexes' own loader output, which is a different shape from
    #    the {n: (path, frontmatter)} map used elsewhere in this module.
    from . import indexes as _indexes
    for idx, load, build in [
        (_indexes.EXP_DIR / "INDEX.md",
         lambda: _indexes.load_kind(_indexes.EXP_DIR, "exp"), _indexes.build_exp_index),
        (_indexes.ADR_DIR / "INDEX.md",
         lambda: _indexes.load_kind(_indexes.ADR_DIR, "adr"), _indexes.build_adr_index),
        (_indexes.EPIC_DIR / "INDEX.md",
         lambda: _indexes.load_epics(_indexes.EPIC_DIR),
         lambda recs: _indexes.build_epic_board(recs, _indexes._declared_arcs())),
        (_indexes.DATA_DIR / "INDEX.md",
         _indexes.load_datasets, _indexes.build_data_index),
    ]:
        if not idx.exists():
            continue
        try:
            records = load()
            if not records:
                continue
            expected = build(records)
        except Exception as exc:                  # a builder that cannot run is its own bug
            issues.append(f"{idx.relative_to(ROOT)} could not be rebuilt for comparison: {exc}")
            continue
        if expected.strip() != idx.read_text().strip():
            issues.append(
                f"{idx.relative_to(ROOT)} does not match its records. "
                "Run `maestro index render --kind=all`.")

    # 2. findings.md / CLAUDE.md cite valid exps
    for f in [DOCS_DIR / "findings.md", ROOT / "CLAUDE.md"]:
        if not f.exists():
            continue
        for n in map(int, EXP_REF.findall(f.read_text())):
            if n not in exps:
                issues.append(f"{f.name} references Exp {n} but exp_{n:02d}_*.md does not exist.")
            elif exps[n][1].get("status") == "superseded":
                issues.append(f"{f.name} references Exp {n} which is superseded.")

    # 3. exp lineage and artifact integrity
    for n, (_, fm) in exps.items():
        parent = fm.get("parent")
        if parent and parent not in exps:
            issues.append(f"exp_{n}: parent={parent} does not exist.")
        elif parent and exps[parent][1].get("status") == "superseded":
            issues.append(f"exp_{n}: parent={parent} is superseded.")
        if legacy(fm):
            legacy_records += 1
            continue
        for path in fm.get("consumes") or []:
            if not evidence_ok(path):
                why = elsewhere(path)
                (notes if why else issues).append(
                    f"exp_{n}: consumes '{path}' — {why}" if why
                    else f"exp_{n}: consumes '{path}' but file is missing.")

    # 4. adr integrity. Two models pass. The live-ADR model (core rule 13): one
    #    live ADR per area, amended in place; a folded or dead ADR leaves docs/adrs/ for
    #    docs/archive/adrs/, so no live record is `superseded` at all. The older model,
    #    which some projects still carry: the old record stays live with
    #    `status: superseded` and a `superseded_by` pointer. That pointer may name an
    #    archived number — the replacement can itself have been folded since.
    archived_adrs = frontmatter.archived_nums(ADR_DIR, "adr")
    for n, (_, fm) in adrs.items():
        sb = fm.get("superseded_by")
        if sb is not None and sb not in adrs and sb not in archived_adrs:
            issues.append(f"adr_{n}: superseded_by={sb} does not exist.")
        if fm.get("status") == "superseded" and not sb:
            issues.append(f"adr_{n}: status=superseded but superseded_by is not set.")

    # 4b. a supersession written into the NEWER record only. `adr_30` says "supersedes
    #     ADR 29 rungs 3-5" while adr_29 stays `accepted`; adr_63 renames adr_54's whole
    #     vocabulary and adr_64 deletes the contract adr_11 kept — none of the older
    #     records said so. Check 4 only sees the superseded_by field, which the OLD record carries,
    #     so a supersession that lands in the new record's prose is invisible to it.
    #     Advisory, actionable: set the old record's status, or add a dated CONTEXT
    #     CORRECTION note to it — the decision text stays verbatim (authority-sweep rule).
    for m, (path, fm) in adrs.items():
        if fm.get("status") == "superseded":      # a retired record supersedes nothing
            continue
        # every prose field of the frontmatter + the body: ADRs 1-59 keep their prose in
        # `decision:` / `context:` / `consequences:`, where YAML line-folds would split
        # "supersedes" from "ADR 29" in the raw text (adr_30 carries it in consequences)
        body = "\n".join(str(v) for v in fm.values() if isinstance(v, str))
        body += "\n" + FM_RE.sub("", path.read_text())
        named = set()
        for pat in (r"supersed\w*\s+(?:ADR|adr)[-\s]?0*(\d+)",
                    r"(?:ADR|adr)[-\s]?0*(\d+)(?:'s)?\s+(?:is|are|was|were)\s+superseded",
                    r"(?:overturns?|overrides?|retires?|revises?|replaces?)\s+(?:ADR|adr)[-\s]?0*(\d+)"):
            named.update(int(x) for x in re.findall(pat, body, re.I))
        # the live-ADR History line: "folds in ADR 7, 11, 13" names every folded number
        for run in re.findall(r"\bfold(?:s|ed)?\s+(?:in\s+)?((?:ADRs?|adrs?)[-\s]?\d+"
                              r"(?:\s*(?:,|and)\s*\d+)*)", body, re.I):
            named.update(int(x) for x in re.findall(r"\d+", run))
        for n in sorted(named):
            if n == m or n not in adrs:
                continue
            old_path, old_fm = adrs[n]
            if old_fm.get("status") == "superseded":
                continue
            if "CONTEXT CORRECTION" in old_path.read_text() and f"ADR {m}" in old_path.read_text():
                continue
            notes.append(
                f"adr_{n} is still live (`{old_fm.get('status')}`), but adr_{m} says it folds in, "
                f"supersedes or retires it. Live-ADR model: move adr_{n} to docs/archive/adrs/ "
                f"with a row in that README's map ({n} → {m}). A project still on the superseded "
                f"model sets `maestro adr update --id={n} --status=superseded --superseded-by={m}`, "
                f"or adds a dated CONTEXT CORRECTION note naming ADR {m}.")

    # 4c. W1 — an ADR cites epics, items or the plan (modules/kanban.md). Dated: text
    #     from W1_SINCE on blocks, older text is one folded legacy advisory per ADR.
    w_issues, w_notes = adr_work_ref_findings(adrs)
    issues.extend(w_issues)
    notes.extend(w_notes)

    # 5. orphan docs in docs/ root
    if DOCS_DIR.exists():
        for f in DOCS_DIR.iterdir():
            if not (f.is_file() and f.suffix == ".md"):
                continue
            if f.name in KNOWN_DOCS:
                continue
            # Allow domain/reference docs that declare themselves via frontmatter
            m = FM_RE.match(f.read_text())
            if m and (yaml.safe_load(m.group(1)) or {}).get("kind") in ("domain-doc", "reference"):
                continue
            issues.append(
                f"docs/{f.name} is not a standard framework file. "
                "Design decision? → maestro adr new --slug=<slug>. "
                "Domain reference? → add 'kind: domain-doc' frontmatter."
            )

    # 6. Hard size caps (core.md). Over-cap files must be split/archived.
    for rel, cap, hint in SIZE_CAPS:
        f = ROOT / rel
        if f.exists():
            n = len(f.read_text().splitlines())
            if n > cap:
                issues.append(f"{rel} is {n} lines (cap {cap}). {hint}")

    for n, (p, _) in exps.items():
        # Count BODY lines only — the prose AFTER the closing frontmatter '---'.
        # The 150-line cap exists to keep the write-up prose tight; the YAML
        # frontmatter is structured data (per-round metric:/source_artifacts: blocks),
        # so counting it against a prose cap is wrong. Strip frontmatter, then count.
        body = FM_RE.sub("", p.read_text(), count=1)
        lines = len(body.splitlines())
        if lines > EXP_LINE_CAP:
            issues.append(
                f"{p.relative_to(ROOT)} body is {lines} lines (cap {EXP_LINE_CAP}). "
                "Experiment is multiple — split into new exp number."
            )

    for p in ROOT.rglob("CLAUDE.md"):
        if any(part.startswith(".") for part in p.relative_to(ROOT).parts):
            continue
        est = len(p.read_bytes()) // BYTES_PER_TOKEN
        if est > CLAUDE_TOKEN_CAP:
            issues.append(
                f"{p.relative_to(ROOT)} is ~{est} tokens (cap {CLAUDE_TOKEN_CAP}). "
                "Move detail to docs/*.md — and give it a 'when to load' row (core rule 12)."
            )

    # 6b. Core rule 12 — a docs/*.md that holds RULES must have a "when to load" trigger
    #     inside CLAUDE.md, not just a prose mention. A doc named only in prose is loaded
    #     by no harness, so its rules are dead. Advisory: it flags intent, and only the
    #     author knows whether a given doc carries rules or is pure reference.
    _claude = ROOT / "CLAUDE.md"
    if _claude.exists():
        _text = _claude.read_text()
        _triggered = {
            m.group(1)
            for line in _text.splitlines() if line.lstrip().startswith("|")
            for m in [re.search(r"docs/([A-Za-z0-9_.-]+\.md)", line)] if m
        }
        _mentioned = set(re.findall(r"docs/([A-Za-z0-9_.-]+\.md)", _text))
        for _doc in sorted(_mentioned - _triggered - KNOWN_DOCS):
            if _doc == "INDEX.md":
                continue
            _path = DOCS_DIR / _doc
            if not _path.exists():
                continue
            _est = len(_path.read_bytes()) // BYTES_PER_TOKEN
            notes.append(
                f"docs/{_doc} (~{_est} tokens) is named in CLAUDE.md prose but has no "
                "'when to load' table row. If it holds RULES they are dead — no harness "
                "auto-loads docs/*.md (core rule 12). Add a trigger row, or inline the rules."
            )

    # 7. Datasets: each data/raw/<name>/ needs a record; recorded sha must match the bytes
    #    (core.md → Source datasets). Records live in docs/data/<name>.md, written by `maestro dataset`.
    #    Both halves are data-path judgments, so both are off under shape `other`.
    datasets = _load_datasets() if research else {}
    if research and data_checked and RAW_DIR.exists():
        for d in sorted(RAW_DIR.iterdir()):
            # data/raw may hold either <name>/ dirs or loose files; key by the stem either way.
            stem = d.name[:-3] if d.is_file() and d.name.endswith(".md") else d.name
            # Match the dataset record key, which is the SLUGIFIED name (case preserved, non-alnum→_),
            # so a raw dir like "My-Dataset" doesn't spuriously read as "no record".
            name = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_")
            if d.is_dir() or d.is_file():
                if name not in datasets and not d.name.startswith("."):
                    issues.append(
                        f"data/raw/{d.name} has no dataset record — run "
                        f"`maestro dataset new --name={name}` (computes the sha, scaffolds docs/data/{name}.md)."
                    )
    # sha drift / missing data for every recorded dataset (catches edit-in-place + dangling symlink).
    unchecked_datasets = 0
    for name, (p, fm) in sorted(datasets.items()):
        rel = fm.get("path", "")
        if legacy(fm):
            legacy_records += 1
            continue
        if not data_checked:
            # `other`: the project's own layout (an append-only feed, a catalog table) has
            # no dir sha the checker could reason about.
            unchecked_datasets += 1
            continue
        if is_collecting(fm):
            # A pull in progress rewrites its own directory by design, so comparing shas
            # would report "changed in place" on every turn for something working exactly
            # as intended. Advisory until `dataset update --complete` stamps the sha.
            notes.append(f"{p.relative_to(ROOT)}: {collecting_note(name, fm)}")
            continue
        actual = _dataset_sha(name, fm.get("version", ""), rel)
        recorded = fm.get("sha256", "")
        why = elsewhere(f"data/{_data_rel(name, fm.get('version', ''), rel)}") if not actual else None
        if why:
            notes.append(f"{p.relative_to(ROOT)}: {why}")
        elif not actual:
            issues.append(
                f"{p.relative_to(ROOT)}: data/{_data_rel(name, fm.get('version', ''), rel)} has no files "
                "(dangling symlink, or data not pulled). Restore it, or archive the record."
            )
        elif recorded and actual != recorded:
            issues.append(
                f"{p.relative_to(ROOT)}: sha drift — recorded {recorded[:12]} != actual {actual[:12]}. "
                "Data changed in place (breaks immutability) — make a new version, or "
                f"`maestro dataset update --name={name} --rehash` if the change is intended."
            )
        elif not recorded:
            issues.append(
                f"{p.relative_to(ROOT)}: no sha256 recorded — run `maestro dataset update --name={name} --rehash`."
            )

    # 8. Orphaned experiment output: a run that wrote data but no record (core.md → one
    #    experiment = one record + one data dir; rule 4 → the log lives next to its data).
    #    Two shapes, both the same failure class ("work ran, record never written"):
    #    a data dir whose exp_NN has no record at all, and a record still `status: planned`
    #    while its data dir already holds output. run.log is matched at ANY depth so every
    #    run_<K>/run.log (ADR 3 → a re-run is the next run dir) counts as output too.
    if research and EXPDATA_DIR.is_dir():
        for d in sorted(EXPDATA_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            logs = sorted(p for p in d.rglob("run.log")
                          if p.is_file() and p.stat().st_size > 0)
            if not logs:
                continue
            rel = logs[0].relative_to(ROOT)
            m = DIR_EXP_NUM.match(d.name)
            if not m:
                issues.append(
                    f"data/experiments/{d.name}/ holds a non-empty run.log ({rel}) but its name "
                    "has no exp_NN prefix — unrecorded scratch. Rename it exp_NN_<slug>/ and mint "
                    "the record (`maestro exp new --slug=<slug>`), or move it out of "
                    "data/experiments/."
                )
                continue
            n = int(m.group(1))
            if n not in exps:
                issues.append(
                    f"data/experiments/{d.name}/ holds a non-empty run.log ({rel}) but "
                    f"docs/experiments/exp_{n:02d}_*.md does not exist — work ran, the record was "
                    f"never written. Run `maestro exp new --slug=<slug>`."
                )
            elif exps[n][1].get("status") == "planned":
                issues.append(
                    f"exp_{n}: status=planned but {rel} is non-empty — work ran, the record was "
                    f"never written up. Run `maestro exp update --id={n} --status=running` "
                    f"(or --status=done with --outcome/--takeaway)."
                )

    # 9. Run dirs agree with their record (rule 4 / ADR 3 → exp_NN_<slug>/run_<K>/).
    #    BLOCKING is reserved for a stored POINTER that resolves to nothing — best_run and
    #    source_artifacts. A recorded number whose evidence path is dead is the rule-2
    #    failure itself, and the fix is mechanical (repoint or restore).
    #    ADVISORY is run-dir COMPLETENESS (run.log + metrics.json present and non-empty).
    #    It has honest exceptions: a crashed or killed run legitimately leaves a partial
    #    dir, a tracker-backed project keeps its metrics in W&B/MLflow instead of on disk,
    #    and dirs predating ADR 3 are grandfathered. Blocking there would teach people to
    #    delete evidence to silence the checker — the opposite of what rule 4 is for.
    if research and EXPDATA_DIR.is_dir():
        for d in sorted(EXPDATA_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            m = DIR_EXP_NUM.match(d.name)
            fm = exps.get(int(m.group(1)), (None, {}))[1] if m else {}
            # An infra run (a probe, a smoke test, a throughput grid) leaves a log, not
            # a metric; a run dir of a record that predates the first shape is history.
            if fm.get("outcome") == "infra" or legacy(fm):
                continue
            for r in run_dirs(d):
                absent = [f for f in ("run.log", "metrics.json")
                          if not (r / f).is_file() or (r / f).stat().st_size == 0]
                if absent:
                    notes.append(
                        f"data/experiments/{d.name}/{r.name}/ has no non-empty "
                        f"{' or '.join(absent)} — a run dir carries params + code provenance, "
                        "run.log and metrics.json (rule 4). Expected only for an aborted run, "
                        "a tracker-backed project, or a dir predating the convention."
                    )

    missing_artifacts = set()
    for n, (p, fm) in sorted(exps.items()):
        if legacy(fm):
            continue
        best = str(fm.get("best_run") or "")
        # best_run is either a local run dir ('run_2') or a tracker run id — only the
        # former can be resolved on disk, so anything else is left to the tracker.
        if RUN_DIR_RE.match(best):
            d = exp_data_dir(n)
            why = None
            if d is None or not (d / best).is_dir():
                why = elsewhere(_run_dir_rel(n, best, d))
            if why:
                notes.append(f"exp_{n}: best_run={best} — {why}")
            elif d is None or not (d / best).is_dir():
                where = f"{d.name}/" if d else f"exp_{n:02d}_<slug>/"
                issues.append(
                    f"exp_{n}: best_run={best} but data/experiments/{where}{best}/ does not "
                    "exist. Point best_run at a run dir that is actually there "
                    f"(`maestro exp update --id={n} --best-run=run_K`)."
                )
        for s in fm.get("source_artifacts") or []:
            if not evidence_ok(s):
                missing_artifacts.add((n, s))
                why = elsewhere(s)
                if why:
                    notes.append(f"exp_{n}: source_artifacts '{s}' — {why}")
                    continue
                issues.append(
                    f"exp_{n}: source_artifacts '{s}' does not exist — the recorded number "
                    "has lost its evidence (rule 2). Restore the file, or repoint with "
                    f"`maestro exp update --id={n} --source-artifacts=...`."
                )

    # 10. Exp files record results only — no forward-looking sections (core.md → File ownership).
    for n, (p, _) in exps.items():
        body = FM_RE.sub("", p.read_text())
        for m in FORBIDDEN_EXP_HEADING.finditer(body):
            issues.append(
                f"{p.relative_to(ROOT)}: forward-looking section '{m.group(0).strip()}' — "
                "exp files record results only. Move planning to docs/progress.md."
            )

    # 11. Code tier import layering (core.md → "Code lives in 3 tiers").
    if research:
        issues.extend(layering_issues(ROOT))

    # 12. The kanban layer (ADR 7 / modules/kanban.md) — K1 a stalled in_progress epic
    #     (advisory), K2 a blocked flag with no reason, K3 frontmatter the CLI did not write,
    #     K10 a log that says "merged"/"complete" over a board that never moved.
    k_issues, k_notes = kanban_findings(epic_records, arcs=decl.arc_names if decl else ())
    issues.extend(k_issues)
    notes.extend(k_notes)

    # 13. Results are cited, not recalled (ADR 9) — A1..A4, STAGED: a finding hard-fails
    #     only when its file was touched this session — uncommitted, untracked, or
    #     rewritten by a commit inside the session window — so the existing backlog stays
    #     advisory while new debt is blocked from day one (ADR 9, step 2).
    #     A record dated before the first declared shape is history to ADR 9 as well.
    live_exps = {n: v for n, v in exps.items() if not legacy(v[1])}
    stage_adr9(adr9_findings(ROOT, live_exps, missing_artifacts, epic_records),
               touched_paths(ROOT), issues, notes)

    # 13b. Evidence git can still follow (rule 2). The write-time guard in `epic item`
    #      refuses a bad sha from now on; this sweeps what was recorded before it, and
    #      catches a sha that has ROTTED since — a branch deleted, a history rewritten.
    notes.extend(evidence_sha_notes(ROOT, epic_records))

    # 14. The stamp (rule 1, enforced): S1 a record edited by hand, S2 unstamped records.
    s_issues, s_notes = stamp_findings(ROOT)
    issues.extend(s_issues)
    notes.extend(s_notes)

    # 9. Dead references: a live doc cites a repo path that does not exist.
    _dead_issues, _dead_notes = dead_path_findings(ROOT)
    issues.extend(_dead_issues)
    notes.extend(_dead_notes)


    if legacy_records:
        notes.append(NonActionable(
            f"{legacy_records} record(s) dated before the current shape's line "
            f"({decl.current.name} since {decl.line}) are history: consumes, source_artifacts, "
            "dataset shas and run dirs were not checked (maestro.toml)."))
    if unchecked_datasets:
        notes.append(NonActionable(
            f"{unchecked_datasets} dataset record(s) not sha-checked: the declared shape is "
            "`other`, the project owns its data layout (maestro.toml)."))

    if staged:
        scope = staged_paths()
        issues = scope_to(issues, scope)
        notes = scope_to(notes, scope)

    # The report shows what a session can act on; the backlog the checker itself calls
    # history is one counted line unless asked for. `notes` stays whole for --strict.
    shown = notes if verbose else [w for w in notes if not isinstance(w, NonActionable)]
    hidden = len(notes) - len(shown)
    if hidden:
        shown = shown + [f"{hidden} advisor{'y' if hidden == 1 else 'ies'} on closed epics / "
                         "untouched files / legacy ADR text suppressed (--verbose shows them)"]

    if issues:
        # STDERR + exit 2. As a hook (pre-commit, or a Stop hook), exit 2 is the BLOCKING path: the
        # stderr report is fed back to the AGENT, which must clear the drift before it can
        # finish. Any OTHER non-zero exit is the "non-blocking" path — it prints to the
        # user's terminal and the agent NEVER SEES IT, so drift accumulates silently unless
        # a human relays the report by hand.
        # Surfacing drift to the agent is the entire point of the hook, hence 2 and not 1.
        # Keep the report on STDERR regardless: the non-blocking path drops stdout, which
        # once made every drift surface as the useless "Failed with non-blocking status
        # code: No stderr output". (Both non-hook callers — tests/e2e/run_smoke.sh and a
        # project's tools/gates.py — merge the two streams, so this is invisible to them.)
        print("DRIFT DETECTED:", file=sys.stderr)
        for i in issues:
            print(f"  - {i}", file=sys.stderr)
        # Advisories ride the SAME stream as the blocking report: on this path stdout is
        # dropped by the hook, so anything printed there would never reach the agent.
        for w in shown:
            print(f"  ~ {w}", file=sys.stderr)
        return 0 if report_only else 2

    # Clean path: stdout is the stream the caller reads, so advisories go there.
    for w in shown:
        print(f"  ~ {w}")
    print(f"OK ({len(exps)} experiments, {len(adrs)} ADRs, no drift detected"
          + (f"; {len(notes)} advisory)." if notes else ")."))
    # --strict turns the advisories into a failure too, for callers that want a hard gate.
    return 1 if (strict and notes and not report_only) else 0
