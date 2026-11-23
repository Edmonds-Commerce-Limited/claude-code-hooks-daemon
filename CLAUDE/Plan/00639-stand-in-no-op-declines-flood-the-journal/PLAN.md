# Plan 00639: stand-in no-op declines flood the journal

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Type**: Bug
**Priority**: Medium (owner, via lts-infra.1 relay Q65: "we really dont need journal flooding on noops"; next after the v2 PRs)
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The one-off `[tick:stand-in]` cron (Plan 00470 Task 5.2, `utils/stand_in_cron.py`) wakes a
`model: fable` sub-agent while a session is awaiting a human. The ruling must be recorded in the
plan journal. When the sub-agent declines and nothing has changed since the previous decline, the
record is still written, one journal entry per tick.

Evidence (relayed by lts-infra.1 from dc's stood-down hooks-daemon checkout; unverified here): from
18 to 23 Nov, Plan 00616 committed about 37 entries "Plan 00616 journal: the Nth stand-in declined"
(sixth to forty-seventh), plus hourly pull merges, leaving about 80 commits that could not be
pushed. The same relay is ledgered as N711 and N712 in Plan 00474.

Plan 00470 owns the stand-in feature; the fix changes the journal rule its Task 5.2 specifies, so
that task gets a cross-link.

## Goals

- A stand-in that declines with nothing changed since the last recorded decline writes no new
  journal entry, or at most one entry stating the decline, then none until the state changes.
- A repeated no-op decline backs off its own cadence rather than firing every tick.
- The first decline and any ruling that CHANGES something are still recorded in full.

## Non-Goals

- Surfacing a blocked push on the bus (N712; a separate fix, queued).
- Changing which decisions a stand-in may take (engineering options only; releases, force and
  remote-branch deletes, QA suppressions, history rewrites and approvals stay blocked).

## Tasks

### Phase 1: Reproduce and fix test-first

- [ ] ⬜ **Task 1.1**: Locate where the stand-in directive tells the agent to journal its ruling
  (the stand-in tick text and `utils/stand_in_cron.py`); confirm the flood from the directive
  alone, not only from the relayed evidence.
- [ ] ⬜ **Task 1.2**: Red test: two consecutive declines with an unchanged state fingerprint
  produce one journal instruction, not two.
- [ ] ⬜ **Task 1.3**: Implement the no-op check (compare against the last recorded decline) and the
  backoff; green.
- [ ] ⬜ **Task 1.4**: Cross-link from Plan 00470 Task 5.2; release note; PR with independent
  review and a green full CI run before merge.

## Success Criteria

- [ ] A no-op decline after the first writes no journal entry (test-pinned).
- [ ] A ruling that changes something is still journalled.
- [ ] Release note filed in the pending-release holding area (R-PLAN-DONE-HOLDING-AREA).

## Delivery & Milestones

- Filed from the Q65 relay; nothing built.
