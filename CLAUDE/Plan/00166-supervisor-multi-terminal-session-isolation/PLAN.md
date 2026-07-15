# Plan 00166: supervisor multi terminal session isolation

**Status**: In Progress
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

- [ ] ⬜ **Task 1.1**: With the user, start a SECOND `ccy` session in this repo
  in a separate terminal so two supervisors run against the shared sidecar
  dir. Record both session ids from `untracked/context-sidecar/*.json`.
- [ ] ⬜ **Task 1.2**: Instrument observation without interfering: tail the
  supervisor decision log(s) and list `untracked/context-sidecar/` before,
  during, and after a compaction. Identify each supervisor's PID and its
  Claude child PID.
- [ ] ⬜ **Task 1.3**: Trigger a compaction in terminal A (manual `/compact` or
  drive context high) and observe whether terminal B injects `continue`.
  Capture the decision-log lines that show B acting on A's signal. This
  confirms H1/H2/H3.

### Phase 2: Confirm identity binding is available (feasibility)

- [ ] ⬜ **Task 2.1**: Prove H4: resolve the child Claude PID's open transcript
  `.jsonl` under `~/.claude/projects/<slug>/` from the supervisor's vantage
  and confirm it yields the correct main session id.
- [ ] ⬜ **Task 2.2**: Determine family-discovery mechanism: check whether the
  main Claude process holds Agent-View / subagent transcripts open, and
  inspect hook payloads / subagent sidecars for a parent/root session link
  (resolves H5 — fd-based family vs daemon-stamped `root_session_id`).
- [ ] ⬜ **Task 2.3**: Decide the identity source (Technical Decision 1) and
  record it, with the fallback behaviour when identity cannot be resolved
  (must FAIL SAFE — act on nothing rather than act on a foreign session).

### Phase 3: Implement identity-scoped matching (TDD)

- [ ] ⬜ **Task 3.1**: Write failing tests: `load_compaction_signal`,
  `load_foreground_sidecar`, and `_scan_sidecars` must ignore sidecars /
  signals whose session id is not in the supervisor's family set. Include a
  two-instance fixture (foreign session freshest + foreign `.compacting`).
- [ ] ⬜ **Task 3.2**: Add a session-family resolver to the supervisor
  (child-pid → session family) with a fail-safe empty-set default and
  caching (fd/transcript lookups are not free per tick).
- [ ] ⬜ **Task 3.3**: Thread the family filter through the three match sites so
  only in-family files are considered; keep the Plan 00160 foreground
  disambiguation operating WITHIN the family.
- [ ] ⬜ **Task 3.4**: If H5 holds, add the minimal daemon-side `root_session_id`
  stamp to the sidecar/signal writers (sensor) plus its unit tests; keep all
  existing fields unchanged.

### Phase 4: Verify, QA, dogfood again

- [ ] ⬜ **Task 4.1**: Run full QA (`./scripts/qa/run_all.sh`) and restart the
  daemon; verify RUNNING.
- [ ] ⬜ **Task 4.2**: Re-run the Phase 1 two-terminal dogfood; confirm a
  compaction in A no longer injects into B, and that within-instance
  Agent-View compaction/resume still works.

## Technical Decisions

### Decision 1: Source of the supervisor's session-family identity

**Context**: The supervisor must know which session ids belong to its own Claude
instance to filter the shared sidecar dir. The child's own environ does not
expose the session id (verified empty). Candidate sources: (A) child's open
transcript fd under the projects dir; (B) walking Claude descendants' environ
for `CLAUDE_CODE_SESSION_ID`; (C) a daemon-stamped `root_session_id` in each
sidecar.

**Options Considered**: to be finalised after Phase 2 evidence. Leaning A for
the main session id (stable, cheap, no daemon change) + C for family discovery
if the main process does not hold subagent transcripts open.

**Decision**: TBD (Task 2.3). Must fail safe: unknown identity => act on nothing.
**Date**: TBD

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
