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

### Phase 1: Tick starvation fix (claude-supervise.py) — ✅ DONE

- [x] ✅ **Task 1.1**: `_forward_io` runs `on_poll` on a monotonic interval even when I/O is continuously readable; transparent passthrough unchanged; all forward-IO tests green.

### Phase 2: CRITICAL tier in the shared classifier — ✅ DONE

- [x] ✅ **Task 2.1**: `ContextTier.CRITICAL`, `critical_pct` on `TierThresholds`/`TierConfig`, `is_critical` helper; `is_red` spans RED+CRITICAL so the trigger holds above critical. Thresholds: 200k crit 90%, 1000k crit **60%** (user-adjusted from 55→50→60).

### Phase 3: Sidecar + status line wiring — ✅ DONE

- [x] ✅ **Task 3.1**: sidecar writes `critical` flag + `tier: "critical"`; `{size}k_critical_pct` options shared via `shares_options_with`.
- [x] ✅ **Task 3.2**: `model_context` renders CRITICAL as a literal `🛑 COMPACT NOW` (bold bright-red on bright-red bg) in place of the circle icon (user request).

### Phase 4/5: Supervisor consumes critical + ESC-flush + human dedup — ✅ DONE

- [x] ✅ **Task 4.1**: `SidecarReading.critical` parsed; `_cooldown_elapsed(critical=True)` bypasses cooldown; cap/await/resume paths unchanged.
- [x] ✅ **Task 5.1 (ESC-flush)**: `Decision.WOULD_ESCAPE` + `escape_after_seconds` (default 60 < await 120); once-latched, idle-gated, suppressed for human-originated awaits; raw `\x1b` injected with NO submit (armed) / visible marker (dry-run).
- [x] ✅ **Task 5.2 (human /compact dedup)**: `HumanInputLine.take_compact_submitted()` detects a submitted `/compact` from forwarded stdin (Enter only, not Ctrl-U/C); machine enters AWAIT without injecting so no duplicate `/compact` (which Claude Code aborts). Still resumes via the compaction signal.

### Phase 6: ccy deploy consistency (user concern #2) — ⬜ TODO

On upgrade the supervisor is deployed/armed, but `ccy.deploy_supervisor` may be
`false` (explicit opt-out) while the armed supervisor is physically present.
`deploy_ccy_supervisor_if_enabled` returns early on `false`, so it NEVER
refreshes the deployed script on future upgrades → clients run a stale
supervisor forever. Surface this contradictory state.

- [ ] ⬜ **Task 6.1**: `ccy_supervisor_integrity` (SessionStart) warns when the supervisor is armed+present but `deploy_supervisor is False` (present-but-opted-out ⇒ upgrades won't refresh it; recommend setting `true`).

### Phase 7: QA + daemon + integration — ⬜ TODO

- [ ] ⬜ **Task 7.1**: `./scripts/qa/llm_qa.py all` green; daemon restart RUNNING; full supervisor + status-line test modules green.

## Success Criteria

- [x] `on_poll` fires on the poll interval during continuous child output (unit-proven)
- [x] CRITICAL tier classified, surfaced in sidecar + status line (`🛑 COMPACT NOW`)
- [x] Critical bypasses cooldown; idle-floor + empty-box guards intact
- [x] ESC-flush emulates the `[esc]` needed to run a queued `/compact`
- [x] Human `/compact` no longer double-compacted by the supervisor
- [ ] ccy deploy/present inconsistency surfaced
- [ ] All QA checks pass; daemon RUNNING after restart

## Notes & Updates

### 2026-07-11

- Plan scaffolded. Root cause diagnosed from `claude-supervise.py` `_forward_io`
  (tick ran only on the `select` timeout branch, starved during output streaming)
  and the live decision log (compact fired at 80% vs 76% red; zero deferrals).
- Scope confirmed with user: Both parts in one plan; CRITICAL bypasses cooldown
  only (idle-floor + empty-box guards preserved).
- User follow-ups folded in: (a) ESC-flush for queued `/compact`; (b) `🛑 COMPACT NOW` status text at critical; (c) 1000k critical at 60%; (d) supervisor must not
  double-compact when a human `/compact` is queued; (e) ccy deploy/present
  consistency (Phase 6).
- Delivery commits: Phase 1 tick starvation; Phase 2-4 CRITICAL classifier+
  sidecar+status; COMPACT NOW status; Phase 5 supervisor (critical bypass, ESC-
  flush, human dedup).
- Failsafe recovery cron: `8c48954e` (hourly at :37, non-durable).
