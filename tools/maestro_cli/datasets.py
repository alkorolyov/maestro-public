"""Dataset provenance records — docs/data/<name>.md, keyed by name rather than a number.

The sha256 is COMPUTED from the bytes on disk (never hand-typed), so a record and the
data it describes cannot silently diverge; `verify` re-checks every one of them.

A dataset that is still being COLLECTED has no stable bytes yet — a paginated pull
writing one file per trading day for two hours changes its own digest on every write.
Hashing it at registration turns every later check into "sha drift — data changed in
place", which is the opposite of what happened. So a record carries a `status`:
`collecting` means the sha is `pending` and drift is not checked until the pull ends;
`complete` (the default, and what a record with no `status` field means) means the sha
is stamped and rule 7 immutability applies.
"""
import re
import sys
from datetime import date

from .frontmatter import DATA_DIR, DATA_ROOT, FM_RE, ROOT, load_datasets, render, write
from .hashing import dataset_sha_rel

# A record's `status`. Absent → COMPLETE: the field arrived after the first records were
# written, and every one of them describes a pull that had already finished.
COLLECTING = "collecting"
COMPLETE = "complete"
# What sits in `sha256` while a dataset is collecting. A word, not "", so the record says
# WHY there is no digest — and so the NO-SHA checks (which test for an empty field) do not
# fire on a dataset that is legitimately mid-pull.
PENDING_SHA = "pending"
# Past this, a collection is reported as stale rather than in progress. Still advisory:
# a slow pull is a fact about the world, not a malformed record.
STALE_COLLECTING_DAYS = 7


def dataset_status(fm) -> str:
    """The record's collection status; a record with no `status` field is complete."""
    return str(fm.get("status") or COMPLETE).strip()


def is_collecting(fm) -> bool:
    return dataset_status(fm) == COLLECTING


def _collecting_days(fm, today=None):
    """Days since `retrieved`, or None when the record carries no usable date."""
    raw = str(fm.get("retrieved", "") or "").strip()
    try:
        started = date.fromisoformat(raw)
    except ValueError:
        return None
    return ((today or date.today()) - started).days


def collecting_note(name: str, fm, today=None) -> str:
    """The one advisory line a collecting dataset gets from `docs check` / `dataset verify`.

    Non-blocking on purpose: the pull is still running, so the bytes SHOULD be changing.
    Past STALE_COLLECTING_DAYS the wording flips to a stale collection — still advisory,
    because the checker cannot tell a two-week backfill from a forgotten record."""
    version = fm.get("version", "") or ""
    where = f"{name}{(' ' + version) if version else ''}"
    days = _collecting_days(fm, today)
    since = fm.get("retrieved", "") or "an unrecorded date"
    if days is not None and days > STALE_COLLECTING_DAYS:
        lead = f"dataset {where} has been collecting for {days} days (since {since}) — stale collection"
    else:
        lead = f"dataset {where} is still collecting (since {since})"
    return (f"{lead}; the sha is stamped at completion, so drift is not checked yet — run "
            f"`maestro dataset update --name={name} --complete` when the pull ends.")


def _dataset_sha(name: str, version: str, path: str = "") -> str:
    """sha256 of a dataset file-set (shared impl — see hashing.py).

    `path` (relative to data/) locates the bytes; absent → raw/<name>[/<version>]."""
    return dataset_sha_rel(DATA_ROOT, name, version, path)


def _data_rel(name: str, version: str, path: str = "") -> str:
    """The dataset's path relative to data/ — explicit `path` or the raw/<name> default.
    Used for record bodies and CLI messages so they name the actual location."""
    if path:
        return path
    return f"raw/{name}/{version}" if version else f"raw/{name}"


def _slug_name(s: str) -> str:
    # Preserve case (and allow uppercase) so a dataset name can match its on-disk
    # data/raw/<name>/ directory verbatim — no lowercase-alias symlink needed.
    return re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_")


def dataset_new(args):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    name = _slug_name(args.name)
    records = load_datasets()
    if name in records:
        sys.exit(f"dataset '{name}' already exists ({records[name][0].relative_to(ROOT)}). "
                 "Use 'maestro dataset update' (a new release is a new version, not a new record).")
    version = args.version or ""
    rel = (args.path.strip("/") if args.path else "")
    collecting = bool(getattr(args, "collecting", False))
    # A collecting dataset is NOT hashed: its bytes are still arriving, so a digest taken
    # now describes a moment nobody will ever reproduce, and every later check reads that
    # as an edit in place. The sha is stamped once, by `--complete`.
    sha = PENDING_SHA if collecting else _dataset_sha(name, version, rel)
    path = DATA_DIR / f"{name}.md"
    fm = {"dataset": name, "version": version}
    if rel:
        fm["path"] = rel                       # explicit location (relative to data/)
    fm.update({"source": args.source or "", "license": args.license or "",
               "retrieved": str(date.today()),
               "status": COLLECTING if collecting else COMPLETE,
               "sha256": sha, "used": "", "tags": []})
    datapath = f"data/{_data_rel(name, version, rel)}"
    body = (f"\n# Dataset — {name}{(' ' + version) if version else ''}\n\n"
            f"**Path**: `{datapath}`\n\n"
            f"**What it is**: \n\n"
            f"**Schema / fields**: \n\n"
            f"**Collection / source method**: \n\n"
            f"**Caveats / known issues**: \n\n"
            f"**How to load**: \n")
    write(path, fm, body)
    render()
    if collecting:
        note = (f"  (status: collecting, sha256 pending — run "
                f"'maestro dataset update --name={name} --complete' when the pull ends)")
    elif not sha:
        note = "  (sha256 empty — path not found yet; run 'data update --rehash' once data lands)"
    else:
        note = ""
    print(f"Created {path.relative_to(ROOT)}{note}")


def dataset_update(args):
    records = load_datasets()
    name = _slug_name(args.name)
    if name not in records:
        sys.exit(f"dataset '{name}' not found. Use 'maestro dataset new --name={name}' first.")
    path, fm = records[name]
    body = FM_RE.sub("", path.read_text())
    updates = {}
    if args.version is not None:
        updates["version"] = args.version
    if getattr(args, "path", None) is not None:
        updates["path"] = args.path.strip("/")
    if args.source:
        updates["source"] = args.source
    if args.license:
        updates["license"] = args.license
    if args.used:
        updates["used"] = args.used
    if args.tags:
        updates["tags"] = [t.strip() for t in args.tags.split(",")]
    complete = bool(getattr(args, "complete", False))
    to_collecting = getattr(args, "status", None) == COLLECTING
    if complete and to_collecting:
        sys.exit("--complete and --status=collecting say opposite things; pass one.")
    if to_collecting:
        # Registered as complete while the pull was still running: clear the sha rather
        # than leave a digest of a half-arrived directory standing as the record's truth.
        updates["status"] = COLLECTING
        updates["sha256"] = PENDING_SHA
    if args.rehash and is_collecting(fm) and not complete and not to_collecting:
        sys.exit(f"dataset '{name}' is still collecting — stamping a sha mid-pull records a "
                 f"moment nobody can reproduce. Use `--complete` when the pull has ended.")
    if args.rehash or complete or getattr(args, "status", None) == COMPLETE:
        version = updates.get("version", fm.get("version", ""))
        rel = updates.get("path", fm.get("path", ""))
        sha = _dataset_sha(name, version, rel)
        if not sha:
            flag = "--complete" if complete else "--rehash"
            sys.exit(f"{flag}: nothing to hash at data/{_data_rel(name, version, rel)}.")
        updates["sha256"] = sha
        updates["status"] = COMPLETE
    fm.update(updates)
    write(path, fm, body)
    render()
    print(f"Updated {path.relative_to(ROOT)}.")
    if complete or getattr(args, "status", None) == COMPLETE:
        print(f"  status: complete, sha256 {updates['sha256'][:12]} — drift is checked from now on.")
    elif to_collecting:
        print(f"  status: collecting, sha256 pending — drift is not checked until "
              f"`maestro dataset update --name={name} --complete`.")


def dataset_show(args):
    records = load_datasets()
    name = _slug_name(args.name)
    if name not in records:
        sys.exit(f"dataset '{name}' not found.")
    _, fm = records[name]
    fm = dict(fm)
    fm.setdefault("status", dataset_status(fm))   # a record written before the field
    parts = [f"dataset: {fm['dataset']}  version: {fm.get('version', '') or '—'}"]
    for field in ("source", "license", "retrieved", "status", "sha256", "used", "tags"):
        if fm.get(field):
            v = ", ".join(str(x) for x in fm[field]) if isinstance(fm[field], list) else fm[field]
            parts.append(f"{field}: {v}")
    print("  ".join(parts))


def dataset_list(args):
    records = load_datasets()
    if not records:
        print("No datasets recorded. Use 'maestro dataset new --name=<name>'.")
        return
    for name, (_, fm) in sorted(records.items()):
        ver = fm.get("version", "") or "—"
        sha = (fm.get("sha256") or "")[:12] or "NO-SHA"
        mark = "  [collecting]" if is_collecting(fm) else ""
        print(f"{name:24s}  {ver:10s}  {sha}  {fm.get('source', '')[:40]}{mark}")


def dataset_verify(args):
    """Recompute each dataset's sha and compare to its recorded sha256 — catches drift / edited-in-place."""
    records = load_datasets()
    if not records:
        print("No datasets to verify.")
        return
    issues = 0
    for name, (_, fm) in sorted(records.items()):
        version = fm.get("version", "")
        rel = fm.get("path", "")
        if is_collecting(fm):
            # No comparison to make: the bytes are meant to be moving. Advisory only, so a
            # two-hour pull does not fail `verify` (or the Stop hook it backs) every turn.
            print(f"  collecting {name}: {collecting_note(name, fm)}")
            continue
        actual = _dataset_sha(name, version, rel)
        recorded = fm.get("sha256", "")
        if not actual:
            print(f"  MISSING  {name}: no files at data/{_data_rel(name, version, rel)} "
                  "(dangling symlink, or data not pulled).")
            issues += 1
        elif not recorded:
            print(f"  NO-SHA   {name}: record has no sha256 — run 'maestro dataset update --name={name} --rehash'.")
            issues += 1
        elif actual != recorded:
            print(f"  DRIFT    {name}: recorded {recorded[:12]} != actual {actual[:12]} "
                  "(data changed in place — that breaks immutability; make a new version).")
            issues += 1
        else:
            print(f"  ok       {name}: {recorded[:12]}")
    if issues:
        sys.exit(f"\n{issues} dataset(s) need attention.")
    print("\nAll dataset shas match.")
