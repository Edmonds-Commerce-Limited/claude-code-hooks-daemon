# Plan 00350: ci builds the relay binary so transport gates run

**Status**: Complete
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Fourteen tests skip in CI with the reason `relay binary not built: <repo>/untracked/bin/hooks-relay` — 11 in
`tests/acceptance/test_transport_toggle_cycle.py` and 3 in
`tests/integration/test_relay_guard_fail_open.py`. The binary is a build
artefact under gitignored `untracked/`, so it is absent from every fresh
checkout and every CI runner, and has been for as long as those tests have
existed.

This is the same defect Plan 00250 fixed for the daemon socket, one artefact
over: a gate that is wired into the workflow, correct, and never load-bearing,
because pytest counts a skip as neither a pass nor a failure. Plan 00250
measured these 14 while counting its own 16 and recorded them as **explicitly
out of scope**, so that a relay gap would not be mistaken for daemon fallout.
This plan is that deferred work.

The relay is the transport that makes a hook dispatch cheap, so the skipped
tests cover a fail-open path with real production consequence: `hooks-relay`
absent or its socket dead must degrade to the Python forwarder rather than
break the hook. Nothing currently proves that on any machine but a developer's
own — and the guard that renders it is described in its own docstring as *"pure
bash builtins only — zero subshells, zero external spawns"*, i.e. a hot path
where a regression is both easy and expensive.

## Goals

- The 14 relay-dependent tests EXECUTE in CI rather than skip, on all three
  interpreters.
- A skip of a relay-dependent gate is visible as a failure rather than absorbed
  into a green run, matching what Plan 00250 established for the daemon gates.
- Building the relay costs the pipeline no more than it has to — the build is
  cached or cheap enough not to be the reason a contributor stops running CI.

## Non-Goals

- Changing the relay's own behaviour, protocol or guard. This plan makes the
  existing tests run; what they assert is already settled.
- Tracking the built binary. It is a compiled artefact and belongs in
  `untracked/`; the fix is to build it, not to commit it.
- Plan 00250's Task 2.4c (the tracked forwarders baking a generating machine's
  absolute path). It touches the same files and is a different question —
  whether `.claude/hooks/*` should be tracked at all.

## Tasks

### Phase 1: Measure

- [x] ✅ **Task 1.1**: **14 confirmed, 11 + 3**, by moving both relay artefacts
  aside and re-running the two files: 8 passed, 14 skipped. The same 14 appear
  in CI. Reproducing it locally also found what a CI log alone would not have:
  **the two files look at DIFFERENT paths**. `test_relay_guard_fail_open.py`
  opens the build output
  (`untracked/relay-build/hooks-relay-x86_64-unknown-linux-musl`), the 11
  toggle-cycle tests the deployed `untracked/bin/hooks-relay`. Building without
  deploying fixes 3 of 14 and leaves 11 skipping — which looks enough like
  success to stop there.
- [x] ✅ **Task 1.2**: Build cost is **~1 second**, and the plan's caching risk
  does not apply. It is one crate-less source file compiled by plain `rustc` —
  no cargo, no dependency graph — so a cache would save nothing and a cache
  miss that skipped would reproduce the very skip being removed. Only
  provisioning needed is `rustup target add x86_64-unknown-linux-musl`; a
  runner's preinstalled `rustc` carries the host target only. **`musl-gcc` is
  NOT required** — verified by building with a deliberately poisoned `musl-gcc`
  first on PATH, which succeeded, so rustc's self-contained linking covers it.
  The CI step reproduces the deployed binary **byte-for-byte** (same sha256).

### Phase 2: Provision

- [x] ✅ **Task 2.1**: A `Build the relay (for the transport gates)` step in the
  QA job, before `Tests + coverage`, on all three interpreters, no second job.
  It adds the musl target, runs `relay/build.sh`, and `install -D -m 755`s the
  output to `untracked/bin/hooks-relay` — both paths, per Task 1.1.
  `test_ci_provisions_the_relay.py` guards the step's existence, the deploy,
  the target, the ordering, and that it cannot fail quietly.
- [x] ✅ **Task 2.2**: Nothing to fix — **22 passed, 0 skipped** against the
  artefact the CI step produces. The task assumed at least one gate would not
  have run correctly since it was written, as happened with the daemon gates.
  That did not hold here, which is worth recording as a result rather than
  quietly dropping: these tests were only ever skipped, not wrong.

### Phase 3: Guard the class

- [x] ✅ **Task 3.1**: `tests/relay_gate_guard.py` turns a relay-provisioning
  skip into a failure **in CI only**, registered from `tests/conftest.py`
  because the gates straddle `acceptance/` and `integration/`. Proven by nested
  pytest runs in both directions: with `CI=true` the relay skip fails and an
  unrelated skip in the same file does not; without it, both still skip.

  Two deliberate departures from the task as written. It keys on the **skip
  reason**, not a file list — the two files spell their skip differently and
  sit in different directories, and what they share is the artefact, not a
  path. And it does **not** extend `RELEASING.md` Step 12.0: adding files there
  makes them release-blocking, which is a decision about release scope rather
  than CI visibility, and is the owner's — the same line Plan 00250 Task 1.2
  drew. Scoping to CI is what makes that unnecessary: a developer with no Rust
  toolchain genuinely cannot run these and is not the defect.

### Phase 4: Verify

- [x] ✅ **Task 4.1**: **QA 26/26, coverage 95.3%**, `18807 passed, 0 failed, 7 skipped`; daemon RUNNING. The seven local skips are the environment guards
  that were always there — no `uv` and no Rust toolchain on this machine's PATH
  — not the relay gates, which the built artefacts let run here too.

- [x] ✅ **Task 4.2**: Run **34197901092 is green on all three interpreters**,
  identically: `18750 passed, 0 failed, 3 skipped`. **Skips 17 → 3** — every
  one of the 14 relay gates executed, on every interpreter. The three that
  remain are unrelated environment skips that were always there.

  The build step cost **~13s wall including `rustup target add`** (07:10:10 →
  07:10:24), against ~1s locally for the compile alone; the target download is
  most of it, and still far below anything worth caching.

  One scoping correction, recorded before anyone relies on the wider claim: the
  binary is **not** byte-identical across machines. Same 570056 bytes, different
  sha256 (`f6484c23…` locally, `79bc27ac…` on the runner) — rustc embeds
  absolute paths and the build directory differs. Nothing depends on the hash
  today, which is exactly why it is written down: a future "cache the relay by
  content hash" step would otherwise find it the expensive way.

## Success Criteria

- [x] The 14 relay-dependent tests report PASSED in CI on all three
  interpreters — run `34206225173` reports **19716 passed, 2 skipped** on each
  of 3.11, 3.12 and 3.13, and neither remaining skip is a relay gate (one is a
  release-cycle manifest, the other a design test)
- [x] A silent skip of a relay-dependent gate fails the run — the CI-scoped
  skip guard, itself among the tests that passed above
- [x] Local `llm_qa.py all` still passes — 26/26

## Dependencies

- Follows: Plan 00250, which established both the provisioning shape and the
  skip guard this plan should reuse, and which measured these 14 skips while
  deliberately leaving them alone.

## Risks & Mitigations

- ~~**The relay build may need a toolchain CI does not have.**~~ Measured in
  Task 1.2: `rustup target add` and nothing else. `musl-gcc` is not needed.
- ~~**Building on every run may be too slow.**~~ Measured at ~1s. No cache, and
  deliberately so: there is nothing for one to save, and a cache miss that
  skipped would reproduce the defect this plan removes.
- **The CI step and the gates are coupled only by two hardcoded path
  literals.** Nothing derives one from the other, so a rename on either side
  silently returns the gates to skipping. `test_ci_provisions_the_relay.py`
  asserts the workflow names both paths; the CI-scoped skip guard catches it if
  that ever stops being enough.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00350-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from Plan 00250's Task 1.1 measurement; dedupe scout checked 41 live
  plans and found no other coverage.
- `5dc7bce1` — CI builds the relay, so fourteen transport gates stop skipping
- Closed against CI run `34206225173`, green on all three interpreters.
