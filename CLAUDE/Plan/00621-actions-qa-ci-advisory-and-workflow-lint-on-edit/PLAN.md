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

This plan is a request from a peer agent, which carries no authority. The design is in [DESIGN.md](DESIGN.md), settled
by a fable sub-agent under the owner's delegation, 2026-11-19; it is not the owner's own words, and a later owner
message overturns it. No fact about the linter could be verified (DESIGN.md section 1), so the design fails open on
every one of them.

## Goals

- A session-start advisory recommends the linter when workflows exist, none uses it and it is not installed, and stays
  silent otherwise. It ships switched off until an install source for the linter is verified.
- A write or edit of a workflow file runs the linter on that file and reports its findings as a lint failure.
- The linter missing, slow or faulting never blocks an edit. Only its findings exit code is a failure.

## Non-Goals

- Copying the linter's rules into the daemon.
- Making the linter a required dependency.
- Linting workflow files a Bash command merely relocates.
- Parsing the linter's JSON output.

## Tasks

### Phase 1: Design and verification

- [ ] ⬜ **Task 1.1**: Run the real linter once against a sample workflow file and record the command line, the output
  and the exit codes in the journal; record where it is published. Not possible from this repository's environment on
  2026-11-19 (DESIGN.md section 1). Gates this plan's completion and the advisory's default, not Task 2.1.
- [x] ✅ **Task 1.2**: The design (advisory trigger, how the linter is located, timeout, failure behaviour):
  [DESIGN.md](DESIGN.md), settled by a fable sub-agent under the owner's delegation, 2026-11-19.

### Phase 2: Build (test first; slices are defined in DESIGN.md section 3)

- [ ] ⬜ **Task 2.1**: Slice 1. The lint registry holds several strategies for one extension; an exit-code capability
  in the lint protocol; `GitHubWorkflowLintStrategy` registered by default. Built against a stub linter, with the tests
  DESIGN.md section 3 lists, including that Ansible files still resolve to the Ansible strategy.
- [ ] ⬜ **Task 2.2**: Slice 2. The `workflow_linter_advisor` session-start handler, off by default, with tests for
  each trigger and silence case.
- [ ] ⬜ **Task 2.3**: Slice 3. Handler guidance, config documentation and a release note.

## Success Criteria

- [ ] The strategy and the handler are covered by tests and pass targeted QA.
- [ ] The design was settled before the build (done under the owner's delegation, DESIGN.md).
- [ ] The real linter was run once and its behaviour matches what the strategy assumes, or the strategy was changed to
  match (Task 1.1).
- [ ] The release-bound consequences are recorded in the pending-release holding area (the release note).

## Delivery & Milestones

- Filed on request of a peer project; design ruled under delegation; Task 2.1 is ready to build.
