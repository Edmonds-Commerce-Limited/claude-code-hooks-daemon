# Plan 00381: niggles ledger three

**Status**: In Progress
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Successor to Plan 00379, which closed with all five entries resolved. Per the
niggles SOP a closed ledger does not stop the collecting: the next niggle found
opens a new one rather than being mentioned in passing.

A niggle is a small, specific, VERIFIED defect — something wrong now, recorded
the turn it is found, with the evidence that makes it checkable by someone who
was not there. An entry needing real design work is graduated to its own plan
with a pointer rather than grown here.

## Goals

- Every niggle found is recorded here in the turn it is found, with evidence.
- Each entry is either fixed here or graduated to a named plan with a pointer.

## Non-Goals

- Redesign. An entry needing design is graduated, not grown in place.
- A dumping ground for wishes. An entry must name something that is WRONG.

## Tasks

### Phase 1: Recorded niggles

- [ ] ⬜ **N1**: `TestFreshClientConfig` in
  `tests/acceptance/test_transport_toggle_cycle.py` cannot pass on its own. Run
  the class alone and
  `test_transport_on_with_absent_binary_and_null_source_refuses_untouched`
  fails; run the whole module and all 11 pass. Its expectations depend on state
  a sibling class leaves behind, and these tests drive the real CLI — `transport on` regenerates forwarders and restarts the daemon — so ordering is
  load-bearing rather than incidental. Two runs produced two DIFFERENT failures
  (`assert 0 != 0` on the return code, then `assert 'relay hot path' not in ...`
  on the generated hook), which says the shared state is mutable and the class
  is reading whatever the previous test left. Found while narrowing an unrelated
  test run with `-k "worktree or cli"` — `cli` matched `TestFreshClientConfig`
  by substring and ran it in isolation. Nothing in the suite as normally run is
  red, so this costs nothing today; it costs the next person who tries to run
  one failing class while debugging, which is exactly when a misleading failure
  is most expensive.

## Success Criteria

- [ ] Every entry above is fixed, or graduated to a named plan with a pointer
  recorded in this ledger.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  the entry records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Successor to Plan 00379 (Completed), per the niggles SOP in
  `CLAUDE/PlanWorkflow.md`.
