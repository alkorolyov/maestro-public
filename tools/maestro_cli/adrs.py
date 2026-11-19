"""Decision records — docs/adrs/adr_NN_<slug>.md.

THE LIVE-ADR MODEL (core.md rule 13). One live ADR per decision AREA, holding
the rules that govern it today — not one file per decision ever taken. A change to an
area AMENDS its ADR in place: the Decision is rewritten to the current rule and the
body's single final `History:` line gains a dated entry naming what changed and the git
sha that still holds the prior text (`maestro adr amend`). A new ADR is opened only when
no live ADR owns the area. An ADR folded into another, or dead, moves to
docs/archive/adrs/ with a row in that directory's README map (old number → live ADR):
history, never listed or checked as live, and its number is never reused (`next_num`
counts the archive).

Why: under the superseded model a reader had to walk a chain of `superseded_by`
pointers and amendments to learn today's rule, and the chain was wrong wherever the
newer record said "supersedes" and the older one never heard (check 4b).

`superseded` stays a valid status so projects that kept the older model — the old
record stays in place, `superseded_by` pointing at its replacement — still pass every
check; new work does not use it.
"""
import re
import subprocess
import sys
from datetime import date

from .frontmatter import (slugify, ADR_DIR, FM_RE, ROOT, archive_dir, archived_nums, load,
                          next_num, render, write)


# `superseded` is the pre-2.43 model's status, kept valid for the projects that used it.
ADR_STATUSES = {"proposed", "accepted", "superseded"}
HISTORY_RE = re.compile(r"^History:[^\n]*(?:\n[ \t]*\S[^\n]*)*", re.MULTILINE)


def adr_new(args):
    ADR_DIR.mkdir(parents=True, exist_ok=True)
    records = load(ADR_DIR, "adr")
    n = next_num(records, ADR_DIR, "adr")
    slug = slugify(args.slug)
    if not slug:
        sys.exit(f"--slug={args.slug!r} has no word characters to name a file with.")
    path = ADR_DIR / f"adr_{n:02d}_{slug}.md"
    fm = {"adr": n, "title": args.slug, "status": "proposed", "date": str(date.today()), "tags": []}
    body = (f"\n# ADR {n} — {args.slug}\n\n"
            f"**Context**: \n\n**Decision**: \n\n**Consequences**: \n")
    write(path, fm, body)
    render()
    print(f"Created {path.relative_to(ROOT)} (status=proposed)")


def _missing(n):
    """The refusal for an ADR number that is not live: archived history, or no record."""
    if n in archived_nums(ADR_DIR, "adr"):
        return (f"adr_{n} is archived ({archive_dir(ADR_DIR).relative_to(ROOT)}/): history, "
                "not a live record — it is not updated.")
    return f"adr_{n} not found."


def _tracked(path):
    """True when `path` is a file git tracks — then a rename goes through `git mv`."""
    try:
        r = subprocess.run(["git", "ls-files", "--error-unmatch", path.name], cwd=path.parent,
                           capture_output=True, text=True)
    except OSError:
        return False
    return r.returncode == 0


def _rename(path, new_path):
    """Move a record file, as a git rename when git tracks it (history follows the file)."""
    if _tracked(path):
        r = subprocess.run(["git", "mv", path.name, new_path.name], cwd=path.parent,
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"git mv {path.name} {new_path.name} failed: {r.stderr.strip()}")
    else:
        path.rename(new_path)


def _retitle(n, path, fm, body, title, slug, records):
    """Validate --title / --slug. Returns (target path, body); nothing is moved yet.

    The number and the date are the record's identity and never change. The body's H1 is
    rewritten only when it is still the scaffolded `# ADR N — <old title>`; a hand-written
    heading is the author's and is left alone.
    """
    if title is not None:
        title = title.strip()
        if not title:
            sys.exit("--title is empty — an ADR needs a name.")
        old = fm.get("title")
        if old is not None:
            body = re.sub(rf"^# ADR {n} — {re.escape(str(old))}[ \t]*$",
                          lambda _: f"# ADR {n} — {title}", body, count=1, flags=re.MULTILINE)
    if slug is not None:
        new_slug = slugify(slug)
        if not new_slug:
            sys.exit(f"--slug={slug!r} has no word characters to name a file with.")
        new_path = path.parent / f"adr_{n:02d}_{new_slug}.md"
        if new_path != path:
            if new_path.exists():
                sys.exit(f"{new_path.relative_to(ROOT)} already exists — pick another slug.")
            for m, (other, _) in records.items():
                if m != n and re.sub(r"^adr_\d+_", "", other.stem) == new_slug:
                    sys.exit(f"--slug={new_slug} collides with {other.relative_to(ROOT)}: "
                             "two live ADRs would share one name.")
            path = new_path
    return path, body


def adr_update(args):
    records = load(ADR_DIR, "adr")
    if args.id not in records:
        sys.exit(_missing(args.id))
    path, fm = records[args.id]
    body = FM_RE.sub("", path.read_text())
    old_path = path

    updates = {}
    title = getattr(args, "title", None)
    slug = getattr(args, "slug", None)
    if title is not None or slug is not None:
        path, body = _retitle(args.id, path, fm, body, title, slug, records)
        if title is not None:
            updates["title"] = title.strip()
    if args.status:
        if args.status not in ADR_STATUSES:
            sys.exit(f"--status must be one of: {', '.join(sorted(ADR_STATUSES))}")
        updates["status"] = args.status
    if args.superseded_by is not None:
        if args.superseded_by == args.id:
            sys.exit(f"adr_{args.id} cannot supersede itself — name the ADR that replaced it.")
        if args.superseded_by not in records:
            sys.exit(f"adr_{args.superseded_by} does not exist.")
        updates["superseded_by"] = args.superseded_by
    if args.decision:
        if len(args.decision) > 300:
            sys.exit(
                "--decision is the ONE-LINE index entry (<=300 chars). The full prose "
                "belongs in the record body — hand-edit the **Decision** section of "
                f"{old_path.relative_to(ROOT)} instead."
            )
        updates["decision"] = args.decision
    if args.tags:
        updates["tags"] = [t.strip() for t in args.tags.split(",")]

    new_status = updates.get("status", fm.get("status"))
    if new_status == "superseded" and not (updates.get("superseded_by") or fm.get("superseded_by")):
        sys.exit("--status=superseded requires --superseded-by.")
    if updates.get("status") == "superseded":
        print("note: under the live-ADR model an overturned rule is amended into the ADR that "
              "owns its area (`maestro adr amend`), and a folded ADR moves to "
              "docs/archive/adrs/ with a README map row (protocols/record_writeup.md).",
              file=sys.stderr)

    old_status, old_title = fm.get("status"), fm.get("title")
    fm.update(updates)
    if path != old_path:          # every refusal above has passed: only now move the file
        _rename(old_path, path)
    write(path, fm, body)
    print(f"Updated adr_{args.id} (status: {old_status} → {fm['status']}).")
    if "title" in updates and updates["title"] != old_title:
        print(f"Retitled adr_{args.id}: {old_title!r} → {updates['title']!r}.")
    if path != old_path:
        print(f"Renamed {old_path.relative_to(ROOT)} → {path.relative_to(ROOT)}; "
              f"citations of `{old_path.name}` elsewhere are not rewritten.")
    render()


def _prior_sha(path):
    """The short sha of the last commit that wrote `path` — where the prior text lives —
    or None when git does not track it."""
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%h", "--", path.name], cwd=path.parent,
                           capture_output=True, text=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def append_history(body, entry):
    """`body` with `entry` added to its LAST `History:` paragraph, or a new final one.

    The paragraph may wrap over several lines; it ends at a blank line or the end of the
    body. Entries are joined with "; " and the paragraph ends with one full stop.
    """
    entry = entry.strip().rstrip(".")
    found = list(HISTORY_RE.finditer(body))
    if not found:
        return body.rstrip("\n") + f"\n\nHistory: {entry}.\n"
    m = found[-1]
    para = m.group(0).rstrip().rstrip(".")
    return body[:m.start()] + f"{para}; {entry}." + body[m.end():]


def adr_amend(args):
    """Rewrite a live ADR's decision in place and log the change on its History line."""
    records = load(ADR_DIR, "adr")
    if args.id not in records:
        sys.exit(_missing(args.id))
    path, fm = records[args.id]
    if fm.get("status") == "superseded":
        sb = fm.get("superseded_by")
        sys.exit(f"adr_{args.id} is superseded: history, not amended."
                 + (f" Amend the ADR that owns the area now (adr_{sb})." if sb else ""))
    decision = (args.decision or "").strip()
    note = (args.note or "").strip()
    if not decision:
        sys.exit("--decision is empty — an amendment states the rule as it now stands.")
    if len(decision) > 300:
        sys.exit("--decision is the ONE-LINE index entry (<=300 chars). The full rule belongs "
                 f"in the body's **Decision** section of {path.relative_to(ROOT)} — rewrite it "
                 "there by hand.")
    if not note:
        sys.exit("--note is empty — say what changed; it is the History entry.")
    body = FM_RE.sub("", path.read_text())
    sha = _prior_sha(path)
    entry = f"amended {date.today()}: {note}" + (f" (prior text in git {sha})" if sha else "")
    fm["decision"] = decision
    write(path, fm, append_history(body, entry))
    render()
    print(f"Amended adr_{args.id}: decision rewritten; History: {entry}.")
    print("Rewrite the body's **Decision** to the current rule by hand if it still states "
          "the old one — the body is the rule, the frontmatter line is its index entry.")


def adr_show(args):
    records = load(ADR_DIR, "adr")
    if args.id not in records:
        sys.exit(_missing(args.id))
    _, fm = records[args.id]
    print(f"adr: {fm['adr']}  status: {fm.get('status', '')}  title: {fm.get('title', '')}")
    for field in ("decision", "context", "consequences", "superseded_by", "tags"):
        if fm.get(field):
            v = ", ".join(str(x) for x in fm[field]) if isinstance(fm[field], list) else fm[field]
            print(f"{field}: {v}")


def adr_list(args):
    records = load(ADR_DIR, "adr")
    for n, (_, fm) in sorted(records.items()):
        if args.status and fm.get("status") != args.status:
            continue
        decision = (fm.get("decision") or "")[:55]
        sb = f" → adr_{fm['superseded_by']}" if fm.get("superseded_by") else ""
        print(f"{n:3d}  {fm.get('status', ''):10s}  {fm.get('title', ''):30s}  {decision}{sb}")
