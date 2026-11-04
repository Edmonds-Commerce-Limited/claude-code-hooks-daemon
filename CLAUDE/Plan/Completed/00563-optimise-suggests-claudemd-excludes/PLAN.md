# Plan 00563: optimise suggests claudemd excludes

**Status**: Complete (2026-11-04)
**Created**: 2026-11-04
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00561 (GitHub #156) found that a sub-agent working in a worktree under the project root loads the project's root `CLAUDE.md` twice. The second copy is the worktree's own, and it can be about 30k tokens. This repository fixed that for itself with Claude Code's `claudeMdExcludes` setting. Its owner question Q1 asked whether client projects should get the same help.

**Owner ruling (4 November 2026): suggest it in `/hooks-daemon optimise`; do not install it.** When a client project keeps worktrees under its own root and has no matching exclusion, the config-optimisation review recommends the `claudeMdExcludes` globs, and applies them only on the confirmation it already asks for.

## Goals

- `/hooks-daemon optimise` detects worktree roots under the project (the daemon's own `untracked/worktrees/` and `.claude/worktrees/`, plus any worktree `git worktree list` reports under the root) that no `claudeMdExcludes` glob covers.
- When it finds any, it recommends the exact globs to add, says why (the duplicate root `CLAUDE.md` load) and which settings file they go in, and stays silent when they are already covered or no worktree lives under the root.

## Non-Goals

- Installing or writing the setting without confirmation.
- Changing this repository's own setting, which Plan 00561 already made.

## Tasks

### Phase 1: implementation

- [x] ✅ **Task 1.1**: Write failing tests for the detection: an uncovered root is recommended, a covered root is silent, and a project with no worktrees under its root is silent.
- [x] ✅ **Task 1.2**: Add the recommendation to the optimise procedure, reusing the worktree-root derivation from `tests/integration/test_worktree_claudemd_excludes.py` rather than a copied list.
- [x] ✅ **Task 1.3**: Document it in the optimise skill doc, and add a release note.

## Success Criteria

- [x] The three detection cases are tested and pass.
- [x] A release note in the pending-release holding area (`CLAUDE/UPGRADES/UNRELEASED/`) describes the new recommendation, because it reaches clients.

## Delivery & Milestones

- Ruling: Plan 00561 Q1, answered by the owner.
