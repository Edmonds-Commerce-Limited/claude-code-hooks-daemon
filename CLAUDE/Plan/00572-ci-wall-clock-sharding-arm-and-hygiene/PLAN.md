# Plan 00572: ci wall clock sharding arm and hygiene

**Status**: In Progress
**Created**: 2026-11-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner asked whether CI wall-clock time can be cut by sharding work across
parallel runners, which CI best practices the repository is missing, and
whether GitHub can run arm64 jobs. The measured durations, designs and the gap
audit are in [ANALYSIS.md](ANALYSIS.md).

What the measurements found:

- `qa.yml`'s slow path is almost all one serial pytest. On a code-tier push
  that touches a file the change mapper calls too broad, CI first runs a
  redundant targeted pytest, then the WHOLE suite serially in one job. The
  nightly is dominated by the same serial test step.
- `release-gate.yml` is already sharded (15+ jobs behind one aggregator), with
  the `integration` shard as its floor. Its shard matrix and coverage-combine
  job can be reused.
- On `main`, GitHub keeps one pending run per concurrency group, so a third
  push cancels the queued second run before it starts. Those SHAs never get a
  verdict.
- GitHub-hosted arm64 runners (`ubuntu-24.04-arm`) are generally available and
  free for public repositories. CI builds only the x86_64 relay, never builds
  hooks-screen, and the release ships only an x86_64 relay asset, so a broken
  aarch64 build would ship undetected. That matters now: #174 made the
  supervisor arch-aware, and a client team is moving to arm64 runners.

## Goals

- The code-tier slow path and the nightly are bounded by the slowest shard,
  not by one serial pytest. Sharding is across runners, not inside one.
- Every `main` push gets a CI verdict. No queued run is silently cancelled.
- Native aarch64 builds of the relay and hooks-screen run in CI. The release
  ships attested assets for both architectures.
- Close the highest value-for-effort practice gaps: Dependabot, SHA-pinned
  actions, job summaries, a shared setup composite action, artifact retention.

## Non-Goals

- `pytest-xdist` inside integration/acceptance shards. Those spawn daemons and
  share sockets inside one runner. Only an experiment on unit shards is in scope.
- Changing what QA checks, as opposed to where and when it runs.

## Repository settings

Checked with the admin token: `main` has no branch protection and no rulesets,
so no job name is a required check and the jobs can be reshaped freely. Adding
protection is a separate decision. This repository's workflow fast-forwards
and pushes `main` directly, which required pull requests would block.

On the owner's instruction, enabled: secret scanning, Dependabot vulnerability
alerts and security updates, and CodeQL default setup. Still off: push
protection. This repository's tests and fixtures deliberately carry
credential-shaped strings for the security guards, and push protection could
refuse those pushes, so check what it would flag before enabling it.

## Tasks

### Phase 1: Quick wins (no timing risk)

- [x] ✅ **Task 1.1**: Add a `QA gate` aggregator job to `qa.yml`, mirroring
  release-gate's, so the jobs behind it can be reshaped without breaking
  branch protection.
- [x] ✅ **Task 1.2**: Skip the mapped pytest step when the mapper reports
  unmapped files, so the full-suite fallback is not preceded by a redundant run.
- [x] ✅ **Task 1.3**: Give each `main` push its own concurrency group, so
  queued runs are never cancelled.
- [x] ✅ **Task 1.4**: Write a short QA verdict to `$GITHUB_STEP_SUMMARY`,
  and set `retention-days` on QA and coverage artifacts.
- [x] ✅ **Task 1.5**: Regression from the job rename: `release_slate.py`
  keyed on the old `QA (Python3.x)` job name, so `release-slate-check` could
  never see a full-tier run. Key it on the new `QA static` and `Full suite`
  jobs, with a test tying the names to `qa.yml`.

### Phase 2: Shard the slow paths

- [x] ✅ **Task 2.1**: Extract release-gate's shard matrix and coverage
  combine into a reusable workflow (`workflow_call`), used by release-gate,
  `qa.yml`'s full-suite fallback and the nightly.
- [x] ✅ **Task 2.2**: Rebalance the `integration` and `unit-handlers` shards
  over measured durations (legs declared in `scripts/ci/shard_legs.yaml`).
- [x] ✅ **Task 2.3**: A composite `setup-env` action replacing the 8+ copies
  of the install block, with a uv cache keyed on `uv.lock`.

### Phase 3: arm64

- [x] ✅ **Task 3.1**: A `native-builds` matrix (x86_64 on `ubuntu-latest`,
  aarch64 on `ubuntu-24.04-arm`) building and smoke-running the relay and
  hooks-screen.
- [ ] ⬜ **Task 3.2**: Tag-triggered release assets for both triples with a
  merged `SHA256SUMS` and `actions/attest-build-provenance`. The relay's
  download path selects its asset by architecture.
- [ ] ⬜ **Task 3.3**: A non-blocking arm64 test leg. Make the tests that
  assume an x86_64 relay name arch-aware.

### Phase 4: Supply chain

- [x] ✅ **Task 4.1**: `.github/dependabot.yml` for `github-actions` and the
  Python dependencies, grouped.
- [ ] ⬜ **Task 4.2**: Pin every `uses:` to a full commit SHA, with the tag in
  a trailing comment.

## Success Criteria

- [ ] Measured on real runs and journalled: after Phase 2, the code-tier
  too-broad path and the nightly each finish when their slowest shard does.
- [ ] No `main` run ends `cancelled` with zero jobs because a later push
  queued behind it.
- [ ] CI builds both architectures' relay and hooks-screen on every code push.
- [ ] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` records the
  arm64 release assets in the pending-release holding area (client-visible).
  The CI-only phases have no release-bound consequences.

## Delivery & Milestones

- Phases 1 and 2 merged to `main` at 4b1317734 through PR #178, whose CI
  exercised the new workflows. Task 1.5 fixed the release-slate regression.
- Phases 3 and 4 follow the release.
