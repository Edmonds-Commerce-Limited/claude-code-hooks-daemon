# Plan 00182: supervisor compact stacking / double-inject

**Status**: Not Started
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

- [ ] ⬜ **Task 1.1**: Add a failing test in the supervise suite that drives the
  IPC path: worker `decide()` times out (host falls back, injects #1), then the
  next tick's `readline()` yields the previous tick's buffered `WOULD_COMPACT`
  reply — assert the host does NOT inject a second `/compact` (no test today
  exercises timeout-then-stale-reply; existing tests cover only the Plan 00164
  fallback-state path and happy-path IPC).

### Phase 2: Fix the IPC desync (GREEN)

- [ ] ⬜ **Task 2.1**: Add a per-tick correlation id to the worker
  request/response and drain/discard any reply whose id does not match the
  current tick (or drain `proc.stdout` before each write). A reply from a
  timed-out tick must never be consumed later.
- [ ] ⬜ **Task 2.2**: State-guard `_apply_decision` (line 2101): do not inject a
  `WOULD_COMPACT` payload while the host is in `AWAIT_COMPACTING`; log a NOOP
  reason instead. Defence in depth so any future desync cannot double-inject.

### Phase 3: Reduce desync frequency

- [ ] ⬜ **Task 3.1**: Cache/throttle the worker's `/proc` scan
  (`cached_own_session_ids`) so a normal tick stays well under the read timeout;
  and/or set the read timeout distinct from (and appropriately related to) the
  poll interval so a merely-slow tick degrades to one clean fallback rather than
  a stale-reply desync.

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full supervise suite + the new desync regression test
  green; version-lockstep test green.
- [ ] ⬜ **Task 4.2**: `./scripts/qa/run_all.sh` (or `llm_qa.py all`) passes;
  daemon restart RUNNING. The supervisor is a standalone process — a live ccy
  relaunch under sustained CRITICAL context is the true dogfood check.

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
