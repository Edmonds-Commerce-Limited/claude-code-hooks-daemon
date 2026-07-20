# Plan 00180: supervisor injection cap — reset on successful compaction

**Status**: Complete
**Created**: 2026-07-20
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Dogfooding bug caught live on a long-running production session (marketing-system,
~6.5h). The ccy PTY supervisor stopped driving `/compact` while context sat at
CRITICAL; its `decision.log` showed `noop: injection cap reached [critical]` on
every actionable idle tick from ~12:47 onward.

Root cause: `CompactStateMachine._injections` (`.claude/ccy/claude-supervise.py`)
is a **cumulative lifetime counter**. It starts at 0 in `__init__`, is `+= 1` on
every `/compact` injection (line ~1668), gated by
`if self._injections >= self._policy.max_injections` (line ~1661,
`_DEFAULT_MAX_INJECTIONS = 20`), and is **never reset**. So after 20 compactions
over a session's life the supervisor is permanently muzzled — even at CRITICAL —
and context climbs unchecked.

The cap was intended as a **runaway-loop fuse** (stop if we inject `/compact`
repeatedly and nothing ever compacts), not a lifetime budget. The genuine
runaway guards already exist and stay: `cooldown_seconds=300`, `max_escapes=5`,
and the AWAIT timeout.

## Goals

- A **successful** compaction resets the injection counter, so legitimate
  compactions are unbounded over a long session.
- The runaway fuse is preserved: consecutive **failed** injections (a `/compact`
  injected but no compaction ever starts → AWAIT times out) still accumulate and
  still trip `max_injections`.
- Regression test proving a post-compaction red reading compacts again.
- QA green; supervisor version lockstep intact; daemon RUNNING.

## Non-Goals

- No change to `cooldown_seconds`, `max_escapes`, or the AWAIT timeout.
- No change to `_DEFAULT_MAX_INJECTIONS` (20 remains, now as a consecutive-failed
  fuse rather than a lifetime cap).
- No new config surface.

## Tasks

### Phase 1: TDD fix

- [x] ✅ **Task 1.1**: RED — add `test_successful_compaction_resets_injection_cap`
  to `tests/unit/supervise/test_compact_state_machine.py`: with `max_injections=1`,
  inject once (WOULD_COMPACT), drive `compacting=True` (WOULD_CONTINUE), then a
  fresh red reading must be WOULD_COMPACT again (fails today — NOOP cap reached).
- [x] ✅ **Task 1.2**: Rework `test_cap_reached_noop` to exercise the fuse via
  **failed** attempts (WOULD_COMPACT → AWAIT timeout → MONITOR, repeated) so the
  cap still trips without any successful compaction between injections.
- [x] ✅ **Task 1.3**: GREEN — reset `self._injections = 0` on the confirmed-
  compaction transition (where `_compaction_handled = True` / `_enter_monitor()`
  on the WOULD_CONTINUE success path), NOT on the AWAIT-timeout give-up path.
- [x] ✅ **Task 1.4**: Audit `test_decision_log.py` / other cap references for the
  same buggy assumption; update any that encode the lifetime-cap behaviour.

### Phase 2: QA & dogfood

- [x] ✅ **Task 2.1**: `./scripts/qa/llm_qa.py all` green (95%+), incl. supervisor
  version-lockstep test.
- [x] ✅ **Task 2.2**: Daemon restart RUNNING.

## Technical Decisions

### Decision 1: reset on success, not on give-up

Resetting `_injections` when a compaction is *detected* (success) makes
`max_injections` a bound on *consecutive failed* injections — the true
runaway-loop fuse. Resetting on the AWAIT-timeout path instead would defeat the
fuse (a permanently-wedged session would inject forever).

## Success Criteria

- [x] Post-compaction red reading compacts again (no lifetime cap).
- [x] Consecutive failed injections still trip `max_injections`.
- [x] QA green, daemon RUNNING, version lockstep intact.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only. -->

- Plan created. Reuses live recovery cron `dffb57b7` (hourly, non-durable).
- Diagnosis evidence: `untracked/ec-mark-supervisor/decision.log` (operator-supplied
  from the affected session); root cause at `claude-supervise.py:1661-1668`.
