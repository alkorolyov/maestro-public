"""maestro — argument parsing and dispatch. No business logic lives here.

Surface (ADR 8):

    maestro <group> <verb> --flag=value

`init` and `option` are the exceptions to the group/verb shape: they act on the project
rather than on a record kind, so they are one level deep (`maestro init --harness`,
`maestro option --add="..."`).

Every argument is a named flag; there are no positionals anywhere, so a value that
contains spaces MUST be quoted. Unquoted multi-word values are the one failure mode
a common failure mode, so they are rejected with a message that names the flag and shows
the quoted form rather than silently keeping the first word.
"""
import argparse
import json
import os
import sys

from . import __version__
from . import (adrs, board, checks, datasets, declaration, epics, experiments, frontmatter, guards,
               indexes, init as init_mod, kb, options as options_mod, runs)
from .info import info

# Leaf parser per (group, verb), plus the flags of each that take a VALUE (as opposed
# to switches). Both are needed before parsing to catch unquoted multi-word values.
LEAVES = {}
VALUE_FLAGS = {}


def _verb(sub, group, name, help_text, func):
    p = sub.add_parser(name, help=help_text, description=help_text)
    p.set_defaults(func=func, _key=(group, name))
    LEAVES[(group, name)] = p
    VALUE_FLAGS[(group, name)] = set()
    return p


def _command(sub, name, help_text, func):
    """A command with no verb, for the two that take no object: `init` acts on the
    project or the machine, `option` on the project's own candidate-work list. Neither
    names a record kind, so `maestro init --harness` beats inventing a verb for it."""
    p = sub.add_parser(name, help=help_text, description=help_text)
    p.set_defaults(func=func, _key=(name,))
    LEAVES[(name,)] = p
    VALUE_FLAGS[(name,)] = set()
    return p


def _flag(p, *names, **kw):
    """Add a flag. A switch (`action="store_true"`) takes no value; everything else does."""
    p.add_argument(*names, **kw)
    if kw.get("action") != "store_true":
        VALUE_FLAGS[p.get_default("_key")].update(n for n in names if n.startswith("-"))
    return p


# ── the unquoted-value guard ──────────────────────────────────────────────────

def _first_stray(tokens, value_flags):
    """Find the first bare word no flag claimed.

    Returns (flag, value_so_far, [stray words]); flag is None when the stray word
    follows no flag at all. Everything after group+verb must be a flag or a flag's
    value, so any leftover bare word is an unquoted continuation of the last value.
    """
    i, flag, value = 0, None, None
    while i < len(tokens):
        t = tokens[i]
        if t == "--":
            i += 1
            continue
        if t.startswith("-") and len(t) > 1:
            if t.startswith("--") and "=" in t:
                flag, value = t.split("=", 1)
            else:
                flag, value = t, None
                nxt = tokens[i + 1] if i + 1 < len(tokens) else None
                if t in value_flags and nxt is not None and not (nxt.startswith("-") and len(nxt) > 1):
                    value = nxt
                    i += 1
            i += 1
            continue
        strays = []
        while i < len(tokens) and not (tokens[i].startswith("-") and len(tokens[i]) > 1):
            strays.append(tokens[i])
            i += 1
        return flag, value, strays
    return None, None, []


def _option_strings(parser):
    """Every flag THIS verb accepts, read off the parser rather than a second registry."""
    return {n for a in parser._actions for n in a.option_strings}


def _example(parser, strays):
    """An example invocation built from THIS verb's own flags, filled with the words the
    user actually typed: `maestro epic item 4 9` is answered with `--id=4 --item=9`.

    Ranking: required flags first (they must appear anyway), then the numeric ones, then
    the rest — and a numeric flag only claims a numeric word. A bare number typed on the
    command line is almost always a record id, so this lands on the flag that was meant.
    A fixed foreign example (`--id=3` on a verb with no `--id`) sends the reader to
    `--help` for the answer, which is the 100 s the message is supposed to save.
    """
    acts = [a for a in parser._actions
            if a.option_strings and a.dest != "help" and a.nargs != 0]
    order = ([a for a in acts if a.required]
             + [a for a in acts if not a.required and a.type is int]
             + [a for a in acts if not a.required and a.type is not int])
    used, pairs = [], []
    for word in strays:
        for a in order:
            if a in used or (a.type is int and not word.lstrip("-").isdigit()):
                continue
            used.append(a)
            pairs.append(f"{a.option_strings[0]}={word}")
            break
    if not pairs:
        # Nothing matched (a word no flag can take, or a verb with no value flags):
        # still name a real flag of this verb rather than one it does not have.
        pairs = [f"{order[0].option_strings[0]}={strays[0]}"] if order else []
    return " ".join(pairs)


def _reject_unquoted(parser, key, tokens):
    """Fail loudly on an unquoted multi-word value instead of keeping only its first word."""
    value_flags = VALUE_FLAGS[key]
    flag, value, strays = _first_stray(tokens, value_flags)
    if not strays:
        return
    extra = " ".join(strays)
    if flag is None:
        example = _example(parser, strays)
        hint = f", e.g. {example}" if example else ""
        parser.error(f'unexpected argument ("{extra}") — every value is a named flag'
                     f'{hint}. Quote any value that contains spaces.')
    if flag not in _option_strings(parser):
        # An unknown flag swallowed the words after it. Report the flag, not the words:
        # "--epic is a switch" would be a lie about a flag this verb does not have.
        parser.error(f"unrecognized arguments: {flag} — no such flag on this verb.")
    if flag in value_flags:
        full = f"{value} {extra}" if value else extra
        parser.error(f'{flag} got extra words ("{extra}"). Quote the value: {flag}="{full}"')
    parser.error(f'{flag} is a switch and takes no value, but got extra words ("{extra}"). '
                 f"Quote any value that contains spaces and attach it to its own flag.")


# ── dispatch wrappers (the only glue the modules do not own) ──────────────────

def _index_render(args):
    indexes.render(args.kind)


def _docs_check(args):
    if args.report_only and args.strict:
        # Opposite intents: --strict fails on advisories, --report-only never fails.
        print("maestro docs check: --report-only and --strict cannot be combined "
              "(--strict fails on advisories; --report-only never fails). Pick one.",
              file=sys.stderr)
        sys.exit(1)
    sys.exit(checks.check(strict=args.strict, staged=args.staged, verbose=args.verbose,
                          report_only=args.report_only))


def _docs_guard(args):
    """The pre-write path guard, as a subprocess for harnesses that cannot import it.

    Reads `{"tool": "<name>", "input": {<raw tool arguments>}}` on stdin. Exit 0 allows
    the call; exit 2 denies it and prints the reason on stderr — the same two exit codes
    `docs stamp --check` uses, so a harness adapter treats every maestro gate alike.
    Anything unparseable exits 0: a guard that cannot read a payload must not block work.
    """
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict):
        return
    reason = guards.verdict(str(payload.get("tool") or ""), payload.get("input") or {})
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)


def _docs_merge_guard(args):
    """The merge-evidence guard, as a subprocess for harnesses that cannot import it.

    Reads `{"command": "<shell command>", "cwd": "<workspace>"}` on stdin. Exit 0 allows
    the command; exit 2 denies it with the reason on stderr — the two exit codes
    `docs guard` and `docs stamp --check` already use, so a harness adapter treats every
    maestro gate alike. Anything unparseable exits 0.

    Inert unless the project declares `[tool.maestro] merge_evidence_log` +
    `merge_evidence_pass` in its pyproject.toml; see the merge-evidence section of
    `guards.py` for what those mean and what the rule costs.
    """
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict):
        return
    reason = guards.merge_evidence_verdict(payload.get("command") or "",
                                           payload.get("cwd") or os.getcwd())
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)


def _docs_stamp(args):
    """`--check`: the stamp check alone, fast enough for a post-tool hook (exit 2 on a
    hand-edited record). `--accept`: re-sign every record as it is on disk — adoption,
    or blessing a deliberate hand fix — without reformatting anything."""
    if args.check == args.accept:
        sys.exit("pass exactly one of --check or --accept.")
    if args.accept:
        files = frontmatter.record_files()
        for p in files:
            frontmatter.restamp(p)
        print(f"stamped {len(files)} record(s).")
        return
    issues, notes = checks.stamp_findings()
    for n in notes:
        print(f"  ~ {n}")
    if issues:
        print("HAND-EDITED RECORDS:", file=sys.stderr)
        for i in issues:
            print(f"  - {i}", file=sys.stderr)
        sys.exit(2)
    print(f"OK ({len(frontmatter.record_files())} record(s), stamps match).")


def _init(args):
    try:
        init_mod.init(args)
    except init_mod.InitError as exc:
        sys.exit(f"maestro init: {exc}")


# ── parser ────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="maestro",
        description="Records, indexes, checks and kb search for a maestro project. "
                    "Every argument is a named flag: maestro <group> <verb> --flag=value.",
    )
    # One rolling version serves every project on the machine (ADR 10), so the
    # version has to be askable.
    p.add_argument("--version", action="version", version=f"maestro {__version__}")
    groups = p.add_subparsers(dest="group", required=True, metavar="<group>")

    # ── epic ──
    epic = groups.add_parser("epic", help="Epic records — work spanning many sessions").add_subparsers(
        dest="verb", required=True, metavar="<verb>")

    s = _verb(epic, "epic", "new", "Scaffold a new epic record (status starts at todo)", epics.epic_new)
    _flag(s, "--slug", required=True, help="Short name of the epic, snake_case")
    _flag(s, "--title", help="Human-readable title (defaults to the slug)")
    _flag(s, "--arc", help="Optional arc this epic belongs to (a name from maestro.toml [[arcs]])")

    s = _verb(epic, "epic", "update",
              "Change an epic's state, blocked flag, linked exps/ADRs, or append a note",
              epics.epic_update)
    _flag(s, "--id", "--epic", type=int, required=True, dest="id",
          help="Epic number (--epic is an accepted alias)")
    _flag(s, "--status", help="review | todo | active | done")
    _flag(s, "--runner", help="Who is on the epic now (free text, e.g. dsh or claude); empty clears. "
                              "Cleared automatically when the status leaves active.")
    _flag(s, "--blocked-by", dest="blocked_by",
          help="Flag the epic as blocked, with the reason. A FLAG, not a state: the status "
               "is untouched. An empty value clears it.")
    _flag(s, "--title", help="Re-title the epic. A CORRECTION: the old wording goes to the "
                             "epic's log and the body heading moves with it, never dropped.")
    _flag(s, "--arc", help="Set the epic's arc (a name from maestro.toml [[arcs]]); empty clears. "
                           "Logged.")
    _flag(s, "--exps", help="Link experiments to the epic: comma-separated numbers, e.g. "
                            "147,148. Added to the `exps` list (deduped, sorted); each must "
                            "exist as docs/experiments/exp_<NN>_*.md")
    _flag(s, "--adrs", help="Link ADRs to the epic: comma-separated numbers, e.g. 31. Added "
                            "to the `adrs` list (deduped, sorted); each must exist as "
                            "docs/adrs/adr_<NN>_*.md")
    _flag(s, "--note", help="Append one line to the epic's log")

    s = _verb(epic, "epic", "item",
              "Add an item row to an epic, or change one — never hand-edit the frontmatter",
              epics.epic_item)
    _flag(s, "--id", "--epic", type=int, required=True, dest="id",
          help="Epic number (--epic is an accepted alias)")
    _flag(s, "--add", help="Title for a NEW item row (id assigned, status starts at todo)")
    _flag(s, "--item", type=int, help="Existing item id to change")
    _flag(s, "--title", help="Re-title an existing item (with --item). The old wording is "
                             "recorded in the epic's log, never dropped.")
    _flag(s, "--status", help="todo | in_progress | done | dropped (with --item). "
                              "dropped leaves only via todo; done is dropped only via todo")
    _flag(s, "--evidence",
          help="REQUIRED with --status=done: the merge sha, test name or artifact path "
               "that shows it. An item closes with evidence the way an epic closes with "
               "an outcome.")
    _flag(s, "--reason",
          help="REQUIRED with --status=dropped: what was measured and why the item was "
               "abandoned. Stored on the row and written to the epic's log.")
    _flag(s, "--blocked-by", dest="blocked_by",
          help="Flag the item as blocked, with the reason; empty value clears (with --item)")
    _flag(s, "--move-to", dest="move_to", type=int,
          help="Move a todo item (with --item) to epic <N>: a new todo row is added there "
               "with the same title, the row leaves this epic, both logs name the other side")
    _flag(s, "--moved-to", dest="moved_to",
          help="\"epic <N> item <M>\": the row was already copied there by hand — remove it "
               "here and log where it went (todo rows only; allowed on a closed epic)")
    _flag(s, "--note", help="Also append one line to the epic's log")

    s = _verb(epic, "epic", "option",
              "The intake above the commitment point — candidate work, not cards",
              epics.epic_option)
    _flag(s, "--id", "--epic", type=int, required=True, dest="id",
          help="Epic number (--epic is an accepted alias)")
    _flag(s, "--add", help="Add an option: one line of text, no status, no owner, no age")
    _flag(s, "--pull", type=int,
          help="Commit to option <n>: it becomes an item (todo) and leaves the list")
    _flag(s, "--drop", type=int, help="Discard option <n>")

    s = _verb(epic, "epic", "done-when",
              "The epic's closing condition — add a clause, or record what its check measured",
              epics.epic_done_when)
    _flag(s, "--id", "--epic", type=int, required=True, dest="id",
          help="Epic number (--epic is an accepted alias)")
    _flag(s, "--add", help="Add a clause: the condition that must hold for this epic to "
                           "close. A CONDITION, not a task — 'OPEN rows: 36 -> 0', never "
                           "'port the combat rules'.")
    _flag(s, "--clause", type=int, help="Existing clause id to change")
    _flag(s, "--text", help="Re-word an existing clause (with --clause). The old wording "
                            "goes to the epic's log, never dropped.")
    _flag(s, "--check", help="The command or artifact path that ANSWERS the clause; empty "
                             "value clears it")
    _flag(s, "--result", help="What the check measured. `epic close` refuses until every "
                              "clause carries one — the same contract as --evidence on an "
                              "item. Empty value clears it back to unanswered.")
    _flag(s, "--drop", action="store_true",
          help="Remove the clause (with --clause); the wording goes to the log")
    _flag(s, "--note", help="Also append one line to the epic's log")

    s = _verb(epic, "epic", "close", "Close an epic; requires the outcome", epics.epic_close)
    _flag(s, "--id", "--epic", type=int, required=True, dest="id",
          help="Epic number (--epic is an accepted alias)")
    _flag(s, "--outcome", required=True,
          help="What the epic actually delivered, stated as a CAPABILITY the project now "
               "has — not a list of the activity performed. The done_when results are the "
               "measurements behind it.")
    _flag(s, "--learned",
          help="One line on what this epic taught us about HOW we work; appended to "
               "docs/retro.md (the outcome says what it delivered, this says what it "
               "taught).")

    s = _verb(epic, "epic", "show", "Print one epic record", epics.epic_show)
    _flag(s, "--id", "--epic", type=int, required=True, dest="id",
          help="Epic number (--epic is an accepted alias)")

    s = _verb(epic, "epic", "list", "List epics, optionally filtered", epics.epic_list)
    _flag(s, "--status", help="Only epics in this state")
    _flag(s, "--blocked", action="store_true", help="Only epics carrying a blocked flag")

    # ── exp ──
    exp = groups.add_parser("exp", help="Experiment records").add_subparsers(
        dest="verb", required=True, metavar="<verb>")

    s = _verb(exp, "exp", "new", "Scaffold a new experiment record", experiments.exp_new)
    _flag(s, "--slug", required=True, help="Short name of the experiment, snake_case")

    s = _verb(exp, "exp", "update", "Fill in results on an experiment record", experiments.exp_update)
    _flag(s, "--id", type=int, required=True, help="Experiment number")
    _flag(s, "--status", help="planned | running | done | failed")
    _flag(s, "--outcome", help="confirmed | refuted | improved | parity | regression | infra | inconclusive")
    _flag(s, "--takeaway", help="One-sentence result")
    _flag(s, "--track", help="Metric track the experiment competes on")
    _flag(s, "--benchmark", help="Evaluation setup the metric was measured on")
    _flag(s, "--metric", action="append",
          help='Measured metric, e.g. accuracy=0.84 or "auc=0.84±0.02" (stores auc + auc_sd). '
               "Repeatable; comma-separated pairs in one flag also accepted.")
    _flag(s, "--n-seeds", type=int, dest="n_seeds",
          help="Number of seeds aggregated. n_seeds=1 auto-flags single_seed.")
    _flag(s, "--parent", type=int, help="Experiment this one descends from")
    _flag(s, "--related", help="Comma-separated exp numbers, e.g. '3,7,12'")
    _flag(s, "--best-run", dest="best_run",
          help="NAME of the run behind the headline metric (exp_NN_<slug>__<variant>__s<seed>), "
               "not a URL. Re-fetched at write-up via the `runs` tool. "
               "(Which tracker is set once in pyproject.toml [tool.maestro], not per-exp.)")
    _flag(s, "--dois", help="Comma-separated DOIs of motivating papers")
    _flag(s, "--adr", type=int, help="Related ADR number")
    _flag(s, "--source-artifacts", dest="source_artifacts",
          help="Comma-separated paths the takeaway was read from (FAIR R1.2 provenance)")
    _flag(s, "--consumes",
          help="Comma-separated input paths this exp reads (data/raw or data/processed). Lineage edge.")
    _flag(s, "--produces",
          help="Comma-separated output paths this exp writes (data/experiments/...). Lineage edge.")
    _flag(s, "--flags",
          help="Comma-separated review flags. Allowed: single_seed, large_unexpected_gain, "
               "conflicts_prior, setup_unverified, interpretation_uncertain")
    _flag(s, "--tags", help="Comma-separated tags")

    s = _verb(exp, "exp", "revise", "Correct a wrong takeaway, keeping a revision trace",
              experiments.exp_revise)
    _flag(s, "--id", type=int, required=True, help="Experiment number")
    _flag(s, "--reason", required=True, help="Why the previous takeaway was wrong")
    _flag(s, "--new-takeaway", dest="new_takeaway", required=True,
          help="Replacement takeaway. The original is preserved in the revisions log.")
    _flag(s, "--by", default="user", choices=("user", "agent"), help="user | agent")

    s = _verb(exp, "exp", "delete", "Delete an experiment record whose results are invalid "
              "(tombstones its number, unlinks it from epics)", experiments.exp_delete)
    _flag(s, "--id", type=int, required=True, help="Experiment number")
    _flag(s, "--reason", required=True, help="Why the record is invalid (kept in the tombstone)")
    _flag(s, "--by", default="user", choices=("user", "agent"), help="user | agent")
    _flag(s, "--purge", action="store_true",
          help="Also delete experiments/exp_NN_*.py and data/experiments/exp_NN_*/")

    s = _verb(exp, "exp", "set_body", "Replace an experiment record's body, keeping its frontmatter",
              experiments.exp_set_body)
    _flag(s, "--id", type=int, required=True, help="Experiment number")
    # Exactly one source, so these two go through argparse's exclusive group rather
    # than _flag(); --from-file still has to be registered as taking a value.
    src = s.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-file", dest="from_file", help="File holding the new body")
    src.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="Read the new body from stdin")
    VALUE_FLAGS[("exp", "set_body")].add("--from-file")

    s = _verb(exp, "exp", "show", "Print one experiment record", experiments.exp_show)
    _flag(s, "--id", type=int, required=True, help="Experiment number")

    s = _verb(exp, "exp", "list", "List experiments, optionally filtered", experiments.exp_list)
    _flag(s, "--tag", help="Only experiments carrying this tag")
    _flag(s, "--status", help="Only experiments in this state")
    _flag(s, "--outcome", help="Only experiments with this outcome")
    _flag(s, "--benchmark", help="Only experiments on this benchmark")

    s = _verb(exp, "exp", "lineage", "Print the parent/child tree an experiment sits in",
              experiments.exp_lineage)
    _flag(s, "--id", type=int, required=True, help="Experiment number")

    s = _verb(exp, "exp", "finding", "Append a finding to findings.md, linked to an experiment",
              experiments.exp_finding)
    _flag(s, "--id", type=int, required=True, help="Experiment the finding came from")
    _flag(s, "--text", required=True, help="The finding itself")
    _flag(s, "--negative", action="store_true", help="File under negative findings")

    # ── adr ──
    adr = groups.add_parser("adr", help="Architecture decision records").add_subparsers(
        dest="verb", required=True, metavar="<verb>")

    s = _verb(adr, "adr", "new", "Scaffold a new architecture decision record", adrs.adr_new)
    _flag(s, "--slug", required=True, help="Short name of the decision, snake_case")

    s = _verb(adr, "adr", "update", "Edit an existing decision record", adrs.adr_update)
    _flag(s, "--id", type=int, required=True, help="ADR number")
    _flag(s, "--status", help="proposed | accepted | superseded")
    _flag(s, "--superseded-by", type=int, dest="superseded_by", help="ADR that replaces this one")
    _flag(s, "--decision", help="One-line index entry (the prose lives in the record body)")
    _flag(s, "--tags", help="Comma-separated tags")
    _flag(s, "--title", help="New title; the number and date stay (the scaffolded H1 follows)")
    _flag(s, "--slug", help="New filename slug: renames adr_NN_<slug>.md (git mv when tracked); "
                            "refused when another live ADR has it")

    s = _verb(adr, "adr", "amend",
              "Amend a live ADR in place: rewrite its decision, log the change on History:",
              adrs.adr_amend)
    _flag(s, "--id", type=int, required=True, help="ADR number (the live ADR owning the area)")
    _flag(s, "--decision", required=True, help="The rule as it now stands, one line (<=300 chars)")
    _flag(s, "--note", required=True,
          help="What changed; appended as `amended <date>: <note> (prior text in git <sha>)`")

    s = _verb(adr, "adr", "show", "Print one decision record", adrs.adr_show)
    _flag(s, "--id", type=int, required=True, help="ADR number")

    s = _verb(adr, "adr", "list", "List decision records, optionally filtered", adrs.adr_list)
    _flag(s, "--status", help="Only ADRs in this state")

    # ── dataset ──
    dataset = groups.add_parser("dataset", help="Dataset provenance records").add_subparsers(
        dest="verb", required=True, metavar="<verb>")

    s = _verb(dataset, "dataset", "new", "Register a dataset; the checksum is computed from the bytes",
              datasets.dataset_new)
    _flag(s, "--name", required=True, help="Dataset name")
    _flag(s, "--path", help="Location relative to data/ (e.g. processed/cohorts/PAMPA_TRUSTED.csv). "
                            "Omit → raw/<name>[/<version>].")
    _flag(s, "--version", help="Release version, e.g. v1")
    _flag(s, "--source", help="URL it was downloaded from, or an internal reference")
    _flag(s, "--license", help="License of the data")
    _flag(s, "--collecting", action="store_true",
          help="The pull is still running: record it with sha256 pending, hash nothing, "
               "and keep drift advisory until `dataset update --complete`")

    s = _verb(dataset, "dataset", "update", "Edit a dataset record or refresh its checksum",
              datasets.dataset_update)
    _flag(s, "--name", required=True, help="Dataset name")
    _flag(s, "--path", help="Re-point the dataset's location")
    _flag(s, "--version", help="Release version")
    _flag(s, "--source", help="URL it was downloaded from, or an internal reference")
    _flag(s, "--license", help="License of the data")
    _flag(s, "--used", help="Which columns or files experiments consume")
    _flag(s, "--tags", help="Comma-separated tags")
    _flag(s, "--rehash", action="store_true", help="Recompute the checksum from the bytes on disk")
    _flag(s, "--complete", action="store_true",
          help="The pull has ended: hash the bytes, stamp the checksum, set status complete")
    _flag(s, "--status", choices=["collecting", "complete"],
          help="Set the collection status; collecting clears the checksum back to pending")

    s = _verb(dataset, "dataset", "show", "Print one dataset record", datasets.dataset_show)
    _flag(s, "--name", required=True, help="Dataset name")

    _verb(dataset, "dataset", "list", "List every registered dataset", datasets.dataset_list)
    _verb(dataset, "dataset", "verify", "Recompute every dataset's checksum and report drift",
          datasets.dataset_verify)

    # ── index ──
    index = groups.add_parser("index", help="Generated INDEX.md tables").add_subparsers(
        dest="verb", required=True, metavar="<verb>")
    s = _verb(index, "index", "render", "Regenerate the INDEX.md tables from record frontmatter",
              _index_render)
    _flag(s, "--kind", default="all", choices=indexes.KINDS,
          help="exp | adr | dataset | epic | all")

    # ── board ──
    board_group = groups.add_parser("board", help="The epic board as an HTML page").add_subparsers(
        dest="verb", required=True, metavar="<verb>")
    s = _verb(board_group, "board", "render", "Render the epics as an HTML kanban board",
              board.board_render)
    _flag(s, "--output", help="Where to write the HTML (default docs/epics/board.html)")
    _flag(s, "--scan", help="Directory to sweep for other maestro projects (one or two levels "
                            "deep), e.g. --scan=~/code. Read-only: only --output is written.")
    _flag(s, "--open", action="store_true", help="Open the board in a browser afterwards")

    # ── runs ──
    runs_group = groups.add_parser(
        "runs", help="Tracked runs (W&B / MLflow) read back for a record").add_subparsers(
        dest="verb", required=True, metavar="<verb>")

    s = _verb(runs_group, "runs", "fetch",
              "Resolve an experiment's runs and print their logged metrics", runs.cmd_fetch)
    # One of the two identifies the run group, never both: --exp resolves it from the
    # record on disk, --group names it directly (a group with no record yet).
    which = s.add_mutually_exclusive_group(required=True)
    which.add_argument("--exp", type=int, help="Experiment number (resolves exp_NN_<slug>)")
    which.add_argument("--group", help="Explicit W&B group / MLflow exp-tag value")
    VALUE_FLAGS[("runs", "fetch")].update({"--exp", "--group"})
    _flag(s, "--metric",
          help="Metric key to pick the best run by (default: the first finished run)")
    _flag(s, "--json", action="store_true",
          help="Emit every run as JSON (default: a summary of the best one)")

    s = _verb(runs_group, "runs", "url",
              "Print the tracker URL for an experiment's run group (no API call)", runs.cmd_url)
    _flag(s, "--exp", type=int, required=True, help="Experiment number")

    # ── docs ──
    docs = groups.add_parser("docs", help="Documentation checks").add_subparsers(
        dest="verb", required=True, metavar="<verb>")
    s = _verb(docs, "docs", "check", "Check the docs against the data on disk and report drift",
              _docs_check)
    _flag(s, "--strict", action="store_true", help="Exit non-zero on any warning")
    _flag(s, "--verbose", action="store_true",
          help="Print every advisory. By default the ones the checker itself calls "
               "non-actionable — findings on a CLOSED epic, ADR 9 findings on files "
               "untouched this session — are folded into one summary line")
    _flag(s, "--report-only", action="store_true",
          help="Print the same report but always exit 0. For a consumer that treats any "
               "non-zero exit as 'block' (a Claude Code Stop hook is one such consumer). "
               "Cannot be combined with --strict")
    _flag(s, "--staged", action="store_true",
          help="Report only drift in files staged for commit — the commit gate. Keeps a "
               "project's pre-existing drift from blocking an unrelated commit, while "
               "refusing to let THIS commit add more (the pre-commit hook runs this)")
    s = _verb(docs, "docs", "guard",
              "The pre-write path guard: may this tool call write this file? "
              "(payload on stdin; exit 2 = denied, reason on stderr)",
              _docs_guard)
    s = _verb(docs, "docs", "merge-guard",
              "The merge-evidence guard: may this `git merge --no-ff` run, or does the "
              "branch tip have no passing line in the log the project declares? "
              "(payload on stdin; exit 2 = denied, reason on stderr; inert when the "
              "project declares no merge-evidence log)",
              _docs_merge_guard)
    s = _verb(docs, "docs", "stamp",
              "The record stamp — verify that the CLI wrote what it owns, or re-sign records",
              _docs_stamp)
    _flag(s, "--check", action="store_true",
          help="Verify every record against its stamp; exit 2 on a hand-edited one "
               "(fast — the post-tool guard runs this, and so does the pre-commit hook "
               "`maestro init` installs)")
    _flag(s, "--accept", action="store_true",
          help="Re-sign every record as it is on disk, without reformatting: the adoption "
               "step, or the explicit way to bless a deliberate hand fix")

    # ── kb ──
    kb_group = groups.add_parser("kb", help="Knowledge-base search").add_subparsers(
        dest="verb", required=True, metavar="<verb>")

    s = _verb(kb_group, "kb", "search", "Semantic search over the knowledge base", kb.cmd_search)
    _flag(s, "--query", required=True, help="What to search for")
    _flag(s, "--top-k", dest="top_k", type=int, default=5, help="How many hits to return")
    _flag(s, "--kb", default=str(kb.DEFAULT_KB), help="Directory holding the kb entries")

    s = _verb(kb_group, "kb", "build", "Rebuild the kb vector index and recalibrate the gate",
              kb.cmd_build)
    _flag(s, "--kb", default=str(kb.DEFAULT_KB), help="Directory holding the kb entries")
    _flag(s, "--margin", type=float, default=kb.DEFAULT_MARGIN,
          help="How far above the measured noise floor the relevance gate sits")

    s = _verb(kb_group, "kb", "selftest", "Label-free health check of the kb index", kb.cmd_selftest)
    _flag(s, "--kb", default=str(kb.DEFAULT_KB), help="Directory holding the kb entries")

    # ── init ──
    s = _command(groups, "option",
                 "Project options — candidate work belonging to no epic yet, parked in "
                 "docs/progress.md `## Up next`",
                 options_mod.option)
    _flag(s, "--add", help="Park an idea: one line, no status, no owner. The date is "
                           "stamped for you, so a line that has sat a year says so.")
    _flag(s, "--drop", type=int,
          help="Remove option <n> — because it is done, or because you decided against "
               "it. An option worth a trace is worth an epic (`maestro epic new`).")
    _flag(s, "--list", action="store_true", help="Print the parked options (the default)")

    s = _command(groups, "init",
                 "Adopt a project (layout, drift hook, git excludes, the [tool.maestro] "
                 "tracker switch, and deletion of tool copies left by the old install "
                 "model), or set the machine up with --harness",
                 _init)
    _flag(s, "--path", help="Project to adopt (default: the working directory)")
    _flag(s, "--harness", action="store_true",
          help="Machine mode: wire the record-guard + kb-index-regen hooks into "
               "~/.claude/settings.json, instead of adopting a project")
    _flag(s, "--repo", help="The maestro checkout to read templates and hooks from "
                            "(default: $MAESTRO_REPO, else the checkout this CLI runs from)")
    _flag(s, "--tracker", choices=init_mod.TRACKERS,
          help="The experiment tracker this project logs to, written to its "
               "pyproject.toml as [tool.maestro] tracker. Omit and an existing value is "
               "kept, with 'none' written when the key is absent. Endpoint and "
               "credentials always come from the environment. A tracker other than "
               "'none' also runs `uv add maestro[tracking]` in a uv project, so "
               "`from maestro.tracking import ...` resolves in the project's own env")
    _flag(s, "--dep-source", dest="dep_source",
          help="Where that requirement points, instead of the pinned git URL: a URL as "
               "given, or a path to a maestro checkout. For a repo not reachable at the "
               "default URL — still private, or local development.")
    _flag(s, "--layers",
          help="Rule layers the project keeps, comma-separated: discipline (every adopted "
               "project) and research (exp files, run dirs, the immutable raw tier). "
               "Default: both. Written to maestro.toml once; never rewritten")
    _flag(s, "--shape", choices=list(declaration.SHAPES),
          help="The data shape at adoption: tiers (data/raw/<dataset>/v<N> + data/processed, "
               "the layout the checker polices) or other (the project's own layout, data "
               "paths and shas not checked). Default: tiers. A later change is "
               "`maestro shape add`, dated")
    _flag(s, "--dry-run", dest="dry_run", action="store_true",
          help="Print every change and write nothing")
    _flag(s, "--force", action="store_true",
          help="Overwrite a starter document or skill that is already there")

    # ── shape ──
    shape_group = groups.add_parser(
        "shape", help="The declared data shape — maestro.toml's dated, append-only history"
    ).add_subparsers(dest="verb", required=True, metavar="<verb>")
    s = _verb(shape_group, "shape", "add",
              "Append a dated shape entry to maestro.toml: a layout change, never an edit "
              "of history. Records dated from --since are checked under the new shape",
              declaration.shape_add)
    _flag(s, "--name", required=True, choices=list(declaration.SHAPES),
          help="tiers | other")
    _flag(s, "--since", required=True,
          help="YYYY-MM-DD the new shape holds from (the ADR's date)")
    _verb(shape_group, "shape", "show", "Print the declaration: layers and the shape history",
          declaration.shape_show)

    # ── info ──
    info_group = groups.add_parser("info", help="Project layout and conventions").add_subparsers(
        dest="verb", required=True, metavar="<verb>")
    _verb(info_group, "info", "show", "Print the project layout and maestro conventions", info)

    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    # Catch unquoted multi-word values BEFORE argparse sees them: it would report the
    # trailing words as an unrecognised-argument blur, or (with parse_known_args) drop
    # them silently. Only possible once the verb is known, since flags are per-verb.
    # A group typed with no verb: argparse reports "the following arguments are
    # required: <verb>" and the metavar hides the choices, so it never says WHICH.
    # Every other refusal in this CLI names the allowed values; this one now does too.
    if len(argv) == 1 and (argv[0],) not in LEAVES:
        verbs = sorted(v for group, *rest in LEAVES for v in rest if group == argv[0])
        if verbs:
            example = "new" if "new" in verbs else verbs[0]
            parser.error(f"{argv[0]} needs a verb: {', '.join(verbs)} "
                         f"(e.g. maestro {argv[0]} {example} --help)")

    if argv:
        one, two = (argv[0],), tuple(argv[:2])
        if one in LEAVES:
            _reject_unquoted(LEAVES[one], one, argv[1:])
        elif two in LEAVES:
            _reject_unquoted(LEAVES[two], two, argv[2:])

    # parse_KNOWN_args, then report the leftovers against the LEAF. `parse_args` is the
    # root parser's method, so an unknown flag on a verb came back as
    # "usage: maestro [-h] [--version] <group> ... unrecognized arguments: --epic=4":
    # the usage of the wrong parser, listing none of the flags the verb does take. The
    # leftovers are the same either way; only who reports them changes, so exit stays 2.
    args, extra = parser.parse_known_args(argv)
    if extra:
        leaf = LEAVES.get(getattr(args, "_key", None), parser)
        leaf.error("unrecognized arguments: " + " ".join(extra))
    args.func(args)


if __name__ == "__main__":
    main()
