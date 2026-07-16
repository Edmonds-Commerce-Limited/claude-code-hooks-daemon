# Plan 00168: supervisor compaction injection not firing

**Status**: In Progress
**Created**: 2026-07-16
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A user reports the ccy PTY supervisor's **compaction injection** stopped firing:
an agent ran all the way to the "COMPACT NOW" (critical) context tier and never
received an automated `/compact`. This feature is high value — when it works it
keeps long sessions alive by auto-compacting at the red/critical bands — so a
silent regression is serious.

This plan captures a live diagnostic pass (2026-07-16) that VERIFIED the healthy
parts of the mechanism and RULED OUT several suspected causes, then ranks the
remaining live hypotheses. It did **not** find a single definitive bug from the
diagnosing session (that session stayed green/yellow, so the supervisor
correctly never injected). The single most important corrective action is
**observability**: the supervisor currently logs nothing on NOOP ticks, so a
red-but-not-compacting session leaves zero diagnostic trace of WHY. That gap is
why "we think there are bugs maybe" cannot yet be turned into "the log says
exactly which gate blocked."

## Verified facts (live, 2026-07-16)

- Supervisor is **armed and running**: host `pid 2` + policy-worker `pid 77`
  (`claude-supervise.py --worker --arm`).
- Running process == on-disk file: `compute_source_hash` == `ecc6405cd200` for
  both — **NOT stale** relative to disk. (The `__version__ = "3.41.0"` string is
  a cosmetic bump-miss; the repo is v3.42.0 and the deployed file already
  contains the Plan 00166 code.)
- Session-identity filter (Plan 00166) works in this single-session container:
  `resolve_own_session_ids()` → `{ebb47fd7-…}`, equal to `CLAUDE_CODE_SESSION_ID`,
  and `_session_in_scope(mine, own)` → True. The "diverging id sources" theory is
  **disproven** here — the sidecar's `session_id` equals the env-var id.
- Tier classification is a shared single source of truth (`context_tiers.py`):
  CRITICAL ("COMPACT NOW") → `is_red` True → the sidecar's `red` flag is True. No
  label-vs-flag mismatch.
- The mechanism demonstrably worked previously: `decision.log` shows real
  `would-compact` / `would-continue` / `would-escape` injections on 2026-07-15.
- The diagnosing session never went red (yellow, 20%), so the absence of new
  `decision.log` entries is EXPECTED — the log records actions/lifecycle, not
  NOOP ticks.

## Ranked live hypotheses (unverified — need deterministic repro)

1. **Foreground-only injection vs a backgrounded Agent-View thread (most likely
   given the "another agent" wording).** The supervisor drives ONE PTY and acts
   only on the FOREGROUND sidecar (`load_foreground_sidecar` + Plan 00160
   ambiguity deferral). A backgrounded thread stops getting status renders, so
   its sidecar goes **stale** → `_evaluate_monitor` returns NOOP "sidecar stale"
   → a backgrounded agent at COMPACT NOW is never compacted. This is a genuine
   coverage gap for background threads, and it is silent.
2. **The `idle` gate blocks even CRITICAL** (`claude-supervise.py:1353`,
   `if not idle: NOOP`). `idle = facts.idle AND facts.input_line_empty`. A
   session that streams continuously (never a quiet select-timeout tick) or that
   has stray non-whitespace text in the input box (a known prior live failure —
   the "input box not empty" deferral) never injects, even at critical. Silent.
3. **Plan 00166 empty `own_sessions` edge.** Disproven in the diagnosing
   container, but a timing/namespace edge (supervisor scans `/proc` before any
   descendant exports `CLAUDE_CODE_SESSION_ID`; or a supervisor restart against
   an idle session; or `/proc` invisibility) yields an empty own-session set →
   every sidecar filtered out → NOOP "no sidecar reading". Silent, fail-safe-to-
   nothing.

## Goals

- Make every NOOP tick self-explaining so a red-but-not-compacting session is
  diagnosable from `decision.log` alone.
- Deterministically reproduce each ranked hypothesis with a test.
- Close the confirmed root cause(s), including the background-thread coverage gap
  if that is the failure.
- Fix the cosmetic `__version__` bump-miss so the running version is honest.

## Non-Goals

- Reworking the whole Agent-View multi-thread status feed (that is Plan 00158).
- Changing the tier thresholds or the compaction payloads.

## Tasks

### Phase 1: Observability first (make NOOP ticks self-explaining)

- [x] ✅ **Task 1.1**: Write failing tests for rate-limited NOOP-reason logging:
  when the sidecar is red/critical but the tick decides NOOP, `decision.log` must
  record the gate that blocked (stale / not-in-scope / not-idle / input-box /
  cooldown / cap / foreground-ambiguous), deduplicated so it never floods.
  DONE — `DecisionLog.write_noop` dedup tests (test_decision_log.py), `_poll_once`
  NOOP-logging tests (test_injection.py: red-busy gate, critical band, no-sidecar,
  benign-green silent, injection-not-noop), and worker-wire roundtrip
  (test_policy_worker.py).
- [x] ✅ **Task 1.2**: Implement the rate-limited NOOP-reason log in the tick
  path (host + policy-worker) without changing decisions. DONE — `TickOutcome`
  gains `noop_reason_log` (wired through `_outcome_to_json`/`_from_json`);
  `decide_once` sets it for every NOOP gate EXCEPT the benign positively-not-red
  steady state (so a green idle session's log stays empty, but the H1 "sidecar
  stale" / H3 "no sidecar reading" blind-spots ARE recorded); `_apply_decision`
  writes it via `DecisionLog.write_noop`, deduped on the low-cardinality message
  (`noop: <reason> [band]`) so an unchanged gate logs once. Decision-preserving
  (pure logging). Live-restart confirmation of a red session is folded into
  Phase 5 Task 5.3 (needs a session relaunch to re-exec the supervisor).

### Phase 2: Deterministic reproduction of each hypothesis

- [ ] ⬜ **Task 2.1**: Repro H1 — a backgrounded thread's stale sidecar at
  critical yields NOOP "sidecar stale" (unit test over `load_foreground_sidecar`
  - monitor).
- [ ] ⬜ **Task 2.2**: Repro H2 — critical + `idle=False` (streaming) and
  critical + non-empty input box both yield NOOP (unit test over the monitor
  gate at line 1353 and the empty-input-box guard).
- [ ] ⬜ **Task 2.3**: Repro H3 — empty `own_sessions` filters out a valid
  red sidecar → NOOP "no sidecar reading" (unit test over `decide_once` with
  `own_sessions=frozenset()`).

### Phase 3: Fix the confirmed root cause

- [ ] ⬜ **Task 3.1**: Based on Phase 2, fix the confirmed cause with TDD. For H1
  (background-thread gap) design a safe coverage path or an explicit, logged
  "background thread not covered" signal so it is never silent.
- [ ] ⬜ **Task 3.2**: Fix the `__version__` bump-miss (3.41.0 → current) so the
  running supervisor and `supervisor-status.json` report the honest version.

### Phase 4: Supervisor active/armed status-line indicator

At-a-glance visibility that the safety net is on — complements the Phase 1
observability. Self-contained status-line handler; needs NO supervisor change.

- [x] ✅ **Task 4.1**: TDD a new `supervisor_indicator` status-line handler that
  reads `{daemon_untracked}/supervise/supervisor-status.json` → `pid`, checks
  liveness (`os.kill(pid, 0)`; EPERM == alive) and reads `/proc/<pid>/cmdline`
  as a pid-reuse guard (`claude-supervise` substring) + armed detection
  (`--arm`). Renders a top hat 🎩 with a state-coloured ANSI **background**
  (green armed / yellow dry-run / orange down) and NO segment when no
  supervisor is configured. Immutable (pid, armed) identity is MEMOISED; a
  crash still flips to orange via the per-render liveness probe. Fail-safe: any
  error → no segment, never breaks the line. 100% coverage.
- [x] ✅ **Task 4.2**: Priority 13 (adjacent to the context section:
  model_context=10, context_sidecar=12); ON by default (safe — renders nothing
  when no supervisor status file exists); enabled in THIS repo. Registered
  HandlerID/Priority, export, config + example config, regenerated docs;
  daemon restarted RUNNING and live-dogfooded (`\033[42m 🎩 \033[0m`).

### Phase 5: Verify

- [ ] ⬜ **Task 5.1**: Run `./scripts/qa/run_all.sh`, restart the daemon and the
  supervisor, and confirm both RUNNING.
- [ ] ⬜ **Task 5.2**: Live dogfood the indicator — confirm `🛡️🟢` shows while the
  supervisor is armed+running, and `🛡️🟠` when it is stopped.
- [ ] ⬜ **Task 5.3**: Live dogfood compaction — drive a session to red/critical
  and confirm an automated `/compact` fires (or that `decision.log` names the
  exact gate when it intentionally defers).

## Technical Decisions

### Decision 1: Observability before a speculative fix

**Context**: The diagnosing session was healthy, so no single bug reproduced. The
supervisor logs only actions, making silent NOOPs undiagnosable.
**Decision**: Ship NOOP-reason logging FIRST (Phase 1) so the next red session
that fails to compact self-reports the blocking gate, converting guesswork into
evidence. Only then fix the confirmed cause. **Date**: 2026-07-16

## Success Criteria

- [ ] A red/critical session that does not compact records the blocking gate in
  `decision.log` (no silent NOOPs).
- [ ] Each ranked hypothesis has a deterministic test.
- [ ] The confirmed root cause is fixed with a regression test.
- [ ] `__version__` reports the honest current version.
- [ ] QA passes; daemon + supervisor restart clean.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). The blow-by-blow activity log lives in JOURNAL/. -->

- Live diagnostic pass captured (2026-07-16): mechanism verified healthy,
  session-isolation + staleness ruled out, three live hypotheses ranked.
