# Durable-Code Hygiene (src/ and scripts/)

Load when writing or refactoring durable code — `src/` and `scripts/`. One-off
`experiments/` stay simple per rule 3; over-applying these to throwaway scripts is
itself a smell. SOLID/DRY/KISS are assumed; what matters is the checkable habit:

- **One responsibility per module.** Don't spin up a module for a handful of lines
  unless it owns a distinct concern likely to grow; don't pile unrelated concerns into
  one file either. Justify a new module by its responsibility, not line count.
- **A refactor is behavior-preserving until proven.** Before claiming one done, verify
  against an existing test or a numeric reproduction (re-run, identical output).
  Structural change without an oracle is a guess, not a refactor.
- **Extract once, replace everywhere.** When promoting shared logic, grep for every
  copy and delete the originals. Duplicated logic that must be edited in two places is
  the bug DRY prevents.
- **No cross-boundary private access.** Don't call `_private` members from another
  module or a script; promote to a public function in its proper home instead.
- **One home per name; import it from there.** No re-export "convenience surfaces" —
  callers import each symbol from its owning module.
- **A move is a cut, never a fallback.** When a config, file, name or API moves, the
  old one is deleted in the same change and every caller is repointed. No read-old-if-
  new-is-missing path, no deprecation shim, no transition period, no compat symlink:
  each one is a second source of truth that outlives its reason.
- **A script holds its own one-off logic; shared logic goes down a tier.** No line cap and no
  "argparse plus one call" rule: forcing script bodies into `src/` made the composition
  root (the top tier, which the layer linter lets import anything) the dumping ground for
  them. Code moves to `src/<tier>/` only when a second caller needs it, into the tier that
  owns the responsibility. The composition root holds only the process mains that run
  unattended; analysis reads and measurements never live there.
