# Plan 00164: supervisor lifecycle and upgrade clarity

**Status**: In Progress
**Created**: 2026-07-14
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Four related fixes/features, shipped together in one release. (1) Client-project
upgrades always print "Already at version X" and take the idempotent fast path
even on a genuine version jump, because Layer 1 (`scripts/upgrade.sh`) checks out
the target tag BEFORE Layer 2 (`scripts/upgrade_version.sh`) evaluates its
git-ref idempotency check — so the check is always true. This misleads the agent
into thinking nothing happened AND silently disables the full-upgrade path
(config preservation/merge, breaking-change detection, snapshot/rollback,
upgrade-guide enforcement) for every client upgrade.

(2) The ccy PTY supervisor (`claude-supervise.py`) launches with no visible
feedback during the perceptible start-up lull. Add an informative ASCII banner +
spinner so a launching ccy session shows "[ ECHD Supervisor starting … ]".

(3) The supervisor carries no version marker and advertises its running version
nowhere, so after a daemon upgrade delivers a NEW `claude-supervise.py` to disk,
there is no way to tell the STILL-RUNNING supervisor is stale. Add a supervisor
`__version__`, have the running supervisor advertise it, and add a SessionStart
advisory that compares the on-disk supervisor version against the running one and
tells the user a ccy restart is required to pick up the new supervisor.

(4) The supervisor runs all decision logic in-process with the PTY loop that owns
the live `claude` child, so it can never reload without killing the session.
Split it into a thin PTY host (owns `claude`, stable) plus a restartable "policy
worker" subprocess (sidecar read + state machine + injection decision). The
worker can be killed and respawned from the new on-disk version without touching
the PTY/`claude` child — making the parts that change most hot-reloadable.

## Goals

- Client upgrades report the TRUE from→to transition and only say "already at
  version" on a genuine no-op; the full-upgrade path (config preservation etc.)
  runs on real version jumps.
- The ccy supervisor shows an informative, good-looking startup banner + spinner
  covering the launch lull.
- A stale running supervisor (on-disk version newer than running version) is
  detected and surfaced at session start with a clear "restart ccy" instruction.
- Supervisor decision logic runs in a restartable worker subprocess; the PTY host
  owning `claude` stays up across a worker reload.
- All changes ship in a single release with full QA, daemon-restart verification,
  and acceptance coverage.

## Non-Goals

- No change to the compact/injection POLICY behaviour (thresholds, cooldowns,
  guards) — only where that logic RUNS (Phase 4) and how it is versioned.
- No automatic ccy restart — staleness is surfaced advisory-only (Phase 3).
- No change to the daemon↔supervisor sidecar schema semantics beyond adding
  supervisor-version advertisement.

## Context & Background

Key files (all under `/workspace`):

- `scripts/upgrade.sh` — Layer 1: pre-checks-out target, then delegates.
- `scripts/upgrade_version.sh` — Layer 2: idempotency + full-upgrade orchestrator.
- `.claude/ccy/claude-supervise.py` — the single tracked supervisor (dogfooded;
  deployed to client `.claude/ccy/` by `install/ccy_supervisor.py`).
- `src/.../handlers/session_start/ccy_supervisor_integrity.py` — existing ccy
  advisory; natural neighbour for the staleness check (Phase 3).
- `src/.../handlers/status_line/context_sidecar.py` — daemon-side sensor writing
  the context sidecar the supervisor reads.

The supervisor is intentionally stdlib-only and standalone (no daemon-venv
import) so a broken daemon venv can never take down ccy launches. Phase 4 MUST
preserve that property: host and worker both run under the container `python3`.

## Tasks

### Phase 1: Upgrade clarity (the "already upgraded" fix)

- [ ] ⬜ **Task 1.1**: Add failing tests capturing the bug — Layer 2 must take the
  full-upgrade path when the installed/from version differs from target, and only
  the idempotent path on a true no-op; "Already at version" must not print on a
  genuine jump.
- [ ] ⬜ **Task 1.2**: Pass Layer 1's captured `FROM_VERSION` into Layer 2 and base
  the idempotency decision + messaging on from-vs-target (and venv-stamp health),
  not the post-checkout git ref.
- [ ] ⬜ **Task 1.3**: Clarify all upgrade output so a refresh vs a true no-op vs a
  real jump are each unambiguous; verify the full-upgrade path (config
  preservation) runs on a real jump.
- [ ] ⬜ **Task 1.4**: QA + shellcheck + targeted upgrade tests green; daemon restart.

### Phase 2: Supervisor startup banner + version marker

- [ ] ⬜ **Task 2.1**: Add failing tests for a `__version__` constant and a
  banner-rendering function (deterministic, no-TTY-safe, honours a no-banner env).
- [ ] ⬜ **Task 2.2**: Add `__version__` to `claude-supervise.py` kept in lockstep
  with the daemon version, and render the ASCII banner + spinner to stderr during
  the startup lull (before/around the PTY fork), TTY-aware and silent when piped.
- [ ] ⬜ **Task 2.3**: QA green; manual visual check of the banner.

### Phase 3: Stale-supervisor detection

- [ ] ⬜ **Task 3.1**: Add failing tests — running supervisor advertises its version
  to a known runtime location; a SessionStart advisory warns when the on-disk
  supervisor version is newer than the running one (and is silent otherwise).
- [ ] ⬜ **Task 3.2**: Running supervisor writes a small `supervisor-status` runtime
  file (pid + version + started-at) on start; remove/ignore on exit.
- [ ] ⬜ **Task 3.3**: Extend the ccy supervisor advisory (SessionStart) to compare
  on-disk `claude-supervise.py` `__version__` vs the running status file and emit a
  clear "running supervisor is stale — restart ccy to load vX.Y.Z" advisory.
- [ ] ⬜ **Task 3.4**: `get_claude_md()` guidance updated; QA green; daemon restart.

### Phase 4: Restartable policy-worker split (hot reload)

- [ ] ⬜ **Task 4.1**: Design the host↔worker protocol (line-delimited JSON over a
  pipe: host streams sidecar-tick facts + input-line state; worker replies
  inject/defer decisions) and record it in this plan. No behaviour change.
- [ ] ⬜ **Task 4.2**: Add failing tests for the worker entry point (given tick
  facts, returns the same decisions the in-process state machine does today) and
  for host↔worker framing/round-trip.
- [ ] ⬜ **Task 4.3**: Extract decision logic (`CompactStateMachine`, `_poll_once`
  and pure helpers) behind a worker entry point that runs as a subprocess of the
  same file (`claude-supervise.py --worker`), keeping stdlib-only + standalone.
- [ ] ⬜ **Task 4.4**: Make the PTY host spawn/supervise the worker, forward tick
  facts, apply returned decisions, and respawn the worker on death — with a
  fallback to in-process decisions if the worker cannot start (never break a
  session).
- [ ] ⬜ **Task 4.5**: Reload trigger — host detects the on-disk supervisor version
  changed (Phase 3 marker) and respawns the worker from the new code without
  touching `claude`; log the reload.
- [ ] ⬜ **Task 4.6**: QA green; live PTY smoke test that a worker restart does not
  disturb the wrapped child; daemon restart.

### Phase 5: Release

- [ ] ⬜ **Task 5.1**: Full QA suite green (`./scripts/qa/run_all.sh`).
- [ ] ⬜ **Task 5.2**: Config/truth-change manifests if warranted; changelog inputs.
- [ ] ⬜ **Task 5.3**: Run `/release` — single release shipping all four changes.

## Dependencies

- Phase 3 and Phase 4 both use the supervisor `__version__` from Phase 2.
- Phase 4's reload trigger uses the runtime status marker from Phase 3.

## Success Criteria

- [ ] A genuine client upgrade prints the true from→to and runs the full-upgrade
  path; a repeat upgrade at the same version cleanly says "already at version".
- [ ] ccy launch shows the banner + spinner; silent when stdout/err is not a TTY.
- [ ] A stale running supervisor is flagged at session start with restart guidance.
- [ ] Killing the policy worker mid-session leaves the wrapped child undisturbed and
  the worker respawns; a new on-disk version reloads the worker without a ccy
  restart.
- [ ] All QA checks pass; daemon restarts RUNNING; released via `/release`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Blow-by-blow log lives in JOURNAL/. -->

- Plan created at 00163 follow-on; execution starting on Phase 1.
