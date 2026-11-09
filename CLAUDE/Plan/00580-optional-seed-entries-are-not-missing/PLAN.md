# Plan 00580: optional seed entries are not missing

**Status**: In Progress
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #167

## Overview

`hooks-daemon check-worktree-seed` reports drift between the `worktree_create` seed configuration and the repository.
`diff_seed_config` (`src/claude_code_hooks_daemon/utils/worktree_seed_suggestions.py`, ~202) builds its `missing` set
from every configured entry whose path does not exist, and never reads `SeedEntry.optional` (`core/worktree_seed.py`).
Creation already skips an absent optional entry with a log line. The report, though, lists that entry under MISSING,
says it aborts the next worktree creation, and tells the reader to remove a correct entry.

The seed mechanism and the report came from Plan 00267. This is separate from Plan 00579 (#164, the removal guard and
copy-mode seeds), so it is fixed on its own.

## Goals

- An absent `optional: true` entry is never listed as MISSING, and nothing tells the reader to remove it.
- An absent required entry is still MISSING, with its current wording.

## Non-Goals

- No change to creation-time seeding, to the removal guard (Plan 00579), or to the `unconfigured` half of the report.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED test: an absent optional entry is not in `missing`; an absent required entry still is
- [ ] ⬜ **Task 1.2**: GREEN in `diff_seed_config`; check that the CLI's MISSING wording is correct for what remains
- [ ] ⬜ **Task 1.3**: release-notes callout

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: targeted QA, merge, verify CI, close #167

## Success Criteria

- [ ] The new test failed before the fix and passes after it, in both directions (optional absent, required absent)
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
- [ ] Merged to main with green CI; #167 closed

## Delivery & Milestones

- (pending)
