#!/usr/bin/env python3
"""Maestro kb-index regenerator — a Claude Code PostToolUse hook.

Its dsh half (a plugin) was removed.
Both run the project's own `maestro index render`, so an entry written in either harness
leaves the catalog current.

Regenerates the kb literature catalog (docs/kb/literature/INDEX.md) whenever a kb
literature ENTRY is written or edited. This closes a wiring gap: the maestro CLI
owns the exp/adr/dataset records and auto-regenerates their INDEX on every write,
but kb literature entries (docs/kb/literature/<slug>.md) are written by the
literature_search protocol via direct Write — NOT by the CLI — so nothing
regenerated docs/kb/literature/INDEX.md and it silently went stale.

This hook is the kb analog of that auto-regen: after a Write/Edit/MultiEdit lands
on a kb literature entry, it runs the PROJECT's own copy of the maestro CLI to
refresh all indexes (the CLI derives its root from its own location, so running
the project's copy targets that project).

It fires only for the main Claude agent's own writes — not subagent batches or
other agents — so the literature_search protocol also runs `maestro index render`
once after all entries land, as a backup (see protocols/literature_search.md).

Wire-up (in ~/.claude/settings.json, alongside any existing PostToolUse entries):

    {"hooks": {"PostToolUse": [
      {"matcher": "Write|Edit|MultiEdit",
       "hooks": [{"type": "command",
                  "command": "python3 <maestro>/global/hooks/regen_kb_index.py",
                  "timeout": 10}]}
    ]}}

Contract: reads the hook payload as JSON on stdin; if the edited file is a kb
literature entry (path tail kb/literature/<name>.md, name != INDEX.md), walks up
to find tools/maestro_cli/ and runs `maestro index render --kind=all` from it;
exits 0 silently for everything else.
"""
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath


def _is_kb_entry(file_path: str) -> bool:
    """True if file_path is a kb literature ENTRY (not the generated INDEX.md)."""
    p = PurePosixPath(file_path)
    name = p.name
    if name == "INDEX.md" or not name.endswith(".md"):
        return False
    # Path tail must be kb/literature/<name>.md.
    return p.parts[-3:-1] == ("kb", "literature")


def _find_cli(file_path: str) -> Path | None:
    """Walk up from the edited file to the first tools/maestro_cli/cli.py, else None."""
    for parent in Path(file_path).resolve().parents:
        candidate = parent / "tools" / "maestro_cli" / "cli.py"
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # no parseable payload → nothing to do

    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path or not _is_kb_entry(str(file_path)):
        return 0  # not a kb literature entry → silent no-op

    cli = _find_cli(str(file_path))
    if cli is None:
        return 0  # no project copy of the maestro CLI (old project) → do nothing

    tools_dir = cli.parent.parent            # <project>/tools
    env = dict(os.environ)
    # Run the PROJECT's copy, whatever `maestro` happens to be on PATH.
    env["PYTHONPATH"] = os.pathsep.join([str(tools_dir), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    subprocess.run(
        [sys.executable, "-m", "maestro_cli.cli", "index", "render", "--kind=all"],
        cwd=str(tools_dir.parent),
        env=env,
        capture_output=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
