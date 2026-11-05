# Plan 00567: lsp coverage extensionless file targets

**Status**: Complete
**Created**: 2026-11-05
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #162

## Overview

`lsp_enforcement` is documented to enforce only where an enabled language server serves the searched file type, and
only to advise elsewhere. When a symbol-like grep names two or more files that carry no suffix (for example shell
scripts with no extension), `_searched_suffixes` finds no suffix and `_searched_directories` returns nothing, because
the targets are files. `_lsp_coverage` then falls back to "covered whenever any server is enabled", so the search is
denied. The same search over the files' directory is judged from the directory survey and allowed with the advisory.

The fix judges named file targets that exist from their own suffixes, treating an extensionless file as unserved. The
"cannot tell, so assume covered" fallback is kept only for targets that cannot be judged, such as a file list piped in
through `xargs`.

## Goals

- `grep -n sym a b` over existing extensionless files that no server serves gets the advisory allow, the same verdict
  as `grep -rn sym <their dir>`.
- A named file with a served suffix is still enforced, including in a mixed list of served and unserved targets.
- Targets that cannot be judged keep the current fallback.

## Non-Goals

- Detecting a language from a shebang. That is a possible follow-up; an extensionless file counts as unserved here.

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: Failing tests: two extensionless named files → allow (advisory); one `.py` plus one extensionless
  file with `.py` served → deny; a nonexistent target → the fallback is unchanged.
- [x] ✅ **Task 1.2**: Implement in `_lsp_coverage` (and helpers); update the guidance if its wording changes.
- [x] ✅ **Task 1.3**: Release callout; targeted QA; merge; comment and close #162.

## Success Criteria

- [x] Same files, same verdict, whether named individually or searched by directory, proven by a test that failed
  before the fix (red `18348ecf8`: two DENY where ALLOW was expected); verified live after the merge.
- [x] Targeted QA passes (42/42 on the combined #161/#162 head, nothing unmapped).
- [x] Release-bound consequence recorded in the pending-release holding area: callout
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/002-lsp-enforcement-extensionless-file-targets.md`.

## Delivery & Milestones

- Plan filed from issue #162 triage.
- Red tests `18348ecf8`; fix `e26195147`; merged to main via `6ab6b7bfb` (release note 002). Issue #162 closed after main CI run 42084490638 passed.
