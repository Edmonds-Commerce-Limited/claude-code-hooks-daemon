# Plan 00361: supervisor worker crash loop visibility and backoff

**Status**: Complete
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The ccy supervisor's decision brain runs in a `--worker` subprocess that the
PTY host respawns whenever the on-disk source's content hash changes (the
edit-to-live contract, Plan 00164 Phase 4). The host's dead-worker handling is
`if not worker.alive(): worker.restart()` on every tick, and a worker that
cannot answer makes the host decide in-process with its own, older code.
Nothing records any of this: `decision.log` never mentions the worker, and the
worker's fatal tracebacks reach its error log through raw stderr with no
timestamp and no source fingerprint.

The owner reported the supervisor had become "much less stable" across the
recent releases. The worker error log holds 165 fatal tracebacks between
2026-09-04 and 2026-09-08 whose module-level line numbers match NO committed
version of the file: every one is a worker spawned from an INTERMEDIATE
on-disk state of an in-tree edit (Plan 00328 deleting the keystroke model
recognition accounts for 88 of them: `take_model_submitted` removed before
its call site, then `human_model_command` passed to a `TickFacts` that no
longer had the field). Each intermediate state crash-looped the worker once
per tick for as long as the state persisted, with the host silently deciding
in-process throughout, and there was no way to tell from the logs.

## Goals

- A worker death is visible in `decision.log` with its exit code, the source
  fingerprint it was spawned from, and whether the host respawned it.
- A worker that dies repeatedly on the SAME source fingerprint is not
  respawned every tick: the host backs off, logs the crash loop ONCE, and
  retries when the source changes or the backoff elapses.
- The transition between worker-answered ticks and host in-process fallback
  ticks is logged in both directions, so a stretch of fallback decisions can
  be seen and dated.
- A worker's own fatal crash is recorded in its error log WITH a timestamp
  and the source fingerprint, so a traceback can be dated and matched to a
  version of the file.

## Non-Goals

- No change to the edit-to-live contract itself: the worker still reloads
  from the on-disk file on a content-hash change, and a stale worker is still
  never left running against changed code.
- No blue/green swap (keeping the old worker alive until the candidate
  answers its first tick). It is the stronger fix for "the host fallback runs
  older code", but it needs a probe protocol; this plan makes the failure
  visible and cheap first, and records blue/green as follow-up work.
- No change to the worker's per-tick `decide_once` safety net.

## Tasks

### Phase 1: Evidence

- [x] ✅ **Task 1.1**: Classify every traceback in the worker error log by error
  kind and module-level line number; confirm none matches a committed version
  (see Overview for the result).

### Phase 2: Visibility and backoff (TDD)

- [x] ✅ **Task 2.1** (delivered at `da5b7258`): Worker-side fatal-crash record: the `--worker` branch of
  `main()` catches an escaped exception from `run_worker`, appends a
  timestamped `worker crashed (source <fingerprint>)` entry with the full
  traceback to the worker error log, and exits non-zero. Hot-reloadable.
- [x] ✅ **Task 2.2** (delivered at `da5b7258`): `WorkerCrashGuard` (pure, host-side): given the dead
  worker's fingerprint, exit code, the on-disk fingerprint and the time,
  decides whether to respawn now and what single line to log. First death on
  a fingerprint: respawn and log. Repeated death on the same fingerprint:
  log the crash loop once, then hold respawns to `_WORKER_CRASH_BACKOFF_SECONDS`
  until the source changes. A worker that answers a tick after a loop logs
  `worker recovered`.
- [x] ✅ **Task 2.3** (delivered at `da5b7258`): `_make_worker_decider` takes the `DecisionLog`, routes
  dead-worker handling through the guard, and writes the guard's lines.
  `PolicyWorker` exposes the fingerprint it was spawned from, the on-disk
  fingerprint, and the last exit code.
- [x] ✅ **Task 2.4** (delivered at `da5b7258`): `FallbackTransitions` (pure): logs `worker did not answer -> host deciding in-process` and `worker answering again` on transitions
  only; wired into `supervise()` at the decider call.

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Supervisor unit suite green; QA on the touched files;
  live worker pid changed after the edit (Task 2.1 is live at once; Tasks
  2.2 to 2.4 are host-side and take effect at the next ccy session start).
  Verified live in the ccy session started after `da5b7258`: one deliberate
  worker kill produced `worker died (exit -15, source 894adfae14bd) -> respawned` in `decision.log` and a new worker pid.

## Success Criteria

- [x] A deliberately crashing worker produces a dated, fingerprinted entry in
  the worker error log and a `worker died` line in `decision.log`.
- [x] A worker dying twice on the same fingerprint is respawned once, logs the
  crash loop once, and is respawned again as soon as the fingerprint changes.
- [x] All QA checks passing (full QA 26/26 on main after the Plan 00362 merges).
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/09-supervisor-worker-crash-loop-visibility.md`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00361-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Evidence gathered and plan filed.
- Phase 2 delivered at `da5b7258` (guard, transitions, accessors, crash record,
  18 tests); the worker-side crash record went live on reload at pid 906006.
  Phase 3's live check of the host-side lines waits for the next ccy session
  start, since the host process never reloads.
