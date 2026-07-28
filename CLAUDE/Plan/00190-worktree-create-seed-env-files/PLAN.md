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

This plan makes the `worktree_create` handler **symlink** a configurable list of
git-ignored files from the repository top-level into the newly-created worktree
root, so a worktree "just works" like the main checkout. A symlink (not a copy)
keeps the main working copy as the **single source of truth**: a copy would fork
into two files that drift apart, whereas a link means editing the canonical file
is reflected in every worktree with no stale duplicate to reconcile. Symlinking
is best-effort, only on fresh creation (never on idempotent re-fire), never
clobbers an existing destination, and never blocks or fails worktree creation.

## Goals

- On fresh worktree creation, symlink a configured list of files (default
  `.env.local`, `.env.test.local`) from the repo top-level into the worktree,
  each link pointing back at the canonical file (single source of truth).
- Make the file list configurable via a `symlink_files` handler option.
- Symlinking is best-effort: a failure logs a warning and is skipped; worktree
  creation (and the returned path) is never broken by a symlink failure.
- Never clobber a destination that already exists; no re-seed on idempotent
  re-fire.

## Non-Goals

- No copying — symlink only, so the main working copy stays the single source of
  truth.
- No symlinking of tracked files (git already provides those in the checkout).
- No glob/wildcard expansion — an explicit filename list only (relative paths
  allowed; absolute paths and `..` traversal are ignored for safety).
- No recursive directory linking.

## Tasks

### Phase 1: TDD implementation

- [x] ✅ **Task 1.1**: Write failing tests for env-file symlinking on the handler
  - [x] ✅ symlinks default env files present at repo root
  - [x] ✅ link is live — reflects edits to the canonical file (single source of truth)
  - [x] ✅ skips sources that do not exist
  - [x] ✅ does not re-seed on idempotent re-fire
  - [x] ✅ honours a configured `symlink_files` list
  - [x] ✅ ignores unsafe entries (absolute / `..`)
  - [x] ✅ never clobbers an existing destination
  - [x] ✅ symlink failure does not break worktree creation
- [x] ✅ **Task 1.2**: Implement symlinking in `WorktreeCreateHandler`
- [x] ✅ **Task 1.3**: Update `get_claude_md()` guidance
- [x] ✅ **Task 1.4**: Document the `symlink_files` option in `hooks-daemon.yaml.example`

### Phase 2: Verify

- [x] ✅ **Task 2.1**: Run full QA (`llm_qa.py all` via uv)
- [ ] ⬜ **Task 2.2**: Hand off diff for `/release`

### Phase 3: Adversarial review fixes (see `opus-review-1.md`)

- [x] ✅ **Task 3.1**: HIGH — relative symlink target (survives host↔container
  path-view remap); absolute link dangled across a bind-mount prefix change
- [x] ✅ **Task 3.2**: MEDIUM — coerce a bare-string `symlink_files` to a list
  (was silently iterated per-character into a no-op)
- [x] ✅ **Task 3.3**: MEDIUM — restore `is_file()` source check so a directory
  source is not linked (honours the no-directory-linking Non-Goal)
- [x] ✅ **Task 3.4**: Tests for all three (relative-link + relocation, string
  coercion, directory-source skip)
- Deferred by decision: MEDIUM SSoT destructive-edit hazard (accepted as-is);
  MEDIUM `_repo_toplevel`/`_get_git_toplevel` DRY extraction (not worth the
  cross-module surface on this change)

## Success Criteria

- [ ] A fresh worktree contains symlinks to the configured files when they exist
      at the repo top-level, resolving to the canonical files.
- [ ] All new + existing tests pass; QA is green.
- [ ] No secrets are embedded in code, tests, or fixtures (public branch).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only. -->

- <!-- delivery commit hash -->
