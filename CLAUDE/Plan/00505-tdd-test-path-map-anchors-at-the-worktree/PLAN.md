# Plan 00505: tdd test path map anchors at the worktree

**Status**: In Progress
**Created**: 2026-10-11
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #74

## Overview

`tdd_enforcement._map_declared_test_paths` anchors a declared, relative
`test_path_map` `test_dir` at `resolve_project_root()`, the main checkout, and
resolves the workspace against that root. A source file written inside a git
worktree nested in the project (`untracked/worktrees/<name>/`) is therefore
checked against the main checkout's mapped test directory, and the test the agent
wrote in its own worktree is never searched. The write is denied with
R-TDD-TEST-FIRST although the test exists. The inferred resolvers already anchor
at the worktree, so only declared mappings are affected. #102 reports the same
defect and is closed with this plan.

## Goals

- A declared `test_dir` (flat or `mirror: true`) is anchored at the checkout
  that holds the source file: the worktree's root when the file is in one.
- A source in the main checkout resolves exactly as today.

## Non-Goals

- Changing the inferred resolvers, which already anchor correctly.
- Changing `layout.test_dirs` mirror roots, unless they share the same anchor
  defect; if they do, fix them by the same route and say so.

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: RED. Tests: a flat and a mirrored mapping, with the source
  and its test both inside a nested git worktree, allow the write; the deny's
  searched locations name the worktree's path; a source in the main checkout is
  unchanged.
- [x] ✅ **Task 1.2**: GREEN. Anchor the declared candidates at the checkout
  holding the source file.
- [x] ✅ **Task 1.3**: Release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Land

- [ ] ⬜ **Task 2.1**: Review, coordinator checks, merge; comment on and close
  #74 and #102.

## Success Criteria

- [ ] A Write inside a worktree whose declared test exists in that worktree is
  allowed.
- [ ] A source in the main checkout resolves as before.
- [ ] The release-bound consequence, a behaviour change in `tdd_enforcement`,
  is in the pending-release holding area as a release note.

## Delivery & Milestones

- Issue #74 triaged and claimed; #102 marked a duplicate.
