# Plan 00610: secret guard trailing slash glob

**Status**: Complete
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

- [x] ✅ **Task 1.1**: Write failing tests: `ls -d */` is allowed when only a
  file at that level is protected. `grep -r x */` and the index-level
  `glob_matches("*/")` are still judged against files below a matching
  directory. Of the 39 new tests, 30 fail on main.
- [x] ✅ **Task 1.2**: Fix the trailing-slash handling. A trailing-slash root
  is judged by `ProtectedFileIndex.directories_matching`, which matches the
  glob against each protected file's ancestor directories with the existing
  `_segments_match`. Nothing is expanded on the filesystem. `[^x]` now negates
  like `[!x]`.
- [x] ✅ **Task 1.3**: Release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/084-secret-guard-trailing-slash-glob.md`.

## Success Criteria

- [x] The failing-then-passing tests are committed, and targeted QA passes
  (43/43 at `765e786e2`).
- [x] The release-bound consequence is recorded in the holding area: release
  note 084 in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [x] Issue #204 is commented and closed after the merge, with main CI green.

## Delivery & Milestones

- Fix `37892b587` (rework after the Opus review `5ddf49624..3415cd1ee`
  replaced an uncapped filesystem walk), merged at `31a2cce4f`. Main CI run
  43816232915 is green.

## Follow-ups

Non-blocking findings from the Opus re-review, not started:

- With `globstar` on, `**/` also matches the base directory, so
  `grep -r x **/` is denied when the only protected file is at the top level.
  The test `test_a_double_star_follows_the_default_expansion_flag`
  (`test_secret_file_guard_trailing_slash_glob.py:125-132`) asserts this
  behaviour. This is a false deny, on the safe side.
- POSIX bracket classes such as `[[:alpha:]]*/` are not translated before
  fnmatch, so they are allowed. Main does the same.
- A symlinked directory that holds a protected file (`grep -r x l*/`) is not
  matched, because the index holds the real path. Main does the same.
- On bash older than 5.2, `.*/` also matches `./` and `../`.
