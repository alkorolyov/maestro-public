"""Unquoted multi-word values must FAIL loudly, never be silently truncated.

Measured in exp 6: models write `--reason=computed from one rep only` without quotes.
Plain argparse would read the trailing words as unknown positionals and (with
parse_known_args) keep only "computed" — a wrong value written into a record with no
error. The CLI therefore rejects the input and shows the quoted form instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli.cli import build_parser, main  # noqa: E402


def _fails(argv, capsys):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2
    return capsys.readouterr().err


def test_unquoted_value_equals_form_names_the_flag(capsys):
    err = _fails(["exp", "revise", "--id=3", "--reason=computed", "from", "one", "rep", "only",
                  "--new-takeaway=median wall time"], capsys)
    assert '--reason got extra words ("from one rep only")' in err
    assert '--reason="computed from one rep only"' in err


def test_unquoted_value_space_form_names_the_flag(capsys):
    err = _fails(["exp", "revise", "--id", "3", "--reason", "computed", "from", "one", "rep", "only",
                  "--new-takeaway=x"], capsys)
    assert '--reason got extra words ("from one rep only")' in err
    assert '--reason="computed from one rep only"' in err


def test_unquoted_takeaway_on_update_is_rejected(capsys):
    err = _fails(["exp", "update", "--id=7", "--takeaway=median", "wall", "time", "27.8s"], capsys)
    assert '--takeaway got extra words ("wall time 27.8s")' in err
    assert '--takeaway="median wall time 27.8s"' in err


def test_positional_value_is_rejected(capsys):
    err = _fails(["exp", "show", "4"], capsys)
    assert "every value is a named flag" in err


def test_switch_followed_by_words_is_rejected(capsys):
    err = _fails(["exp", "finding", "--id=6", "--negative", "depth", "beyond", "12"], capsys)
    assert "--negative is a switch and takes no value" in err


@pytest.mark.parametrize("argv,expected", [
    (["exp", "revise", "--id=3", "--reason=computed from one rep only", "--new-takeaway=x"],
     "computed from one rep only"),
    (["exp", "revise", "--id=3", "--reason", "computed from one rep only", "--new-takeaway=x"],
     "computed from one rep only"),
])
def test_quoted_multi_word_value_survives_intact(argv, expected):
    # The quoted form is the one the error message teaches — it must parse, whole.
    args = build_parser().parse_args(argv)
    assert args.reason == expected


def test_no_value_is_ever_silently_truncated():
    # The guard runs before argparse, so a truncated value can never reach a record.
    with pytest.raises(SystemExit):
        main(["exp", "revise", "--id=3", "--reason=computed", "from", "one", "rep",
              "--new-takeaway=x"])


# ── the hint names THIS verb's flags ─────────────────────────────────────────
#
# The example used to be a hard-coded `--id=3` on every verb. An agent read it, retried,
# and still had to reach `--help` — three round trips at ~100 s each. The
# example is now built from the verb's own flags and filled with the words that were
# actually typed, so the corrected command can be read straight off the error.

def test_positional_hint_is_built_from_the_verbs_own_flags(capsys):
    err = _fails(["epic", "item", "4", "9", "--status=done", "--evidence=sha"], capsys)
    assert 'unexpected argument ("4 9")' in err
    assert "e.g. --id=4 --item=9" in err


def test_positional_hint_on_a_verb_with_one_required_flag(capsys):
    err = _fails(["exp", "show", "3"], capsys)
    assert "e.g. --id=3" in err


def test_positional_hint_names_no_flag_the_verb_lacks(capsys):
    """`dataset show` has --name and no --id at all; the old fixed example named --id."""
    err = _fails(["dataset", "show", "pampa"], capsys)
    assert "--id" not in err
    assert "e.g. --name=pampa" in err


def test_an_unknown_flag_that_swallowed_words_is_named_as_unknown(capsys):
    """Not "--epic is a switch": the verb has no --epic, so that would be a lie."""
    err = _fails(["epic", "close", "--epik", "4", "9"], capsys)
    assert "unrecognized arguments: --epik" in err


def test_find_root_prefers_cwd_project_over_package(tmp_path, monkeypatch):
    # ADR 10 regression: a machine-level install must resolve ROOT from the caller's
    # cwd, never from the package's own checkout.
    from maestro_cli import frontmatter
    proj = tmp_path / "someproj"
    (proj / "docs").mkdir(parents=True)
    monkeypatch.chdir(proj)
    monkeypatch.delenv("MAESTRO_ROOT", raising=False)
    assert frontmatter._find_root() == proj
