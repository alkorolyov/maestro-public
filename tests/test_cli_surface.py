"""Tests for the CLI surface itself — `maestro <group> <verb> --flag=value` (ADR 8).

test_cli_flag_parsing.py covers the unquoted-value guard. This file covers the shape
that guard depends on, and the dispatch around it:

  * NO POSITIONALS anywhere. The whole surface is named flags, which is what makes an
    unquoted multi-word value detectable rather than silently truncated;
  * every value-taking flag is registered in VALUE_FLAGS. A flag added straight through
    `add_argument` instead of `_flag` still parses, so nothing fails — it just stops
    being guarded, and the failure resurfaces as the truncation ADR 8 was written about;
  * every leaf carries a `func`, so no reachable verb dead-ends;
  * a group with no verb, or an unknown one, fails with the choices listed rather than
    a traceback.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import __version__  # noqa: E402
from maestro_cli.cli import LEAVES, VALUE_FLAGS, build_parser, main  # noqa: E402


build_parser()          # LEAVES/VALUE_FLAGS are filled as the parser is built


def leaf_ids():
    return sorted(" ".join(k) for k in LEAVES)


def actions_of(key):
    """Every flag action on one leaf parser, help excluded."""
    return [a for a in LEAVES[key]._actions if a.option_strings and a.dest != "help"]


def usage(argv, capsys):
    """Run a bad invocation and return what argparse printed."""
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2
    return capsys.readouterr().err


# ── the shape ADR 8 fixed ────────────────────────────────────────────────────

@pytest.mark.parametrize("leaf", leaf_ids())
def test_no_verb_takes_a_positional(leaf):
    key = tuple(leaf.split())
    positionals = [a for a in LEAVES[key]._actions if not a.option_strings]
    assert positionals == [], f"{leaf} takes a positional — every value is a named flag"


@pytest.mark.parametrize("leaf", leaf_ids())
def test_every_value_flag_is_registered_for_the_guard(leaf):
    """`_flag` does this bookkeeping; an `add_argument` that bypasses it is the hole."""
    key = tuple(leaf.split())
    for a in actions_of(key):
        takes_value = a.nargs != 0
        for name in a.option_strings:
            assert (name in VALUE_FLAGS[key]) == takes_value, (
                f"{leaf} {name}: registered={name in VALUE_FLAGS[key]}, "
                f"takes a value={takes_value}")


@pytest.mark.parametrize("leaf", leaf_ids())
def test_every_flag_is_long_form(leaf):
    for a in actions_of(tuple(leaf.split())):
        assert all(n.startswith("--") for n in a.option_strings), f"{leaf}: {a.option_strings}"


@pytest.mark.parametrize("leaf", leaf_ids())
def test_every_leaf_dispatches_somewhere(leaf):
    key = tuple(leaf.split())
    assert callable(LEAVES[key].get_default("func"))
    assert LEAVES[key].get_default("_key") == key


@pytest.mark.parametrize("leaf", leaf_ids())
def test_every_flag_says_what_it_is_for(leaf):
    for a in actions_of(tuple(leaf.split())):
        assert a.help, f"{leaf} {a.option_strings} has no help text"


def test_only_two_commands_skip_the_group_verb_shape():
    """ADR 8's exception, and it stays an exception.

    `maestro <group> <verb>` holds for every record kind. The two that skip it take no
    object at all: `init` acts on the project or the machine, `option` on the project's
    own candidate-work list. Neither names a record kind, so inventing a verb for them
    would name nothing. A THIRD one-level command fails here — the exception is meant to
    be argued for, not accumulated.
    """
    assert sorted(k for k in LEAVES if len(k) == 1) == [("init",), ("option",)]


# ── dispatch and its refusals ────────────────────────────────────────────────

def test_the_version_is_the_one_the_package_reports(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"maestro {__version__}"


def test_a_group_with_no_verb_lists_the_verbs(capsys):
    err = usage(["exp"], capsys)
    assert "new" in err and "revise" in err


def test_an_unknown_verb_names_the_ones_that_exist(capsys):
    err = usage(["exp", "remove"], capsys)
    assert "invalid choice" in err and "revise" in err


def test_an_unknown_group_is_not_a_traceback(capsys):
    assert "invalid choice" in usage(["nonsense"], capsys)


def test_a_missing_required_flag_names_it(capsys):
    assert "--slug" in usage(["exp", "new"], capsys)


def test_a_verb_reaches_its_module_function(monkeypatch):
    seen = {}
    monkeypatch.setattr("maestro_cli.experiments.exp_new", lambda args: seen.update(vars(args)))
    main(["exp", "new", "--slug=rf_baseline"])
    assert seen["slug"] == "rf_baseline"


def test_the_group_and_verb_reach_the_parsed_args(monkeypatch):
    """The unquoted-value guard keys off (group, verb), so both must survive parsing."""
    seen = {}
    monkeypatch.setattr("maestro_cli.epics.epic_show", lambda args: seen.update(vars(args)))
    main(["epic", "show", "--id=2"])
    assert (seen["group"], seen["verb"], seen["id"]) == ("epic", "show", 2)


# ── a refusal names the VERB, never the root ─────────────────────────────────
#
# argparse's `parse_args` is a method of the ROOT parser, so leftovers a subparser did
# not recognise were reported as "usage: maestro [-h] [--version] <group> ..." — the
# usage of the wrong parser, listing none of the flags the verb does take. An agent
# spent two retries (~100 s each) before reading `--help`.

def test_an_unknown_flag_shows_the_verbs_usage_not_the_roots(capsys):
    err = usage(["epic", "item", "--sprint=4", "--id=9", "--status=done"], capsys)
    assert "usage: maestro epic item" in err
    assert "[--version] <group>" not in err
    assert "unrecognized arguments: --sprint=4" in err


def test_an_unknown_flag_lists_the_flags_the_verb_does_take(capsys):
    err = usage(["exp", "update", "--result=0.84", "--id=3"], capsys)
    assert "usage: maestro exp update" in err
    assert "--takeaway" in err          # the flag that was meant is on the usage line


# ── --epic as an alias of --id on the epic verbs ─────────────────────────────

EPIC_VERBS_WITH_ID = [k for k in LEAVES
                      if k[0] == "epic" and "--id" in VALUE_FLAGS[k]]


@pytest.mark.parametrize("key", sorted(EPIC_VERBS_WITH_ID))
def test_every_epic_verb_takes_epic_as_an_alias_of_id(key):
    """`--id` on an epic verb means the epic number, and `--epic=4` is what gets typed.

    One argument with two option strings, not two arguments: dest stays `id`, so no
    module below cli.py knows the alias exists.
    """
    ids = [a for a in actions_of(key) if a.dest == "id"]
    assert len(ids) == 1
    assert ids[0].option_strings == ["--id", "--epic"]


def test_the_alias_reaches_the_module_as_id(monkeypatch):
    seen = {}
    monkeypatch.setattr("maestro_cli.epics.epic_item", lambda args: seen.update(vars(args)))
    main(["epic", "item", "--epic=4", "--item=9", "--status=done", "--evidence=abc123"])
    assert (seen["id"], seen["item"], seen["status"]) == (4, 9, "done")


def test_help_lists_the_alias(capsys):
    with pytest.raises(SystemExit) as e:
        main(["epic", "item", "--help"])
    assert e.value.code == 0
    assert "--id ID, --epic ID" in capsys.readouterr().out
