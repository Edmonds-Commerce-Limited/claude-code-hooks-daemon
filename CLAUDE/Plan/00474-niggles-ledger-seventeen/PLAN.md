# Plan 00474: niggles ledger seventeen

**Status**: In Progress
**Created**: 2026-09-30
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger sixteen
([00466](../00466-niggles-ledger-sixteen/PLAN.md)) stays open for its own
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

Full write-ups are in [NIGGLES.md](NIGGLES.md). One line each here:

| #    | Verdict                                                                     | Origin          | Status                  |
| ---- | --------------------------------------------------------------------------- | --------------- | ----------------------- |
| N264 | A sub-agent's edits landed, uncommitted, in another branch's worktree       | 00466 landing   | ⬜ Open                 |
| N263 | The release empties UNRELEASED post-upgrade tasks but not the README index  | v3.67.0 CI      | ✅ Remedied             |
| N262 | The release procedure has no check that the notes fit a GitHub release body | v3.67.0 publish | ✅ Remedied (ea8dcd542) |

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
