# Plan 00381: niggles ledger three

**Status**: Complete
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Successor to Plan 00379, which closed with all five entries resolved. Per the
niggles SOP a closed ledger does not stop the collecting: the next niggle found
opens a new one rather than being mentioned in passing.

A niggle is a small, specific, VERIFIED defect — something wrong now, recorded
the turn it is found, with the evidence that makes it checkable by someone who
was not there. An entry needing real design work is graduated to its own plan
with a pointer rather than grown here.

## Goals

- Every niggle found is recorded here in the turn it is found, with evidence.
- Each entry is either fixed here or graduated to a named plan with a pointer.

## Non-Goals

- Redesign. An entry needing design is graduated, not grown in place.
- A dumping ground for wishes. An entry must name something that is WRONG.

## Tasks

### Phase 1: Recorded niggles

- [x] ✅ **N1** (graduated to Plan 00383): `TestFreshClientConfig` in
  `tests/acceptance/test_transport_toggle_cycle.py` cannot pass on its own. Run
  the class alone and
  `test_transport_on_with_absent_binary_and_null_source_refuses_untouched`
  fails; run the whole module and all 11 pass. Its expectations depend on state
  a sibling class leaves behind, and these tests drive the real CLI — `transport on` regenerates forwarders and restarts the daemon — so ordering is
  load-bearing rather than incidental. Two runs produced two DIFFERENT failures
  (`assert 0 != 0` on the return code, then `assert 'relay hot path' not in ...`
  on the generated hook), which says the shared state is mutable and the class
  is reading whatever the previous test left. Found while narrowing an unrelated
  test run with `-k "worktree or cli"` — `cli` matched `TestFreshClientConfig`
  by substring and ran it in isolation. Nothing in the suite as normally run is
  red, so this costs nothing today; it costs the next person who tries to run
  one failing class while debugging, which is exactly when a misleading failure
  is most expensive.
  **Diagnosis sharpened after the first recording, which was shallower.** It is
  not merely "a sibling leaves state". The module-scoped `client_project`
  fixture seeds `relay_enabled: false` (`_fixture_config`) but copies the
  forwarders from THIS repository's live `.claude/hooks/` — and this repo runs
  with `relay_enabled: true`, so its `pre-tool-use` forwarder carries the relay
  hot path twice. The fixture therefore starts INTERNALLY INCONSISTENT: config
  says relay off, forwarders say relay on. `TestFreshClientConfig`'s first test
  runs `transport off`, which reports "already" and regenerates nothing, so the
  contradiction survives into the next test, whose
  `assert "relay hot path" not in ...` then fails. Running the full module hides
  it because the earlier classes toggle transport and regenerate the forwarders
  as a side effect. So the precondition is really the HOST repository's
  transport setting, normalised incidentally — the class would behave
  differently on a checkout with `relay_enabled: false`.
  **The product half is now VERIFIED, and GRADUATED to Plan 00383.** The open
  question above — whether `transport off` reporting "already" without
  reconciling is itself a product gap — was answered by asking the production
  function directly with every side effect injected, so the result depends on
  no daemon and not on this repo's own transport setting: config at
  `relay_enabled: false` beside a forwarder carrying the relay hot path gives
  `changed=False`, `verified=None`, ZERO side effects, forwarder untouched.
  `install/transport_toggle.py:360-362` decides the no-op from the config alone
  and never reads what is deployed, so it can never repair it — the operator is
  told the relay is off, gets exit 0, and every hook still routes through it.
  That is a production behaviour change owing tests, a release note and
  guidance, so it graduates rather than growing here:
  **Plan 00383 — transport toggle trusts config over deployed state.** The
  test-isolation symptom that surfaced it is closed by the same fix, because
  the fixture's contradiction is exactly the drift the toggle will reconcile.

## Success Criteria

- [x] Every entry above is fixed, or graduated to a named plan with a pointer
  recorded in this ledger — N1 graduated to Plan 00383, which shipped the fix
  and closed N1's own symptom with no test change.
- [x] N1's release-bound consequence is in the pending-release holding area
  under the plan that took it on:
  `UNRELEASED/release-notes/35-transport-off-repairs-forwarders-that-drifted.md`.
  The ledger ships no release note of its own, because a graduated entry's
  consequence belongs to the plan that fixed it, not to the ledger that found
  it.
- [x] Full QA passes and CI is green — 29/29 locally, CI run `34628257960`
  succeeded on `3292cd09`.

## Delivery & Milestones

- Successor to Plan 00379 (Completed), per the niggles SOP in
  `CLAUDE/PlanWorkflow.md`.
