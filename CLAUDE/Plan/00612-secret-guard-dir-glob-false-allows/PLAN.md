# Plan 00612: secret guard dir glob false allows

**Status**: In Progress
**Created**: 2026-11-16
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

This plan follows up Plan 00610 (GitHub #204). That plan made
`secret_file_guard` judge a glob ending in `/` as the directories it expands
to, through `ProtectedFileIndex.directories_matching`. Its Opus re-review left
two false allows, and main had both before Plan 00610 as well. Each lets a
recursive reader past the guard to a protected file:

1. POSIX bracket classes such as `[[:alpha:]]*/` reach `fnmatch` without
   being translated, so they never match. `grep -r x [[:alpha:]]*/` is
   allowed even when a matching directory holds a protected file.
2. A symlinked directory that holds a protected file is not matched, because
   the index holds the real path. `grep -r x l*/` is allowed when `l` is a
   symlink to such a directory.

The work was chosen by the awaiting-human stand-in (see JOURNAL/), not by the
owner.

## Goals

- `grep -r x [[:alpha:]]*/` and the other POSIX classes are judged as bash
  expands them: denied when a matching directory holds a protected file.
- A trailing-slash glob that matches a symlink to a directory holding a
  protected file is denied.

## Non-Goals

- Changing the base-directory match of `**/` under globstar (Plan 00610
  follow-up 3). It is a false deny on the safe side, a test asserts it, and
  the stand-in left it for the owner.
- The bash older than 5.2 `.*/` behaviour.

## Tasks

### Phase 1: test-first fixes

- [ ] ⬜ **Task 1.1**: Write failing tests for POSIX bracket classes in
  trailing-slash globs, and in the shared matcher if file globs are affected
  too.
- [ ] ⬜ **Task 1.2**: Translate POSIX classes in the shared segment matcher.
- [ ] ⬜ **Task 1.3**: Write failing tests for a symlinked directory matched by
  a trailing-slash glob in a recursive reader, then fix it without walking
  the whole filesystem.
- [ ] ⬜ **Task 1.4**: Add a release note under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [ ] Both false allows are reproduced by failing tests and fixed, and
  targeted QA passes.
- [ ] The release-bound consequence is recorded in the holding area: a release
  note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] Merged to main with CI green.

## Delivery & Milestones

- <!-- merge commit hash -->
