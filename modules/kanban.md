# Module: Kanban (epics — work that spans many sessions)

Load when opening, updating, or closing an `epic`, or when a body of engineering work is
too large for one session and has no experiment to hang it on. A single session's work
needs none of this: it is a branch and a commit.

**Why the kind exists.** `exp` records a hypothesis, `adr` a decision, `data` a dataset.
Multi-session engineering work had no home, so projects improvised one inside
`progress.md` — which is how that file blows its 200-line cap (rule 10) and how status
claims end up written once and never re-checked.

## Vocabulary — Kanban mechanics, Jira names

```
epic  ── a standing goal, many sessions          → docs/epics/epic_NN_<slug>.md
 ├─ option ── candidate work, NOT committed      → a line in the epic's `options:` list
 │            (`maestro epic option --add`; pull one to commit)
 └─ item ── one session ~= one branch ~= one PR  → a row in the epic's frontmatter
            (written by `maestro epic item --add/--item`, never by hand)
     └─ task ── the individual edits             → commits; NOT recorded anywhere else
```

**These three words are the only words.** Epic, item, task — at every level, in every
plan, brief, log line, subagent prompt and report. "Door", "unit", "work unit",
"wave", "slice", "work order", "lane", "row" standing in for one of the three is drift:
the moment a plan says "8 units" for what the board calls "6 items", nothing can compare
the two, and the count that is not on the board is the count that gets lost. A task lives in commits, or in the project's own task-level record (a
conformance table, a test list) — never as a list inside an item title. An item title
that holds a list is N tasks wearing one item (check K11).

**Options exist at two levels.** Under an epic (`maestro epic option --id=<N> --add`) for
candidate work that clearly belongs to that goal; and at the project (`maestro option
--add`) for an idea that belongs to no epic yet, parked in `progress.md` `## Up next`.
The second is a capture slot, and it is what makes the WIP limit survivable: an idea
arriving mid-session has exactly one cheap thing you can do with it, so the limit produces
focus rather than a context switch or amnesia. The CLI stamps the date — the one property
an option is otherwise denied — because the executor cannot feel time pass, and an idea
from June should not read like one from this morning. Project options carry no log
line: `progress.md` is the live plan, not a record, and an idea worth a trace is worth an
epic.

**The commitment point sits between option and item.** An option has no status, no owner
and no age — that is the whole of its definition. Everything below it is work being done
and reports as such. Collapsing the two is what turns a `todo` queue into a swamp: a list
that grows without limit, where every line carries a status word nobody re-checks, and the
list starts being cited as if it were a record. Pulling an option
(`maestro epic option --pull=<n>`) is the act of committing, and it is written to the log.

**An item title states its DONE-TEST and its SCOPE, and the CLI refuses one that does
not.** `maestro epic item --add` requires two markers in the title: `Done:` (or
`Done-test:`) naming the command or artifact that ends the item, and `N files` / `N sites`
naming how wide it reaches. An idea that cannot yet state either is an OPTION, not an
item — that is what the intake is for. One real item read "port the
remaining read sites", was held by a single planner for many hours, and turned out to cover
255 files; nothing could refuse it, split it, or size the brief written from it, because
the title never said.

**The size rule judges SHAPE, not size.** Above `[items] max_files` in the project's
`maestro.toml` (default 40) an item must be a MECHANICAL pass — a compiler-driven sweep
the planner cuts into child units — and must declare it: `223 files in 9 units`. Without
that plan the title is refused. A DESIGN item is one seam, one decision, one judgement
call, and is never that wide: it is split off first and carries its own done-test. Wide
is not the problem; wide-and-undeclared, or wide-and-a-design-call, is.

**An item is not a question.** A title carrying `TBD`, "to be decided", "decide whether"
or "open question" is refused at any size: a question cannot be closed with evidence
(rule 2), and its answer arrives mid-session and re-scopes whatever was being built
around it. The decision is its own small item — an ADR, or a step-0 measurement — and
the work that depends on the answer is the item after it.

**No agent-lane guards run any more.** `maestro epic item --add` refuses a malformed item
in every harness — it is the CLI, and the record is the record. The root-code and
spawn-brief (`Files:` / `Done:`) guards were dsh plugins and were removed with them; dsh
now runs unguarded for simple jobs. The `[agents.dsh] root_writes_code` setting is inert.

**An epic holds one session's worth of committed work.** `epic item --add` and
`epic option --pull` refuse once the epic's OPEN items (todo or in_progress) reach
`[epics] max_open_items` (default 8), naming the split: a new epic, items moved with
`epic item --item=<k> --move-to=<N>`, `blocked_by` the first half. Done and dropped
items do not crowd — they are history, not queue.

**A moved item leaves its epic.** `--move-to=<N>` adds the row to epic N as todo (title
and blocked flag carried) and deletes it from the source; each log gets one line naming
the other side, so no count ever sees it again. A row already copied by hand is recorded
with `--moved-to="epic N item M"` (the pointer must resolve; allowed on a closed epic).
Only todo rows move; ids stay stable and a moved-out id is never reused. The WIP limit above governs what is being WORKED; this one governs
what has been COMMITTED, and without it an epic drifts back into the unlimited `todo`
queue the commitment point exists to prevent.

**The board line is an index entry.** `[board] max_title_chars` (700) caps a new item
title and `[board] max_note_chars` (500) caps `--note`, because the reasoning belongs in
the record body or an ADR.

**The strategic layer — prose in the README, no tooling.** The commitment point needs a
written criterion to pull against, or every session re-derives what "finished" means and
plans leak into whatever record is open (the shape goals-in-ADRs takes). So an ADR cites
its decision's evidence (exps, artifacts), never an epic, an item or the plan (check W1: blocking for text dated from its cutoff on, advisory before). That criterion is
prose, not a record kind: it lives in the project README, human-edited, no CLI behind it.
Three sections, sorted by how long a statement stays true:

```
README §Goals      years    what the project is FOR; can one day be done
       §Route     ~a year   ordered ARCS the next epics are drawn from — never
                            tasks; an arc is a GROUPING of epics, not an epic
                            itself — its work is drawn as epics when it starts
       §Non-goals  years    refused at the source, so scope creep is caught at
                            the option stage instead of argued epic by epic
```

**An arc is identified by its SLUG, never by its number.** The slug is short and
kebab-case (`decoupling`, `deep-refactor`, `skeleton`); the number is only the arc's place
in the list. Inserting an arc is therefore adding a row — nothing is renumbered, because
renumbering would break every citation in records that are never rewritten (rule 5). Epics
and ADRs cite the slug, in prose: the epic body's `**Arc**:` line. No frontmatter field, no
CLI — the strategic layer stays untooled. A project that numbered its arcs before this
keeps the old numbers as FROZEN legacy aliases in the route table, so old citations still
resolve; an alias is never reassigned and a new arc gets none.

```
order  slug           legacy alias  epics   status
1      decoupling     arc 0         5-9     closes with epic 9
2      deep-refactor  -             11-14   next
3      skeleton       arc 1         10
```

The discipline is also prose: an arc that revises a standing ADR goes through a new ADR
before work starts; editing §Goals or §Non-goals is a decision — name the ADR in the
commit; and the project's CLAUDE.md carries the rule-12 trigger ("opening an epic /
pulling an option → read §Goals + §Route"), because a doc named only in prose is loaded
by no harness. Enforcement is an occasional agent read-through, not a validator —
altitude is invisible to code.

NOT imported: sprints, story points, velocity, standups, burndown. An agent's capacity is
context window plus wall clock — it does not have a two-week rhythm, so no ceremony that
measures one belongs here. The same test retired a CLI realization of the strategic layer
(`docs/vision.md` + `epic new --serves` + board grouping) the day it shipped: at the two
or three goals a real project has, id machinery has nothing to grip.

## States and the blocked flag

**Epic statuses are `review | todo | active | done`.**
- `review` waits for a human; a session never picks it up and never starts it.
- `todo` is approved by a human and nobody is on it; any session (dsh or claude) may take it.
- `active` means a session is working on it NOW. A paused session is not active: whoever
  pauses or stops a session puts its epic back to `todo`.
- `done` is closed (`epic close`).

**Continuing a closed epic's area reopens it; never `epic new`.** Before `epic new`, read
`maestro epic list` including the done epics: work that extends one (its next iteration, a
second reader of the same source) goes back to it with `epic update --status=active` and
new items. A new epic only when no epic, open or closed, owns the area.

Two rules. A session runs `todo` and `active` epics to the end and never starts a `review`
epic; only a human moves `review` to `todo`. A session sets `active` (and `--runner=NAME`,
free text such as `dsh` or `claude`, never checked) when it starts an epic, and sets it back
to `todo` when it stops without finishing; the runner clears itself when the status leaves
`active`. Old records that say `in_progress` read as `active`; the CLI writes only the new
names.

ITEMS keep `todo | in_progress | done` and have one more: `dropped` — measured and
deliberately abandoned (its result fell below the bar).

**`dropped` is settled, not done.** `epic item --item=<k> --status=dropped --reason="..."`
refuses a bare drop the way `done` refuses bare evidence; the reason is stored on the row
and written to the epic's log. Only todo or in_progress rows drop. A done row is not
dropped directly and a dropped row leaves only by re-opening (`--status=todo`, which
takes the reason off the row; the log keeps it) — both moves pass through todo, so
evidence and reason are never swapped for each other. Close, `max_open_items` and the
checks count a dropped row as settled; `epic list` and `epic show` show it apart (`items 3/5 done,
1 dropped`). An epic has no `dropped` state: an abandoned epic still closes, and its
`--outcome` says why.

**`blocked_by` is a FLAG, not a state.** It can be set on anything in any state, and it
carries a reason. Never model blocking as a status: `status: blocked` destroys the
information about where the work actually stands, and that information is exactly what is
needed to unblock it. The board marks a flagged epic with ` · blocked` on its line.

**The board** (`docs/epics/INDEX.md`) is one view: with declared arcs, per arc a heading
`### <arc> — <status>` (active if any epic is active, else todo if any is todo, else review,
else done; `later` with no epics); without arcs, sections Active, Todo, Review, Done. One
line per epic: `epic N — <title up to the first ':'> · <status>[ · runner] · items d/t[ · N
options][ · blocked]`; done epics collapse to one `done:` line.

## The clock

Every item carries `since:` — the date it entered its current state — written by the CLI on
creation and re-stamped on every status change. A re-title does not re-stamp it: the wording
changed, the work did not.

**This exists because the executor cannot feel time pass.** It can read a clock whenever it
likes, and never notices that it should. A human team catches a stalled card in standup; an
agent between context windows has no equivalent, so ageing has to be written down by the
tool rather than remembered. `blocked_by` is dated the same way (`blocked_since:`), because
a flag nobody has cleared in a fortnight is not a flag, it is a decision waiting to be made.

The checks report both as advisories: an item `in_progress` beyond
`STALE_ITEM_DAYS` (7 — one item is one session), and a flag older than `STALE_BLOCK_DAYS`
(14). Neither blocks: a stalled item is a fact about the world, not a malformed record.

## The closing condition (`done_when`)

Every epic states, in frontmatter, the condition that ends it — and `close` REFUSES until
each clause carries the result it measured.

```
done_when:
  - id: 1
    text: 0 in-preset OPEN rows in the conformance log    <- a CONDITION
    check: python tools/ledger_summary.py --check            <- what answers it
    result: null                                             <- filled in at close
```

**Written at open, answered at close.** The clause is the contract; `result` is the reading
taken against it. They are deliberately two edits: a condition first written while closing
is not a condition, it is a description of whatever happened.

**A condition, never a task.** `OPEN rows: 36 -> 0` is a clause; `port the combat rules` is
an item. The test: a clause can still be FALSE after every item is done. That is the whole
point — it is the moment the epic has to say so rather than close anyway. Clauses written
as deliverables turn the board back into a task list with extra ceremony.

**`--outcome` names the capability; the clauses carry the numbers.** Closing text that
lists activity ("241 status words evidenced, 6 dead paths reworded") describes a session;
"the log can now be trusted without re-reading it" describes what the project can do
that it could not before. Only the second tells a reader arriving cold whether to build on
it. The clause results are the measurements underneath, so the outcome does not have to
carry them.

**It moved out of the body.** The template always asked for a `**Done when**` paragraph and
nothing ever read it — which is how an epic closes on an activity report while its own
condition sits three paragraphs above, unexamined. One home per claim: the frontmatter,
where the CLI can refuse.

Re-wording a clause leaves a revision trace in the log, the same contract `exp revise`,
`epic item --title` and `epic update --title` carry (rule 1). A closing condition quietly
reworded to match what happened proves nothing.

## WIP limits

- **One item `in_progress` per session** — one thread per session, one branch at a time.
  This is core rule 9 (one code-writer at a time) stated as a WIP limit.
- **Under fan-out** (`modules/concurrency.md`: several subagents, one item each, own
  branches) the orchestrator's merge lane holds the single `in_progress` slot; a worker's
  item goes `todo` → `done` at its merge, evidence = the merge sha. Items are cut one per
  branch BEFORE the first spawn, through the CLI, so the board carries the plan the
  workers execute. This is the same board in both lanes — remote workers spawned in
  parallel, or local workers run one at a time; only the spawn cadence differs.
- **At most two epics `active` per project.** A third means the first two are really
  `todo` wearing a costume.
- The CLI refuses to exceed either limit rather than warning: a limit that can be ignored
  by reflex is not a limit.

## Discipline

- **Records only via the CLI** (rule 1) — this kind is no exception. Hand-written epic
  frontmatter is a drift-checker finding.
- **Re-word an item, do not shadow it.** An item whose title turned out wrong — scoped at the
  wrong thing, or superseded by what the work actually taught you — is corrected with
  `maestro epic item --item=<id> --title=...`, which records the old wording in the log
  (the `exp revise` contract, rule 1). Leaving the stale title in place and doing something
  else is drift; so is adding a second item that quietly replaces the first without saying so.
  When the item should not be worked *at all* as written, set `--blocked-by` with the
  supersession as the reason — that stops the work while keeping its state visible.
  An EPIC is re-worded the same way, with `maestro epic update --id=<n> --title=...`: the
  old wording goes to the log and the body's `# Epic <n> — ...` heading moves with it, so
  the board and the record cannot end up saying different things.
- **Link the records the epic produced, through the CLI.** `maestro epic update --id=<n>
  --exps=147,148 --adrs=31` adds those numbers to the epic's `exps` / `adrs` frontmatter
  (deduped, sorted; one log line per list, e.g. `linked exps 147, 148`). Each number must
  name an existing `docs/experiments/exp_<NN>_*.md` or `docs/adrs/adr_<NN>_*.md`; an
  unknown one is refused and nothing is written. `epic show` prints the lists.
- **Closing requires `--outcome`.** An epic that closes with no statement of what it
  delivered leaves the same hole `progress.md` had.
- **Closing requires every item settled.** `close` refuses while any item is todo or
  in_progress, and names them: close each with its evidence, drop it with its reason, or
  move it to another epic. A leftover todo row on a closed epic read as unfinished work
  forever; the outcome was the only place that said it was abandoned, and no count read it.
- **An item closes with `--evidence`** — a merge sha, a test name, an artifact path. The CLI
  refuses `--status=done` without it, exactly as it refuses a third epic in progress. `done`
  is the claim that gates everything downstream, and moving a card is the activity that most
  reliably FEELS like progress while what is underneath goes unexamined. Nothing to point
  at yet means it is not done. Reopening an item drops its evidence, because the old
  evidence no longer holds.
- **The evidence must be a sha git can still follow.** `--status=done` resolves every
  sha-shaped token in `--evidence` and refuses two shapes: one that resolves to no commit
  (a typo, or a sha from another repo), and an ORPHAN — a real commit no branch or tag
  contains, unreachable and gone at the next `git gc`. The orphan is the one that happens:
  an executor commits, is asked to reword, and the first commit is stranded while its sha
  is still quoted as proof. Cite the sha that survives on the trunk — usually the MERGE
  commit, not the branch commit that went into it. Paths, test names and prose are left
  alone, and a tree with no git gets no opinion. `docs check` sweeps what was recorded
  before the guard, and reports a sha that has rotted since, as an advisory.
- **An answered `done_when` clause, and the outcome, must cite an artifact** (check A5).
  A repo path, a sha, or a `verified:` marker — a command alone is not enough, because it
  names how a number was made but not the run that made it. This is A1 on the other record
  kind: A1 catches an exp whose takeaway names no `source_artifacts`, A5 catches an epic
  whose result points at nothing. It went unchecked for a structural reason worth knowing:
  A3 reads prose and skips frontmatter, and an epic's results live IN the frontmatter, so
  the one place an epic states its outcomes was the one place no evidence check looked.
  It BLOCKS only while the epic is open, which is the window in which the citation can
  still be added honestly; a closed epic's answers are dated history and report advisory.
- **`--learned` on close writes the retrospective line** to `docs/retro.md`. `--outcome` says
  what the epic delivered; `--learned` says what it taught us about how we work. That second
  claim has no other home — an ADR records a decision, `findings.md` records a measurement,
  and neither is about the process itself. Optional, one line, append-only.
- **An epic with no `done_when` is reported before it closes, not after.** The drift
  checker raises it as an advisory the moment the epic is open (K9): stating the condition
  is cheap while the work is a decision and worthless once it is a rationalisation. A
  closed epic carrying an unanswered clause is a BLOCKING finding (K8) — `close` refuses
  that, so the record was hand-edited.
- **Fan-out is a contract, not a retelling.** When an item's scope is a list (rows,
  files, tests) and the work is split across subagents, the briefs are GENERATED from
  that list, and the union of the briefs is diffed against it BEFORE the first spawn
  and again at close-out against what actually closed. Never retype the list: a
  hand-copied scope loses members every time it crosses a context boundary (a wrapped
  YAML title, a re-titled item, a summary table), and the loss is invisible because the
  workers report only what they were given. The tally comes from the contract, never
  from the workers' reports, and a green gate proves the code is healthy, not that the
  scope was covered. Read the scope from `maestro epic show --id=N` (titles print
  unwrapped), not from the raw YAML. Recipe, must print nothing:
  `comm -23 <(sort contract.ids) <(cat brief_*.ids | sort)`. Case: one real run —
  8 briefs, 5 of 36 rows never in any brief, gate green, "30/36 closed" reported.
  A worker's report is progress, not completion: merge, switch or delete a branch only
  after that worker's "finished" event, because the report can arrive while it is still
  editing the shared checkout.
- **The log and the board must agree.** The board (item states) is the contract the
  log is read against: a log line saying the work merged or completed while every
  item is still `todo` is a BLOCKING finding (K10) — either close the items with
  evidence, or the line is a claim from memory.
- **The log is append-only**, one dated line per session. It is the epic's memory
  across context windows: what moved, what was learned, what is next. Not a diary of
  every edit — git holds those.
- **An item's status is a claim, so rule 2 governs it.** `unported`, `reachable: no`,
  `CONFORMANT` gate future work exactly as a metric does — they carry `verified: <sha|date>`
  or are written `unverified`, and citing an unverified row means re-checking it first.
  The rule itself lives in core rule 2 (ADR 9); it is not restated here.
- **`progress.md` points at the epic, it does not embed it.** `## Current` gets a link
  and a sentence. The moment item rows start appearing in `progress.md`, the layer failed.
