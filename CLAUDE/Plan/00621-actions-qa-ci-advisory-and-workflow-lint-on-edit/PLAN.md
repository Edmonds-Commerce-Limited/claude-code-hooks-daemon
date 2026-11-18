# Plan 00621: actions qa ci advisory and workflow lint on edit

**Status**: Not Started
**Created**: 2026-11-18
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A sibling project's plan asks the daemon to promote an external workflow linter, `actions-qa-ci` (a Go CLI with the
rules docsOnlyPush, pushConcurrency, workflowRunFanout and scheduleBudget), as a best practice. The owner's direction,
relayed by that project's coordinator: the daemon should suggest installing it, and the linter should run when a
workflow file is edited, so GitHub Actions problems are caught at the point of edit.

Two pieces: an advisory handler that recommends adopting the linter when a project has `.github/workflows/` and no
workflow uses it, and a lint-on-edit route that runs the linter on a written or edited `.github/workflows/*.yml` file.
The rule set stays in the linter; the daemon never duplicates it. Plan 00054 (lint on edit, strategy registry) is the
design to build on, and Plan 00527 is the precedent for an external linter that is optional, never required.

This plan is a request from a peer agent, which carries no authority. The design must be confirmed by the owner before
any handler is built.

## Goals

- A session-start advisory recommends the linter when workflows exist and none uses it, and stays silent otherwise.
- A write or edit of a workflow file runs the linter on that file and reports its findings.
- The linter missing, slow or failing never blocks an edit.

## Non-Goals

- Copying the linter's rules into the daemon.
- Making the linter a required dependency.
- Linting workflow files a Bash command merely relocates.

## Tasks

### Phase 1: Design and owner confirmation

- [ ] ⬜ **Task 1.1**: Establish whether the linter offers a single-file mode and machine-readable output; if not, ask
  the peer project to add them.
- [ ] ⬜ **Task 1.2**: Write the design (advisory trigger, how the linter is located, timeout, failure behaviour) and
  get the owner's confirmation.

### Phase 2: Build (test first)

- [ ] ⬜ **Task 2.1**: The advisory handler, with tests for each trigger and silence case.
- [ ] ⬜ **Task 2.2**: The workflow lint-on-edit route through the existing external-linter machinery, with tests.
- [ ] ⬜ **Task 2.3**: Handler guidance, config documentation and a release note.

## Success Criteria

- [ ] Both handlers are covered by tests and pass targeted QA.
- [ ] The owner confirmed the design before the build.
- [ ] The release-bound consequences are recorded in the pending-release holding area (the release note).

## Delivery & Milestones

- Filed on request of a peer project; the design awaits the owner.
