# Plan 00614: secret guard resolves links against hook cwd

**Status**: In Progress
**Created**: 2026-11-16
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00613 Task 1.1 ran the real `SecretFileGuardHandler` against synthetic
repos and symlinks (report: `../00613-worktree-link-secret-verb/subagent-reports/261116-symlink-resolution.md`).
Absolute link paths are judged on their resolved target in every tool. Three
gaps remain, each a way to reach a protected file's content through a link:

1. A RELATIVE Bash token (`cat link`, `cat < link`, `python -c "open('link')"`)
   is allowed when the daemon process cwd is not the command's cwd.
   `_realpath_if_resolvable` resolves the raw token against the process cwd,
   and the daemon runs `os.chdir("/")` (`daemon/cli.py:929`), so in production
   the link is judged against `/` and passes.
2. `Grep` or `grep -r` rooted at a directory link into another checkout is
   allowed when the project root is the worktree, because only the primary's
   index covers the target.
3. A glob under a directory link (`cat dlink/*`) is never realpath-resolved.

This is a defect in a guard that protects secrets, so it is fixed test-first and
fails closed. It is independent of 00613's verb; it also matters for any
project whose worktrees carry seeded links to protected files.

## Goals

- Every case above is denied, with a failing test first for each.
- No loosening anywhere: an absolute link, a literal protected path and every
  existing deny stay denied.

## Non-Goals

- A link-creating verb (Plan 00613).
- The Glob tool, which only lists names and is allowed by design.

## Tasks

### Phase 1: Defence

- [x] ✅ **Task 1.1**: Failing tests for gaps 1, 2 and 3 on synthetic fixtures
  (dummy protected file, relative and directory links, hook `cwd` set to the
  worktree while the process cwd is `/`).

### Phase 2: Fix

- [x] ✅ **Task 2.1**: Join a relative token to the hook `cwd` before the
  `is_symlink` check and `realpath`, and resolve when any path component is a link.
- [ ] ⬜ **Task 2.2**: Add the realpath of a directory link's target to the
  index bases, or deny by default when it lies outside the indexed project.
- [ ] ⬜ **Task 2.3**: Expand glob tokens and realpath each match.
- [ ] ⬜ **Task 2.4**: Release note.

## Success Criteria

- [ ] Each gap has a test that failed before its fix.
- [ ] Every pre-existing deny still holds (the existing secret-guard suite is green).
- [ ] Release-bound consequences recorded in the pending release notes.

## Delivery & Milestones

- Found by the 00613 Task 1.1 probe; no delivery yet.
