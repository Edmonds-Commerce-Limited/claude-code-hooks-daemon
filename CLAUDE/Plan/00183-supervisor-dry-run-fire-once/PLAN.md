# Plan 00183: Supervisor dry-run fires once per session (once only)

**Status**: In Progress
**Created**: 2026-07-20
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded (TDD)

## Overview

The ccy PTY supervisor (`.claude/ccy/claude-supervise.py`) loops in **dry-run**
mode. The state machine is pure and identical in dry-run and armed modes — the
only divergence is *environment feedback*. In armed mode a `WOULD_COMPACT`
decision injects a real `/compact`, the context actually compacts, the
`.compacting` signal appears, the machine resumes and resets — the episode
**resolves** because the real action changed the world. In dry-run the "harmless
marker" is injected **with a trailing Enter** (`submit=True` for every payload
except the armed raw ESC), so (1) the marker becomes a **real prompt line** that
wakes the agent (each fake prompt draws a `STOPPING BECAUSE` reply), and (2)
because the marker never compacts, context stays red, so the machine cycles
`MONITOR → WOULD_COMPACT → AWAIT → WOULD_ESCAPE×max_escapes → MONITOR → …` up to
`max_injections` (20) before the fuse trips — dozens of fake prompts.

**User requirement (verbatim):** *"dry run — it can only fire once per session —
once only."*

## Goals

- In dry-run mode the supervisor injects **at most one** marker for the whole
  session (process lifetime), then stays silent — no loop, no fake-prompt flood.
- Armed-mode behaviour is **completely unchanged**.
- The suppression survives the policy-worker round-trip (Plan 00164 Phase 4: the
  host ships machine state to the worker and adopts the worker's returned state).

## Non-Goals

- No change to compaction bands, cooldowns, or ESC-flush logic.
- No change to armed-mode injection semantics.
- Not switching dry-run to a non-submitting/log-only marker (the once-only latch
  is what was requested).

## Root Cause

`decide_tick` resolves the payload via `_resolve_payload(decision, dry_run=…)`
but nothing tracks that a dry-run demonstration already happened, so every
red+idle episode re-fires. The dry-run marker never changes context, so the loop
only ends when `max_injections` trips.

## Design

Add a **process-lifetime latch** to `CompactStateMachine`: `_dry_run_fired`,
serialised in `export_state()`/`import_state()` (key `dry_run_fired`) so it
round-trips through the policy worker; accessor `dry_run_fired` +
`mark_dry_run_fired()`. Gate at the single choke point `decide_tick` (the whole
"brain", used by the worker AND the in-process fallback), right after
`_resolve_payload`: if `dry_run` and a payload would be injected, suppress it
(payload → None, log a NOOP) when already fired, else mark fired. `_apply_decision`
already guards actual injection on `payload is not None`, so a suppressed tick
performs no PTY write. The first marker still submits once (the intended
end-to-end demonstration); every later tick is a logged NOOP.

## Tasks

### Phase 1: TDD fix

- [x] ✅ **Task 1.1**: RED — failing tests in `tests/unit/supervise/`
  - [x] ✅ dry-run: two consecutive red+idle ticks → first returns a payload,
    second returns `payload is None` (latched)
  - [x] ✅ latch survives `export_state()` → `import_state()` round-trip
  - [x] ✅ armed mode: two red+idle ticks still both inject (regression guard)
- [x] ✅ **Task 1.2**: GREEN — add latch to `CompactStateMachine` + gate in
  `decide_once`; supervisor `__version__` unchanged (matches `version.py`; the
  pending release bumps both in lockstep)
- [x] ✅ **Task 1.3**: Full QA (`./scripts/qa/llm_qa.py all`) 13/13 (10462 tests,
  95.2% cov) + daemon restart RUNNING (PID 1181704)

### Phase 2: Live dogfood

- [ ] ⬜ **Task 2.1**: Relaunch ccy in dry-run, confirm exactly one marker then
  silence (no `STOPPING BECAUSE` flood)

## Success Criteria

- [ ] Dry-run injects at most once per session
- [ ] Armed mode unchanged
- [ ] All QA green, 95%+ coverage, daemon RUNNING
- [ ] Supervisor version matches `version.py`

## Notes & Updates

- Failsafe recovery cron: `e626acaa` (hourly at :37, non-durable, session-only).

## Delivery & Milestones

<!-- commit hashes recorded as tasks land -->
