"""`maestro init` — adopt a project, or set up the machine (ADR 10).

The CLI is machine-level: one isolated install (`uv tool install`) serves every
project, and nothing is copied into a project any more. What is left over is the work
packaging cannot do — wheels have no install-time hooks by design — so it lives here,
in Python that can be tested and dry-run, instead of in a bash heredoc:

    maestro init [--path=DIR]     scaffold the layout, remove retired hook rows,
                                  exclude the untracked shared memory from git, install
                                  the pre-commit guard, set the [tool.maestro] tracker
                                  switch, and delete tool copies left by the old install
                                  model
    maestro init --tracker=NAME   choose that project's experiment tracker
                                  ("none" | "wandb" | "mlflow"); the endpoint and the
                                  credentials always come from the environment
    maestro init --harness        wire the record-guard and kb-index hooks into
                                  the record-guard + kb-index-regen hooks

Three properties every path below holds to:

  * **idempotent** — a second run reports "no changes" and writes nothing;
  * **`--dry-run` writes nothing at all**, and names every file, hook and deletion it
    would touch, so the JSON surgery on a settings file is reviewable before it happens;
  * **never clobber** — a `settings.json` that is not valid JSON is left exactly as it
    is, with the hook printed for the reader to add by hand, and an existing file the
    scaffold would place is skipped unless `--force`.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# ── what a project gets ───────────────────────────────────────────────────────

# The maestro layout (core.md → Layout). Only the directories records and runs are
# written into; src/, scripts/ and experiments/ belong to the project's own language.
SCAFFOLD_DIRS = (
    "docs/experiments",
    "docs/adrs",
    "docs/epics",
    "docs/data",
    "docs/kb",
    "docs/archive",
    "data/raw",
    "data/processed",
    "data/experiments",
)

# Starter documents, copied from the maestro repo's templates/ (templates/README.md is
# the same table). Reference-only skeletons — exp_NN.md, adr_NN.md, data_NN.md — are not
# copied: `maestro exp new` and friends generate the real records.
SEED_FILES = (
    ("CLAUDE.md", "CLAUDE.md"),
    ("progress.md", "docs/progress.md"),
    ("findings.md", "docs/findings.md"),
    # CLAUDE.md's own "when to load" table cites these two. A citation to a file the
    # same init never wrote is a dead path (rule 2), and a fresh project used to fail
    # `maestro docs check` on its first run because of it.
    ("setup.md", "docs/setup.md"),
    ("data.md", "docs/data.md"),
)

# The untracked shared memory. It goes in .git/info/exclude rather than .gitignore
# because these paths are AI-context state, not part of the project's public tree.
EXCLUDE_PATHS = ("docs/", "CLAUDE.md", ".claude/", "data/presentations/")

# Tool copies the pre-ADR-10 install model left in projects. They shadow the installed
# CLI on PYTHONPATH and freeze at whatever version install.sh last copied, which is the
# drift ADR 8 named and ADR 10 removes.
STALE_TOOLS = (
    "rec.py",
    "render_index.py",
    "check_drift.py",
    "index_kb.py",
    "dataset_hash.py",
    "maestro_cli",
)

# The experiment tracker a project logs to, declared in its own pyproject.toml as
# [tool.maestro] tracker. Off by default: without one, an experiment's metrics stay
# machine-written artifacts under data/experiments/. The endpoint and the credentials for
# "wandb"/"mlflow" come from the environment — this key only names which client to load,
# so nothing host- or account-specific is ever written into a repo.
TRACKERS = ("none", "wandb", "mlflow")
TRACKER_DEFAULT = "none"
PYPROJECT = "pyproject.toml"

_TABLE_RE = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$")
# What an adopted project declares so `from maestro.tracking import ...` resolves. The
# CLI is machine-level and isolated (ADR 10), so its environment is deliberately NOT on
# the project's import path; the library therefore arrives as an ordinary dependency,
# managed and upgradable, which is a different thing from the pre-ADR-10 copies that
# froze in <project>/tools/ and shadowed the installed CLI.
#
# A git requirement so the project's pyproject names no machine. `--dep-source=`
# overrides the location for a checkout that is not reachable there — a repo that is
# still private, or local development.
MAESTRO_REPO_URL = "https://github.com/alkorolyov/maestro-public"
DEP_NAME = "maestro"
DEP_EXTRA = "maestro[tracking]"

_TRACKER_RE = re.compile(r"""^(?P<lead>\s*tracker\s*=\s*)(?P<q>["'])(?P<value>[^"']*)(?P=q)(?P<tail>.*)$""")

# A leftover worktree-symlink git hook. Worktrees are the harness's concern
# (modules/concurrency.md) and carry no shared-memory symlinks.
V1_GIT_HOOK = ".git/hooks/post-checkout"
V1_GIT_HOOK_MARK = "maestro post-checkout git hook"

# The commit-time guard (templates/pre-commit): the record stamp on every branch,
# `docs check --staged` over the files being committed, and rule 9's "only docs/ is
# committed directly on main".
#
# The template carries `# maestro pre-commit vN` so init can tell ITS hook from a hook
# the project wrote: only its own is ever replaced, and only when the template is newer.
PRE_COMMIT_TEMPLATE = "pre-commit"
PRE_COMMIT_HOOK = "pre-commit"
PRE_COMMIT_MARK_RE = re.compile(r"^#\s*maestro pre-commit v(\d+)\s*$", re.M)

MATCHER = "Write|Edit|MultiEdit"
# The stamp guard also has to see a SHELL write: `cat >>`, `sed -i` and an inline python
# all end as a record whose hash no longer matches, and none of them is a Write.
STAMP_MATCHER = "Bash|Write|Edit|MultiEdit"
# The gh-auth guard reads a command line, so it only ever fires on the shell.
SHELL_MATCHER = "Bash"


class InitError(Exception):
    """A condition the caller must fix before anything can be written."""


# ── locating the maestro repo ─────────────────────────────────────────────────

def is_repo(path):
    """Whether `path` is a maestro checkout — the trees init reads from.

    Keyed on templates/ and the rules, not on global/skills/: the skills that were
    a checkout can legitimately have no skills at all.
    """
    path = Path(path)
    return (path / "templates").is_dir() and (path / "core.md").is_file()


def repo_dir(explicit=None):
    """The maestro checkout to read templates and hooks from, or None.

    Explicit `--repo` wins, then MAESTRO_REPO, then the checkout this package is
    running from. An installed CLI lives in its own environment with no checkout
    around it, which is why the flag exists at all.
    """
    for candidate, origin in ((explicit, "--repo"), (os.environ.get("MAESTRO_REPO"), "MAESTRO_REPO")):
        if candidate:
            path = Path(candidate).expanduser().resolve()
            if not is_repo(path):
                raise InitError(f"{origin}={path} is not a maestro checkout "
                                "(expected templates/ and core.md inside it).")
            return path
    here = Path(__file__).resolve().parents[2]
    return here if is_repo(here) else None


# ── the report ────────────────────────────────────────────────────────────────

class Plan:
    """Collects what was done — or, under --dry-run, what would be done.

    Every write in this module goes through a Plan, so `--dry-run` is one branch in one
    place rather than a flag threaded through each file operation.
    """

    def __init__(self, dry_run=False, force=False):
        self.dry_run = dry_run
        self.force = force
        self.changes = 0
        self.lines = []

    def change(self, text):
        self.changes += 1
        self.lines.append(("+", ("would " + text) if self.dry_run else text))

    def keep(self, text):
        self.lines.append((" ", text))

    def warn(self, text):
        self.lines.append(("!", text))

    def section(self, title):
        self.lines.append((None, title))

    def render(self):
        out = []
        for mark, text in self.lines:
            out.append(f"\n{text}" if mark is None else f"  {mark} {text}")
        return "\n".join(out)

    def print(self):
        print(self.render())
        if self.dry_run:
            print(f"\nDry run — nothing written. {self.changes} change(s) pending.")
        elif self.changes:
            print(f"\nDone: {self.changes} change(s).")
        else:
            print("\nDone: no changes — already set up.")


# ── file primitives ───────────────────────────────────────────────────────────

def _mkdir(path, plan, label):
    if path.is_dir():
        plan.keep(f"{label} exists")
        return
    plan.change(f"create {label}")
    if not plan.dry_run:
        path.mkdir(parents=True, exist_ok=True)


def _copy(src, dst, plan, label, origin):
    if dst.exists() and not plan.force:
        plan.keep(f"{label} exists — kept (--force overwrites)")
        return
    verb = "overwrite" if dst.exists() else "create"
    plan.change(f"{verb} {label} from {origin}")
    if not plan.dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def _remove(path, plan, label):
    plan.change(f"remove {label}")
    if plan.dry_run:
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


# ── settings.json surgery ─────────────────────────────────────────────────────

def read_settings(path):
    """(data, ok). ok is False only when the file exists and is not valid JSON."""
    if not Path(path).exists():
        return {}, True
    try:
        return json.loads(Path(path).read_text()), True
    except (OSError, ValueError):
        return None, False


def _entry_for(entries, matcher):
    """The hook entry a command belongs in, appended if it is not there yet.

    Stop entries carry no matcher, so the first matcher-less entry is reused.
    """
    if matcher:
        entry = next((e for e in entries if e.get("matcher") == matcher), None)
        if entry is None:
            entry = {"matcher": matcher, "hooks": []}
            entries.append(entry)
    else:
        entry = next((e for e in entries if not e.get("matcher")), None)
        if entry is None:
            entry = {"hooks": []}
            entries.append(entry)
    entry.setdefault("hooks", [])
    return entry


# Hook commands this repo has RETIRED. A row naming one of these is removed from the
# settings file it is found in, because an installed row outlives the decision behind it:
# A row for a missing script would make every Claude Code tool call shell out to nothing
# (the root-code rule is dsh-only). A Stop hook that exits 2 blocks the turn from ending,
# and every real project has some drift, so such a hook blocks every turn. Drift is
# caught by the pre-commit gate and by running the check by hand.
# The three shared-checkout guards on the Claude Code side — live-child, executor, spawn —
# are not wired: Claude Code gets guidance, not rules (design.md → "Claude Code: guidance,
# not guards"). The scripts and their tests stay, their dsh halves stay armed, and a
# machine that installed them loses the rows on its next `init --harness`.
# Removal is announced like any other change and honours --dry-run.
RETIRED_HOOKS = ("guard_root_code.py", "maestro docs check",
                 "guard_live_child.py", "guard_executor.py", "guard_spawn.py")


def wire_hooks(settings, specs, plan, retired=RETIRED_HOOKS):
    """Add each (event, matcher, command, timeout, label) hook to `settings`, once, and
    remove any row that names a RETIRED hook script.

    One read and at most one write, so a mode wiring several hooks does not rewrite the
    file per hook. A file that is not valid JSON is left untouched and the commands are
    printed for the reader to add by hand — the same bargain the old bash struck, since
    silently rewriting somebody's settings is the one unrecoverable move here.
    """
    settings = Path(settings)
    data, ok = read_settings(settings)
    if not ok:
        plan.warn(f"{settings} is not valid JSON — leaving it untouched.")
        for event, matcher, command, _timeout, _label in specs:
            where = f"matcher '{matcher}'" if matcher else "no matcher"
            plan.warn(f"add this {event} hook by hand ({where}): {command}")
        return

    dirty = False
    for event, entries in list((data.get("hooks") or {}).items()):
        for entry in list(entries):
            rows = entry.get("hooks") or []
            kept = [h for h in rows
                    if not any(name in str(h.get("command", "")) for name in retired)]
            if len(kept) != len(rows):
                for name in retired:
                    if any(name in str(h.get("command", "")) for h in rows):
                        plan.change(f"remove the retired {name} {event} hook from {settings}")
                entry["hooks"] = kept
                dirty = True
            if not entry.get("hooks"):
                entries.remove(entry)
        if not entries:
            data["hooks"].pop(event, None)

    for event, matcher, command, timeout, label in specs:
        entry = _entry_for(data.setdefault("hooks", {}).setdefault(event, []), matcher)
        if any(h.get("command") == command for h in entry["hooks"]):
            plan.keep(f"{label} hook already wired")
            continue
        entry["hooks"].append({"type": "command", "command": command, "timeout": timeout})
        plan.change(f"wire the {label} {event} hook into {settings}: {command}")
        dirty = True

    if dirty and not plan.dry_run:
        if not data.get("hooks"):
            data.pop("hooks", None)
        if not data:
            # Nothing left but the row that was retired: no file beats an empty one.
            settings.unlink()
            return
        settings.parent.mkdir(parents=True, exist_ok=True)
        with open(settings, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")


def _is_tracked(project, relpath):
    """True when git already tracks anything under `relpath` in `project`."""
    try:
        out = subprocess.run(
            ["git", "-C", str(project), "ls-files", "--error-unmatch", "--", relpath.rstrip("/")],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


# ── git excludes ──────────────────────────────────────────────────────────────

def wire_excludes(project, plan):
    exclude = project / ".git" / "info" / "exclude"
    if not (project / ".git").is_dir():
        plan.keep("no .git directory — skipping .git/info/exclude")
        return
    present = set()
    if exclude.exists():
        present = {line.strip() for line in exclude.read_text().splitlines()}
    missing = [p for p in EXCLUDE_PATHS if p not in present]
    # Never exclude something the project already TRACKS. docs/ tracking is a
    # per-project choice (ADR 2) and maestro's own repo opts in — excluding it
    # there would hide every future docs change from git status.
    tracked = [p for p in missing if _is_tracked(project, p)]
    for path in tracked:
        plan.keep(f"{path} is tracked in git — not excluding it")
    missing = [p for p in missing if p not in tracked]
    if not missing:
        plan.keep(".git/info/exclude already covers the untracked shared memory")
        return
    for path in missing:
        plan.change(f"add {path} to .git/info/exclude")
    if not plan.dry_run:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with open(exclude, "a") as fh:
            for path in missing:
                fh.write(path + "\n")


# ── the commit-time guard ─────────────────────────────────────────────────────

def hook_version(text):
    """The `# maestro pre-commit vN` version in a hook's text, or None when it is not
    maestro's hook. Anything without the marker is somebody else's file."""
    found = PRE_COMMIT_MARK_RE.search(text or "")
    return int(found.group(1)) if found else None


def _hooks_path_override(project):
    """The repo's `core.hooksPath`, or None. Set means git ignores .git/hooks entirely."""
    try:
        out = subprocess.run(["git", "-C", str(project), "config", "--get", "core.hooksPath"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    if not value:
        return None
    # A hooksPath that merely names the default directory is not an override: git
    # would read .git/hooks either way, so the hook belongs there.
    configured = Path(value) if os.path.isabs(value) else Path(project) / value
    try:
        if configured.resolve() == (Path(project) / ".git" / "hooks").resolve():
            return None
    except OSError:
        pass
    return value


def wire_pre_commit(project, templates, plan):
    """Install templates/pre-commit as <project>/.git/hooks/pre-commit.

    Four states, one line each: `installed (vN)`, `outdated (vM < vN)` (replaced),
    `foreign hook present` (never touched — the line says what to append), and
    `not a git repo` (skipped). A repo with `core.hooksPath` set is skipped too: git
    reads hooks from that directory instead, and it is usually shared across repos or
    owned by another tool (husky, pre-commit), so writing into it is not init's call.
    """
    if not (project / ".git").is_dir():
        plan.keep("pre-commit hook: not a git repo — skipped")
        return
    if templates is None:
        plan.keep("pre-commit hook: no maestro checkout found — skipping "
                  "(pass --repo=<maestro checkout>)")
        return
    source = templates / "templates" / PRE_COMMIT_TEMPLATE
    if not source.is_file():
        plan.warn(f"pre-commit hook: {source} is missing from the checkout — skipped")
        return
    ours = hook_version(source.read_text(errors="ignore"))

    override = _hooks_path_override(project)
    if override:
        plan.keep(f"pre-commit hook: core.hooksPath = {override} — not installed; "
                  f"copy {source} there yourself if that directory is this repo's")
        return

    target = project / ".git" / "hooks" / PRE_COMMIT_HOOK
    if target.exists():
        theirs = hook_version(target.read_text(errors="ignore"))
        if theirs is None:
            plan.warn(f"pre-commit hook: foreign hook present at {target} — not installed; "
                      f"append the three guards from {source} to it by hand")
            return
        if theirs >= ours:
            plan.keep(f"pre-commit hook: installed (v{theirs})")
            return
        plan.change(f"replace the pre-commit hook: outdated (v{theirs} < v{ours}) "
                    f"→ .git/hooks/{PRE_COMMIT_HOOK}")
    else:
        plan.change(f"install the pre-commit hook (v{ours}) → .git/hooks/{PRE_COMMIT_HOOK}: "
                    "record stamp and staged-docs drift check on every branch, and only "
                    "docs/ committed directly on main")
    if plan.dry_run:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    os.chmod(target, 0o755)


# ── the tracker switch ────────────────────────────────────────────────────────

def read_tracker(text):
    """The `[tool.maestro] tracker` value in a pyproject.toml, or None when absent."""
    return _locate_tracker(text.splitlines())[2]


def _locate_tracker(lines):
    """(table_header_index, key_index, value) for [tool.maestro] tracker.

    Any of the three is None when that part is absent. Line-based rather than a TOML
    round-trip on purpose: rewriting the file through a parser would reformat and strip
    the comments of a table maestro does not own.
    """
    header = key = value = None
    in_table = False
    for i, line in enumerate(lines):
        table = _TABLE_RE.match(line)
        if table:
            in_table = table.group(1).replace(" ", "") == "tool.maestro"
            if in_table and header is None:
                header = i
            continue
        if in_table and key is None:
            found = _TRACKER_RE.match(line)
            if found:
                key, value = i, found.group("value")
    return header, key, value


def maestro_dep_spec(source=None, version=None):
    """The requirement a project declares to import `maestro.tracking`.

    Pinned to this CLI's version by default, so the project records WHICH maestro its
    runs were logged by. `source` replaces the location: a URL is taken as given, a
    filesystem path becomes a file:// URL because PEP 508 has no bare-path form.
    """
    from . import __version__
    if source:
        src = str(source)
        if "://" not in src:
            src = Path(src).expanduser().resolve().as_uri()
        return f"{DEP_EXTRA} @ {src}"
    return f"{DEP_EXTRA} @ git+{MAESTRO_REPO_URL}@v{version or __version__}"


def write_tracker(text, value):
    """`text` with [tool.maestro] tracker set to `value`, touching nothing else.

    The key is rewritten in place when it exists, added under an existing
    [tool.maestro] when the table is there, and otherwise appended as a new table at
    the end. Neighbouring keys, comments and any other table are left byte-identical.
    """
    trailing_newline = text.endswith("\n") or not text
    lines = text.splitlines()
    header, key, current = _locate_tracker(lines)

    if key is not None:
        if current == value:
            return text
        found = _TRACKER_RE.match(lines[key])
        q = found.group("q")
        lines[key] = f"{found.group('lead')}{q}{value}{q}{found.group('tail')}"
    elif header is not None:
        lines.insert(header + 1, f'tracker = "{value}"')
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["[tool.maestro]", f'tracker = "{value}"']

    out = "\n".join(lines)
    return out + "\n" if trailing_newline else out


UV_ADD_TIMEOUT = 300        # seconds; a resolve that outruns this is not init's problem


def is_uv_project(project):
    """True when uv manages this project's environment (modules/python_env.md)."""
    return (project / "uv.lock").is_file() or (project / ".venv").is_dir()


def _uv_add(project, spec):
    """Run `uv add <spec>`. Returns (ok, message) — never raises, never blocks forever."""
    if shutil.which("uv") is None:
        return False, "uv is not on PATH"
    try:
        done = subprocess.run(["uv", "add", spec], cwd=str(project), timeout=UV_ADD_TIMEOUT,
                              capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return False, f"uv add timed out after {UV_ADD_TIMEOUT}s"
    except OSError as exc:
        return False, str(exc)
    if done.returncode == 0:
        return True, ""
    tail = (done.stderr or done.stdout or "").strip().splitlines()
    return False, (tail[-1] if tail else f"uv add exited {done.returncode}")


def wire_maestro_dep(project, plan, source=None):
    """Put the tracking library in the project that just turned tracking on.

    `uv add` where uv manages the project: it edits pyproject, resolves, locks and
    installs in one call, and it is idempotent. Nothing here parses or rewrites TOML —
    a dependency array is the package manager's file format, and a second
    implementation of it would only be a worse one.

    Everywhere else (conda projects are first-class in modules/python_env.md and have
    no equivalent one-shot command) the requirement is printed for a person to add.
    """
    spec = maestro_dep_spec(source)

    if not is_uv_project(project):
        plan.keep(f'not a uv project — add the requirement yourself: "{spec}"')
        return
    if plan.dry_run:
        plan.change(f'uv add "{spec}"')
        return

    ok, why = _uv_add(project, spec)
    if ok:
        plan.change(f'uv add "{spec}" — declared, locked and installed')
        return
    # Not fatal: the reason is usually one only a person can clear (a repo still
    # private, a release tag not pushed), and tracking simply stays unimportable.
    plan.warn(f'uv add failed ({why}) — run it yourself once that is resolved: '
              f'uv add "{spec}"')


def wire_tracker(project, choice, plan, dep_source=None):
    """Set (or leave) the project's `[tool.maestro] tracker`.

    With `--tracker=` the choice wins. Without it the existing value is left alone and
    "none" is only written when the key is absent, so re-adopting a project never
    silently turns its tracking off. A project with no pyproject.toml at all is left
    without one unless the flag asked for a tracker — ADR 10's point is that maestro
    does not force Python packaging into a Rust or JS repo.
    """
    if choice is not None and choice not in TRACKERS:
        raise InitError(f"--tracker must be one of {', '.join(TRACKERS)}, got {choice!r}.")

    path = project / PYPROJECT
    text = path.read_text() if path.is_file() else None
    current = read_tracker(text) if text is not None else None

    if text is None and choice is None:
        plan.keep(f'no {PYPROJECT} — tracker stays "{TRACKER_DEFAULT}" (the default)')
        return
    if current is not None and current not in TRACKERS:
        plan.warn(f'{PYPROJECT} [tool.maestro] tracker = "{current}" is not one of '
                  f'{", ".join(TRACKERS)} — leaving it for you to fix')
        return

    value = choice if choice is not None else TRACKER_DEFAULT
    switched = False
    if current == value:
        plan.keep(f'[tool.maestro] tracker = "{current}" in {PYPROJECT} — kept'
                  + ("" if choice is not None else " (--tracker= changes it)"))
    elif current is not None and choice is None:
        plan.keep(f'[tool.maestro] tracker = "{current}" in {PYPROJECT} — kept '
                  "(--tracker= changes it)")
        value = current
    else:
        was = f'"{current}"' if current is not None else "absent"
        plan.change(f'set [tool.maestro] tracker = "{value}" in {PYPROJECT} (was {was})')
        switched = True
        if not plan.dry_run:
            path.write_text(write_tracker(text or "", value))

    if value == TRACKER_DEFAULT:
        plan.keep("tracking is off: metrics stay machine-written artifacts in "
                  "data/experiments/exp_NN_*/ (metrics.json, run.log)")
        return
    plan.keep(f"{value} endpoint and credentials come from the environment, "
              "never from a file in the repo")
    # Only when tracking was just turned on, or --tracker/--dep-source asked for it.
    # `uv add` is idempotent but it resolves over the network, and re-adopting a
    # project should not pay for that every time.
    if switched or choice is not None or dep_source is not None:
        wire_maestro_dep(project, plan, dep_source)
    else:
        plan.keep("maestro[tracking] left as the project declares it "
                  "(--tracker= or --dep-source= re-runs `uv add`)")


# ── the migration off copied tools ────────────────────────────────────────────

def wire_declaration(project, plan, layers=None, shape=None):
    """maestro.toml — the membership switch (design.md → "Shape declaration"). Written
    once; an existing declaration is never rewritten, since its shape history is
    appended by `maestro shape add` and never edited."""
    from . import declaration
    path = project / declaration.DECLARATION_FILE
    if path.exists():
        plan.keep(f"{declaration.DECLARATION_FILE} exists — kept (a layout change is "
                  "`maestro shape add`, never an edit)")
        return
    layers = tuple(layers) if layers else declaration.LAYERS
    bad = [l for l in layers if l not in declaration.LAYERS]
    if bad or "discipline" not in layers:
        raise InitError(f"--layers must name discipline and optionally research, got {list(layers)}")
    shape = shape or "tiers"
    if shape not in declaration.SHAPES:
        raise InitError(f"--shape must be one of {list(declaration.SHAPES)}, got {shape!r}")
    plan.change(f"create {declaration.DECLARATION_FILE} (layers {', '.join(layers)}; "
                f"shape {shape} since today)")
    if not plan.dry_run:
        path.write_text(declaration.render(layers, shape))



def is_maestro_checkout(project):
    """True when `project` is the maestro source repo rather than a project using it.

    In the source checkout tools/maestro_cli/ is the product, not a copy, and the
    ADR 10 migration must never touch it.
    """
    pyproject = project / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        text = pyproject.read_text(errors="ignore")
    except OSError:
        return False
    return 'name = "maestro"' in text and (project / "tools" / "maestro_cli" / "cli.py").is_file()


def drop_copied_tools(project, plan):
    """Delete anything the pre-ADR-10 install model copied into <project>/tools/."""
    if is_maestro_checkout(project):
        plan.keep("this is the maestro checkout — tools/maestro_cli/ is the source, not a copy")
        return
    tools = project / "tools"
    found = False
    for name in STALE_TOOLS:
        target = tools / name
        if target.exists() or target.is_symlink():
            found = True
            _remove(target, plan, f"copied tools/{name}" + ("/" if target.is_dir() else ""))
    hook = project / V1_GIT_HOOK
    try:
        stale_hook = hook.is_file() and V1_GIT_HOOK_MARK in hook.read_text(errors="ignore")
    except OSError:
        stale_hook = False
    if stale_hook:
        found = True
        _remove(hook, plan, f"v1 worktree-symlink hook {V1_GIT_HOOK}")
    if not found:
        plan.keep("no copied tools left behind")


# ── project mode ──────────────────────────────────────────────────────────────

def seed_indexes(project, plan):
    """Render the four INDEX.md files empty, so a new project cites nothing dead.

    CLAUDE.md points a cold session at these before anything else, and `docs check`
    counts the citation as a dead path until the file exists — which is why a project
    used to fail the framework's own drift check the moment it was created. An empty
    table is also a better answer to "what has been recorded" than a missing file.

    The index module resolves its directories from the ROOT it found at import, and
    `init --path=` can target any tree, so they are pointed at THIS project for the
    call and put back afterwards.
    """
    from contextlib import redirect_stdout
    from io import StringIO
    from . import indexes

    rendered = ["docs/experiments/INDEX.md", "docs/adrs/INDEX.md",
                "docs/epics/INDEX.md", "docs/data/INDEX.md", "docs/kb/literature/INDEX.md"]
    missing = [rel for rel in rendered if not (project / rel).exists()]
    if not missing:
        plan.keep("indexes already rendered")
        return
    if plan.dry_run:
        for rel in missing:
            plan.change(f"render {rel}")
        return

    docs = project / "docs"
    targets = {"ROOT": project, "EXP_DIR": docs / "experiments", "ADR_DIR": docs / "adrs",
               "EPIC_DIR": docs / "epics", "DATA_DIR": docs / "data",
               "KB_DIR": docs / "kb" / "literature"}
    saved = {k: getattr(indexes, k) for k in targets if hasattr(indexes, k)}
    try:
        for key, value in targets.items():
            if hasattr(indexes, key):
                setattr(indexes, key, value)
        with redirect_stdout(StringIO()):        # its own tally is noise inside init's
            indexes.render("all")
    finally:
        for key, value in saved.items():
            setattr(indexes, key, value)

    for rel in missing:
        if (project / rel).exists():
            plan.change(f"rendered {rel}")


def init_project(path=None, repo=None, dry_run=False, force=False, tracker=None,
                 dep_source=None, layers=None, shape=None):
    project = Path(path or Path.cwd()).expanduser().resolve()
    if not project.is_dir():
        raise InitError(f"Project path not found: {project}")
    templates = repo_dir(repo)
    plan = Plan(dry_run=dry_run, force=force)

    print(f"Project init → {project}")
    plan.section("Layout:")
    for rel in SCAFFOLD_DIRS:
        _mkdir(project / rel, plan, rel + "/")

    plan.section("Starter documents:")
    if templates is None:
        plan.keep("no maestro checkout found — skipping (pass --repo=<maestro checkout>)")
    else:
        for name, rel in SEED_FILES:
            _copy(templates / "templates" / name, project / rel, plan, rel, f"templates/{name}")

    plan.section("Declaration (maestro.toml — membership, rule layers, shape history):")
    wire_declaration(project, plan, layers, shape)
    plan.section("Generated indexes:")
    seed_indexes(project, plan)

    plan.section("Retired hooks:")
    wire_hooks(project / ".claude" / "settings.json", [], plan)

    plan.section("Git excludes:")
    wire_excludes(project, plan)

    plan.section("Commit-time guard:")
    wire_pre_commit(project, templates, plan)

    plan.section("Experiment tracker:")
    wire_tracker(project, tracker, plan, dep_source)

    plan.section("Copied tools (ADR 10 — the CLI is machine-level):")
    drop_copied_tools(project, plan)

    plan.print()
    return plan


# ── harness mode ──────────────────────────────────────────────────────────────

def init_harness(repo=None, home=None, dry_run=False, force=False):
    checkout = repo_dir(repo)
    if checkout is None:
        raise InitError("No maestro checkout found. Harness mode wires the hooks that "
                        "live in the repo, so point at it: "
                        "maestro init --harness --repo=<path to the maestro checkout>")
    home = Path(home or os.environ.get("HOME") or Path.home()).expanduser().resolve()
    plan = Plan(dry_run=dry_run, force=force)

    print(f"Harness init → {home}/.claude   (maestro checkout: {checkout})")
    plan.section("Global hooks:")
    hooks = checkout / "global" / "hooks"
    # These rows are the Claude Code guard set. The dsh set is not mirrored here: the two
    # harnesses are NOT mirrors. Claude Code gets guidance on how to DOCUMENT, not rules on
    # how to run git: only the
    # record-surface guards and the machine's gh rule are wired here. How code and git
    # work is organised — worktrees, parallel agents, merges — is the session's call; the
    # shared-checkout guards (live children, executors, spawn) run under dsh only.
    wire_hooks(home / ".claude" / "settings.json", [
        ("PreToolUse", MATCHER, f"python3 {hooks / 'guard_records.py'}", 5, "record-guard"),
        ("PostToolUse", STAMP_MATCHER, f"python3 {hooks / 'guard_stamps.py'}", 10, "stamp-guard"),
        ("PostToolUse", MATCHER, f"python3 {hooks / 'regen_kb_index.py'}", 10, "kb-index-regen"),
        # Claude Code only: gh with a per-project token, never a
        # global login — a machine rule, not a record rule, so no dsh half.
        ("PreToolUse", SHELL_MATCHER, f"python3 {hooks / 'guard_gh_auth.py'}", 5, "gh-auth-guard"),
    ], plan)

    plan.print()
    return plan


# ── verb ──────────────────────────────────────────────────────────────────────

def init(args):
    common = dict(repo=getattr(args, "repo", None),
                  dry_run=getattr(args, "dry_run", False),
                  force=getattr(args, "force", False))
    if getattr(args, "harness", False):
        if getattr(args, "path", None):
            raise InitError("--path is a project-mode flag; --harness targets the machine.")
        if getattr(args, "tracker", None) is not None:
            raise InitError("--tracker is a project-mode flag; --harness targets the machine.")
        if getattr(args, "dep_source", None) is not None:
            raise InitError("--dep-source is a project-mode flag; --harness targets the machine.")
        for flag in ("layers", "shape"):
            if getattr(args, flag, None) is not None:
                raise InitError(f"--{flag} is a project-mode flag; --harness targets the machine.")
        init_harness(home=getattr(args, "home", None), **common)
    else:
        layers = getattr(args, "layers", None)
        init_project(path=getattr(args, "path", None),
                     tracker=getattr(args, "tracker", None),
                     dep_source=getattr(args, "dep_source", None),
                     layers=[l.strip() for l in layers.split(",") if l.strip()] if layers else None,
                     shape=getattr(args, "shape", None), **common)
