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

- [x] ✅ **Task 1.1**: Add failing tests for a source-safe transition helper that
  describes the TRUE installed→target transition (`test_upgrade_transition_messages.py`).
- [x] ✅ **Task 1.2**: Add `scripts/install/upgrade_transition.sh` (pure, source-safe
  headline/summary helpers keyed on the venv `.daemon-version` stamp vs target).
- [x] ✅ **Task 1.3**: Wire it into `upgrade_version.sh` — capture `INSTALLED_VERSION`
  from the existing venv stamp BEFORE `ensure_venv`, and replace the misleading
  unconditional "Already at version $TARGET" headline + completion line.
- [x] ✅ **Task 1.4**: shellcheck clean; transition tests + all 39 upgrade
  integration tests green.

**Decision (scope)**: the idempotent deploy block is the effective single path
(Layer 1 always pre-checks-out the tag), so the fix makes ITS messaging truthful
rather than reviving the never-run-in-prod full-upgrade path below it. Reviving
that path (config-preservation baseline + rollback ref are both defeated by
Layer 1's pre-checkout) is a real but separate, risk-managed follow-up — noted
here honestly, not deflected — because activating never-run code across all
clients in one release is a regression risk out of proportion to a messaging fix.

### Phase 2: Supervisor startup banner + version marker

- [x] ✅ **Task 2.1**: Failing tests (`test_supervisor_banner.py`) for `__version__`,
  `render_startup_banner` (deterministic), and `_should_show_banner` TTY/opt-out gate.
- [x] ✅ **Task 2.2**: Added `__version__ = "3.40.0"` (lockstep at release), a pure
  `render_startup_banner`, a TTY/env `_should_show_banner` gate, and a
  `_StartupSpinner` (daemon thread) — banner printed + spinner started before the
  PTY fork and stopped/cleared immediately after, so it never overlaps the child.
- [x] ✅ **Task 2.3**: 222 supervise tests pass; mypy clean; banner visually verified.

### Phase 3: Stale-supervisor detection

- [x] ✅ **Task 3.1**: Failing tests — supervisor status helpers
  (`test_supervisor_status.py`) + SessionStart staleness advisory
  (`TestStaleness` in `test_ccy_supervisor_integrity.py`).
- [x] ✅ **Task 3.2**: Supervisor writes `supervise/supervisor-status.json` (pid +
  version + source content hash + started-at) in `main()` and removes it on exit;
  `compute_source_hash` fingerprints the running script; `_daemon_untracked_dir`
  factored so daemon + supervisor agree on the location.
- [x] ✅ **Task 3.3**: Extended the ccy integrity handler — compares the running
  supervisor's source fingerprint (from the status file, gated on a LIVE pid)
  against the on-disk `claude-supervise.py`; emits a "restart ccy to load the new
  supervisor vX.Y.Z" advisory when they differ. Fingerprint (not just version)
  catches dev edits between releases; dead-pid status never false-alarms.
- [x] ✅ **Task 3.4**: `get_claude_md()` documents the staleness advisory; 33 handler
  tests + 6 status tests pass; mypy clean; QA lint passes; daemon restarted RUNNING.

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

### Phase 6: Output-capture helper (`echd-capture`)

Agents defeat the `pipe_blocker` with pointless theatre — capturing full output to
a file and then echoing ALL of it to stdout anyway (net token bloat). Ship a
first-class helper so the intended "capture full, read a slice" workflow is one
short command.

- [x] ✅ **Task 6.1**: Failing tests (`test_echd_capture.py`) — helper tees FULL
  output to a capture file, prints a bounded tail/`--head` preview + absolute
  capture path; `set -o pipefail` preserves the producer's exit status.
- [x] ✅ **Task 6.2**: Implemented `scripts/echd-capture` (portable bash): tees stdin
  to a capture file (`$ECHD_CAPTURE_DIR` → `$CLAUDE_PROJECT_DIR/untracked/captures`
  → `${TMPDIR}/echd-captures`), prints N-line tail (default 20) / `--head N` /
  `--all`, footer with counts + full path. shellcheck clean, +x (100755) tracked.
- [x] ✅ **Task 6.3**: `pipe_blocker` block messages (verbose + terse, blacklisted +
  unknown) and `get_claude_md` now lead with `echd-capture`, resolving the helper's
  ABSOLUTE path from the daemon dir so the recommended command works from any cwd;
  temp-file demoted to secondary. 5 new tests; all 177 pipe_blocker tests green.
- [x] ✅ **Task 6.4**: Deployment = repo inclusion (client installs get
  `.claude/hooks-daemon/scripts/echd-capture` via the git clone); the block message
  points at the resolved absolute path so no PATH setup is required. Documented via
  `get_claude_md`. Daemon restarted RUNNING; live probe shows the resolved path.

### Phase 7: Release

- [ ] ⬜ **Task 7.1**: Full QA suite green (`./scripts/qa/run_all.sh`).
- [ ] ⬜ **Task 7.2**: Config/truth-change manifests if warranted; changelog inputs.
- [ ] ⬜ **Task 7.3**: Run `/release` — single release shipping all changes.

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
