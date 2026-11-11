# Plan 00598: resolve venv prefers own slug over sibling view

**Status**: In Progress
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

- [ ] ⬜ **Task 1.1**: slug-match tie-break in `_rv_pick_ranked_scan` and `_scan_rank`, kept
  in step (a parity test if one exists for the pair)
- [ ] ⬜ **Task 1.2**: no drift warning for a non-matching-slug candidate; the own-slug
  warning is unchanged
- [ ] ⬜ **Task 1.3**: release note

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: independent review, merge, main CI green, close #199

## Success Criteria

- [ ] The #199 reproduction prints no warning and resolves the same venv
- [ ] A broken own-slug venv still warns
- [ ] Release-bound consequences in the holding area: a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`

## Delivery & Milestones

- <!-- delivery commit hash -->
