# Plan 00171: supervisor indicator proc scan negative caching

**Status**: Not Started
**Created**: 2026-07-16
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

This plan captures three findings from the **v3.43.0** release code review
(RELEASING.md Step 10). All were assessed **non-blocking**, so v3.43.0 shipped
with them tracked here per the Plan 00157 "never drop a finding" rule. They are
to be fixed as a fast follow-up immediately after v3.43.0.

The substantive finding is a per-render performance concern in the newly
on-by-default `supervisor_indicator` status-line handler; the other two are
cosmetic cleanups.

## Goals

- Eliminate the full `/proc` walk on every status-line render for projects that
  never run the ccy supervisor (the common case), without regressing detection
  of a live supervisor whose status file has gone missing.
- Correct `supervisor_indicator.py`'s module docstring so its "cheap per-render
  liveness probe" claim matches the actual fast-path behaviour.
- Tidy two cosmetic review nits.

## Non-Goals

- No change to supervisor detection semantics (green/yellow/orange/none states).
- No change to the on-by-default rollout of the new status-line handlers.

## Tasks

### Phase 1: supervisor_indicator /proc-scan negative caching (MUST-FIX)

- [ ] ⬜ **Task 1.1**: Reproduce the cost with a failing test
  - File: `src/claude_code_hooks_daemon/handlers/status_line/supervisor_indicator.py`
  - Symptom: when no supervisor is configured, `_cached_pid` is never populated
    (memoisation only happens in `_activate`, reached only when a supervisor IS
    found). So `_detect_state` -> `_resolve_state` -> `_scan_for_supervisor`
    walks all of `/proc` reading every pid's `cmdline` on **every** render.
    Severity: LOW (fail-safe, bounded by process count) but affects an
    on-by-default handler on every status-line render.
  - [ ] ⬜ Failing test: `_scan_for_supervisor` is NOT re-invoked on every render
    once a "no supervisor" resolution was made within the throttle window.
- [ ] ⬜ **Task 1.2**: Implement time-throttled negative caching
  - Cache a "no live supervisor found" resolution with a short TTL so repeated
    renders in quick succession do not re-walk `/proc`, while a newly-started
    supervisor is still picked up within a bounded delay.
  - Preserve the observed-bug fix: a supervisor alive with a missing status file
    must still be detected on the next scan after the TTL.
- [ ] ⬜ **Task 1.3**: Correct the module docstring (lines ~27-32) — the fast
  path (cheap `os.kill` liveness probe) applies only AFTER a supervisor has
  been resolved; document the negative-cache throttle for the no-supervisor
  case.

### Phase 2: Cosmetic cleanups (non-blocking nits)

- [ ] ⬜ **Task 2.1**: `core/event.py` — reconcile the stale 11-entry `EventKey`
  literal with the canonical hook-event catalogue introduced in Plan 00170.
- [ ] ⬜ **Task 2.2**: De-duplicate the `_STATUS_*_KEY` constants duplicated
  across `core/input_schemas.py` / `core/response_schemas.py` into a single
  source of truth.

### Phase 3: Verify

- [ ] ⬜ Run QA: `./scripts/qa/llm_qa.py all` (all checks pass, 95% coverage)
- [ ] ⬜ Restart daemon and verify RUNNING
- [ ] ⬜ Live-verify the status line still shows the correct top-hat states

## Success Criteria

- [ ] No `/proc` walk on every render for non-ccy projects (throttled)
- [ ] Live supervisor with missing status file still detected within the TTL
- [ ] Docstring matches behaviour
- [ ] Cosmetic nits resolved
- [ ] All QA checks pass; daemon restarts cleanly

## Delivery & Milestones

<!-- Record delivery commit hashes here as work lands. -->
