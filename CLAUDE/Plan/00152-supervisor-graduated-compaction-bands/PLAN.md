# Plan 00152: supervisor graduated compaction bands

**Status**: In Progress
**Created**: 2026-07-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The ccy PTY supervisor (`.claude/ccy/claude-supervise.py`) injects `/compact`
into the session when the daemon-written context sidecar reports `red`. Since
Plan 00151 the supervisor tick fires on a fixed monotonic interval (fixing tick
starvation), so at red the compact now fires **very promptly** — mid-turn,
while the agent is actively working. The previous behaviour (pre-00151) was that
the compact was effectively *blocked whilst the child was streaming output*: the
tick was starved during busy bursts and only fired once the session settled.
The user found that "wait for a lull" behaviour valuable at the red threshold.

This plan restores a graduated response keyed to how deep into the danger zone
the context is, using three bands defined by the existing red and critical
thresholds:

- **Red band** `[red_pct, midpoint)`: patient — defer `/compact` until the child
  output has settled (work-idle), restoring the pre-00151 "blocked whilst things
  were happening" behaviour so an in-progress turn is never interrupted.
- **Elevated band** `[midpoint, critical_pct)` where
  `midpoint = (red_pct + critical_pct) // 2`: the current behaviour — inject
  `/compact` promptly on the next idle tick even while the child is busy.
- **Critical band** `[critical_pct, 100]`: prompt `/compact` **plus** the ESC-key
  flush escalation (interrupt the in-flight turn so a queued `/compact` runs).

## Goals

- Add a `compact_urgent` band (the midpoint between red and critical) as a single
  source of truth in `context_tiers`, emitted on the sidecar exactly like `red`
  and `critical` so the stdlib-only supervisor never re-thresholds a raw pct.
- Track child→stdout output activity in the supervisor and derive a `work_idle`
  signal ("the turn has settled").
- Gate the red band's `/compact` on `work_idle` (patient); let the elevated and
  critical bands act promptly even while the child streams.
- Restrict the ESC-flush escalation to critical (latched at inject time OR a
  live-critical reading during await).
- Preserve every existing guard: human-keystroke idle, empty-input-box, human
  `/compact` dedup, cooldown, injection cap, compaction-resume `continue`.

## Non-Goals

- No new display tier / status-line colour (the midpoint is a supervisor concept
  only; the 5 visible tiers are unchanged).
- No change to how or when the daemon writes the sidecar (still every Status
  render).
- No change to the armed/dry-run injection payloads.

## Context & Background

- Sidecar sensor: `handlers/status_line/context_sidecar.py` (writes
  `{red, critical, tier, pct, ...}`).
- Tier SSOT: `handlers/status_line/context_tiers.py` (`is_red`, `is_critical`).
- Supervisor actuator: `.claude/ccy/claude-supervise.py` (single tracked copy;
  self-install dogfoods it in place). State machine = `CompactStateMachine`.
- Loaded in tests via `tests/unit/supervise/_load.py`.

## Tasks

### Phase 1: context_tiers midpoint band (SSOT)

- [ ] ⬜ **Task 1.1**: RED — add failing tests to
  `tests/unit/handlers/status_line/test_context_tiers.py` for
  `compact_urgency_pct(thresholds)` and `is_compact_urgent(pct, window, cfg)`
  (200k midpoint 83; 1000k midpoint 50; critical implies urgent; below midpoint
  not urgent).
- [ ] ⬜ **Task 1.2**: GREEN — implement `compact_urgency_pct` +
  `is_compact_urgent` in `context_tiers.py`.

### Phase 2: sidecar emits compact_urgent

- [ ] ⬜ **Task 2.1**: RED — extend sidecar handler tests to assert the payload
  carries `compact_urgent`.
- [ ] ⬜ **Task 2.2**: GREEN — emit `compact_urgent` in
  `context_sidecar.py` payload via `is_compact_urgent`.

### Phase 3: supervisor SidecarReading + machine bands

- [ ] ⬜ **Task 3.1**: RED — tests: `SidecarReading.compact_urgent` loaded
  (defaults False when absent); red-band `/compact` deferred when `work_idle`
  False; elevated band compacts despite `work_idle` False; ESC only for a
  critical-driven await.
- [ ] ⬜ **Task 3.2**: GREEN — add `compact_urgent` to `SidecarReading` +
  `load_freshest_sidecar`; thread `work_idle` through `evaluate` /
  `_evaluate_monitor` (defer non-urgent red when not work-idle;
  `urgent = compact_urgent or critical`); latch `escalate` on inject and gate
  ESC in `_evaluate_await` on escalate-or-live-critical.

### Phase 4: child-output tracking + wiring

- [ ] ⬜ **Task 4.1**: RED — tests for `OutputActivity.record`, `_is_work_idle`,
  and `_poll_once` passing `work_idle` into the machine.
- [ ] ⬜ **Task 4.2**: GREEN — add `OutputActivity`, record master→stdout bytes
  in `_forward_io`, compute `work_idle` in `_on_poll`, thread through
  `_poll_once`; add `work_settle_seconds` policy/param.

### Phase 5: integration, QA, dogfood

- [ ] ⬜ **Task 5.1**: Run full QA: `./scripts/qa/run_all.sh`.
- [ ] ⬜ **Task 5.2**: Restart daemon, verify RUNNING (sidecar change is in the
  daemon); regenerate docs if handler summary changed.
- [ ] ⬜ **Task 5.3**: Config-changes / truth-changes manifests if warranted.

## Success Criteria

- [ ] Red-band `/compact` waits for the child to settle (no mid-turn interrupt).
- [ ] Elevated band injects `/compact` promptly even mid-turn.
- [ ] Critical band injects `/compact` and escalates with ESC.
- [ ] All existing supervisor/sidecar/tier tests still pass; coverage ≥ 95%.
- [ ] Full QA passes; daemon restarts RUNNING.

## Notes & Updates

### 2026-07-12

- Plan scaffolded.
- Failsafe recovery cron: `d4cb559d` (hourly at :37, non-durable).
  </content>
  </invoke>
