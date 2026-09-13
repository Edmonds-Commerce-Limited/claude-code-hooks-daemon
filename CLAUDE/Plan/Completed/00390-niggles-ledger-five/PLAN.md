# Plan 00390: niggles ledger five

**Status**: Complete
**Created**: 2026-09-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open ledger for small defects. Ledgers one through four (00377, 00379,
00381, 00385) are all closed, and SOP is that the next niggle found opens a new
one rather than reopening an archived plan — so this exists because a niggle was
found, not in anticipation of one.

A niggle is recorded **in the turn it is found**, before the work that surfaced
it continues. The rule exists because the alternative is reporting it in context
output, where it is read once and then lost when the window compacts. Every
entry names what was OBSERVED, not what was guessed.

Entries may be fixed here, or GRADUATED to their own plan when they turn out to
be larger than a niggle. Graduating is a success: the ledger's job is to make
sure nothing is dropped, not to force every fix into one plan.

## Goals

- Every small defect found while doing other work is recorded, with enough
  evidence that someone else could reproduce it.
- Each entry is either fixed here or graduated to a named plan — never dropped.

## Non-Goals

- Batching. An entry is appended the turn it is found; the ledger is never
  "caught up" later from memory.
- Large work. Anything needing its own design graduates to its own plan.

## Tasks

### Phase 1: Entries

- [x] ✅ **N1**: `markdown_organization` denies a `.md` write under
  `untracked/` when a `.claude/` segment appears deeper in the path, even though
  its own deny message lists `./untracked/` as an allowed location.

  **Observed** while building a client-shaped fixture for Plan 00386:
  `untracked/scratch/e2e-386/project/.claude/HOOKS-DAEMON.md` was DENIED, while
  `untracked/scratch/e2e-386/plain-note.md` — same tree, same turn — was
  allowed. So the nested `.claude/` segment, not the location, decided it.

  **Why it matters here specifically**: this repository dogfoods a daemon whose
  fixtures are client installs, and a realistic client fixture must contain a
  `.claude/` directory with exactly these filenames. `untracked/` is gitignored
  scratch, so nothing written there can rot the repository — which is the whole
  reason it is on the allow list. The guard is protecting a tree that does not
  need protecting, and the cost is that the honest way to build a fixture is
  blocked while a Bash redirect (which no content guard inspects) is not.

  **Diagnosed — accident, not design.** `normalize_path` iterated the MARKER
  LIST and stopped at the first name found anywhere in the path, so list order
  decided the root. `.claude/` precedes `untracked/`, so the nested segment won.
  The function's own docstring settles the intent: it says "find first
  OCCURRENCE of project markers", which is positional, while the implementation
  was ordinal — so the deny message was right and the code was wrong.

  **Fixed**: the earliest segment-aligned marker in the path wins. Two of the
  six new tests were green beforehand and are kept as controls, so the fix
  cannot have been bought by loosening the stripping the function exists to do.

- [x] ✅ **N2**: The generated `CLAUDE.md` rules table states an INERT handler's
  rule as a present-tense fact about this project, so an agent reads a gate that
  cannot fire as one that governs it.

  **Observed**: `CLAUDE.md:479` (daemon-generated) carries
  `R-PLAN-CLOSE-APPROVAL` with the Why column reading "This project requires a
  human to close a plan; the daemon enforces that rather than leaving it to a
  sentence in a document". That project does not require it:
  `.claude/hooks-daemon.yaml:1051` sets
  `plan_workflow.close_requires_human_approval: false`, and
  `plan_close_approval.py:110-111` returns `False` from `matches()` before
  anything else when the key is off. The handler is `enabled: true` with the
  config comment "Inert while the key is false", so the registry loads it and
  `get_rules()` contributes the row regardless of whether it can ever fire.

  **The cost is measured, not hypothetical.** This is what made the agent
  believe Plans 00386 and 00389 could not be closed without
  `approve-plan-close`. Two finished plans sat open across a multi-day cron run,
  the belief was written into both plan documents as fact, and the owner was
  briefed to run two commands that would have done nothing. The handler's own
  `Blocked` column is accurate ("while `...` is on"), which is exactly why the
  Why column reads as confirmation rather than as a conditional.

  **The sibling gate had it too.** An earlier revision of this entry claimed
  `R-MERGE-TO-MAIN-APPROVAL` was honest because its key "is true here". It is
  not: there is no `worktree:` section in `.claude/hooks-daemon.yaml` at all, so
  `merge_to_main_requires_human_approval` takes its declared default `False`.
  The claim came from reading one grep line of a comment that continues onto the
  next and says "inert here since that key is false (default)" — the config
  comment was right and the reading was wrong. Both rows were removed.

  **Fixed**: an optional `CanBeDormant` protocol. A handler that config has
  switched off reports `is_dormant()`, and the CLAUDE.md generator leaves it out
  of the block entirely rather than listing it under headings that call it
  active and its rules enforced. Default-active, because most handlers gate on
  their INPUT, which is undecidable at generation time.

  **A smaller fix was available and rejected**: reword the Why column so it
  reads conditionally instead of removing the row. It is one string per handler
  and touches no mechanism. It was rejected because the row would still sit
  under a heading reading "All other ENFORCED rules" while enforcing nothing,
  and because resident guidance is not free — this block is read in full at the
  start of every session, and the guidance-coverage suite's own measurement puts
  it at ~73 KB / ~18,300 tokens here. A section for a handler that cannot fire
  fails that suite's stated criterion outright rather than marginally.

  Proved against the real path, not only stubs: a test registers the handler
  through the actual registry with the key ON and OFF and asserts the row is
  present then absent. The ON half is the important one — it is what stops this
  fix silently deleting a gate a project really did turn on. `.claude/HOOKS-DAEMON.md`
  was checked and left alone: its row already reads "while the key is on", which
  is a conditional a reader cannot mistake for policy.

## Success Criteria

- [x] Every entry above is either fixed with a regression test, or graduated to
  a named plan and that plan is linked from the entry.
- [x] No entry is closed on reasoning alone — each fix is proved against the
  case that was actually observed. N1 was re-run as the ORIGINAL denied write,
  through the real handler, after the fix. N2 was proved by regenerating the
  real `CLAUDE.md` and confirming the row it wrongly carried is gone.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/39-a-gate-you-switched-off-is-no-longer-announced-as-policy.md`
  — N2 changes what ships in a client's generated `CLAUDE.md`, so a project
  with either approval key at its default will see those rows disappear on the
  next restart. N1 needs none: it corrected a handler's path handling to match
  its own documented behaviour, so nothing a client relies on changes.
- [x] Full QA passes and CI is green — 29/29 locally, CI green at `abf11eb0`,
  which sits directly on the N2 code fix `915f168b`.

## Delivery & Milestones

- Opened because ledgers 00377/00379/00381/00385 are all closed and a new niggle
  was found, per the SOP in `CLAUDE/core/PlanWorkflow.core.md`.
- N1 fixed at `7e0756af`.
- N2 found while answering the owner's question "close requires human approval —
  is this a first class feature?". It is: a config key, a dedicated handler, a
  CLI subcommand, a one-shot marker store shared with the worktree gate, a
  docs-QA check that stops docs prescribing unenforced gates, and a rule ID. It
  is also OFF by default and OFF here — which is exactly the policy the owner
  stated they wanted, already shipped. The defect was the generated block
  claiming otherwise.
- **CORRECTION — an earlier revision of this line was wrong.** It said this
  ledger "stays OPEN while it is the current one" and closes only when a
  successor opens. The canonical SOP in `CLAUDE/core/PlanWorkflow.core.md` says
  the opposite: "When every entry is resolved, close and archive the ledger. Do
  not keep a ledger open as a permanent fixture," and "The next niggle found
  opens a NEW ledger. Never reopen a closed one." Ledgers 00377, 00379, 00381
  and 00385 are all Complete and archived, so four precedents agree with the SOP
  and not with the note. It was the only reason this ledger was still open.
- Both entries are resolved, so this ledger closes. The next niggle runs
  `mkplan.bash` for ledger six rather than reopening this one — reopening a
  terminal plan breaks the archive's atomicity guarantees.
