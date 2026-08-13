# Plan 00160: Supervisor Foreground Identity & Dead-File Reaping

**Status**: Dormant
**Blocker**: The remaining verification needs a live 2-thread Agent-View session, which requires a ccy re-exec that cannot be forced from inside a supervised session — the same external dependency already recorded at Plan 00168 Task 5.3. Phase 3's signal scoping shipped under Plan 00166 with regression tests at `tests/unit/supervise/test_session_identity.py`.
**Created**: 2026-07-13
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded (TDD)

## Overview

The ccy PTY supervisor (`.claude/ccy/claude-supervise.py`, Plan 00135) senses
context state from the daemon-written context sidecars and injects `/compact`
(and `continue`) into its child PTY. It wraps ONE `claude` process on ONE PTY,
but the human uses Agent View in the Claude Code UI to switch between multiple
threads (independent sessions) inside that one UI. Whatever the supervisor types
lands on the **foreground** thread.

Empirical finding (verified against 205 real Status payloads in
`untracked/payload-capture/Status.jsonl` and the live sidecar/registry dirs):

- The Status payload carries **no** focus/foreground/visible/active field
  (Plan 00158 "Truth #1" confirmed across all 205 records).
- **Only the foreground thread renders its `statusLine`.** Two real interactive
  threads (`b2b6dcb4`, `2b651a46`, same human session "Improve Claude Code status
  line with agent threads") switch exactly ONCE across 205 renders — 65 in a
  block, then 52 in a block. Backgrounded threads do NOT keep heartbeating (if
  they did they would alternate every refresh tick). So freshest-by-`ts` sidecar
  ≈ foreground, with a ≤`refreshInterval` (10s) ambiguity window after a switch.
- No cleanup exists for sidecars/signals: 17 files on disk today, most dead since
  Jul 10–12, plus test fixtures. The registry prunes only at read-time (drops
  from the count), never unlinking.

This plan makes "compact the currently-focused session" **explicit and robust**
(not a freshness proxy) and adds dead-file reaping. Actively looping through
background agents to compact them is explicitly OUT OF SCOPE (future, invasive).

## Goals

- **Reaping**: the sidecar/signal directory is bounded — dead
  `{session}.json` / `{session}.compacting` files are reaped on a TTL so they
  never accumulate and never widen the foreground ambiguity window.
- **Explicit foreground identity**: the supervisor acts on the context state of
  the session ACTUALLY foreground in its PTY, from an explicit signal — not
  merely "freshest sidecar" — eliminating the post-switch window.
- **Defensive signal scoping**: a supervisor only ever consumes the compaction
  signal of the session it acted on (closes the multi-`ccy` signal-theft race).
- All changes TDD-first, QA green, daemon restart verified.

## Non-Goals

- Looping through / compacting BACKGROUND threads (future work, invasive).
- Changing the observe-only daemon/actuator boundary (daemon still never types).
- Rewriting the compact state machine (Decision H) semantics.

## Context & Background

Key files:

- `.claude/ccy/claude-supervise.py` — the standalone supervisor (self-install
  canonical; the ccy deploy copies it verbatim — `install/ccy_supervisor.py`).
- `src/claude_code_hooks_daemon/handlers/status_line/context_sidecar.py` — sensor (writes sidecars).
- `src/claude_code_hooks_daemon/handlers/pre_compact/compaction_signal.py` — writes `.compacting`.
- `src/claude_code_hooks_daemon/handlers/status_line/thread_registry.py` — Plan 00158,
  the newer per-session-keyed, atomic-write registry (the model to emulate).
- Plan 00135 (`SPIKES.md`, `HOSTILE-REVIEW-1.md` flagged multi-session).

Verified constraints: refreshInterval = 10s; supervisor freshness = 30s; poll =
2s. The supervisor is stdlib-only and imports nothing from the daemon.

## The foreground-identity mechanism (Phase 2 — spike-gated)

The ONLY mechanism that removes the switch window (rather than shrinking it) is
to read foreground identity from **on-screen ground truth**: only the foreground
thread paints its `statusLine` into the PTY stream the supervisor forwards. If
the daemon tags the rendered status line with the foreground `session_id` in a
way that (a) survives Claude Code's status composition, (b) reaches the PTY
output bytes, and (c) is invisible / non-corrupting to the human, the supervisor
can parse the foreground `session_id` from child output and act only on THAT
session's sidecar.

**This is unverified and must be spiked before building** (Task 2.0). If the
marker cannot be embedded safely, the fallback is an explicit daemon-written
`foreground.json` pointer (last-renderer + ts) plus a "clearly-freshest + margin"
guard — a shrunk window, not a closed one — and that tradeoff is reported back
before shipping Phase 2.

## Tasks

### Phase 1: Dead-file reaping (independent, ship first)

- [x] ✅ **Task 1.1**: RED — tests for a pure reaper: given a dir with fresh +
  stale `*.json` and `*.compacting`, reap only those older than a TTL; never reap
  the freshest; tolerate unlink races (OSError); report reaps. (9 tests, RED confirmed.)
- [x] ✅ **Task 1.2**: GREEN — `reap_stale_sidecars(dir, now, ttl)` in
  `claude-supervise.py`, called once per `_poll_once` tick; TTL threaded via
  `CompactPolicy.reap_ttl_seconds`. 198 supervise tests pass; mypy --strict clean.
- [x] ✅ **Task 1.3**: TTL = `_DEFAULT_REAP_TTL_SECONDS = 1800.0` (30 min) —
  ≥ compaction-signal TTL (600s) and ≫ freshness (30s) / refreshInterval (10s),
  so a live/idle-foreground session (renders every 10s) is never a reap candidate.
- [x] ✅ **Task 1.4**: Evaluated → **deferred** (Decision 3). Supervisor reaper
  bounds the dir robustly (every 2s, all cases incl. crash); a SessionEnd reaper
  would need a THIRD local copy of the `context-sidecar` subdir + safe-stem
  constants (context_sidecar.py + compaction_signal.py already each have one),
  tipping into a DRY-smell that warrants a shared helper — a separate refactor.
- [x] ✅ **Task 1.5**: QA 13/13 green (9901 tests, 95.6% cov), daemon restart
  RUNNING, committed as `2094d76b`. **Phase 1 complete.**

### Phase 2: Explicit foreground identity (guarded freshest-sidecar)

- [x] ✅ **Task 2.0/2.1**: Mechanism chosen = **guarded freshest-sidecar** (user
  approved the recommendation). The marker-parse spike is moot per Decision 2:
  paint ≡ sidecar-write (same statusLine invocation), so a marker carries no
  fresher foreground info than the sidecar. No live spike needed.
- [x] ✅ **Task 2.2**: RED tests — `test_foreground_sidecar.py` (9 tests) for the
  resolver, `TestForegroundAmbiguityGate` (5 tests) for the machine gate, and two
  `_poll_once` integration tests (ambiguous defers / unambiguous injects).
- [x] ✅ **Task 2.3**: GREEN — `load_foreground_sidecar()` returns
  `(freshest_reading, ambiguous)`; ambiguous ⇔ a second still-fresh sidecar's ts
  is within `_DEFAULT_FOREGROUND_MARGIN_SECONDS` (10s) of the freshest.
  `CompactStateMachine.evaluate(..., foreground_ambiguous=)` defers ONLY the
  compact path (resume/AWAIT untouched). `load_freshest_sidecar` refactored to
  share one `_scan_sidecars` pass (DRY, behaviour-preserving — 198 prior tests
  still green). Margin threaded via `CompactPolicy.foreground_margin_seconds`.
  216 supervise tests pass; mypy --strict clean.
- [ ] 🔄 **Task 2.4**: QA green, daemon restart RUNNING, commit. Live verify in a
  real 2-thread Agent View is a follow-up (needs an interactive session; the
  logic is unit-proven and the running supervisor is old code until relaunch).

### Phase 3: Defensive signal scoping

- [ ] ⬜ **Task 3.1**: RED — signal load/consume scoped to a target `session_id`;
  a foreign session's `.compacting` is not consumed.
- [ ] ⬜ **Task 3.2**: GREEN implement; QA; daemon restart; commit.

## Technical Decisions

### Decision 1: Reaping ships first, independent of foreground identity

**Context**: The user confirmed "dead file reaping is something we need." It is
decoupled from the spike-gated foreground mechanism.
**Decision**: Phase 1 lands and commits on its own before Phase 2's spike.

### Decision 2: Foreground mechanism is spike-gated — premise now in question

**Finding (during Phase 1, awaiting live spike confirmation)**: the
"marker-in-painted-statusline" redesign may give NO advantage over a guarded
freshest-sidecar. The sidecar WRITE and the status-line PAINT are driven by the
SAME Claude Code `statusLine` invocation: the daemon's Status handler both writes
`{session}.json` AND returns the `statusLineLeft/Right` that gets painted. So a
marker parsed from the PTY carries the same freshness as the sidecar (both update
on the same event; between invocations the painted marker is cached-stale, same
as the sidecar). Under the VERIFIED model-b (only the foreground renders), the
freshest sidecar already IS the foreground, and the only switch-over window — the
gap between the human pressing the switch key and Claude Code invoking statusLine
for the new thread — is identical for both mechanisms (neither has updated yet).

**Therefore the likely-correct "explicit foreground" mechanism is a GUARDED
freshest-sidecar**, not an ANSI-paint parser: act only when one sidecar is
unambiguously freshest (fresher than the runner-up by a margin covering the
switch settle), else defer one tick; reaping (Phase 1) keeps the field clean.
This is far simpler and less fragile than screen-scraping the PTY.

**Task 2.0 spike must confirm** whether Claude Code ever repaints the foreground
status line with FRESHER thread identity than the sidecar reflects (e.g. repaints
on switch BEFORE re-invoking the hook). If it does not (expected), the marker
approach is pointless. Bring this to the user before building either way — do NOT
silently substitute the guarded-freshest approach for the chosen redesign.

### Decision 3: SessionEnd immediate-reap deferred (not built in Phase 1)

**Context**: A daemon-side SessionEnd handler could delete the ending session's
own `{stem}.json` / `{stem}.compacting` immediately, rather than waiting for the
supervisor's TTL sweep, and would clear the "always-spared freshest" residue.
**Options**: (a) extend the existing `cleanup` SessionEnd handler; (b) new
handler; (c) defer.
**Decision**: Defer (c). The supervisor reaper already bounds the dir robustly
every 2s across all cases (including crash/kill, which SessionEnd does NOT
cover). The only residue is a single spared-freshest file — harmless and
regenerated on the owner's next render. Building it now would add a THIRD local
copy of the `context-sidecar` subdir + safe-stem constants
(`context_sidecar.py` and `compaction_signal.py` each already carry their own),
which tips the DRY smell into "extract a shared helper" — a broader refactor of
released handlers better tracked on its own. Revisit alongside that refactor.
**Date**: 2026-07-13

## Success Criteria

- [ ] Sidecar/signal dir stays bounded across many sessions (reaping verified).
- [ ] Supervisor injects into the foreground thread's state only; a backgrounded
  red thread does not drive an injection into the foreground.
- [ ] A supervisor never consumes another session's compaction signal.
- [ ] All QA checks pass; daemon restarts RUNNING; live 2-thread verify passes.

## Risks & Mitigations

| Risk                                          | Impact | Probability | Mitigation                                                                          |
| --------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------------------- |
| Status-line marker not embeddable / stripped  | High   | Medium      | Spike FIRST (Task 2.0); fall back to pointer + margin guard and report the tradeoff |
| Reaping deletes a live foreground file        | High   | Low         | TTL >> refreshInterval; never reap the freshest; unlink w/ OSError tolerance        |
| Supervisor is stdlib-only — no daemon imports | Med    | —           | Reaper implemented inline in the standalone script                                  |

## Notes & Updates

### 2026-07-13

- Plan created. Failsafe recovery cron: **a8af59d9** (hourly at :37, non-durable).
- Scope confirmed by user: **full redesign** (explicit foreground identity) +
  **dead-file reaping**. Background-thread looping is future / out-of-scope.
- **Phase 1 shipped** (`2094d76b`): per-tick reaper, 11 tests, QA 13/13, live
  17→1. Reaped sidecars self-heal on the owner's next render.
- **Phase 2 gate**: surfaced Decision 2 finding — the marker-parse redesign
  likely has no advantage over a guarded freshest-sidecar (paint ≡ sidecar
  write, same event). Paused for user input before building Phase 2; Task 2.0
  spike needs a live 2-thread Agent-View experiment to confirm.
