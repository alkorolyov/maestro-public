#!/usr/bin/env python3
"""Maestro stamp-guard — a Claude Code PostToolUse hook.

Its dsh half (a plugin) was removed;
both ask the same question of the same CLI, so a record hand-edited in either harness is
refused in the same turn.

After ANY tool call (Bash, Write, Edit, ...) it asks `maestro docs stamp --check` whether
some record's CLI-owned surface (frontmatter; the epic log) no longer matches the stamp
the CLI wrote. If so it returns a BLOCKING decision whose reason names the file and the
CLI verb, so the model sees it in the same turn — before a commit, before the session ends.

It does not read the tool's command text at all: a `cat >>`, a `sed -i`, an inline python,
or an edit tool all end the same way, as a file whose hash no longer matches. That is why
this hook covers the shell where the Write/Edit pre-hook (guard_records.py) cannot.

Wire-up (~/.claude/settings.json), alongside the existing entries:

    {"hooks": {"PostToolUse": [
      {"matcher": "Bash|Write|Edit|MultiEdit",
       "hooks": [{"type": "command",
                  "command": "python3 <maestro>/global/hooks/guard_stamps.py",
                  "timeout": 10}]}
    ]}}

Exits 0 silently when the cwd is not a maestro project (no docs/ with records), when the
CLI is not on PATH, or when every stamp matches.

Under `MAESTRO_GATES=warn` (tools/maestro_cli/gates.py) the mismatch is not a block: the
same report reaches the model as PostToolUse `additionalContext`. It is shown ONCE per
distinct report, not after every later tool call while the record stays as it is — a
warning repeated every turn is noise that teaches the reader to skip it. A state file in
the temp dir (one per project root) holds the hash of the last report shown; a clean
check clears it, so the same breach warns again if it comes back.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
try:
    from maestro_cli.gates import warning, warns
except ImportError:  # pragma: no cover - a checkout without tools/ on disk
    def warns():
        return False


def maestro_command():
    """The CLI as argv: the installed `maestro`, else this checkout's package run as a
    module (so the hook works from a bare clone), else None."""
    if shutil.which("maestro"):
        return ["maestro"]
    tools = Path(__file__).resolve().parent.parent.parent / "tools"
    if (tools / "maestro_cli" / "cli.py").is_file():
        os.environ["PYTHONPATH"] = str(tools) + os.pathsep + os.environ.get("PYTHONPATH", "")
        return [sys.executable, "-m", "maestro_cli.cli"]
    return None


def _state_file(root: Path) -> Path:
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"maestro-stamp-warned-{key}"


def _already_warned(root: Path, report: str) -> bool:
    """True when this exact report was the last one shown for this root; records it."""
    state = _state_file(root)
    digest = hashlib.sha256(report.encode()).hexdigest()
    try:
        if state.read_text() == digest:
            return True
    except OSError:
        pass
    try:
        state.write_text(digest)
    except OSError:
        pass
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    root = Path(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    docs = root / "docs"
    declared = (root / "maestro.toml").is_file()
    if not declared and (not docs.is_dir()
                         or not any((docs / d).is_dir() for d in ("epics", "experiments", "adrs", "data"))):
        return 0
    cmd = maestro_command()
    if cmd is None:
        return 0
    run = subprocess.run([*cmd, "docs", "stamp", "--check"], cwd=root,
                         capture_output=True, text=True, timeout=8)
    if run.returncode != 2:
        if run.returncode == 0:
            try:
                _state_file(root).unlink()
            except OSError:
                pass
        return 0
    if warns():
        report = run.stderr.strip()
        if _already_warned(root, report):
            return 0
        text = warning("stamp-guard", "A record's CLI-owned surface no longer matches its "
                       "stamp (rule 1). Redo the change through the CLI, or bless a deliberate "
                       "hand fix with `maestro docs stamp --accept`:\n" + report)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": text}}))
        return 0
    reason = ("A maestro record was edited by hand (its stamp no longer matches). Records are "
              "written only via the maestro CLI (rule 1). Revert the hand edit and redo it "
              "through the CLI:\n" + run.stderr.strip())
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
