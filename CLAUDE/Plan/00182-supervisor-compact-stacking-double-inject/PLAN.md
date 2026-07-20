# Plan 00182: supervisor compact stacking / double-inject

**Status**: In Progress
**Created**: 2026-07-20
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The ccy PTY supervisor (`.claude/ccy/claude-supervise.py`) injected TWO
`/compact` commands back-to-back into the Claude Code REPL when only one should
ever be in flight. Observed live:

```
❯ /compact 🤖 [ccy-supervisor] automated compaction — NOT human-initiated...
❯ /compact 🤖 [ccy-supervisor] automated compaction — NOT human-initiated...
  ⎿  Not enough messages to compact.
❯ 🤖 [ccy-supervisor] continue
```

The second `/compact` ran after the first had already compacted, producing
"Not enough messages to compact." This plan reproduces the desync with a
failing test, fixes the host↔worker IPC so a stale decision can never be
injected, and closes the loop with QA + the version-lockstep test.

## Root Cause (code-verified)

**This is NOT a state-machine defect.** `AWAIT_COMPACTING` correctly prevents
in-process re-injection (the machine emits `WOULD_COMPACT` once, then only fires
`[esc]` to flush a queued compact — verified). The double-`/compact` is a
**host ↔ policy-worker IPC desync**, confirmed against the code by a review
agent and re-verified line-by-line:

1. The PTY host offloads each tick's decision to a subprocess `PolicyWorker`.
   `PolicyWorker.decide()` (claude-supervise.py:2362-2385) uses a
   **one-write / one-blocking-read** protocol with **no correlation id and no
   stale-reply drain**: it writes the facts (line 2368), then
   `select.select([proc.stdout], [], [], self._read_timeout)` (line 2373) and,
   on `not ready`, returns `None` so the host falls back to computing the
   decision **in-process** (lines 2374-2375).
2. The worker read timeout `_WORKER_READ_TIMEOUT_SECONDS = 2.0` (line 125)
   **equals** the poll interval `_DEFAULT_POLL_SECONDS = 2.0` (line 1822). A
   worker tick that runs just over 2 s — realistic, since it scans all of
   `/proc` via `cached_own_session_ids` — times out. The host falls back and
   injects `/compact` **#1**.
3. On the NEXT tick, `proc.stdout.readline()` (line 2377) returns the worker's
   now-**buffered stale `WOULD_COMPACT` reply** from the previous slow tick.
   `_apply_decision` (line 2101) injects **any non-None payload**
   (`if outcome.payload is not None: _perform_injection(...)`) **without
   re-checking the host's authoritative `AWAIT_COMPACTING` state** — so
   `/compact` **#2** is injected on top of the still-queued #1. When the long
   turn ends, both fire: #1 compacts; #2 hits "Not enough messages to compact."

Plan 00164 fixed the *fallback-machine* divergence but not this
*pipe-buffer* divergence. The supervisor also never parses child output —
`output_activity.record(...)` (line 2552) uses it for timing only — so the
"Not enough messages" no-op is invisible and cannot self-correct.

**Relation to Plan 00180**: unrelated to *this* 2-compact incident (the
injection cap was never approached). Plan 00180 fixed the lifetime-cap fuse,
which would only matter for a *repeated* compact loop, not this stale-reply
double-inject.

## Goals

- Reproduce the desync with a failing test: a `decide()` timeout (fallback +
  in-process inject) followed by a buffered stale `WOULD_COMPACT` reply on the
  next tick, asserting NO second injection.
- Make a stale/late worker reply structurally un-injectable (correlation +
  drain), so a timed-out tick's reply is never consumed on a later tick.
- Add a host-side state guard so a `WOULD_COMPACT` payload is never injected
  while the host is already in `AWAIT_COMPACTING` (defence in depth).
- Reduce worker-tick latency (cut the `/proc` scan cost) and/or decouple the
  read timeout from the poll interval so a normal slow tick does not desync.
- Keep the version-lockstep test green (`__version__` ↔ `version.py`).

## Non-Goals

- No change to the compaction decision policy (thresholds/tiers/bands, cooldown,
  CRITICAL urgency) — only the IPC correctness and injection guard are in scope.
- No REPL-output parsing feature (detecting "Not enough messages" by scraping
  child output is a heavier, separate idea — note it, don't build it here).
- No change to the `AWAIT_COMPACTING` state machine logic itself (it is correct).

## Tasks

### Phase 1: Reproduce (RED)

- [x] ✅ **Task 1.1**: Added `test_decide_drops_stale_buffered_reply` (+ siblings:
  only-stale→None, matching-reply, worker echoes id, roundtrips) in
  `test_policy_worker.py` driving the IPC path. Meaningful RED by construction —
  pre-fix `decide()` returns the stale `/compact`; pre-fix `_apply_decision`
  injects it.

### Phase 2: Fix the IPC desync (GREEN)

- [x] ✅ **Task 2.1**: Added a per-request `tick_id` to `TickFacts`/`TickOutcome`
  (+ serialization + worker echo). `PolicyWorker.decide()` stamps each request
  and drains/discards any reply whose id does not match, returning None (safe
  fallback) if only stale replies arrive.
- [x] ✅ **Task 2.2**: State-guarded `_apply_decision` with a `host_state` param:
  a `WOULD_COMPACT` outcome is suppressed (logged NOOP) while the host is already
  `AWAIT_COMPACTING`. Wired from the host loop passing `machine.state.value`.

### Phase 3: Reduce desync frequency

- [x] ✅ **Task 3.1**: Throttled the worker's `/proc` environ scan in
  `cached_own_session_ids` to `_OWN_SESSION_SCAN_TTL_SECONDS = 30.0` — once the
  own-session set is known, most ticks return the accumulated set without
  touching `/proc`, keeping the tick well under the 2s read timeout. Fail-safe:
  an EMPTY cache always re-scans so session discovery is never starved.
  `now` is injectable for tests.

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Full supervise suite green (346 tests, +22 new across the
  two files); version-lockstep test (`TestSupervisorVersionMatchesDaemon`) green.
- [x] ✅ **Task 4.2**: `llm_qa.py all` green (12/13; the one "fail" is the format
  check auto-fixing the file — re-run shows 0), 10413 tests, 95.3% cov,
  type_check/lint/security/error_hiding all clean. NOTE: the supervisor is a
  standalone process the daemon does not load, so a daemon restart does not
  exercise it — the true dogfood is a **ccy relaunch under sustained CRITICAL
  context** (out of band for this session; left as the live-verification step).

## Dependencies

- Related: Plan 00164 (fixed fallback-machine divergence; introduced the
  host/worker split this bug lives in). Related: Plan 00180 (supervisor
  injection-cap reset — same file, different mechanism). Related: Plan 00151
  (CRITICAL tier / cooldown-bypass — raises re-decision frequency, so it makes a
  desync more likely to actually inject).

## Success Criteria

- [ ] The RED regression test passes after the fix and fails without it.
- [ ] A timed-out worker tick can never cause a second injection — proven by a
  test that buffers a stale `WOULD_COMPACT` and asserts it is dropped.
- [ ] `_apply_decision` refuses to inject `WOULD_COMPACT` while `AWAIT_COMPACTING`.
- [ ] Worker tick latency is bounded below the read timeout in the common case;
  no wedge, no regression to compaction timing.
- [ ] QA green; version-lockstep green; ccy relaunch verified.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Activity log lives in JOURNAL/. -->

- Root cause verified (host↔worker IPC stale-reply desync) + reproduction path
  identified (this document) at plan creation.
