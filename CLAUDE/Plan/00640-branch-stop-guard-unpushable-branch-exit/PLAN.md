# Plan 00640: branch stop guard unpushable branch exit

**Status**: In Progress
**Created**: 2026-11-25
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Found by the hooks-daemon seat of the lts-ops team (seat 5, arm64 dev VM) on 25 Nov. A branch that cannot be pushed for access reasons (the push is refused with a 403 for the account the container holds) has no clean exit from `branch_stop_guard`. Every stop is denied three times, and the branch is then recorded as abandoned, although nothing is lost and the work is waiting on a human grant.

The guard already has an exit for a handed-over branch: `bin/hooks-daemon branch-park <name> --reason ...` records the tip, and `_handed_over_by_park` in `core/branch_stop_guard.py` then treats a tip on no remote as not abandoned. The observed gap is that the park is bound to the exact tip commit. `branch-park` itself commits (tip `f014161d5`), and any later commit moves the tip off the record, so the branch is judged again. In this session the coordinator asked for a handoff journal entry to be kept current on the same branch, so each such commit re-armed the three-block cycle and the final stop was recorded as abandoned. A park is also cleared at the next session start, so a branch that stays unpushable across a relaunch starts again from block 1.

The fix must keep what the guard is for: work that is neither pushed nor deliberately handed over must still be refused. It must not let an agent wave a branch through on its own say-so.

## Goals

- A branch that is parked with a reason, and whose push is refused for access reasons, stays handed over while further commits land on it, until a human clears the park or the push succeeds.
- The final abandoned record is not written for such a branch, and its wording does not call a branch with commits that only a push is missing "abandoned".
- A reproduction test exists first and is shown failing.

## Non-Goals

- Changing the three-block limit, or the rule that an agent's own assertion never deletes a branch.
- Granting or working around push access; that is the owner's decision.

## Tasks

### Phase 1: Reproduce and decide

- [x] ✅ **Task 1.1**: Write a failing unit test in `tests/unit/handlers/stop/test_branch_stop_guard.py` (or the core test for `branch_stop_guard`): a parked branch, then one more commit, then a stop. Today it is denied; the chosen rule says whether it should be.
- [x] ✅ **Task 1.2**: Decide the rule with the owner's constraints in mind: a park that follows the branch (bounded by a recorded reason and a maximum age) versus a park pinned to a tip. Record the decision in the JOURNAL.

### Phase 2: Fix

- [x] ✅ **Task 2.1**: Implement the chosen rule in `core/branch_stop_guard.py` and `core/branch_park.py`, test first.
- [x] ✅ **Task 2.2**: Make the abandoned record and the deny text say what is true for a branch that only lacks a push. Also: `announce_ended_parks` follows the same ancestor rule (shared `park_covers_tip` in `core/branch_park.py`); release callout `CLAUDE/UPGRADES/UNRELEASED/release-notes/107-...` (numbered 107 because PR 251 holds 106).
- [x] ✅ **Task 2.3**: Restart the daemon and verify live with an unpushable branch, then run targeted QA. Daemon restarted on the new code; a park recorded at `1bf547492` with the later commit `1e069f69d` on top was not named by the next stop. Targeted QA: 5109 changed tests passed; `magic_values` flags only literals outside this plan on `main` after the one this plan introduced was replaced; `changed_tests` lists three `[too-broad]` unmapped source files (`core/branch_park.py`, `daemon/cli.py`, `handlers/session_start/branch_sweep.py`) that need `--allow-unmapped` or a map rule.

## Success Criteria

- [x] The Task 1.1 test failed before the fix and passes after it (the sub-agent saw 9 failed before; my rerun of the 7 touched test files: 271 passed).
- [x] A parked, unpushable branch with later commits does not produce the three-block cycle or an abandoned record (live check, Task 2.3).
- [x] An unparked unpushed branch is still denied: `test_unparked_branch_is_still_denied` in `tests/unit/core/test_branch_stop_guard.py` passes; not re-run live.
- [x] Release-bound consequences: recorded in the pending-release holding area as release note 107.
- [ ] PR 255 is merged, and the plan is then flipped to Complete and archived in that same step.

## Delivery & Milestones

- Defect logged by seat 5 (lts-ops).
- Implemented and verified on branch `fix-ccy-dockerfile-arm64-dart`, delivered by PR 255 (commits `c5c29e2d6`, `1bf547492`, `c99e7f9fb`). The plan is complete when PR 255 merges: the archive move to `Completed/` ships with that merge.
