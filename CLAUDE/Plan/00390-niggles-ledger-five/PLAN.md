# Plan 00390: niggles ledger five

**Status**: In Progress
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

## Success Criteria

- [x] Every entry above is either fixed with a regression test, or graduated to
  a named plan and that plan is linked from the entry.
- [x] No entry is closed on reasoning alone — each fix is proved against the
  case that was actually observed. N1 was re-run as the ORIGINAL denied write,
  through the real handler, after the fix.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Opened because ledgers 00377/00379/00381/00385 are all closed and a new niggle
  was found, per the SOP in `CLAUDE/core/PlanWorkflow.core.md`.
- N1 fixed at `7e0756af`.
- **This ledger stays OPEN while it is the current one.** It is not "finished"
  when its entries are: it closes when a successor opens, which is what the SOP
  means by the next niggle opening a new ledger. Record new entries here.
