"""Experiment records — docs/experiments/exp_NN_<slug>.md.

One experiment = one hypothesis = one record (core rule 3). Results are filled in by
`update`; a wrong takeaway is corrected by `revise`, which keeps the original on record.
"""
import re
import shutil
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import epics
from .frontmatter import slugify, tombstone_path, EXP_DIR, FINDINGS, FM_RE, ROOT, load, next_num, render, write


EXP_OUTCOMES = {"confirmed", "refuted", "improved", "parity", "regression", "infra", "inconclusive"}


def exp_new(args):
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    records = load(EXP_DIR, "exp")
    n = next_num(records, EXP_DIR, "exp")
    slug = slugify(args.slug)
    if not slug:
        sys.exit(f"--slug={args.slug!r} has no word characters to name a file with.")
    path = EXP_DIR / f"exp_{n:02d}_{slug}.md"
    fm = {"exp": n, "title": args.slug, "status": "planned", "date": str(date.today()), "tags": []}
    body = f"\n# Exp {n} — {args.slug}\n\n**Goal**: \n\n**Method**: \n\n**Results**: \n\n**Takeaway**: \n"
    write(path, fm, body)
    render()
    print(f"Created {path.relative_to(ROOT)} (status=planned)")


def exp_update(args):
    records = load(EXP_DIR, "exp")
    if args.id not in records:
        sys.exit(f"exp_{args.id} not found.")
    path, fm = records[args.id]
    body = FM_RE.sub("", path.read_text())

    updates = {}
    if args.status:
        updates["status"] = args.status
    if args.outcome:
        if args.outcome not in EXP_OUTCOMES:
            sys.exit(f"--outcome must be one of: {', '.join(sorted(EXP_OUTCOMES))}")
        updates["outcome"] = args.outcome
    if args.takeaway:
        updates["takeaway"] = args.takeaway
    if args.track:
        updates["track"] = args.track
    if args.benchmark:
        updates["benchmark"] = args.benchmark
    if args.metric:
        # Accept either "key=val" or "key=val±sd" (the literature-recommended form).
        # --metric is repeatable (action="append") and each flag may also carry
        # multiple comma-separated key=val pairs.
        metric_dict = {}
        pieces = [p for entry in args.metric for p in entry.split(",")]
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            k, v = piece.split("=", 1)
            k, v = k.strip(), v.strip()
            sd = None
            for sep in ("±", "+/-", "+-"):
                if sep in v:
                    v, sd = v.split(sep, 1)
                    v, sd = v.strip(), sd.strip()
                    break
            try:
                v = float(v)
            except ValueError:
                pass
            metric_dict[k] = v
            if sd is not None:
                try:
                    sd = float(sd)
                except ValueError:
                    pass
                metric_dict[f"{k}_sd"] = sd
        updates["metric"] = metric_dict
    if args.parent is not None:
        if args.parent not in records:
            sys.exit(f"Parent exp_{args.parent} does not exist.")
        if records[args.parent][1].get("status") == "superseded":
            sys.exit(f"Parent exp_{args.parent} is superseded — dangling lineage.")
        updates["parent"] = args.parent
    if args.related:
        related = []
        for tok in args.related.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                n = int(tok)
            except ValueError:
                sys.exit(f"--related: '{tok}' is not an integer experiment number.")
            if n == args.id:
                sys.exit(f"--related cannot include self (exp_{n}).")
            if n not in records:
                sys.exit(f"--related: exp_{n} does not exist.")
            related.append(n)
        updates["related"] = sorted(set(related))
    if args.best_run:
        updates["best_run"] = args.best_run
    if args.dois:
        updates["paper_dois"] = [d.strip() for d in args.dois.split(",") if d.strip()]
    if args.adr is not None:
        updates["adr"] = args.adr
    if args.n_seeds is not None:
        updates["n_seeds"] = args.n_seeds
    if args.source_artifacts:
        updates["source_artifacts"] = [s.strip() for s in args.source_artifacts.split(",") if s.strip()]
    if args.consumes:
        updates["consumes"] = [p.strip() for p in args.consumes.split(",") if p.strip()]
    if args.produces:
        updates["produces"] = [p.strip() for p in args.produces.split(",") if p.strip()]
    if args.flags:
        valid_flags = {"single_seed", "large_unexpected_gain", "conflicts_prior",
                       "setup_unverified", "interpretation_uncertain"}
        flags = [f.strip() for f in args.flags.split(",") if f.strip()]
        for f in flags:
            if f not in valid_flags:
                sys.exit(f"--flags: '{f}' not recognized. Valid: {sorted(valid_flags)}")
        updates["flags"] = sorted(set(flags))
    if args.tags:
        updates["tags"] = [t.strip() for t in args.tags.split(",")]

    new_status = updates.get("status", fm.get("status"))
    new_outcome = updates.get("outcome", fm.get("outcome"))
    if new_status in ("done", "failed") and not (updates.get("outcome") or fm.get("outcome")):
        sys.exit("--status=done|failed requires --outcome.")
    if new_status in ("done", "failed") and not (updates.get("takeaway") or fm.get("takeaway")):
        sys.exit("--status=done|failed requires --takeaway.")
    if new_outcome in ("improved", "parity", "regression"):
        if not (updates.get("track") or fm.get("track")):
            sys.exit(f"--outcome={new_outcome} requires --track.")
        if not (updates.get("metric") or fm.get("metric")):
            sys.exit(f"--outcome={new_outcome} requires --metric.")
    # best_run is a run NAME (exp_NN_<slug>__<variant>__s<seed>), never a URL — the `runs` tool
    # derives URLs from the repo name + the project's tracker ([tool.maestro] in pyproject.toml).
    # An experiment with no tracked runs (sim, comp-chem, analysis) simply sets neither field.
    nb = updates.get("best_run")
    if nb and f"exp_{args.id:02d}" not in nb and f"exp_{args.id}" not in nb:
        print(f"  ! warning: --best-run '{nb}' does not embed 'exp_{args.id:02d}'. "
              "Run names should follow exp_NN_<slug>__<variant>__s<seed> so the tracker links back.")

    old_status = fm.get("status")
    fm.update(updates)
    write(path, fm, body)
    print(f"Updated exp_{args.id} (status: {old_status} → {fm['status']}).")
    render()


def exp_revise(args):
    """Append-only correction: don't lose the original takeaway, capture why it changed."""
    records = load(EXP_DIR, "exp")
    if args.id not in records:
        sys.exit(f"exp_{args.id} not found.")
    path, fm = records[args.id]
    body = FM_RE.sub("", path.read_text())
    previous = fm.get("takeaway") or ""
    if not previous:
        sys.exit(f"exp_{args.id} has no takeaway to revise. Use 'maestro exp update' first.")
    if args.new_takeaway.strip() == previous.strip():
        sys.exit("--new-takeaway is identical to the existing takeaway.")
    revisions = list(fm.get("revisions") or [])
    revisions.append({
        "date": str(date.today()),
        "by": args.by,
        "reason": args.reason,
        "previous_takeaway": previous,
        "new_takeaway": args.new_takeaway,
    })
    fm["revisions"] = revisions
    fm["takeaway"] = args.new_takeaway
    write(path, fm, body)
    print(f"Revised exp_{args.id} takeaway. {len(revisions)} revision(s) on record.")
    render()


EXP_LINE_CAP = 150  # mirrors core.md "Hard size caps" — exp_NN_*.md


def exp_set_body(args):
    """Replace the body of an experiment record, preserving its frontmatter verbatim.

    The frontmatter block is CLI-owned and stays byte-for-byte; only the prose
    under it is replaced. This is the CLI path for condensing/rewriting a record body
    (e.g. an over-cap exp), so the guard treats it as legitimate tooling rather than a
    hand-edit. The supplied body must not carry its own '---' frontmatter block.
    """
    records = load(EXP_DIR, "exp")
    if args.id not in records:
        sys.exit(f"exp_{args.id} not found.")
    path, fm = records[args.id]

    if args.from_stdin:
        new_body = sys.stdin.read()
    else:
        src = Path(args.from_file)
        if not src.exists():
            sys.exit(f"--from-file: {src} does not exist.")
        new_body = src.read_text()

    # The body must NOT contain its own frontmatter block — the frontmatter is preserved
    # verbatim from the existing record, never supplied via the new body.
    if FM_RE.match(new_body):
        sys.exit("--from-file/--from-stdin body starts with its own '---' frontmatter block. "
                 "Supply the body text ONLY; the frontmatter is preserved from the existing record.")

    # Preserve the record's existing frontmatter verbatim by writing it back unchanged.
    write(path, fm, new_body)
    render()

    # Count BODY lines only — the prose AFTER the closing frontmatter '---'.
    # The 150-line cap is a prose cap; YAML frontmatter is structured data, so
    # counting it against the cap is wrong (matches checks.py's body-counting).
    # Strip frontmatter, then count.
    body_lines = len(FM_RE.sub("", path.read_text(), count=1).splitlines())
    print(f"Set body of exp_{args.id} ({body_lines} body lines).")
    if body_lines > EXP_LINE_CAP:
        print(f"  ! warning: exp_{args.id} body is {body_lines} lines, over the {EXP_LINE_CAP}-line cap "
              "(core.md Hard size caps). Condense further or split into a new exp number.")


def exp_show(args):
    records = load(EXP_DIR, "exp")
    if args.id not in records:
        sys.exit(f"exp_{args.id} not found.")
    _, fm = records[args.id]
    parts = [f"exp: {fm['exp']}  status: {fm.get('status', '')}"]
    for field in ("outcome", "metric", "n_seeds", "track", "benchmark", "parent", "related",
                  "best_run", "paper_dois", "adr",
                  "consumes", "produces", "source_artifacts", "flags", "takeaway", "tags"):
        if fm.get(field):
            v = ", ".join(str(x) for x in fm[field]) if isinstance(fm[field], list) else fm[field]
            parts.append(f"{field}: {v}")
    if fm.get("revisions"):
        parts.append(f"revisions: {len(fm['revisions'])} (latest: {fm['revisions'][-1].get('date', '?')})")
    print("  ".join(parts))


def exp_list(args):
    records = load(EXP_DIR, "exp")
    for n, (_, fm) in sorted(records.items()):
        if args.tag and args.tag not in fm.get("tags", []):
            continue
        if args.status and fm.get("status") != args.status:
            continue
        if args.outcome and fm.get("outcome") != args.outcome:
            continue
        if args.benchmark and fm.get("benchmark") != args.benchmark:
            continue
        metric = fm.get("metric", "")
        if metric and isinstance(metric, dict):
            metric = ", ".join(f"{k}={v}" for k, v in metric.items())
        takeaway = (fm.get("takeaway") or "")[:60]
        print(f"{n:3d}  {fm.get('status', ''):10s}  {fm.get('outcome', ''):12s}  {str(metric):15s}  {takeaway}")


def exp_lineage(args):
    records = load(EXP_DIR, "exp")
    if args.id not in records:
        sys.exit(f"exp_{args.id} not found.")
    chain = [args.id]
    current = args.id
    while True:
        parent = records[current][1].get("parent")
        if not parent or parent not in records:
            break
        chain.append(parent)
        current = parent
    children = defaultdict(list)
    for num, (_, fm) in records.items():
        if fm.get("parent"):
            children[fm["parent"]].append(num)
    chain_str = " ← ".join(str(x) for x in chain)
    if children.get(args.id):
        chain_str += f" → children: {children[args.id]}"
    print(chain_str)
    _, fm = records[args.id]
    if fm.get("consumes"):
        print(f"consumes: {fm['consumes']}")
    if fm.get("produces"):
        print(f"produces: {fm['produces']}")


def _append_finding(content: str, section: str, line: str) -> str:
    """Insert `line` under `section` in findings.md text, creating the section if absent.
    A '## Superseded findings' block (if present) is kept last.

    `section` is the heading text WITHOUT a trailing newline.
    """
    heading = section + "\n"
    if heading in content:
        # Insert right after the heading line (preserve existing behavior).
        return content.replace(heading, heading + "\n" + line)
    block = f"\n{section}\n\n{line}"
    superseded = "## Superseded findings"
    if superseded in content:
        return content.replace(superseded, block + "\n" + superseded)
    return content + block


def exp_finding(args):
    records = load(EXP_DIR, "exp")
    if args.id not in records:
        sys.exit(f"exp_{args.id} not found.")
    _, fm = records[args.id]
    if not FINDINGS.exists():
        sys.exit("docs/findings.md not found.")
    content = FINDINGS.read_text()
    section = "## Negative findings (what doesn't work)" if args.negative else "## Positive findings (what works)"
    # A record written by hand may carry no title; the finding still has to land, and
    # the exp number is what a reader follows anyway.
    line = f"- **{fm.get('title') or f'exp_{args.id}'}**: {args.text} — Exp {args.id}\n"
    created = section not in content
    FINDINGS.write_text(_append_finding(content, section, line))
    if created:
        print(f"Created section '{section}' in docs/findings.md and appended finding.")
    else:
        print("Appended to docs/findings.md.")


def _citation_refusal(n: int, records: dict) -> str | None:
    """Why exp n cannot be deleted: a finding, or another record's lineage, still cites it."""
    cite = re.compile(rf"(?<![A-Za-z0-9])exp[ _]?0*{n}(?!\d)", re.IGNORECASE)
    if FINDINGS.exists() and cite.search(FINDINGS.read_text()):
        return (f"exp_{n} is cited in {FINDINGS.relative_to(ROOT)}. Move that finding to "
                "'## Superseded findings' or remove the citation first.")
    for num, (path, fm) in sorted(records.items()):
        if num == n:
            continue
        if fm.get("parent") == n:
            return f"exp_{n} is the parent of exp_{num} ({path.relative_to(ROOT)})."
        if n in (fm.get("related") or []):
            return f"exp_{n} is listed as related by exp_{num} ({path.relative_to(ROOT)})."
    return None


def exp_delete(args):
    """Remove an experiment record whose results are invalid; its number is never reused."""
    records = load(EXP_DIR, "exp")
    if args.id not in records:
        sys.exit(f"exp_{args.id} not found.")
    reason = " ".join(args.reason.split())
    if not reason:
        sys.exit("--reason cannot be empty.")
    path, _ = records[args.id]
    refusal = _citation_refusal(args.id, records)
    if refusal:
        sys.exit(refusal)

    n = args.id
    prefix = f"exp_{n:02d}_"
    slug = path.stem[len(prefix):] if path.stem.startswith(prefix) else path.stem
    tomb = tombstone_path(EXP_DIR)
    tomb.parent.mkdir(parents=True, exist_ok=True)
    if not tomb.exists():
        tomb.write_text("# Deleted experiments\n\nNumbers below are never reallocated. "
                        "Format: exp N | slug | date | by | reason.\n\n")
    with tomb.open("a") as f:
        f.write(f"- exp {n} | {slug} | {date.today()} | {args.by} | {reason}\n")

    path.unlink()
    unlinked = epics.unlink_exp(n)
    render()

    scripts = sorted((ROOT / "experiments").glob(f"exp_{n:02d}_*.py"))
    data_dirs = [p for p in sorted((ROOT / "data" / "experiments").glob(f"exp_{n:02d}_*")) if p.is_dir()]
    print(f"Deleted {path.relative_to(ROOT)}")
    print(f"Tombstone: {tomb.relative_to(ROOT)} (exp {n} is never reallocated)")
    if unlinked:
        print(f"Unlinked from epics: {', '.join(str(e) for e in unlinked)}")
    print("INDEX.md files re-rendered.")
    if args.purge:
        for p in scripts:
            p.unlink()
            print(f"Purged {p.relative_to(ROOT)}")
        for p in data_dirs:
            shutil.rmtree(p)
            print(f"Purged {p.relative_to(ROOT)}/")
    else:
        for p in scripts + data_dirs:
            print(f"Kept {p.relative_to(ROOT)} (--purge removes it)")
