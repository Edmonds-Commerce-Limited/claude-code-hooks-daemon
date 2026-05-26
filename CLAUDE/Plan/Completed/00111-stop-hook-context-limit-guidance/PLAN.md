# Plan 00111: Stop Hook — Context-Limit Guidance Clause

**Status**: Complete
**Created**: 2026-05-26
**Owner**: Joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

User reported a dogfooding issue: the agent voluntarily stops near the context
window limit (e.g. ~75% utilisation) believing it needs to "checkpoint" before
auto-compact. This causes massive delays in long-running work. Claude Code's
auto-compact triggers automatically when the threshold is crossed — voluntary
stopping near the limit is incorrect behaviour.

The Stop hook's `_EXPLAIN_OR_CONTINUE_REASON` (Branch 4) message currently
says only:

> "You stopped without explaining why. Either: (1) prefix with STOPPING
> BECAUSE:, or (2) use AUTO-CONTINUE."

It does NOT tell the agent that context-limit pressure is never a valid reason
to stop. This plan adds an explicit clause.

## Goals

- Add explicit "DO NOT STOP NEAR CONTEXT LIMIT — auto-compact handles it"
  guidance to the Branch 4 reason message.
- Regression-test the new clause is present.

## Non-Goals

- v2.1.114 delivery-gap fix (deferred — already covered by Plan 00101).
- Context-checkpoint detection branch (deferred — needs design work).
- Tool-error recovery improvements beyond the existing Branch 2.5
  (already covered by Plan 00101).

## Context & Background

The transcript-inspector sub-agent reviewed the session and found:

- 12 Stop events in one session, two were premature context-checkpoints at
  ~50% context (no compaction was imminent).
- The current Branch 4 message does not address this voluntary-stop pattern.

Plan 00101 (completed) established that high-context turns produce
tool-only output that triggers a different bug shape — but did NOT address
the "agent thinks it should stop and let compact happen" failure mode the
user is reporting now.

## Tasks

### Phase 1: TDD — message update

- [x] ✅ **Task 1.1**: Added failing regression test class
  `TestExplainOrContinueReasonContent` with two assertions: new
  context-limit clause present + existing clauses retained.
- [x] ✅ **Task 1.2**: Extended `_EXPLAIN_OR_CONTINUE_REASON` with paragraph
  telling the agent auto-compact handles context pressure automatically.
- [x] ✅ **Task 1.3**: Targeted stop-handler suite (97 tests) and related
  integration tests (48 tests) all pass. Bumped `test_handle_reason_is_concise`
  cap from 500→1000 chars (load-bearing guidance, not prose).

### Phase 2: QA + daemon restart

- [x] ✅ **Task 2.1**: Black + Ruff + MyPy clean on changed files.
- [x] ✅ **Task 2.2**: Daemon restarted, status RUNNING.

### Phase 3: Commit

- [x] ✅ **Task 3.1**: Committed as `7d1b9b8` with `Plan 00111:` prefix.

## Success Criteria

- [x] Stop hook Branch 4 message explicitly tells agents not to stop near
  the context limit.
- [x] Regression test pins the clause.
- [x] Targeted lint/format/types/tests pass on changed files.
- [x] Daemon restarts cleanly.

## Notes & Updates

### 2026-05-26

- Plan created in response to user dogfooding interrupt mid-Plan-00110.
- Scope intentionally narrow — just the message clause. Larger
  context-checkpoint detection deferred.
- Delivery commit: `7d1b9b8`.
