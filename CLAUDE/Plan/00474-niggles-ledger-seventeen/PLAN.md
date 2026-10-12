# Plan 00474: niggles ledger seventeen

**Status**: Blocked
**Created**: 2026-09-30
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct
**GitHub Issue**: #59 (the mkplan.bash worktree lock, fixed in this ledger and released in v3.68.0; closed 2026-10-11)

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
table (145 rows) is in [STATUS-INDEX.md](STATUS-INDEX.md).
Counted by the status column's emoji:

- 4 rows are open (⬜): N424, the LSP guard denying a grep over piped output; N427, the provision sync tests leaving stub daemon processes behind; N430, the conflict-marker gate denying a commit into a repository the same command creates; and N435, the report-path verifier resolving a worktree agent's relative path against the main checkout. N53 of archived ledger 00466 is 🟡: batch AJ reproduced
  the mechanism of an exit 127 and extended the diagnostic, but the live cause awaits a recurrence. The other 41 of the
  "42 still open in 00466" were fixed on main (39), fixed by batch AI (N33) or graduated to Plan 00485 (N96); see
  [the 00466 evidence](../Completed/00466-niggles-ledger-sixteen/STATUS-2026-10.md).
- No row awaits an owner decision. The owner ruled on all 15 questions in
  [OWNER-QUESTIONS-261011.md](OWNER-QUESTIONS-261011.md) on 2026-10-11, recorded in
  [OWNER-RULINGS-261011.md](OWNER-RULINGS-261011.md):
  - 2 rows are closed by the ruling (N333, N397);
  - 12 of the 15 went into progress: batches AL, AM and AN, the supervisor items, or a GitHub issue (rows since fixed are counted below);
  - 1 stays part-fixed (🟡, N376), with its remainder tracked in #107;
  - the new work the owner asked for is filed as GitHub Issues #106 to #110. #104, the usage-aware sub-agent cutoff, came from a separate owner request the same day, not from this sheet.
- 122 rows carry ✅ (118 of the 141 N rows, plus 4 "carried from dropped branch" summary rows) (fixed, dismissed, remedied, guarded or closed); 6 of them also carry a 🚫 limit, and
  2 also carry 🔄: N280 (guarded by batch AN) for its review follow-ups, and N425 (fixed) until CI confirms
  it. N428 (the Python 3.11 CI hang) is confirmed by main run 38204671323.
- 7 rows record a deliberate limit (🚫); 20 are in progress or graduated (16 🔄, 3 🟡, 1 ↩️), N280,
  N425 (main CI red after batch AL), N431 (the CI fallback's daemon idles out), N433 (a quiet journal
  fails CI) and N440 (#90, plan QA and README table rows) among the 16.

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
