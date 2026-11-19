"""`maestro info show` — print the project layout and maestro conventions.

Single source of truth for a maestro project's directory layout. Anything that wants
to know "where do experiments live?" prints this instead of hardcoding paths: the
layout changes in frontmatter.py's constants and every consumer follows.
"""
from . import declaration
from .frontmatter import ADR_DIR, DATA_DIR, EXP_DIR, FINDINGS, KB_LIT_DIR, ROOT, rel


def info(_args=None):
    try:
        decl_lines = declaration.describe(declaration.load(ROOT))
    except declaration.DeclarationError as exc:
        decl_lines = [f"  UNREADABLE — {exc}"]
    try:
        kb_raw = str(declaration.kb_raw_dir(ROOT))
    except declaration.DeclarationError as exc:
        kb_raw = f"UNREADABLE — {exc}"
    lines = [
        f"maestro project at {ROOT}",
        "",
        "Declaration (maestro.toml — membership, rule layers, the dated shape history):",
        *decl_lines,
        "",
        "Records (all written via the maestro CLI — never hand-author the files):",
        f"  experiments → {rel(EXP_DIR)}/   (maestro exp new --slug=<slug> / exp update / exp revise)",
        f"  ADRs        → {rel(ADR_DIR)}/   (maestro adr new --slug=<slug> / adr update)",
        f"  datasets    → {rel(DATA_DIR)}/   (maestro dataset new --name=<name>; sha computed, body hand-edited)",
        f"  findings    → {rel(FINDINGS)}   (maestro exp finding --id=<N> --text=\"...\"; hand-editing is fine)",
        f"  kb raw      → {kb_raw}   (downloaded sources of the literature protocol; `kb_raw` in maestro.toml)",
        "",
        "Indexes (recall tier — load on session start; GENERATED, never hand-edit):",
        f"  {rel(EXP_DIR / 'INDEX.md')}",
        f"  {rel(ADR_DIR / 'INDEX.md')}",
        f"  {rel(DATA_DIR / 'INDEX.md')}",
        f"  {rel(KB_LIT_DIR / 'INDEX.md')}",
        "",
        "Machine-level wiring (`maestro init --harness`, once per machine):",
        "  ~/.claude/settings.json  PreToolUse  guard_records.py  blocks a direct",
        "                           edit of a record file, which is what makes",
        "                           'records only via the CLI' hold",
        "                           PostToolUse regen_kb_index.py rebuilds the kb index",
        "",
        "Search and read-back are CLI verbs, not slash commands:",
        '  maestro kb search --query="..."   semantic search over docs/kb/literature/',
        "  maestro runs fetch --exp=<N>      a tracked run's metrics, read back not retyped",
        "",
        "Somewhere to put an idea you do not want to forget:",
        '  maestro option --add="..."                 belongs to no epic yet → parked,',
        "                                             dated, in progress.md ## Up next",
        '  maestro epic option --id=<N> --add="..."   belongs to that goal',
        "",
        "Rules:",
        "  - NEVER hand-author exp_*.md / adr_*.md / INDEX.md, nor hand-CREATE a",
        "    docs/data/<name>.md. Use the maestro CLI; a PreToolUse hook blocks",
        "    Write/Edit on them.",
        "  - Every argument is a named flag: maestro <group> <verb> --flag=value.",
        "    Quote any value that contains spaces.",
        "  - Treat INDEX.md takeaways as summaries — re-read source artifacts in",
        "    data/experiments/exp_NN_*/ before propagating any conclusion.",
        "  - An epic states its closing condition in `done_when` (maestro epic",
        "    done-when --add=\"...\" --check=\"...\"), and `epic close` refuses until",
        "    every clause carries the result it MEASURED (--clause=<k> --result=...).",
        "    A condition, never a task: it can still be false after every item is done.",
        "  - Use outcome='infra' for infrastructure runs (fleet tests, smoke tests,",
        "    benchmarks of the platform itself).",
        "  - Metrics are read back from a machine-written store at write-up, never",
        "    hand-typed: the tracker if pyproject [tool.maestro] names one (default",
        "    'none'), else metrics.json / run.log in data/experiments/exp_NN_*/.",
        "    Datasets: maestro dataset new computes the sha; `maestro dataset verify`",
        "    checks drift.",
        "",
        "Write-up protocol: <maestro>/protocols/record_writeup.md",
        "Reference:         <maestro>/design.md",
    ]
    print("\n".join(lines))
