# Plan 00610: secret guard trailing slash glob

**Status**: In Progress
**Created**: 2026-11-16
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #204

## Overview

`secret_file_guard` denies `ls -d */` when the project root holds a protected
file. The guard judges a shell glob with `ProtectedFileIndex.glob_matches`
(`src/claude_code_hooks_daemon/utils/protected_file_index.py`). That function
normalises each glob with `os.path.normpath`, which drops a trailing `/`, so
`*/` is matched like `*`, against protected FILE paths.

In the shell, a glob ending in `/` expands only to directories. It can never
name a file at its own level. The fix is to judge a trailing-slash glob as the
directories it can expand to.

## Goals

- A glob ending in `/` matches a protected file only through one of that
  file's ancestor directories. It is never matched against the file itself.
- For a trailing-slash glob, the verdict agrees with the verdict for the same
  literal directory argument. A tool that recurses into the directory
  (`grep -r x */`) is still denied when a protected file lies below a matching
  directory, exactly as `grep -r x dir/` is.

## Non-Goals

- No change to protected patterns, default config or other glob shapes. The
  absolute multi-wildcard fail-closed case belongs to Plan 00481.

## Tasks

### Phase 1: test-first fix

- [ ] ⬜ **Task 1.1**: Write failing tests: `ls -d */` is allowed when only a
  file at that level is protected. `grep -r x */` and the index-level
  `glob_matches("*/")` are still judged against files below a matching
  directory.
- [ ] ⬜ **Task 1.2**: Fix the trailing-slash handling in `glob_matches` and
  in any caller that strips the slash first. Then make the new tests pass.
- [ ] ⬜ **Task 1.3**: Add a release note under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [ ] The failing-then-passing tests are committed, and targeted QA passes.
- [ ] The release-bound consequence is recorded in the holding area: a release
  note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] Issue #204 is commented and closed after the merge, with main CI green.

## Delivery & Milestones

- <!-- merge commit hash -->
