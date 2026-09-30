# Plan 00476: release through a pr with ci tagging

**Status**: Not Started
**Created**: 2026-09-30
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

**Owner direction:** a release branch exists for QA. It is proposed as a pull
request, and the pull request runs the whole QA gate in CI. The actual release
stays a local process with the daemon live: acceptance testing, tagging and
publishing run from the session, as `/release` does today, once the release
branch's CI gate is green.

Why. Today `/release` runs the whole gate locally on the main thread, holding the
host lock for the entire suite, then tags and publishes from the session. Two
defects of v3.67.0 came from that: the tag carried a stale UNRELEASED index
because nothing ran between Step 6 and the tag (ledger 00474 N263), and the
release body only failed its size limit after the tag was pushed (N262). A pull
request gate tests the exact commit that gets tagged, and moves the one full run
off this host. It is also the natural home for Plan 00475's rule that the full
gate runs only at release preparation.

Starts after Plan 00475's first batch finishes (small-batches rule).

## Design

1. **Prepare (in session, `/release`):** create a release branch from `main`,
   bump the version, assemble the release notes and changelog section from the
   `CLAUDE/UPGRADES/UNRELEASED/release-notes/` callouts and the merges since the
   last tag, move the UNRELEASED upgrade tasks, and run the Opus documentation
   review and the upgrade-guide gate. Push and open the pull request.
2. **QA gate (CI, on the pull request):** run `llm_qa.py all` across the
   supported Pythons, including the checks that need a live daemon. CI already
   starts a daemon and fetches full history. This replaces the local full gate,
   so the host never runs the whole suite.
3. **Release (in session, local daemon):** once the pull request's CI is green,
   `/release` resumes. It runs the acceptance tests (they need real tool calls
   in a Claude session, so they cannot move to CI), merges the pull request,
   tags the merge commit, builds the body with
   `scripts/release/build_github_release_body.py`, and publishes the GitHub
   release with its assets. `/release` stays the human gate, as today.
4. **The tagged commit is the gated commit:** merges to `main` are frozen while
   a release pull request is open. If `main` moves anyway, the release branch is
   updated and CI re-runs before tagging.

**Not included:** whole-codebase mutation testing. The repository has no
mutation-testing tooling, and across the whole suite it would far exceed any
pull request check. If wanted, it gets its own plan, starting with changed
modules only.

## Goals

- A release is only tagged on a commit whose release pull request passed the
  whole gate in CI.
- The whole gate runs in CI, not on this host.
- Acceptance testing, tagging and publishing stay local, in `/release`.

## Non-Goals

- Mutation testing.
- Tagging or publishing from CI.
- Changing the tag naming or version scheme.

## Tasks

### Phase 1: Prove the gate runs in CI

- [ ] ⬜ **Task 1.1**: Run each of the 40 `llm_qa.py` checks on a CI runner in a
  trial workflow. List the ones that need changes to run there.

### Phase 2: Workflows

- [ ] ⬜ **Task 2.1**: A release pull request workflow that runs the whole gate.

### Phase 3: Procedure

- [ ] ⬜ **Task 3.1**: Rewrite `RELEASING.md`, the release skill and the release
  agent: prepare, open the pull request, wait for CI green, then acceptance
  tests, merge, tag and publish locally.
- [ ] ⬜ **Task 3.2**: A freeze on merges to `main` while a release pull request
  is open.

## Success Criteria

- [ ] A release goes from `/release` to a published GitHub release with no
  local full gate, and its tag is on a commit the pull request's CI passed.

## Delivery & Milestones

- Not started. Follows Plan 00475's first batch.
