# Plan 00474: niggles ledger seventeen

**Status**: In Progress
**Created**: 2026-09-30
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger sixteen
([00466](../Completed/00466-niggles-ledger-sixteen/PLAN.md)) stays open for its own
entries, whose remaining branches the owner parked. But its PLAN.md reached
the 35,000-byte hard limit with N261, so its index table cannot take another
row. New entries are filed here, and 00466 takes no more.

Numbering continues from 00466, so an entry number stays unique across both
ledgers.

Each entry gets enough evidence for someone else to reproduce it, and ends
in a terminal state: fixed, graduated to its own plan, or dismissed as
not-a-defect with the reasoning kept.

## Goals

- Record each niggle with reproducible evidence in [NIGGLES.md](NIGGLES.md).
- Resolve each entry to a terminal state.

## Non-Goals

- Becoming a feature plan. A niggle that needs design graduates to its own
  numbered plan and leaves a pointer here.

## Niggles

Full write-ups are in [NIGGLES.md](NIGGLES.md). The one-line-per-niggle status
table (123 rows) is in [STATUS-INDEX.md](STATUS-INDEX.md).
Counted by the status column's emoji:

- No row is open (⬜ Open) except the owner decisions below. N53 of archived ledger 00466 is 🟡: batch AJ reproduced
  the mechanism of an exit 127 and extended the diagnostic, but the live cause awaits a recurrence. The other 41 of the
  "42 still open in 00466" were fixed on main (39), fixed by batch AI (N33) or graduated to Plan 00485 (N96); see
  [the 00466 evidence](../Completed/00466-niggles-ledger-sixteen/STATUS-2026-10.md).
- 15 rows carry an owner decision (⬜ Owner decision, including three fixed or part-fixed rows with a decision left).
- 100 rows are fixed, dismissed, remedied or closed (✅; some of them also count in the lines above and below).
- 7 rows record a deliberate limit (🚫); 8 are in progress or graduated (4 🔄, 3 🟡, 1 ↩️).

## Tasks

### Phase 1: Work the ledger

- [ ] 🔄 **Task 1.1**: Bring every entry above to a terminal state.

## Success Criteria

- [ ] Every entry is fixed, graduated with a pointer, or dismissed with the
  reasoning recorded.
- [ ] Every release-bound consequence is in the pending-release holding area,
  or the entry says it has none.

## Delivery & Milestones

- Opened when ledger sixteen (00466) reached its PLAN.md size limit.
