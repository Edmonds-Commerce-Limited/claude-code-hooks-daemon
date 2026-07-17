# Plan 00171: supervisor indicator proc scan negative caching

**Status**: Complete
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

- [x] ✅ **Task 1.1**: Reproduce the cost with a failing test
  - File: `src/claude_code_hooks_daemon/handlers/status_line/supervisor_indicator.py`
  - Symptom: when no supervisor is configured, `_cached_pid` is never populated
    (memoisation only happens in `_activate`, reached only when a supervisor IS
    found). So `_detect_state` -> `_resolve_state` -> `_scan_for_supervisor`
    walks all of `/proc` reading every pid's `cmdline` on **every** render.
    Severity: LOW (fail-safe, bounded by process count) but affects an
    on-by-default handler on every status-line render.
  - [x] ✅ Failing test: `_scan_for_supervisor` is NOT re-invoked on every render
    once a "no supervisor" resolution was made within the throttle window
    (`TestSupervisorIndicatorNegativeCaching`, 5 new tests).
- [x] ✅ **Task 1.2**: Implement time-throttled negative caching
  - `_negative_cache_state` + `_negative_cache_until` (monotonic deadline,
    `_NEGATIVE_CACHE_TTL_SECONDS = 5.0`) reused within the window; any positive
    resolution and a dropped stale positive cache both clear it, so a
    replacement/newly-started supervisor is picked up within one TTL.
- [x] ✅ **Task 1.3**: Corrected the module docstring — documents the positive
  (`os.kill` liveness) fast path AND the new negative-cache throttle.

### Phase 2: Cosmetic cleanups (non-blocking nits)

- [x] ✅ **Task 2.1**: `constants/events.py` — completed the stale 11-entry
  `EventKey` literal to the full 31-event catalogue (declaration order) and
  pinned it against `all_event_metas()` with a drift-guard test
  (`tests/unit/constants/test_events.py`).
- [x] ✅ **Task 2.2**: De-duplicated the StatusLine dual-naming constants into
  `constants/events.py` (`STATUS_LINE_JSON_KEY` / `STATUS_SCHEMA_KEY`);
  `core/input_schemas.py` and `core/response_schemas.py` now import them.

### Phase 3: Verify

- [x] ✅ Run QA: `./scripts/qa/llm_qa.py all` — 13/13 PASSED (10267 tests, 0
  failed, 95.3% coverage, smoke 3/3)
- [x] ✅ Restart daemon and verify RUNNING (PID 193495, new code loaded)
- [x] ✅ Live-verify the status line: green top-hat still renders under the live
  ccy supervisor; `daemon_stats` health-only; `upgrade_notifier` silent

## Success Criteria

- [ ] No `/proc` walk on every render for non-ccy projects (throttled)
- [ ] Live supervisor with missing status file still detected within the TTL
- [ ] Docstring matches behaviour
- [ ] Cosmetic nits resolved
- [ ] All QA checks pass; daemon restarts cleanly

## Delivery & Milestones

<!-- Record delivery commit hashes here as work lands. -->

- All three findings landed in a single follow-up commit (see the closing
  commit for `Plan 00171: Complete`). Phase 1 negative caching +
  `TestSupervisorIndicatorNegativeCaching` (5 tests); Phase 2 `EventKey`
  catalogue reconciliation + `tests/unit/constants/test_events.py` (6 tests) and
  StatusLine dual-naming de-dup into `constants/events.py`.
