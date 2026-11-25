# Plan 00615: secret guard find exec and xargs reads

**Status**: Complete
**Created**: 2026-11-16
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

An independent adversarial review of the Plan 00614 branch (report kept under
`untracked/scratch/review-614.md` at the time; reproduced commands are in the
review) found that a command which makes `find` or `xargs` run a reader over a
set of paths reads protected files without the secret guard denying it:
`find <dir> -exec cat {} +` and `find <dir> | xargs cat`. It holds both through
a link and for a protected file inside the project. It is present on `main`
today, so it is independent of the 00614 change. The reviewer found no row for
it in the dangerous-invocation corpus.

The secret guard exists so a protected file's contents never reach an agent by
any route; a command that expands a path set and hands it to a reader is a
route. This plan closes it test-first and fails closed.

**Outcome**: the work was done under Plan 00618 Task 2.1, in `6301485f7` (red
tests, `tests/unit/handlers/pre_tool_use/test_secret_file_guard_directory_readers.py`)
and `d22224dc0` (the fix in `utils/recursive_search.py`, plus the corpus rows),
and shipped in v3.75.0. This plan was never ticked at the time. Closed after
re-running that test file on `main` (162 passed) and finding the one item
missing: the operator-facing release note, now written as UNRELEASED note 111.

## Goals

- `find ... -exec <reader> {} +`, `find ... -exec <reader> {} \;`,
  `find ... | xargs <reader>` and `-print0 | xargs -0 <reader>` are denied when
  the searched root can contain a protected file, with a failing test first for
  each form, for both a file inside the project and one reached through a link.
- No loosening, and ordinary `find` with a harmless action stays allowed.

## Non-Goals

- Link resolution for relative tokens (Plan 00614).
- A link-creating verb (Plan 00613).

## Tasks

### Phase 1: Defence

- [x] ✅ **Task 1.1**: Failing tests for each `find -exec` and `xargs` form on
  synthetic fixtures only (a dummy protected-named file; never a real secret).
  Done in `6301485f7`.
- [x] ✅ **Task 1.2**: Add the forms to the dangerous-invocation corpus so a
  future regression is caught by the corpus test. Done in `d22224dc0`
  (`scripts/qa/dangerous-invocation-corpus.yaml`).

### Phase 2: Fix

- [x] ✅ **Task 2.1**: Treat a reader named as the `-exec` command, or as the
  command `xargs` runs, as a reader of every path the search root expands to,
  and judge the root with the existing recursive-search rules. Done in
  `d22224dc0`.
- [x] ✅ **Task 2.2**: Release note. UNRELEASED note 111 (this plan's closing
  commit); v3.75.0 shipped the fix without one.

## Success Criteria

- [x] Each form has a test that failed before its fix (red in `6301485f7`, green in `d22224dc0`).
- [x] Every pre-existing deny and allow still holds (the secret-guard suite is green).
- [x] Release-bound consequences recorded in the pending release notes (UNRELEASED note 111).

## Delivery & Milestones

- Found by the 00614 review. Fixed and shipped as part of Plan 00618 (v3.75.0); closed at the archiving commit.
