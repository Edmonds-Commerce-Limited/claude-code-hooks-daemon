# Plan 00637: coordinator no-value remote branch retire

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (g) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md);
design in its [DESIGN.md](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md)
section 21. The owner settled Q17 (lts-infra Q66 (a), yes): a coordinator may
delete an UNMERGED remote branch it has judged to hold no value, provided it
logs the verdict, lists the branch in the daily report, and never deletes a
branch with open review comments.

The existing `branch-reject` route (Plan 00620) is LOCAL-only and states "No
remote delete". This plan adds a REMOTE no-value retire on top of it, without
weakening `R-BRANCH-REJECT-DISPATCH`, `R-GIT-PUSH-DELETE-REMOTE` or
`R-GIT-BRANCH-FORCE-DELETE`. DESIGN.md section 21 states exactly what exists
and what is new.

## Goals

- A remote-branch variant of the reject route: same independent reviewer
  verdict, same recovery bundle, same ledger, then a leased remote delete.
- Seat-gated: coordinator only, via the Plan 00631 probe.
- Open-review-comments refusal, read through `gh`, failing closed.
- A daily-report line per retired branch.

## Non-Goals

- Any change to the local route or to the guards named above.
- Regenerable-ignored-glob retire (retrospective s1, second half): a separate
  decision, not ruled; not built here.
- A weaker verdict for coordinators.

## Tasks

### Phase 1: RED

- [ ] ⬜ **Task 1.1**: Fixtures: a coordinator seat with a reviewer `no-value`
  verdict, a verified bundle and no review comments retires the remote branch;
  no verdict, a `keep` verdict, an expired or reused verdict, a worker or
  unknown role, a branch with an open review comment (any PR, any thread), an
  unreadable or erroring `gh`, a missing PR lookup, and a tip that moved since
  review are each refused with the reason; `R-GIT-PUSH-DELETE-REMOTE` still
  denies a bare `git push --delete` of the same branch.

### Phase 2: Route

- [ ] ⬜ **Task 2.1**: `branch-reject request` accepts a remote-only branch
  (fetch the tip; same inventory and prompt); the verdict, bundle and
  single-use state are unchanged. Targeted QA green.
- [ ] ⬜ **Task 2.2**: Open-review-comments check (`gh`, fail closed) run at
  request time AND again at delete time. Targeted QA green.
- [ ] ⬜ **Task 2.3**: Coordinator gate (`role == coordinator` in a held team)
  on the remote variant; delete under a lease on the reviewed tip.
- [ ] ⬜ **Task 2.4**: Remote retires count against the existing removal-rate
  window. DECIDED: ONE shared window with local removals, not a second
  (coordinator agreed; DESIGN.md section 21). Red first: a local removal plus
  a remote retire past the shared limit refuses the second.

### Phase 3: Record and report

- [ ] ⬜ **Task 3.1**: Ledger line (`remote: true`, verdict id, reviewer, tip,
  bundle) and a daily-report line listing each retired branch; `branch-reject digest` shows them. Live check in a coordinator seat.

## Dependencies

- Plan 00631 (probe). Prior art Plan 00620 (`branch-reject`). Related 00636
  (daily report content), 00634 (HUMAN check; not required here, the
  reviewer verdict is the evidence).

## Success Criteria

- [ ] No remote retire without a reviewer verdict, bundle, ledger line and
  report line; none with an open review comment or an unreadable `gh`.
- [ ] The three guards' existing tests pass unchanged.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed from the owner's Q66 (a) answer.
