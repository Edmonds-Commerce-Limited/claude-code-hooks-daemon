# Plan 00561: worktree sub-agents load the root CLAUDE.md twice

**Status**: In Progress
**Created**: 2026-11-03
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #156

## Overview

A sub-agent dispatched from the main checkout loads the root `CLAUDE.md` at launch, because its working directory is the main checkout. A subdirectory `CLAUDE.md` loads on demand, so the agent's first read inside `untracked/worktrees/<name>/` injects that worktree's copy of the same root file. That copy is about 119 KB, roughly 30,000 tokens, and it repeats what is already loaded. On Plan 00558 this pushed several worktree agents to their context budget before they wrote any code.

Claude Code's `claudeMdExcludes` setting takes absolute-path globs and skips the named files. An experiment in a live session showed that excluding the worktree-root copies stops the duplicate while every other on-demand file still loads, including a worktree's `src/CLAUDE.md`. It took effect without a restart. The experiment is recorded in the GitHub #156 triage comment.

## Goals

- A worktree agent in this repository loads the root `CLAUDE.md` once.
- The exclusion covers every worktree location the daemon creates: `untracked/worktrees/` (`scripts/setup_worktree.sh`) and `.claude/worktrees/` (the WorktreeCreate handler).
- A test fails when a new worktree location is added without a matching exclusion.

## Non-Goals

- Deciding whether the daemon should recommend or install the setting in client projects. That is an owner question (Q1 below).
- Shrinking the resident block. Plan 00204 Task 3.2 covers that separately.

## Tasks

### Phase 1: Fix and guard

- [ ] ⬜ **Task 1.1**: Add `claudeMdExcludes` with `**/untracked/worktrees/*/CLAUDE.md` and `**/.claude/worktrees/*/CLAUDE.md` to `.claude/settings.local.json` (tracked in this repository).
- [ ] ⬜ **Task 1.2**: Add a test that reads `.claude/settings.local.json` and asserts that every worktree root the daemon creates is covered by one of its `claudeMdExcludes` globs. Derive the roots from the code that creates them, not from a copied list.
- [ ] ⬜ **Task 1.3**: Document the setting and the reason in `CLAUDE/Worktree.md`.

## Open questions (owner)

- **Q1**: Should the daemon recommend `claudeMdExcludes` to client projects that keep worktrees under their own root, for example in the install or optimise checklist? Or install it?

## Success Criteria

- [ ] The setting is in `.claude/settings.local.json`, and a test proves it covers every daemon worktree root.
- [ ] `CLAUDE/Worktree.md` explains the setting.
- [ ] No release-bound consequence: the change is this repository's own configuration and docs, and ships nothing to clients. So nothing goes to the pending-release holding area unless Q1 is answered "install".
- [ ] GitHub #156 is commented on and closed.

## Delivery & Milestones

- Triage and experiment: GitHub #156 comment 6618446633.
