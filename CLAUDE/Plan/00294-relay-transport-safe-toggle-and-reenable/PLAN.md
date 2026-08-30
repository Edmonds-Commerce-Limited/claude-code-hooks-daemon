# Plan 00294: relay transport safe toggle and reenable

**Status**: In Progress
**Created**: 2026-08-30
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner direction (2026-08-30, after the live dogfood outage): *"we also need
to properly get the rust forwarder working as well — we have started so we
need to finish — it needs to be fully safe, easy and safe to toggle on and
off at will."*

Plan 00290 shipped the relay and its dogfood exposed a chain of real defects
(wire event name, missing `hook_event_name` enrichment, raw_stdout events
structurally unable to ride a byte pump, and the `/dev/stdin` ENXIO break of
the legacy path in the REAL socket-stdin invocation context). The fixes and
the invocation-context test contracts (LESSONS.md "Test in the host's
invocation context") are landing under the post-00290 bug work. What remains
— this plan — is the operational finish: toggling the relay is today a
three-step manual dance (config edit, forwarder regeneration, daemon
restart), and every mis-sequenced step during the dogfood smeared a broken
window across live sessions. A transport that is safe to run must be safe to
TURN ON AND OFF, atomically, with verification built in.

Dedupe note: filed as the direct continuation of just-archived Plan 00290;
no live plan covers transport toggling (scout deliberately skipped — the
lineage is one commit old).

## Goals

- One command each way: `bin/hooks-daemon transport on` / `transport off`
  (naming per CLI conventions) performs config flip → forwarder
  regeneration → daemon restart → REAL-CONTEXT verification, atomically
  from the operator's view.
- Verification inside the toggle: socket-stdin probes (the
  `test_forwarder_socket_stdin.py` invocation manner) through a
  relay-eligible event, a raw_stdout event, and the stop hard-block
  contract, plus per-event listener count — all against the live daemon.
- AUTO-REVERT on any verification failure: the toggle restores the previous
  transport state (config + forwarders + daemon) and reports exactly what
  failed — a toggle can never strand a session on a broken transport.
- `transport status` reports the current rung, listener count, binary
  digest/route, and the last toggle's verification result.
- Re-enable the dogfood in THIS repo via the new toggle once the post-00290
  eligibility/enrichment/e2e fixes are merged and green — and record the
  soak restart in this plan.
- Client parity: the same toggle works in client installs (canary-verified).

## Non-Goals

- No transport behaviour changes beyond the toggle machinery — eligibility,
  enrichment and e2e coverage belong to the in-flight post-00290 fix work
  this plan builds on.
- No automatic/unattended toggling — the command is an operator act.

## Tasks

### Phase 1: Toggle command

- [x] ✅ **Task 1.1**: TDD `transport on|off|status` CLI: config flip via a
  targeted comment-preserving line edit of `relay_enabled:` (explicitly
  round-trip tested), forwarder regeneration through `forwarder_generator`,
  daemon restart, state reporting
  (`install/transport_toggle.py`, `cmd_transport`). Idempotent (on-when-on /
  off-when-off are clean no-ops).
- [x] ✅ **Task 1.2**: TDD the built-in verification pass: socket-stdin
  probes (real invocation manner, unmodified payload shapes) for
  pre-tool-use + status-line + stop hard-block, listener-count check,
  bounded per-probe budget (`install/transport_verify.py`).
- [x] ✅ **Task 1.3**: TDD auto-revert: any verification failure restores the
  prior state end-to-end and exits non-zero with the failure named;
  the revert itself is verified by the same probes.

### Phase 2: Integration and safety proofs

- [ ] ⬜ **Task 2.1**: Acceptance tests: toggle on→verify→off→verify cycles
  against a real daemon, including an induced-failure case proving
  auto-revert (e.g. a deliberately broken relay binary).
- [ ] ⬜ **Task 2.2**: Docs (HANDLER_REFERENCE transport section + design
  doc update) and UPGRADES manifest entries for the new CLI.

### Phase 3: Re-enable and soak

- [ ] ⬜ **Task 3.1**: With the post-00290 fixes merged and the full gate
  green, run `transport on` in THIS repo; verify live session health
  (status line rendering, zero daemon errors over a soak window); journal
  the soak start. Any regression: `transport off` is the first response,
  diagnosis second.
- [ ] ⬜ **Task 3.2**: Canary: run the toggle cycle in the php-qa-ci canary
  (pristine reset, test-only per the standing canary policy); full QA gate
  - acceptance suite green on the final tree.

## Success Criteria

- [ ] Toggling either way is ONE command, verified, and auto-reverting —
  demonstrated by the induced-failure acceptance test.
- [ ] The relay dogfood is live again in this repo via the toggle, with the
  status line healthy and zero daemon errors across the soak window.
- [ ] Canary proves the same toggle behaviour in a client install.
- [ ] Full QA + acceptance suites green.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
