# Plan 00166: supervisor multi terminal session isolation

**Status**: Dormant
**Blocker**: Needs a human at TWO terminals — not a decision to resume. All 17
tasks across Phases 1–5 are ticked and the implementation shipped; what remains
is closure verification. Success criteria 3–5 are met (22 tests in
`tests/unit/supervise/test_session_identity.py` pass; QA green; daemon restarts
RUNNING). Criteria 1–2 require live two-terminal / Agent-View dogfooding that
cannot be performed from inside a single session. Commit 26e4a71f asserts
criterion 1 was confirmed live, but that is left UNTICKED here because it is a
commit message rather than a check this plan witnessed.
**Created**: 2026-07-15
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

When two terminals each run `ccy` against the SAME repo, a compaction in
terminal A can inject the post-compaction `continue` message into terminal B's
Claude PTY. The user observed the mis-injection appearing to follow whichever
gnome-terminal tab they were interacting with.

Code review confirms this is a **design-level cross-session bug**, not a race.
The daemon "sensor" half is correctly session-scoped: it writes
`<session_id>.json` context sidecars and `<session_id>.compacting` compaction
signals into the ONE shared per-repo directory
(`untracked/context-sidecar/`). The supervisor "actuator" half is NOT: each
terminal runs its own supervisor process, but every supervisor reads that same
shared directory and matches signals by **freshness / first-fresh-file**, never
by session identity. So terminal A's `A.compacting` file is seen by BOTH
supervisors, and terminal B's supervisor injects `continue` into terminal B's
own PTY.

The existing multi-thread reasoning (Plan 00160 "foreground ambiguity") was
scoped to Agent-View threads *within one Claude instance sharing one PTY/one
supervisor*. It uses "freshest sidecar == foreground thread" as a proxy for
identity. That proxy is unsound the moment there are N independent Claude
instances (N terminals) writing into the same shared directory, because there
is no single foreground across instances and no per-instance filter.

## Goals

- Confirm the root cause with a reproducible dogfooding test across two live
  ccy terminals in this repo.
- Make each supervisor act ONLY on context sidecars and compaction signals that
  belong to its own Claude instance's session family (the main session plus any
  Agent-View / subagent sessions spawned under it).
- Preserve the existing within-instance foreground-thread behaviour (Plan 00160
  / 00151 / 00152 bands) once the cross-instance filter is in place.
- Add regression tests that fail on the current cross-injection behaviour and
  pass once identity filtering lands.

## Non-Goals

- Reworking the daemon-side sensor writers (they are already session-keyed and
  correct). Any daemon change here is limited to ADDING identity metadata the
  supervisor needs (e.g. a family/root-session field), never changing existing
  fields.
- Giving every session its own isolated daemon. Parallel sessions deliberately
  share one daemon (Plan 00127); the fix must work WITH the shared daemon and
  shared sidecar dir.
- Changing the compaction decision bands / timing (Plan 00151/00152/00164).

## Context & Background

Confirmed evidence (code review + live `/proc` inspection in this container):

- **Sensor is session-keyed** (correct):
  - `context_sidecar.py` writes `<session_id>.json` with a `session_id` field.
  - `compaction_signal.py` writes `<session_id>.compacting`.
  - Both land in the single shared `daemon_untracked_dir()/context-sidecar/`.
- **Actuator has NO identity filter** (the bug), three match sites in
  `.claude/ccy/claude-supervise.py`:
  - `load_compaction_signal` (lines ~886-909) returns the FIRST `*.compacting`
    within TTL — any session's.
  - `load_foreground_sidecar` / `_scan_sidecars` (lines ~807-864) pick the
    max-`ts` `*.json` across ALL sessions.
  - `SidecarReading.session_id` exists (line ~595, populated ~877) but is never
    compared to anything.
  - `decide_once` (lines ~1400-1456) merges whichever compaction signal it
    found onto the reading and injects `continue` into ITS OWN PTY.
- **Live process topology** (this container, one terminal):
  - Supervisor = pid 2 (`claude-supervise.py --arm -- claude …`); its Claude
    child = pid 76. Supervisor DOES know its child pid.
  - `/proc/76/environ` has `CLAUDE_CODE_SESSION_ID` **empty** — Claude sets the
    session id internally AFTER exec, so it is NOT in the child's exec-time
    environ snapshot. Reading the child's own `/proc/<pid>/environ` will NOT
    yield the session id.
  - Claude's DESCENDANTS do carry it: bash tool child (pid 40674) and the
    Explore subagent (pid 23779) both show `CLAUDE_CODE_SESSION_ID=…`. The
    subagent is reparented to pid 1 (tini), so a naive subtree walk misses it.
  - The shared sidecar dir already held TWO sessions from ONE terminal (main
    `7ef60468…` + subagent `2e5ea61e…`) — proving the "session family per
    instance" reality that any fix must respect.
  - `ccy` keeps per-session dirs under `.claude/ccy/session-env/<session_id>/`.

## Hypotheses (ranked, testable)

### H1 — Root cause: no per-instance identity filter (HIGH confidence)

Each supervisor reads the shared sidecar dir and matches by freshness /
first-fresh-file, never by session identity, so it acts on OTHER terminals'
sidecars and compaction signals. **Test**: dogfood two terminals (see Phase 1);
trigger a compaction in A and watch for `continue` injected into B. Expected:
reproduces. This is the primary hypothesis; all others are corroborating.

### H2 — The compaction-signal path is the sharpest cross-injection vector

`load_compaction_signal` returns the FIRST fresh `*.compacting` regardless of
which sidecar was freshest, so even a supervisor whose own session is idle and
NOT freshest will resume on a foreign compaction. **Test**: in terminal B, keep
the session idle (do not interact), compact in A; if B still injects `continue`,
the signal path (not just the freshest-sidecar path) is implicated.

### H3 — "Followed the tab I was interacting with" == freshest-sidecar effect

The mis-injection tracked the interacted terminal because only a foreground /
recently-rendering session refreshes its sidecar `ts`, so the interacted
terminal's sidecar is freshest and wins `load_foreground_sidecar`. **Test**:
compact in A while interacting with B; observe whether the injection lands in B
(freshest) rather than A (the one that compacted).

### H4 — Identity IS recoverable for the fix (feasibility, HIGH confidence)

The supervisor can bind to its child Claude's session family without daemon
help via the child's OPEN TRANSCRIPT fd:
`/proc/<child_pid>/fd/*` → readlink → `~/.claude/projects/<slug>/<session_id>.jsonl`.
**Test**: from pid 2, resolve pid 76's open `.jsonl` under the projects dir and
confirm the stem equals the main session id `7ef60468…`. Determine whether the
main Claude process ALSO holds subagent transcripts open (family discovery) or
whether the family must be assembled another way (e.g. daemon stamping a
`root_session_id` into each sidecar).

### H5 — A daemon-stamped family id may be required for Agent-View subagents

If H4 shows the main process does not hold subagent transcripts open, the
supervisor cannot discover the family from fds alone. The daemon (which sees
`CLAUDE_CODE_SESSION_ID` and possibly a parent/root id in every hook payload)
may need to stamp a `root_session_id` into each sidecar so the supervisor can
group `{sidecars where root_session_id == my child's session id}`. **Test**:
inspect hook payloads for a parent/root session field; inspect subagent sidecar
JSON for anything linking it to its parent.

## Tasks

### Phase 1: Reproduce via dogfooding (two live terminals)

- [x] ✅ **Task 1.1**: Two `ccy` terminals started (A=`7ef60468`, B=`e7247afe`)
  against the shared sidecar dir; both session ids recorded (JOURNAL 13:30).
- [x] ✅ **Task 1.2**: Process topology captured — supervisor pid + Claude child
  pid per terminal; shared `context-sidecar/` listed before/during/after a
  compaction (JOURNAL 13:30).
- [x] ✅ **Task 1.3**: Compaction triggered in B; daemon wrote
  `e7247afe.compacting` into the ONE shared dir; deterministic module-level
  proof showed terminal A's `load_compaction_signal()` returns B's foreign
  signal with no session filter — confirms H1/H2/H3 (JOURNAL 13:30).

### Phase 2: Confirm identity binding is available (feasibility)

- [x] ✅ **Task 2.1**: H4 DISPROVEN by live `/proc` probe — claude keeps NO
  `.jsonl` transcript open; no process in the container holds any transcript
  open, so the fd→transcript route is not viable (JOURNAL 14:10).
- [x] ✅ **Task 2.2**: Family-discovery mechanism found — `CLAUDE_CODE_SESSION_ID`
  is present in claude's DESCENDANT process environs (learnable + cacheable).
  Each `ccy` terminal is a separate container/PID namespace, so the env scan
  surfaces ONLY the local family; foreign sessions leak only via the shared
  on-disk surfaces the actuator must filter. Daemon-stamped `root_session_id`
  (H5) is NOT required for the minimal fix.
- [x] ✅ **Task 2.3**: Decision 1 recorded below — learn+cache own session-id set
  from container process env; filter the shared dir to own ids; FAIL SAFE (act
  on nothing) until the id is learned.

### Phase 3: Implement identity-scoped matching (TDD)

- [x] ✅ **Task 3.1**: Failing tests written first (RED) in
  `tests/unit/supervise/test_session_identity.py` — `load_compaction_signal`,
  `load_foreground_sidecar`, and `_scan_sidecars` must ignore sidecars /
  signals whose session id ∉ the own-session set. Two-instance fixtures
  included (foreign session freshest + foreign `.compacting`).
- [x] ✅ **Task 3.2**: Added the namespace-broad resolver to the supervisor:
  `_session_ids_from_environ`, `resolve_own_session_ids` (scans `/proc/<pid>/environ`
  for `CLAUDE_CODE_SESSION_ID`), and `cached_own_session_ids` (union-accumulates,
  stable per claude process). Fail-safe empty set = act on nothing. Production
  callers `run_worker` and the main loop `_poll_once` resolve it once per tick.
- [x] ✅ **Task 3.3**: Threaded `own_sessions` through all THREE match sites
  (`_scan_sidecars`, `load_foreground_sidecar`, `load_compaction_signal`) and
  `decide_once`/`_poll_once` via `_session_in_scope` (None = no filter, keeps
  the Plan 00160 within-family foreground disambiguation untouched).
- [x] ❌ **Task 3.4**: NOT NEEDED — Decision 1 (option B, namespace-broad) makes
  the daemon-side `root_session_id` stamp (H5) unnecessary: each `ccy` terminal
  is its own container/PID namespace, so the env scan already excludes foreign
  sessions. No sensor change required. Deferred as a possible later refinement
  only if a `--pid=host` shared-namespace deployment ever needs precise grouping.

### Phase 4: Verify, QA, dogfood again

- [x] ✅ **Task 4.1**: Full QA green — `./scripts/qa/llm_qa.py all` → 13/13
  PASSED (mypy covers `claude-supervise.py`; tests 10142 passed, coverage
  95.3%; error_hiding 0). Daemon restarted and verified RUNNING (pid 163442).
- [x] ✅ **Task 4.2**: Deterministic live proof against REAL `/proc` + real
  filter logic (JOURNAL entry) — `cached_own_session_ids()` returns `{7ef60468}`
  only (never B's `e7247afe`); with the own filter A's `load_compaction_signal`
  returns `None` for B's fresh `e7247afe.compacting` (bug fixed) while still
  returning A's own signal (no regression). A full two-terminal live re-dogfood
  additionally requires relaunching BOTH `ccy` terminals so their running
  supervisors pick up the new `claude-supervise.py` (the live supervisors run
  the pre-fix code until re-exec) — user can do this at leisure; the fix is
  deterministically proven.

### Phase 5: Worker error safety net (flood containment)

Triggered by a live dogfooding incident: live-editing the shared supervisor
file left a brief window where the worker's `main()` called
`_redirect_worker_stderr_to_log()` before it was defined, so every worker the
OLD host respawned `NameError`'d and flooded BOTH PTYs (the host inherits the
worker's stderr and restarts a dead worker every tick). See JOURNAL 16:45.

- [x] ✅ **Task 5.1**: Route ALL worker diagnostics to a FILE, never the PTY —
  `worker_error_log_path` / `open_worker_error_log` / `append_worker_error`
  (`untracked/claude-supervise-worker.err.log`); `open_*` → None falls back to
  `subprocess.DEVNULL`, never the inherited terminal.
- [x] ✅ **Task 5.2**: `PolicyWorker.start` passes `stderr=<log|DEVNULL>` to
  Popen and closes the handle in `close()`; host-side worker-lifecycle noise
  rerouted from `sys.stderr` to the error log.
- [x] ✅ **Task 5.3**: `_redirect_worker_stderr_to_log` — the worker's first
  action in `--worker` mode dup2's fd 2 onto the log so it self-contains even
  under an OLD host (defence in depth).
- [x] ✅ **Task 5.4**: `run_worker` per-tick `except Exception` guard → traceback
  to FILE + safe `_worker_error_noop()` so a bad tick never kills the worker
  (no crash-loop) and the host still gets a reply.
- [x] ✅ **Task 5.5**: Regression tests in
  `tests/unit/supervise/test_worker_error_safety_net.py` (9): survives raising
  `decide_once`, zero stderr leak, bad-tick logged-not-stderr, start never
  inherits stderr, DEVNULL fallback. mypy clean; 278 supervise tests pass.

## Technical Decisions

### Decision 1: Source of the supervisor's session-family identity

**Context**: The supervisor must know which session ids belong to its own Claude
instance to filter the shared sidecar dir. The child's own environ does not
expose the session id (verified empty). Candidate sources: (A) child's open
transcript fd under the projects dir; (B) walking Claude descendants' environ
for `CLAUDE_CODE_SESSION_ID`; (C) a daemon-stamped `root_session_id` in each
sidecar.

**Options Considered** (Phase 2 live-probe evidence, JOURNAL 14:10):
(A) child's open transcript fd — **DISPROVEN**: claude keeps no transcript open,
no process holds any `.jsonl` open. Not viable.
(C) daemon-stamped `root_session_id` — not required for the minimal fix; deferred
as a possible later refinement for precise Agent-View family grouping.
(B) walk Claude descendants' `CLAUDE_CODE_SESSION_ID` — **WORKS**: present in
claude's child processes, learnable + cacheable. Each `ccy` terminal is a
separate container/PID namespace, so an env scan surfaces only the local
family; the probe saw A's `7ef60468` but never B's `e7247afe`.

**Decision**: Adopt **(B)**, **namespace-broad** variant (user steer). The
supervisor learns its own session-id SET by scanning its container's process
environs (`/proc/<pid>/environ`) for `CLAUDE_CODE_SESSION_ID` — treating EVERY
id found in its own PID namespace as "mine" — CACHES it (ids are stable per
claude process; the set only grows), and filters the shared sidecar/signal dir
to act only on files whose `session_id` ∈ that set. FAIL SAFE: an empty/unknown
set means act on NOTHING (never resume/compact off an unidentified signal). This
is correct under the one-container-per-terminal deployment `ccy` uses; it is
over-broad only if a deployment shares a PID namespace across terminals (e.g.
`--pid=host`), for which the `CLAUDE_HOOKS_SOCKET_PATH` / `_PID_PATH` /
`_LOG_PATH` socket-isolation escape hatch remains available. The precise
direct-child subtree variant was rejected: subagents reparent to pid 1 (tini)
and would be missed, whereas the namespace-broad scan catches the whole family.
**Date**: 2026-07-15

## Success Criteria

- [ ] Two-terminal dogfood: a compaction in terminal A never injects `continue`
  (or `/compact`, or `[esc]`) into terminal B.
- [ ] Within a single instance, Agent-View foreground compaction and
  post-compaction resume still behave as before (Plan 00160/00151/00152).
- [ ] New regression tests fail on current code and pass after the fix.
- [ ] Full QA passes and the daemon restarts RUNNING.
- [ ] Identity resolution fails safe (no foreign action when identity unknown).

## Delivery & Milestones

- Root cause confirmed by code review + live `/proc` topology (pre-implementation).
