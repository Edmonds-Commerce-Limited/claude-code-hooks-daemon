# Plan 00151: supervisor tick starvation and critical tier

**Status**: In Progress
**Created**: 2026-07-11
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The ccy PTY supervisor (`.claude/ccy/claude-supervise.py`) is meant to inject
`/compact` when the context sidecar goes red and the session is idle. In
practice it "holds back" on busy threads and lets context climb past red. Root
cause: the supervisor tick (`on_poll`) only runs on the `select` timeout branch
in `_forward_io`. While the child is streaming output, `master_fd` is almost
always readable, so `select` returns immediately every iteration and the timeout
branch — the ONLY caller of `on_poll` — never fires. The compact decision is
never evaluated during a busy burst; it only runs once the thread goes quiet, by
which point context has overshot red. Live decision log confirms: compact fired
at 80% on a 200k window (red = 76%), with zero input-box deferrals (so the human
input guard was never the gate — pure tick starvation).

This plan fixes the starvation (Part 1, the real fix) and adds a CRITICAL tier
above red (Part 2, the escalation the user asked for): a louder status-line
signal plus a cooldown bypass so once context is critical the very next idle
tick compacts without waiting out the 300s cooldown. The idle-floor and
empty-input-box guards are preserved at all tiers — critical never injects into
human keystrokes or a non-empty input box.

## Goals

- Supervisor evaluates the compact decision at least every `poll_seconds` even
  while the child is streaming output (no more starvation on busy threads).
- New CRITICAL tier above RED in the shared `context_tiers` classifier, wired
  into the sidecar (`critical` flag + `tier: "critical"`) and the status line
  colour/label.
- At CRITICAL, the compact cooldown is bypassed so the next idle+empty-box tick
  compacts immediately. Idle-floor and empty-box guards remain enforced.
- ESC-flush: after injecting `/compact`, if no compaction starts within
  `escape_after_seconds` (default 60, per-project configurable), inject a single
  `[esc]` to interrupt the turn and flush Claude Code's queued `/compact`.
- Full TDD coverage; daemon restarts RUNNING; supervisor unit tests green.

## Non-Goals

- No change to the empty-input-box guard or the idle-floor semantics (critical
  bypasses cooldown ONLY — chosen aggressiveness level).
- No change to the compaction-signal / resume (`continue`) path.
- Not adding new config surface beyond a critical-pct threshold that shares
  options with `model_context` like the existing tier thresholds.

## Tasks

### Phase 1: Tick starvation fix (claude-supervise.py)

- [ ] ⬜ **Task 1.1**: RED — test `_forward_io` runs `on_poll` on an interval even when I/O is continuously readable
  - [ ] ⬜ Add a monotonic last-tick clock; force a tick when `poll_seconds` elapsed regardless of readability
  - [ ] ⬜ GREEN — implement interval-forced tick; keep transparent passthrough unchanged
  - [ ] ⬜ Verify existing forward-IO tests still pass

### Phase 2: CRITICAL tier in the shared classifier

- [ ] ⬜ **Task 2.1**: RED — tests for `ContextTier.CRITICAL`, `classify_context`, `is_critical`, threshold resolution (200k crit ~90%, 1000k crit ~55%)
  - [ ] ⬜ GREEN — add tier enum member, `critical_pct` to `TierThresholds`/`TierConfig`, `is_critical` helper
  - [ ] ⬜ Keep `is_red` semantics (red band now = red_pct..critical_pct; critical is its own band)

### Phase 3: Sidecar + status line wiring

- [ ] ⬜ **Task 3.1**: RED/GREEN — sidecar writes `critical` + `tier: "critical"`; shares `critical_pct` option
- [ ] ⬜ **Task 3.2**: RED/GREEN — `model_context` status line renders a distinct CRITICAL colour/label

### Phase 4: Supervisor consumes critical (cooldown bypass)

- [ ] ⬜ **Task 4.1**: RED — `SidecarReading.critical`; state machine bypasses cooldown when critical; idle + empty-box still required
  - [ ] ⬜ GREEN — parse `critical` from sidecar JSON; `_cooldown_elapsed` returns True when reading is critical
  - [ ] ⬜ Verify cap + await-timeout + resume paths unchanged

### Phase 5: ESC-flush for queued /compact (user requirement)

Claude Code queues a `/compact` typed mid-turn and does NOT run it until the
current turn is interrupted — the human normally presses `[esc]`. The supervisor
must emulate that: after it injects `/compact` (enters AWAIT_COMPACTING), if no
compaction signal appears within `escape_after_seconds` (default 60, per-project
configurable), inject a single `ESC` (`\x1b`) to interrupt the turn and flush the
queued command. This is distinct from — and shorter than — the existing
`await_timeout_seconds` (120s) that gives up back to MONITOR.

- [ ] ⬜ **Task 5.1**: RED — in AWAIT_COMPACTING, once `escape_after_seconds` elapses with no compaction, decide `WOULD_ESCAPE` exactly once (latched); still gated on idle + empty-box (never ESC over human typing)
  - [ ] ⬜ GREEN — add `Decision.WOULD_ESCAPE`, `_escape_sent` latch, `escape_after_seconds` to `CompactPolicy`; `_resolve_payload` returns the ESC byte for WOULD_ESCAPE (both dry-run and armed — ESC is harmless)
  - [ ] ⬜ Injection writes bare `\x1b` with NO submit `\r` (it is an interrupt key, not a line)
  - [ ] ⬜ Latch resets when compaction starts or the machine returns to MONITOR, so it can re-fire on the next episode
  - [ ] ⬜ Reason logged so the decision log shows the ESC escalation

### Phase 6: QA + daemon + integration

- [ ] ⬜ **Task 6.1**: `./scripts/qa/llm_qa.py all` green; daemon restart RUNNING; supervisor test module green

## Success Criteria

- [ ] `on_poll` fires on the poll interval during continuous child output (unit-proven)
- [ ] CRITICAL tier classified, surfaced in sidecar + status line
- [ ] Critical bypasses cooldown; idle-floor + empty-box guards intact
- [ ] All QA checks pass; daemon RUNNING after restart

## Notes & Updates

### 2026-07-11

- Plan scaffolded. Root cause diagnosed from `claude-supervise.py:814-827` and
  the live decision log (compact fired at 80% vs 76% red; zero deferrals).
- Scope confirmed with user: Both parts in one plan; CRITICAL bypasses cooldown
  only (idle-floor + empty-box guards preserved).
- Failsafe recovery cron: `8c48954e` (hourly at :37, non-durable).
