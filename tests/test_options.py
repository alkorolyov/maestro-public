"""Tests for project-level options (`maestro option`, modules/kanban.md).

The capture slot above every epic. What is pinned here is the property that makes it
worth having at all: parking an idea is ONE command that cannot fail on where to put it,
and the line it writes carries the date, because an idea from June should not read like
one from this morning.

Every case drives the real CLI entry point against a throwaway progress.md, so the flag
names are exercised alongside the behaviour.
"""
from __future__ import annotations

from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest  # noqa: E402

from maestro_cli import options  # noqa: E402
from maestro_cli.cli import main  # noqa: E402


TEMPLATE = (Path(__file__).resolve().parent.parent / "templates" / "progress.md").read_text()


@pytest.fixture
def progress(tmp_path, monkeypatch):
    """A throwaway docs/progress.md, seeded from the real shipped template."""
    path = tmp_path / "docs" / "progress.md"
    path.parent.mkdir(parents=True)
    path.write_text(TEMPLATE)
    monkeypatch.setattr(options, "PROGRESS", path)
    monkeypatch.setattr(options, "ROOT", tmp_path)
    return path


def refusal(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code not in (0, None), "a refused command must exit non-zero"
    return str(e.value.code)


def test_the_shipped_template_starts_with_no_options(progress, capsys):
    # The template's "- {nothing yet}" placeholder is prose, not a parked idea.
    main(["option", "--list"])
    assert "no options parked" in capsys.readouterr().out
    assert options.parse(progress.read_text()) == []


def test_parking_stamps_the_date(progress, capsys):
    main(["option", "--add=back-tag v2.4 through v2.7"])
    capsys.readouterr()
    rows = options.parse(progress.read_text())
    assert rows == [(str(date.today()), "back-tag v2.4 through v2.7")]
    # The date is the ONE property an option is otherwise denied, and it is the tool's
    # to write: the executor reads a clock but never notices that it should.
    assert f"- {date.today()} — back-tag" in progress.read_text()


def test_options_keep_their_order_and_number_from_one(progress, capsys):
    for text in ("first idea", "second idea", "third idea"):
        main(["option", f"--add={text}"])
    capsys.readouterr()
    main(["option", "--list"])
    out = capsys.readouterr().out
    assert out.index("first idea") < out.index("second idea") < out.index("third idea")
    assert "  1. " in out and "  3. " in out


def test_drop_removes_one_and_renumbers(progress, capsys):
    for text in ("first idea", "second idea", "third idea"):
        main(["option", f"--add={text}"])
    capsys.readouterr()
    main(["option", "--drop=2"])
    assert 'option 2 dropped — "second idea"' in capsys.readouterr().out
    assert [t for _d, t in options.parse(progress.read_text())] == ["first idea", "third idea"]


def test_a_bad_index_refuses_and_shows_what_there_is(progress, capsys):
    main(["option", "--add=the only idea"])
    capsys.readouterr()
    msg = refusal(["option", "--drop=9"])
    assert "no option 9 (there are 1)" in msg
    assert "the only idea" in capsys.readouterr().err     # the list, so you can retry
    assert options.parse(progress.read_text())            # refused means unwritten


def test_writing_an_option_leaves_every_other_section_alone(progress, capsys):
    before = progress.read_text()
    main(["option", "--add=an idea"])
    main(["option", "--add=another"])
    main(["option", "--drop=1"])
    capsys.readouterr()
    after = progress.read_text()
    # Only the bullets move: the section's own explanatory paragraph and every other
    # heading are byte-identical, because progress.md is hand-written around them.
    for heading in ("## Current", "## Loose ends", "## Open questions"):
        assert heading in after
        assert (before.split(heading, 1)[1].splitlines()[1:4]
                == after.split(heading, 1)[1].splitlines()[1:4])
    assert 'Written by `maestro option --add="..."`' in after


def test_empty_and_ambiguous_calls_refuse(progress, capsys):
    main(["option", "--add=an idea"])
    capsys.readouterr()
    assert "--add cannot be empty" in refusal(["option", "--add= "])
    assert "exactly one of" in refusal(["option", "--add=x", "--drop=1"])
    assert "exactly one of" in refusal(["option", "--add=x", "--list"])


def test_a_missing_progress_file_says_which_command_makes_one(progress, capsys):
    progress.unlink()
    assert "maestro init" in refusal(["option", "--add=an idea"])


def test_a_progress_file_without_the_section_says_so(progress, capsys):
    progress.write_text("# Progress\n\n## Current\n\nnothing.\n")
    msg = refusal(["option", "--add=an idea"])
    assert "## Up next" in msg and "core rule 10" in msg


def test_a_bare_bullet_written_before_this_verb_is_still_an_option(progress, capsys):
    # Projects that kept a hand-written list under ## Up next do not lose it; it simply
    # has no date until someone re-parks it.
    text = progress.read_text().replace("- {nothing yet}", "- an idea somebody typed")
    progress.write_text(text)
    main(["option", "--add=a new one"])
    capsys.readouterr()
    assert [t for _d, t in options.parse(progress.read_text())] == [
        "an idea somebody typed", "a new one"]
