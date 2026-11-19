"""maestro — one CLI for a project's records, indexes, checks and kb search.

Surface (ADR 8): `maestro <group> <verb> --flag=value`. Every argument is a named
flag; there are no positionals. Parsing and dispatch live in `cli.py`, one module
per record kind beside it.
"""

__version__ = "2.48.0"
