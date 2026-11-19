"""Two git states the record checks must not mistake for a breach.

MERGE RESOLUTION IS NOT A HAND EDIT. While a merge is in progress (MERGE_HEAD exists), a
record whose CLI-owned surface — frontmatter, and an epic's `## Log` — is byte-identical
to that surface in one side of the merge (HEAD, or a MERGE_HEAD commit) was TAKEN from a
side, not written by hand now. Resolving a conflict by picking a side is what a merge is;
the stamp guard, the stamp check and the pre-write record guard used to refuse it,
because the picked side's stamp can disagree with the merged file. A surface that matches neither
side is still judged as before.

A WORKTREE WITHOUT THE IGNORED DIRS IS NOT DRIFT. `data/` and its kin are gitignored, so
a linked worktree (`git worktree add`, an isolated agent's checkout) starts without them.
A record citing `data/experiments/.../metrics.json` then looks like lost evidence, and
`docs check` blocked on it although the file sits in the main checkout. A missing path
that git ignores, in a linked worktree, is resolved against the main checkout: present
there → a warning, not drift. Missing there too → the evidence really is gone, and the
check keeps its verdict. Outside a linked worktree nothing changes: a missing ignored
artifact in the main checkout is the rule-2 failure itself.

A NUMBER TAKEN ON ANOTHER BRANCH IS TAKEN. Parallel sessions — two worktrees, or a
worktree and the main checkout — each see only their own `docs/`, so both handed out the
same record number, and one of them had to be renumbered. `taken_elsewhere` reads the numbers every
local branch commits and every other worktree holds on disk, so `next_num` steps past them.

Every function here fails quiet: no git, no repo, a git error — the caller's original
verdict stands.
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path


def _git(cwd, *args) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                              timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


# ── merge resolution ─────────────────────────────────────────────────────────

def merge_heads(cwd) -> list[str]:
    """The MERGE_HEAD commits of the merge in progress at `cwd`, or [] when none is."""
    r = _git(cwd, "rev-parse", "--git-path", "MERGE_HEAD")
    if r is None or r.returncode != 0:
        return []
    p = Path(r.stdout.strip())
    if not p.is_absolute():
        p = Path(cwd) / p
    try:
        return [ln.strip() for ln in p.read_text().splitlines() if ln.strip()]
    except OSError:
        return []


def side_texts(path, heads=None) -> list[str]:
    """The file's text in HEAD and in each MERGE_HEAD commit (the sides that have it)."""
    path = Path(path)
    heads = merge_heads(path.parent) if heads is None else heads
    if not heads:
        return []
    out = []
    for rev in ("HEAD", *heads):
        r = _git(path.parent, "show", f"{rev}:./{path.name}")
        if r is not None and r.returncode == 0:
            out.append(r.stdout)
    return out


def taken_from_a_side(path, text: str, owned) -> bool:
    """During a merge: is `text`'s CLI-owned surface (as `owned(text)` extracts it) the same
    as one side's? False outside a merge, or when no side has the file."""
    mine = owned(text)
    return any(owned(side) == mine for side in side_texts(path))


# ── the linked worktree ──────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def main_checkout(root: str) -> Path | None:
    """The main worktree's root when `root` is a LINKED worktree, else None."""
    r = _git(root, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")
    if r is None or r.returncode != 0:
        return None
    lines = r.stdout.split()
    if len(lines) != 2 or Path(lines[0]) == Path(lines[1]):
        return None                      # the main checkout itself (or a bare repo)
    common = Path(lines[1])
    return common.parent if common.name == ".git" else None


def ignored(root, rel: str) -> bool:
    r = _git(root, "check-ignore", "-q", "--", rel)
    return r is not None and r.returncode == 0


def worktree_absence(root, rel: str) -> str | None:
    """Why a missing `rel` is not drift here, or None when its absence stands as found.

    A reason is returned only for a path git ignores, in a linked worktree, that exists
    in the main checkout.
    """
    main = main_checkout(str(Path(root).resolve()))
    if main is None or not ignored(root, rel):
        return None
    if not (main / rel).exists():
        return None
    return (f"`{rel}` is gitignored and absent from this linked worktree, but present in "
            f"the main checkout ({main}) — not drift; check it there.")


# ── record numbers held elsewhere ────────────────────────────────────────────

def taken_elsewhere(directory, kind: str) -> set[int]:
    """Numbers of `kind_NN_*.md` records under `directory` as every local branch commits it
    and as every other worktree of this repository holds it on disk (uncommitted included).

    Empty when `directory` is not inside a git work tree or git cannot answer.
    """
    directory = Path(directory)
    probe = directory if directory.is_dir() else directory.parent
    top = _git(probe, "rev-parse", "--show-toplevel")
    if top is None or top.returncode != 0:
        return set()
    root = Path(top.stdout.strip())
    try:
        rel = directory.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return set()
    name_re = re.compile(rf"^{re.escape(kind)}_(\d+)")
    nums: set[int] = set()

    def add(name: str) -> None:
        m = name_re.match(Path(name).name)
        if m:
            nums.add(int(m.group(1)))

    refs = _git(root, "for-each-ref", "--format=%(refname)", "refs/heads")
    for ref in (refs.stdout.split() if refs is not None and refs.returncode == 0 else []):
        r = _git(root, "ls-tree", "--name-only", ref, "--", f"{rel}/")
        if r is not None and r.returncode == 0:
            for line in r.stdout.splitlines():
                add(line)

    wt = _git(root, "worktree", "list", "--porcelain")
    for line in (wt.stdout.splitlines() if wt is not None and wt.returncode == 0 else []):
        if not line.startswith("worktree "):
            continue
        other = Path(line[len("worktree "):])
        if other.resolve() == root.resolve():
            continue
        for p in (other / rel).glob(f"{kind}_*.md"):
            add(p.name)
    return nums
