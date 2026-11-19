"""Regenerate docs/{experiments,adrs,data,epics}/INDEX.md + docs/kb/literature/INDEX.md from frontmatter.

The tables are GENERATED: every value is read back from record frontmatter, so an index
can be rebuilt from the records at any time and never becomes a second source of truth.
"""
import re
import yaml
from collections import defaultdict

from . import epics as epics_mod
from .epics import blocked_reason, counts_text, item_counts, items_of
from .frontmatter import norm_epic
from .frontmatter import ROOT, slugify, EXP_DIR, ADR_DIR, DATA_DIR, EPIC_DIR, KB_LIT_DIR as KB_DIR

FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
TAKEAWAY_RE = re.compile(r"^##\s+Takeaway\s*\n(.*?)(?=\n##\s|\Z)", re.S | re.M)


def fmt_metric(m):
    if not m:
        return ""
    if isinstance(m, dict):
        # Pair "<k>" with "<k>_sd" and render as "k=v±sd"; keep solo keys plain.
        parts = []
        seen = set()
        for k, v in m.items():
            if k.endswith("_sd") or k in seen:
                continue
            sd = m.get(f"{k}_sd")
            if sd is not None:
                parts.append(f"{k}={v}±{sd}")
                seen.add(f"{k}_sd")
            else:
                parts.append(f"{k}={v}")
            seen.add(k)
        return ", ".join(parts)
    return str(m)


def _count_runs(e):
    """Run count is DERIVED from the run dirs on disk (rule 4 layout), never stored
    in frontmatter — a copied count is a number that can drift from its source."""
    # slugify, because `title` is prose: "Depth Sweep" names a record written to
    # exp_07_depth_sweep.md, and its run dirs sit under that name too. Reading the
    # title raw looked for a directory that no experiment has ever had.
    slug = f"exp_{e['exp']:02d}_{slugify(e.get('title', ''))}"
    d = ROOT / "data" / "experiments" / slug
    if not d.is_dir():
        return None
    n = len([p for p in d.glob("run_*") if p.is_dir()])
    return n or None


def load_kind(directory, kind):
    records = []
    if not directory.exists():
        return records
    for p in sorted(directory.glob(f"{kind}_*.md")):
        m = FM_RE.match(p.read_text())
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        if kind in fm:
            records.append(fm)
    records.sort(key=lambda r: r[kind])
    return records


def build_exp_index(exps):
    # Auto-flag rule: n_seeds==1 implies single_seed (rule-based, not vibes-based).
    # Verbalized confidence is empirically miscalibrated (UQ Survey 2503.15850), so we
    # use deterministic flags instead of asking the agent to self-rate.
    for e in exps:
        if e.get("n_seeds") == 1:
            flags = list(e.get("flags") or [])
            if "single_seed" not in flags:
                flags.append("single_seed")
                e["flags"] = sorted(set(flags))

    # Best is keyed by (track, benchmark). Splitting on benchmark keeps prior bests
    # visible after a benchmark change instead of being silently shadowed by a newer
    # run on a different evaluation setup.
    best_by_track_bench = {}
    for e in exps:
        if e.get("track") and e.get("metric") and e.get("outcome") in ("improved", "parity"):
            v = next(iter(e["metric"].values()), None) if isinstance(e.get("metric"), dict) else None
            if v is None:
                continue
            key = (e["track"], e.get("benchmark") or "—")
            cur = best_by_track_bench.get(key)
            if cur is None or v > cur[1]:
                best_by_track_bench[key] = (e, v)

    refuted = [e for e in exps if e.get("outcome") == "refuted"]
    open_inc = [e for e in exps if e.get("status") == "running" or e.get("outcome") == "inconclusive"]
    children = defaultdict(list)
    for e in exps:
        if e.get("parent"):
            children[e["parent"]].append(e["exp"])
    roots = [e for e in exps if not e.get("parent")]

    out = [
        "# Experiment Index",
        "",
        "_Generated from `docs/experiments/exp_*.md` frontmatter. Do not edit by hand._",
        "_Run `maestro index render --kind=exp` to regenerate. New experiment: `maestro exp new --slug=<slug>`._",
        "",
        "## All Experiments",
        "",
        "| # | Title | Status | Outcome | Takeaway | Tags |",
        "|---|-------|--------|---------|----------|------|",
    ]
    for e in exps:
        tags = ", ".join(e.get("tags", []))
        out.append(f"| {e['exp']} | {_title(e)} | {e.get('status', '')} | "
                   f"{e.get('outcome', '')} | {e.get('takeaway', '')} | {tags} |")

    out += ["", "## Best by Track / Benchmark", "",
            "| Track | Benchmark | Best Exp | Metric | Flags |",
            "|-------|-----------|----------|--------|-------|"]
    for (track, bench), (e, _) in sorted(best_by_track_bench.items()):
        flags = ", ".join(e.get("flags") or []) or "—"
        out.append(f"| {track} | {bench} | {e['exp']} | {fmt_metric(e.get('metric'))} | {flags} |")

    out += ["", "## Refuted Hypotheses (do not re-try)", "", "| # | Takeaway | Date |", "|---|----------|------|"]
    for e in refuted:
        out.append(f"| {e['exp']} | {e.get('takeaway', '')} | {e.get('date', '')} |")

    out += ["", "## Open / Inconclusive", "", "| # | Title | Tags |", "|---|-------|------|"]
    for e in open_inc:
        tags = ", ".join(e.get("tags", []))
        out.append(f"| {e['exp']} | {_title(e)} | {tags} |")

    out += ["", "## Lineage Roots", "", "| # | Title | Children |", "|---|-------|----------|"]
    for e in roots:
        kids = ", ".join(map(str, children.get(e["exp"], []))) or "—"
        out.append(f"| {e['exp']} | {_title(e)} | {kids} |")

    related_rows = [e for e in exps if e.get("related")]
    if related_rows:
        out += ["", "## Related Networks", "",
                "_Non-parent links — same-topic, contrasting-method, or shared-component experiments._",
                "", "| # | Title | Related to |", "|---|-------|------------|"]
        for e in related_rows:
            rel = ", ".join(map(str, e["related"]))
            out.append(f"| {e['exp']} | {_title(e)} | {rel} |")

    ext_rows = [e for e in exps if any(e.get(f) for f in
                ("best_run", "paper_dois", "adr"))]
    if ext_rows:
        out += ["", "## External Pointers", "",
                "_Where to follow when the markdown isn't enough — tracked runs, decisions, motivating papers. "
                "Resolve a run to its tracker via `runs fetch --exp <#>` (tracker set in pyproject [tool.maestro])._",
                "", "| # | Best run | Runs | DOIs | ADR |",
                "|---|----------|------|------|-----|"]
        for e in ext_rows:
            best = e.get("best_run") or "—"
            nruns = _count_runs(e) or "—"   # derived: rule 2, never a stored copy
            dois = ", ".join(e["paper_dois"]) if e.get("paper_dois") else "—"
            adr = f"adr_{e['adr']}" if e.get("adr") else "—"
            out.append(f"| {e['exp']} | {best} | {nruns} | {dois} | {adr} |")

    review_rows = [e for e in exps if e.get("flags")]
    if review_rows:
        out += ["", "## Needs Review", "",
                "_Experiments with one or more deterministic review flags. Re-verify before propagating "
                "the takeaway into a new experiment, write-up, or refuted-list rejection._",
                "", "| # | Title | Flags | Takeaway |",
                "|---|-------|-------|----------|"]
        for e in review_rows:
            flags = ", ".join(e["flags"])
            out.append(f"| {e['exp']} | {_title(e)} | {flags} | {e.get('takeaway', '')} |")

    prov_rows = [e for e in exps if e.get("source_artifacts")]
    if prov_rows:
        out += ["", "## Source Artifacts (provenance)", "",
                "_Per-experiment data files the takeaway is derived from. When an artifact is "
                "found wrong, grep this section to find every dependent claim (FAIR R1.2)._",
                "", "| # | Sources |", "|---|---------|"]
        for e in prov_rows:
            srcs = ", ".join(e["source_artifacts"])
            out.append(f"| {e['exp']} | {srcs} |")

    revised_rows = [e for e in exps if e.get("revisions")]
    if revised_rows:
        # Most recent revisions first, capped at the latest 10 across all experiments.
        all_revs = []
        for e in revised_rows:
            for r in e["revisions"]:
                all_revs.append((r.get("date", ""), e["exp"], _title(e), r))
        all_revs.sort(key=lambda x: x[0], reverse=True)
        out += ["", "## Recent Revisions", "",
                "_Append-only correction log. Original takeaway preserved; reason captures why it was wrong._",
                "", "| Date | # | Title | By | Reason |",
                "|------|---|-------|-----|--------|"]
        for d, n, t, r in all_revs[:10]:
            out.append(f"| {d} | {n} | {t} | {r.get('by', '')} | {r.get('reason', '')} |")

    return "\n".join(out) + "\n"


def load_datasets():
    """Dataset records are keyed by name (docs/data/<name>.md), not exp_/adr_ numbers."""
    records = []
    if not DATA_DIR.exists():
        return records
    for p in sorted(DATA_DIR.glob("*.md")):
        if p.name == "INDEX.md":
            continue
        m = FM_RE.match(p.read_text())
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        if "dataset" in fm:
            records.append(fm)
    records.sort(key=lambda r: r["dataset"])
    return records


def build_data_index(datasets):
    out = [
        "# Dataset Index",
        "",
        "_Generated from `docs/data/*.md` frontmatter. Do not edit by hand._",
        "_Run `maestro index render --kind=dataset` to regenerate. New dataset: `maestro dataset new --name=<name>`._",
        "",
        "## Datasets",
        "",
        "| Dataset | Version | Status | Source | License | sha256 | Used |",
        "|---------|---------|--------|--------|---------|--------|------|",
    ]
    for d in datasets:
        sha = (d.get("sha256") or "")[:12] or "—"
        # A record written before the `status` field existed describes a finished pull.
        status = str(d.get("status") or "complete").strip()
        out.append(f"| [{d['dataset']}]({d['dataset']}.md) | {d.get('version', '') or '—'} | "
                   f"{status} | {d.get('source', '') or '—'} | {d.get('license', '') or '—'} | "
                   f"{sha} | {d.get('used', '') or '—'} |")
    collecting = [d["dataset"] for d in datasets if str(d.get("status") or "").strip() == "collecting"]
    if collecting:
        out += ["", "## Still collecting (sha stamped by `maestro dataset update --name=<name> --complete`)",
                "", ", ".join(collecting)]
    missing = [d["dataset"] for d in datasets if not d.get("sha256")]
    if missing:
        out += ["", "## Missing sha256 (run `maestro dataset update --name=<name> --rehash`)", "",
                ", ".join(missing)]
    return "\n".join(out) + "\n"


def load_kb_literature(directory):
    """Literature kb entries (docs/kb/literature/<slug>.md). Takeaway lives in the
    body (## Takeaway), not frontmatter, so we extract it separately."""
    records = []
    if not directory.exists():
        return records
    for p in sorted(directory.glob("*.md")):
        if p.name == "INDEX.md":
            continue
        text = p.read_text()
        m = FM_RE.match(text)
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        if not fm.get("title"):
            continue
        tm = TAKEAWAY_RE.search(text)
        takeaway = " ".join(tm.group(1).split()) if tm else ""
        if len(takeaway) > 140:
            takeaway = takeaway[:139].rstrip() + "…"
        fm["_takeaway"] = takeaway
        fm["_slug"] = p.stem
        records.append(fm)

    def year_key(r):
        y = r.get("year")
        try:
            return int(y)
        except (TypeError, ValueError):
            return 0

    records.sort(key=lambda r: (-year_key(r), str(r.get("title", ""))))
    return records


def _cell(s):
    """Make a free-text value safe for a markdown table cell: escape pipes and
    collapse any newlines so the row never breaks."""
    return " ".join(str(s).split()).replace("|", "\\|")


def _title(rec):
    """A record's title as a table cell — dash when it has none.

    Frontmatter is CLI-written (rule 1), so a record without a title is malformed. But
    that is precisely the case `maestro docs check` exists to REPORT, and it cannot
    report anything if rendering the INDEX dies on a KeyError first. The epic and kb
    indexes already read the field this way; the exp and adr tables did not.
    """
    return _cell(rec.get("title", "")) or "—"


def build_kb_index(entries):
    out = [
        "# Literature Index",
        "",
        "_Generated from `docs/kb/literature/*.md` frontmatter + `## Takeaway`. Do not edit by hand._",
        "_Run `maestro index render --kind=all` to regenerate. Add entries via the literature_search protocol (/find-kb)._",
        "",
        "## Papers",
        "",
        "| Year | Title | Tags | Status | Takeaway |",
        "|------|-------|------|--------|----------|",
    ]
    for e in entries:
        year = e.get("year") if e.get("year") is not None else "—"
        title = _cell(e.get("title", ""))
        tags = e.get("tags") or []
        tags = _cell(", ".join(tags)) if isinstance(tags, list) else _cell(tags)
        status = e.get("status") or "—"
        takeaway = _cell(e.get("_takeaway") or "—")
        out.append(f"| {year} | [{title}]({e['_slug']}.md) | {tags} | {status} | {takeaway} |")

    attention = [e for e in entries if e.get("status") in ("placeholder", "flagged")]
    if attention:
        out += ["", "## Needs attention", "",
                "_Placeholder (unfetched) or flagged entries — treat their content as unreliable "
                "until refetched/reviewed._",
                "", "| Slug | Status | Title |", "|------|--------|-------|"]
        for e in attention:
            out.append(f"| {e['_slug']} | {e.get('status')} | {_cell(e.get('title', ''))} |")

    return "\n".join(out) + "\n"


def load_epics(directory, errors=None):
    """Epic records, with the file stem kept so the board can link each card.

    Pass `errors` (a list) to survive a malformed record: it collects (path, why) for
    every file that would not parse, and those files are skipped instead of raising.
    Without it a broken record raises, which is what the INDEX renderer wants — a
    record it cannot read is a bug to fix, not a row to omit silently.
    """
    records = []
    if not directory.exists():
        return records
    for p in sorted(directory.glob("epic_*.md")):
        try:
            text = p.read_text()
            m = FM_RE.match(text)
            if not m:
                raise ValueError("no YAML frontmatter block")
            fm = yaml.safe_load(m.group(1)) or {}
            if isinstance(fm, dict):
                norm_epic(fm)
            if not isinstance(fm, dict) or "epic" not in fm:
                raise ValueError("frontmatter has no `epic:` key")
            if not isinstance(fm["epic"], int):
                raise ValueError(f"`epic:` is not a number ({fm['epic']!r})")
        except Exception as exc:
            if errors is None:
                if isinstance(exc, ValueError):
                    continue        # unchanged: a file that is not a record is not an error
                raise
            errors.append((p, f"{type(exc).__name__}: {exc}"))
            continue
        fm["_slug"] = p.stem
        records.append(fm)
    records.sort(key=lambda r: r["epic"])
    return records


def _bar(done, total, width=10):
    """A fixed-width progress bar for a board card.

    Only a genuinely complete epic shows a full bar: everything short of it keeps at
    least one empty cell, so "nearly done" never renders as done.
    """
    if not total:
        return ""
    filled = width if done >= total else min(width - 1, int(width * done / total))
    return "`" + "\u2588" * filled + "\u2591" * (width - filled) + "`"


def short_title(e):
    """The epic's title up to the first ':' (fallback: its first 60 chars)."""
    title = str(e.get("title", "")).strip()
    head = title.split(":", 1)[0].strip() if ":" in title else ""
    return _cell(head or title[:60])


def arc_status(members):
    """active if any epic is active; todo if any is todo; review if every open one is
    review; done if all are done; later when the arc has no epics."""
    if not members:
        return "later"
    st = [m.get("status") for m in members]
    if "active" in st:
        return "active"
    if "todo" in st:
        return "todo"
    if all(x == "done" for x in st):
        return "done"
    return "review"


def _epic_line(e):
    done, total = item_counts(e)
    bits = [str(e.get("status", "todo"))]
    if e.get("runner"):
        bits.append(_cell(str(e["runner"])))
    bits.append(f"items {done}/{total}")
    n_opts = len(epics_mod.options_of(e))
    if n_opts:
        bits.append(f"{n_opts} options")
    if blocked_reason(e):
        bits.append("blocked")
    return f"- epic {e['epic']} \u2014 {short_title(e)} \u00b7 " + " \u00b7 ".join(bits)


def _epic_lines(members):
    out = [_epic_line(e) for e in members if e.get("status") != "done"]
    closed = [e for e in members if e.get("status") == "done"]
    if closed:
        out.append("- done: " + ", ".join(f"{e['epic']} {short_title(e)}" for e in closed))
    return out


def build_epic_board(epics, arcs=()):
    """The board, one view: per arc (when declared) or per status, one line per epic."""
    out = [
        "# Epic Board",
        "",
        "_Generated from `docs/epics/epic_*.md` frontmatter. Do not edit by hand._",
        "_Run `maestro index render --kind=epic` to regenerate. New epic: `maestro epic new --slug=<slug>`._",
        "",
    ]
    _closed = [e for e in epics if e.get("status") == "done"]
    _i_done = sum(item_counts(e)[0] for e in epics)
    _i_total = sum(item_counts(e)[1] for e in epics)
    out += [
        f"{_bar(len(_closed), len(epics))} **{len(_closed)}/{len(epics)} epics closed** \u00b7 "
        f"{_bar(_i_done, _i_total)} **{_i_done}/{_i_total} items done**",
        "",
    ]
    if arcs:
        known = [a.name for a in arcs]
        groups = [(a.name, [e for e in epics if e.get("arc") == a.name]) for a in arcs]
        stray = [e for e in epics if e.get("arc") not in known]
        for name, members in groups:
            out += [f"### {name} \u2014 {arc_status(members)}", ""]
            out += _epic_lines(members) or ["_no epics_"]
            out.append("")
        if stray:
            out += ["### no arc", ""] + _epic_lines(stray) + [""]
    else:
        for status, heading in (("active", "Active"), ("todo", "Todo"),
                                ("review", "Review"), ("done", "Done")):
            rows = [e for e in epics if e.get("status") == status]
            out += [f"## {heading}", ""]
            if status == "done":
                out += _epic_lines(rows) if rows else ["_none_"]
            else:
                out += [_epic_line(e) for e in rows] or ["_none_"]
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def build_adr_index(adrs):
    accepted = [a for a in adrs if a.get("status") == "accepted"]
    superseded = [a for a in adrs if a.get("status") == "superseded"]
    # A superseded decision is listed below by number and replacement only. Repeating its
    # decision text here would put a retracted rule into the context of every session that
    # reads this index, next to the rule that replaced it (core rule 12).
    standing = [a for a in adrs if a.get("status") != "superseded"]

    out = [
        "# ADR Index",
        "",
        "_Generated from `docs/adrs/adr_*.md` frontmatter. Do not edit by hand._",
        "_Run `maestro index render --kind=adr` to regenerate. New decision: `maestro adr new --slug=<slug>`._",
        "",
        "## Decisions",
        "",
        "| # | Title | Status | Decision | Tags |",
        "|---|-------|--------|----------|------|",
    ]
    for a in standing:
        tags = ", ".join(a.get("tags", []))
        status = a.get("status", "")
        if a.get("superseded_by"):
            status += f" → adr_{a['superseded_by']}"
        out.append(f"| {a['adr']} | {_title(a)} | {status} | {a.get('decision', '')} | {tags} |")

    if accepted:
        out += ["", "## Active Decisions", "", "| # | Title | Decision |", "|---|-------|----------|"]
        for a in accepted:
            out.append(f"| {a['adr']} | {_title(a)} | {a.get('decision', '')} |")

    if superseded:
        out += ["", "## Superseded (history only)", "", "| # | Title | Superseded by |", "|---|-------|--------------|"]
        for a in superseded:
            sb = f"adr_{a['superseded_by']}" if a.get("superseded_by") else "—"
            out.append(f"| {a['adr']} | {_title(a)} | {sb} |")

    return "\n".join(out) + "\n"


def _declared_arcs():
    from . import declaration
    try:
        decl = declaration.load(ROOT)
    except declaration.DeclarationError:
        return ()
    return decl.arcs if decl else ()


KINDS = ("exp", "adr", "dataset", "epic", "all")


def render(kind="all"):
    """Rebuild the INDEX.md of one record kind, or of all of them.

    'all' also covers the kb literature catalog, which has no record CLI of its own.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown index kind '{kind}' (expected one of: {', '.join(KINDS)})")
    every = kind == "all"
    totals = []

    if every or kind == "exp":
        exps = load_kind(EXP_DIR, "exp")
        if exps or EXP_DIR.exists():
            EXP_DIR.mkdir(parents=True, exist_ok=True)
            (EXP_DIR / "INDEX.md").write_text(build_exp_index(exps))
            n_refuted = sum(1 for e in exps if e.get("outcome") == "refuted")
            totals.append(f"{len(exps)} experiments ({n_refuted} refuted)")

    if every or kind == "adr":
        adrs = load_kind(ADR_DIR, "adr")
        if adrs or ADR_DIR.exists():
            ADR_DIR.mkdir(parents=True, exist_ok=True)
            (ADR_DIR / "INDEX.md").write_text(build_adr_index(adrs))
            totals.append(f"{len(adrs)} ADRs")

    if every or kind == "epic":
        epics = load_epics(EPIC_DIR)
        if epics or EPIC_DIR.exists():
            EPIC_DIR.mkdir(parents=True, exist_ok=True)
            (EPIC_DIR / "INDEX.md").write_text(build_epic_board(epics, _declared_arcs()))
            n_wip = sum(1 for e in epics if e.get("status") == "active")
            totals.append(f"{len(epics)} epics ({n_wip} active)")

    if every or kind == "dataset":
        datasets = load_datasets()
        if datasets or DATA_DIR.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / "INDEX.md").write_text(build_data_index(datasets))
            totals.append(f"{len(datasets)} datasets")

    if every:
        lit = load_kb_literature(KB_DIR)
        if lit or KB_DIR.exists():
            KB_DIR.mkdir(parents=True, exist_ok=True)
            (KB_DIR / "INDEX.md").write_text(build_kb_index(lit))
            totals.append(f"{len(lit)} literature entries")

    if totals:
        print(f"Rendered: {', '.join(totals)}.")
    else:
        print("Nothing to render (no docs/experiments/, docs/adrs/, or docs/data/ yet).")
