# Plan 00598: resolve venv prefers own slug over sibling view

**Status**: Complete (2026-11-11)
**Created**: 2026-11-11
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #199

## Overview

When one checkout is visible at two paths (for example a container bind mount of the
host checkout), each path builds its own venv under `untracked/`, slugged by its path
(GitHub #199). Both venvs carry the same `lock_hash`. `_rv_pick_ranked_scan` in
`scripts/lib/resolve_venv.sh` ranks candidates by `lock_hash` only, as `_scan_rank` in
`daemon/paths.py` does. So the other path's venv ties at rank 0, sorts first, and
fails the usable probe when that venv was built by another Python. Each time the
interpreter cache misses, which is every write into `untracked/`, the CLI prints
`resolve_venv: candidate … interpreter drift … -- skipping` before choosing the right
venv. The call succeeds; only the warning is wrong, and agents read it as a fault.

## Goals

- Among candidates of equal rank, a venv whose slug names THIS project path is probed
  first, in the shell resolver and its Python mirror alike.
- A failed probe of a venv slugged for a different path is not reported on every call.
- The resolver still chooses the same venv as before, and a genuinely broken own venv
  still warns.

## Non-Goals

- Pruning or rebuilding another view's venv; it belongs to that view.

## Tasks

### Phase 1: Fix (TDD)

- [x] ✅ **Task 1.1**: own-slug tie-break in `_rv_pick_ranked_scan` and in the Python
  mirror's `_scan_sort_key` (`_scan_rank`, then own slug first)
- [x] ✅ **Task 1.2**: no drift warning for a non-matching-slug candidate; the own-slug
  warning is unchanged; the no-usable-venv error adds a line counting the skipped
  other-path venvs
- [x] ✅ **Task 1.3**: release note

### Phase 2: Delivery

- [x] ✅ **Task 2.1**: independent review, merge, main CI green, close #199

## Success Criteria

- [x] The #199 reproduction prints no warning and resolves the same venv
- [x] A broken own-slug venv still warns
- [x] Release-bound consequences in the holding area: a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (054)

## Delivery & Milestones

- Merged at `81ebd9bf9` (commits `b74c48571`, `40d1dcf61`). CI follow-up `6f4f8a401`
  counts a skipped other-path venv by `venv_python_usable` rather than the exec bit.
  Main CI run 42967283894 green at `0be1b9d19`.

## Follow-ups

- Existing before this plan, raised by the review: the shell scan still accepts a
  working venv slugged for another path, while `paths.py` `_venv_slug_eligible`
  rejects one. Low impact (the shell's choice only runs `paths.py`); unscheduled.
- `_rv_venv_is_own_slug` matches the slug as a literal prefix where Python takes the
  rightmost match; they differ only for a slug that itself contains `-pyNN-<hex>`.
