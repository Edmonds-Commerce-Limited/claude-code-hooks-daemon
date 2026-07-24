# Plan 00190: worktree create seed env files

**Status**: In Progress
**Created**: 2026-07-24
**Owner**: vasyl
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

When Claude Code creates a git worktree (an `isolation: "worktree"` agent or a
`--worktree` session), the daemon's `worktree_create` handler owns creation and
places the worktree at a semantic path. Local, git-ignored environment files
(`.env.local`, `.env.test.local`, etc.) live only in the main working copy, so a
fresh worktree checkout has none of them — the agent then runs against a
configuration with no local secrets/overrides and behaves differently from the
main checkout.

This plan makes the `worktree_create` handler seed a configurable list of
git-ignored files from the repository top-level into the newly-created worktree
root, so a worktree "just works" like the main checkout. Copying is best-effort,
only on fresh creation (never on idempotent re-fire), and never blocks or fails
worktree creation.

## Goals

- On fresh worktree creation, copy a configured list of files (default
  `.env.local`, `.env.test.local`) from the repo top-level into the worktree.
- Make the file list configurable via a `copy_files` handler option.
- Copy is best-effort: a failure logs a warning and is skipped; worktree
  creation (and the returned path) is never broken by a copy failure.
- No re-copy on idempotent re-fire (must not clobber edits made inside the
  worktree).

## Non-Goals

- No copying of tracked files (git already provides those in the checkout).
- No glob/wildcard expansion — an explicit filename list only (relative paths
  allowed; absolute paths and `..` traversal are ignored for safety).
- No recursive directory copy.

## Tasks

### Phase 1: TDD implementation

- [x] ✅ **Task 1.1**: Write failing tests for env-file seeding on the handler
  - [x] ✅ copies default env files present at repo root
  - [x] ✅ skips files that do not exist
  - [x] ✅ does not copy on idempotent re-fire
  - [x] ✅ honours a configured `copy_files` list
  - [x] ✅ ignores unsafe entries (absolute / `..`)
  - [x] ✅ copy failure does not break worktree creation
- [x] ✅ **Task 1.2**: Implement seeding in `WorktreeCreateHandler`
- [x] ✅ **Task 1.3**: Update `get_claude_md()` guidance
- [x] ✅ **Task 1.4**: Document the `copy_files` option in `hooks-daemon.yaml.example`

### Phase 2: Verify

- [x] ✅ **Task 2.1**: Run full QA (`llm_qa.py all` via uv)
- [ ] ⬜ **Task 2.2**: Hand off diff to user for `/release`

## Success Criteria

- [ ] A fresh worktree contains the configured env files when they exist at the
      repo top-level.
- [ ] All new + existing tests pass; QA is green.
- [ ] No secrets are embedded in code, tests, or fixtures (public branch).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only. -->

- <!-- delivery commit hash -->
