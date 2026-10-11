# Plan 00466: niggles ledger sixteen

**Status**: Superseded
**Created**: 2026-09-24
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

**Superseded by [00474](../../00474-niggles-ledger-seventeen/PLAN.md).** The
entries still open in the index below remain open and are tracked from 00474.
Every branch of this ledger was resolved: landed, or dropped with its
branch-only entries carried into 00474.

The rolling ledger for defects found in passing. Ledger fifteen
([00422](../00422-niggles-ledger-fifteen/PLAN.md)) stays open for its own
entries: four are waiting on stated owner questions, and several are
graduated to plans still in flight. But its PLAN.md passed the 25,000-byte
warning line with N29. So new entries are filed here, and 00422 takes no
more.

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

Full write-ups are in [NIGGLES.md](NIGGLES.md). The one-line-per-niggle status table (157 rows) is in
[STATUS-INDEX.md](STATUS-INDEX.md); evidence for the entries marked in October 2026 is in
[STATUS-2026-10.md](STATUS-2026-10.md). Counted by the status column's emoji: 148 rows carry ✅, 1 (N53) is 🟡 with its mechanism reproduced and its live cause awaiting a recurrence, 4 are
in progress or graduated (🔄), 1 is deferred (⏸️), 1 records a deliberate limit (🚫), and two rows (N32, N92) have a
broken status cell and are fixed on main.

## Branches

Every branch was landed (n101, n211, lifecycle, d-00376) or dropped, its
branch-only entries carried into 00474 (n466-small-a, p422-close, d-00421,
upgrade-scripts, 464, N38); the former parking table is in
[PARKED-BRANCHES.md](PARKED-BRANCHES.md).

## Tasks

### Phase 1: Resolve entries

- [ ] ⬜ **Task 1.1**: Bring every entry to a terminal state.

## Success Criteria

- [ ] Every row is terminal: remedied, graduated, or dismissed with reasoning.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00466-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened with N1.
