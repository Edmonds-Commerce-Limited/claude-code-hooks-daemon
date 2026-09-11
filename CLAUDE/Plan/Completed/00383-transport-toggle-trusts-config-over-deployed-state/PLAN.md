# Plan 00383: transport toggle trusts config over deployed state

**Status**: Complete
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus

## Overview

`transport on` / `transport off` decide they have nothing to do by reading the
CONFIG alone. `run_toggle` (`install/transport_toggle.py:360-362`) compares
`relay_enabled` against the requested state and, on a match, returns
`ToggleOutcome(changed=False, verified=None)` before looking at anything. The
deployed forwarders under `.claude/hooks/` are never read, so they can never be
repaired, and `verified=None` is the honest record that nothing was checked.

The consequence is a command that reports a state it has not established. A
project whose config says `relay_enabled: false` while its `pre-tool-use`
forwarder still carries the relay hot path is told `transport off: relay already disabled — nothing to do`, exit 0 — and every hook still routes through
the relay. Verified directly against the production function with every side
effect injected, so the result depends on no daemon, no socket, and not on this
repository's own transport setting: `changed=False`, `verified=None`, zero side
effects, forwarder untouched.

Drift is reachable without anyone doing anything strange — an interrupted
toggle, a hand-edited config, a `git checkout` that moves the config but not
the forwarders, or an upgrade that redeploys forwarders. It was found as the
mechanism behind a test-isolation failure (Plan 00381 N1): the acceptance
fixture seeds `relay_enabled: false` but copies THIS repository's live
forwarders, which carry the hot path, and nothing reconciles the two.

The repair does not need new drift-detection logic. `regenerate_deployed_hooks`
already scans every forwarder, writes only when the generated content differs,
and RETURNS the basenames it actually rewrote — an exact drift signal that is
byte-identical-by-default, so a converged project still pays nothing.

## Goals

- After `transport on`/`off` exits 0, the deployed forwarders match the config
  it reports — the report is established, not assumed.
- A converged project still performs no write, no restart and no probe.
- Drift that is repaired is reported as repaired, not as "nothing to do".

## Non-Goals

- Changing what a real flip does. The flip path, its auto-revert and its probe
  set are unchanged.
- Making `transport status` reconcile. Status reports; it must not mutate.
- Reconciling anything outside the forwarders the generator owns (client-owned
  files in `.claude/hooks/` are already excluded by the generator).

## Tasks

### Phase 1: Reproduce before fixing

- [x] ✅ **Task 1.1**: A failing test for the shape verified by probe — config
  already at the target, a forwarder carrying the opposite state, and the
  toggle leaving it untouched while reporting success. The drift is built the
  way it actually happens (move the config, leave the forwarders), so the
  fixture cannot drift from the format the generator owns.
- [x] ✅ **Task 1.2**: A failing test for the same shape on `transport on`
  (config already true, forwarders lacking the hot path), so the fix is not
  written for the `off` direction alone.

### Phase 2: Converge instead of short-circuiting

- [x] ✅ **Task 2.1**: On a config match, run `regenerate_deployed_hooks` and
  treat a non-empty return as drift. An empty return is the clean no-op and
  must keep its current behaviour exactly — no restart, no probes.
- [x] ✅ **Task 2.2**: When drift was repaired, restart and verify with the
  same probes the flip path uses, so the state is established rather than
  assumed. A reconcile that fails verification reports `verified=False` and
  does NOT auto-revert — the only state to revert to is the drift being
  fixed, so restoring it would be wrong. Said in the code, not only here.
- [x] ✅ **Task 2.3**: Decided and pinned — provisioning gates the
  enable-direction reconcile, and the test asserts the refusal leaves the
  forwarder without a hot path AND restarts nothing.
- [x] ✅ **Task 2.4**: Carried as a new `reconciled` field rather than
  overloading `changed`. A reconcile leaves the config alone, which the test
  asserts directly by comparing the config text before and after.

### Phase 3: Say so

- [x] ✅ **Task 3.1**: The CLI message distinguishes a clean no-op from a
  repaired drift. `already disabled — nothing to do` must not be printed when
  something WAS done.
- [x] ✅ **Task 3.2**: Release note
  `35-transport-off-repairs-forwarders-that-drifted.md`, and the pointer is
  recorded in Plan 00381's N1.

## Success Criteria

- [x] A config-matching toggle over drifted forwarders repairs them, verifies,
  and reports the repair.
- [x] A converged project's toggle still writes nothing, restarts nothing and
  probes nothing — pinned by a test, not by inspection.
- [x] `transport on` cannot deploy a relay hot path with no relay binary behind
  it.
- [x] Plan 00381 N1 carries a pointer to this plan.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/35-transport-off-repairs-forwarders-that-drifted.md`.
- [x] Full QA passes and CI is green — 29/29 locally, CI run `34628257960`
  succeeded on `3292cd09`.

## Delivery & Milestones

- Graduated from Plan 00381 (niggles ledger three) entry N1 per the niggles
  SOP, once the product half was verified against production code rather than
  inferred from acceptance-test ordering.
- Prior art: Plan 00294 built the toggle, its verification and its auto-revert;
  this plan closes the case 00294 did not cover — the toggle that believes it
  has nothing to do.
