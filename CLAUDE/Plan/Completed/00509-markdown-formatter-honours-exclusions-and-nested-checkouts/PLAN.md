# Plan 00509: markdown formatter honours exclusions and nested checkouts

**Status**: Complete
**Created**: 2026-10-12
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #79

## Overview

The PostToolUse handler `markdown_table_formatter` runs mdformat over the whole
of every `.md` file that is written. There are two problems with that:

- **Nothing can scope it.** It reads no handler options and never consults
  `daemon.exclude_paths`. Its only scoping is the built-in plan `JOURNAL/`
  exemption.
- **It reformats other repositories' files.** It reformats a `.md` file inside
  a nested, separately versioned git checkout below the project root. The
  `format-markdown` CLI stopped doing that in Plan 00429 (#47).

Its advisory also understates what changed. It says "aligned table pipes" when
bullet markers, blank lines and escapes also changed.

Coordinator ruling (the triage is in #79):

- **Exclusions:** the handler honours its own `exclude_paths` option and the
  project-wide `daemon.exclude_paths`.
- **Nested checkouts:** a file inside a nested separate git checkout is skipped.
  A linked worktree of this repository is still formatted.
- **Whole-file formatting:** this stays, because it is the project policy
  shared with `format-markdown` (Plan 00098).
- **Advisory:** it names every kind of change, or says plainly that the whole
  file was reformatted.

## Goals

- `exclude_paths`, both the handler option and the project-wide setting,
  stops the handler for a matching path.
- A `.md` file in a nested separate git checkout is never rewritten.
- The advisory never claims a narrower change than the one made.
- The guidance states that formatting is whole-file, and how to exclude a path.

## Non-Goals

- Formatting tables only.
- Recognising generated-content markers. An excluded path covers that case.

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: RED. Tests cover:
  - a path excluded by the handler option is left alone;
  - a path excluded by `daemon.exclude_paths` is left alone;
  - a file in a nested `git init` directory below the root is untouched;
  - a file in a linked worktree is still formatted;
  - the advisory names bullet, blank-line and escape changes, or says the
    whole file was reformatted, never only "aligned table pipes";
  - the existing behaviour is unchanged otherwise.
- [x] ✅ **Task 1.2**: GREEN. Implement, reusing the shared exclude-path
  matcher and the nested-checkout boundary that already exist.
- [x] ✅ **Task 1.3**: Update the handler's `get_claude_md` guidance and its
  HANDLER_REFERENCE entry. Add a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Land

- [x] ✅ **Task 2.1**: Review, coordinator checks and merge; then comment on
  and close #79. Merged `52fd716f4` after one review round, in which a linked
  worktree of an unrelated repository was found to be still formatted. The
  range-QA fix is `4c30051d8`.

## Success Criteria

- [x] The issue's reproduction is fixed for nested checkouts and for excluded
  paths, and its advisory is accurate.
- [x] The release-bound consequence, a new option and a changed boundary, is in
  the pending-release holding area as release note 032 in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- Issue #79 triaged and claimed.
- Merged `52fd716f4` and `4c30051d8`; the range QA was green in substance.
