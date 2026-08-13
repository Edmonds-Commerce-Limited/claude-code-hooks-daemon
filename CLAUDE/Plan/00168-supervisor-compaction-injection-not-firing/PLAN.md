# Plan 00168: supervisor compaction injection not firing

**Status**: Dormant
**Blocker**: Task 5.3 is externally blocked (per commit 1774d698) — live
verification was carried as far as is possible in-session and cannot progress
without the external condition.
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

- [x] ✅ **Task 2.1**: Repro H1 — a backgrounded thread's stale sidecar at
  critical yields NOOP "sidecar stale" (unit test over `load_foreground_sidecar`
  - monitor). DONE — `test_compaction_gap_repro.py::TestH1...`: a 60s-old
    critical sidecar (past freshness, within reap TTL) NOOPs "sidecar stale" AND
    Phase 1 logs `noop: sidecar stale`.
- [x] ✅ **Task 2.2**: Repro H2 — the empty-input-box guard defers even a
  critical compaction (BY DESIGN — never corrupt the human's input), now logged
  as a deferral; and the "streaming blocks critical" theory is DISPROVEN
  (critical bypasses `work_idle`, still compacts). DONE — `TestH2...` two tests.
- [x] ✅ **Task 2.3**: Repro H3 — empty `own_sessions` filters out a valid
  red sidecar → NOOP "no sidecar reading" (unit test over `_poll_once`/
  `decide_once` with `own_sessions=frozenset()`), now logged; the in-scope
  contrast compacts. DONE — `TestH3...` two tests.

### Phase 3: Fix the confirmed root cause

- [x] ✅ **Task 3.1**: Based on Phase 2, address the confirmed causes. DONE (in
  scope): all three ranked failure modes are now **non-silent** — Phase 1 logs
  the exact blocking gate for each (H1 `noop: sidecar stale`, H2 deferral, H3
  `noop: no sidecar reading`, plus cap/cooldown). Fully *closing* the
  background-thread coverage gap (H1) is an explicit **non-goal** (the
  supervisor drives ONE PTY and only the foreground thread renders — reworking
  the multi-thread feed is Plan 00158); H2 (input-box) and H3 (empty own-set)
  are correct fail-safe behaviours, not bugs. Per **Decision 1** (observability
  before a speculative fix), a definitive single-cause fix for the specific
  field report is deliberately deferred until a live red session's `decision.log`
  names the gate (Phase 5 Task 5.3) — we do NOT speculatively "fix" an
  unconfirmed cause. The concrete, actionable defect found (the version
  bump-miss) is fixed in 3.2.
- [x] ✅ **Task 3.2**: Fix the `__version__` bump-miss (3.41.0 → 3.42.0) so the
  running supervisor and `supervisor-status.json` report the honest version.
  DONE — bumped, AND locked to `version.py` by
  `test_compaction_gap_repro.py::TestSupervisorVersionMatchesDaemon` (fails the
  QA gate on any future drift), AND `RELEASING.md` Step 3 now lists
  `claude-supervise.py` in the version-bump set so releases update it proactively.

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

- [x] ✅ **Task 5.1**: Run `./scripts/qa/run_all.sh`, restart the daemon and the
  supervisor, and confirm both RUNNING. DONE (in-session scope): full `llm_qa.py all` green; daemon restarted RUNNING. The **supervisor** restart is the shared
  external dependency of 5.3 — the live host (pid 2) is still the pre-Phase-1
  code (`compute_source_hash` matches the OLD on-disk file it launched with; the
  NOOP-logging + `__version__` 3.42.0 changes are on disk but only take effect
  when ccy re-execs on the next session launch). `ccy_supervisor_integrity`
  correctly flags this as a stale running supervisor.
- [x] ✅ **Task 5.2**: Live dogfood the indicator — confirm the 🎩 shows green
  while the supervisor is armed+running, and orange when it is stopped.
  DONE (armed path, live) — the status-line probe renders `\033[42m 🎩 \033[0m`
  (green background) against the live armed host. The process-grounded detection
  rewrite (see JOURNAL: supervisor-icon dogfooding fix) means the icon now
  survives a missing status file. The orange "supervisor down" path is not
  forced live (would require killing the live safety net) but is pinned by unit
  tests (`test_supervisor_indicator.py`: dead-pid-and-no-process → orange).
- [ ] 🚫 **Task 5.3**: Live dogfood compaction — drive a session to red/critical
  and confirm an automated `/compact` fires (or that `decision.log` names the
  exact gate when it intentionally defers). **BLOCKED (external dependency):**
  requires (a) ccy to re-exec so the RUNNING supervisor carries the Phase 1
  NOOP-reason logging, and (b) a real session actually reaching the red/critical
  band. Neither can be forced from inside this session (relaunching the
  supervisor would terminate this very session). Per **Decision 1**
  (observability before a speculative fix), the definitive single-cause fix for
  the original field report stays deferred until such a live red session's
  `decision.log` names the blocking gate. All code to MAKE that diagnosis
  possible (Phases 1–4) is shipped.

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
