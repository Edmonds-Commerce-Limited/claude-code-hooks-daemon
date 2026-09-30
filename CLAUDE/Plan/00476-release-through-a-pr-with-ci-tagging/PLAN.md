# Plan 00476: release through a pr with ci tagging

**Status**: Not Started
**Created**: 2026-09-30
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

**Owner proposal (the general idea, adapted to this repository):** a release is
prepared on a release branch and proposed as a pull request. The pull request
runs the whole QA gate in CI. The owner reviews the release notes and merges,
and on merge a CI workflow creates the tag and the GitHub release. Only that
workflow can create release tags.

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
   last tag, move the UNRELEASED upgrade tasks, run the Opus documentation review
   and the upgrade-guide gate, and run the acceptance tests. Acceptance tests
   need real tool calls in a Claude session, so they cannot move to CI. Then
   push and open the pull request.
2. **Gate (CI, on the pull request):** run `llm_qa.py all` across the supported
   Pythons, including the checks that need a live daemon. CI already starts a
   daemon and fetches full history.
3. **Human gate:** the owner reviews the notes on the pull request and merges.
   That merge is the release decision.
4. **Publish (CI, on merge):** a workflow creates the tag on the merge commit,
   builds the release assets, builds the release body with
   `scripts/release/build_github_release_body.py`, and creates the GitHub
   release.
5. **Tag protection:** a repository ruleset allows only that workflow to create
   release tags. The repository has no rulesets today.
6. **`main` while a release pull request is open:** merges to `main` are frozen
   until the release merges or is abandoned, so the gated commit is the tagged
   commit.

**Not included:** whole-codebase mutation testing. The repository has no
mutation-testing tooling, and across the whole suite it would far exceed any
pull request check. If wanted, it gets its own plan, starting with changed
modules only.

## Goals

- A release tag is only ever created by CI, on a commit the whole gate passed.
- The whole gate runs in CI, not on this host.
- The owner's pull request merge is the release decision.

## Non-Goals

- Mutation testing.
- Changing the tag naming or version scheme.

## Tasks

### Phase 1: Prove the gate runs in CI

- [ ] ⬜ **Task 1.1**: Run each of the 40 `llm_qa.py` checks on a CI runner in a
  trial workflow. List the ones that need changes to run there.

### Phase 2: Workflows

- [ ] ⬜ **Task 2.1**: A release pull request workflow that runs the whole gate.
- [ ] ⬜ **Task 2.2**: A publish-on-merge workflow: tag, assets, body, release.
- [ ] ⬜ **Task 2.3**: A tag ruleset restricting release tags to that workflow.

### Phase 3: Procedure

- [ ] ⬜ **Task 3.1**: Rewrite `RELEASING.md`, the release skill and the release
  agent for prepare, pull request, merge and CI publish.
- [ ] ⬜ **Task 3.2**: A freeze on merges to `main` while a release pull request
  is open.

## Success Criteria

- [ ] A test release goes from `/release` to a published GitHub release with no
  local full gate and no tag created from the session.
- [ ] A tag pushed from a session is refused by the ruleset.

## Delivery & Milestones

- Not started. Follows Plan 00475's first batch.
