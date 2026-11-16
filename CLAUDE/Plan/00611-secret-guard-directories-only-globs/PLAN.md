# Plan 00611: secret guard directories only globs

**Status**: In Progress
**Created**: 2026-11-16
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #204

## Overview

`secret_file_guard` denied `ls -d */` whenever a protected file sat at that level of the tree. The glob matcher in `utils/protected_file_index.py` normalised the token with `os.path.normpath`, which drops the trailing slash, so the directories-only glob `*/` was judged as `*` and matched the protected file.

A trailing slash means the glob matches directories only, so it can never name a protected file directly. The matcher now skips such a token. Every other glob shape (`*`, `keys/*`, `*/<name>`, `**/<name>`) is denied exactly as before.

The fix and its unit tests are already on the branch; this plan is the home for that work and for the release note that records it.

## Goals

- `ls -d */` is not denied by the secret file guard.
- No protected file becomes reachable through any other glob shape.

## Non-Goals

- Changing how any glob without a trailing slash is matched.

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: Skip a trailing-slash (directories-only) glob token in `protected_file_index.py`
- [x] ✅ **Task 1.2**: Unit tests in `tests/unit/utils/test_protected_file_index.py` (allowed `*/`, still denied `*`, `keys/*`, `*/<name>`, `**/<name>`)
- [x] ✅ **Task 1.3**: Release note `085-secret-guard-allows-directories-only-globs.md` carrying this plan number

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: CI green on the branch, then merge

## Success Criteria

- [x] Unit tests for the trailing-slash glob pass
- [x] Release-note holding area: the pending release note `085-secret-guard-allows-directories-only-globs.md` records the operator-visible consequence
- [ ] Branch merged with CI green

## Delivery & Milestones

- Fix commit: cb152b184
