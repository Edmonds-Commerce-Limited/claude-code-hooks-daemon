# Plan 00191: worktree create seed env files

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

This plan makes the `worktree_create` handler **symlink** an **opt-in** list of
git-ignored files from the repository top-level into the newly-created worktree
root, so a worktree "just works" like the main checkout. A symlink (not a copy)
keeps the main working copy as the **single source of truth**: a copy would fork
into two files that drift apart, whereas a link means editing the canonical file
is reflected in every worktree with no stale duplicate to reconcile. The links
are **relative** so they survive the identical tree being viewed at different
absolute prefixes (host vs container bind-mount). Symlinking runs only on fresh
creation (never on idempotent re-fire) and never clobbers an existing
destination. It is **fail-fast**: every configured entry must resolve to a file
at the repo root, or worktree creation aborts loudly — surfacing a
misconfiguration rather than silently producing a worktree missing its files.

## Goals

- On fresh worktree creation, symlink an opt-in list of files (recommended
  `.env.local`, `.env.test.local`) from the repo top-level into the worktree,
  each **relative** link pointing back at the canonical file (single source of
  truth).
- Make the file list configurable via a `symlink_files` handler option
  (default empty — opt-in).
- Fail-fast: a configured entry that is unsafe, missing, or not a regular file
  raises `WorktreeSeedError` **before** the worktree is created (no partial
  state); a symlink syscall failure propagates.
- Never clobber a destination that already exists; no re-seed on idempotent
  re-fire.

## Non-Goals

- No copying — symlink only, so the main working copy stays the single source of
  truth.
- No symlinking of tracked files (git already provides those in the checkout).
- No glob/wildcard expansion — an explicit filename list only (relative paths
  allowed; absolute paths and `..` traversal are rejected for safety).
- No recursive directory linking (a directory source is a configuration error).
- Not on-by-default — a shared upstream daemon must not abort worktree creation
  in repos that simply lack these files, so symlinking only runs when a project
  opts in.

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

### Phase 4: PR #35 review round 2 (maintainer) + merge main

- [x] ✅ **Task 4.0**: Merge latest `origin/main` into the branch; resolve the
  plan-number collision by renumbering this plan 00190 → **00191** (main claimed
  00190 for the plan-journal-separation plan)
- [x] ✅ **Task 4.1**: "symlinks MUST be relative" — already satisfied by Task 3.1
- [x] ✅ **Task 4.2**: "fail fast and loud for any configured path not present in
  repo root" — reworked to **opt-in + fail-fast**: `symlink_files` defaults empty;
  a configured entry that is unsafe/missing/not-a-file raises `WorktreeSeedError`
  before creation. Removed the best-effort skip + both `error_hiding_exclusions`
  entries (handler no longer swallows anything)
- [x] ✅ **Task 4.3**: Rewrote tests for opt-in + fail-fast (unconfigured no-op,
  missing-file-raises-before-creation, unsafe-raises, directory-raises,
  syscall-failure-propagates) + kept relative-link/relocation, string coercion,
  never-clobber, SSoT live-link
- [x] ✅ **Task 4.4**: Updated `get_claude_md()` + `yaml.example` (opt-in,
  fail-fast, SSoT write-through corollary)

## Success Criteria

- [ ] A fresh worktree contains symlinks to the configured files when they exist
      at the repo top-level, resolving to the canonical files.
- [ ] All new + existing tests pass; QA is green.
- [ ] No secrets are embedded in code, tests, or fixtures (public branch).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only. -->

- <!-- delivery commit hash -->
