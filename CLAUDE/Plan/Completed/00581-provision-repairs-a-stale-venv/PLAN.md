# Plan 00581: provision repairs a stale venv

**Status**: Complete
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #168

## Overview

`provision.sh` (root, deployed byte-identical as `.claude/provision.sh`) builds a checkout's local daemon install at
the expected version. When the daemon clone is already at that version (Step 2, ~line 1027), it prints "already at vX,
the expected version: nothing to do" and exits 0. It never checks that the venv was built for the current
`pyproject.toml` / `uv.lock`. After a pull that changes the lock file but not the version, the venv is stale. The
restart path warns "DAEMON VENV NOT BUILT FOR THIS SOURCE", while provisioning still reports nothing to do. This state
was seen on this repository at a session start today, and `hooks-daemon repair` cleared it.

The lock-hash comparison already exists (`venv_lock_hash_matches` in `scripts/install/venv.sh`), and provisioning
already runs the bootstrap `repair` elsewhere (~line 1122). Prior art: Plan 00517 (lock hash and stale venvs) and Plan
00477 (provisioning and its background sync). Plan 00559 (#148) is adjacent: it covers the background sync of a clone
at the wrong version, not this equal-version path.

## Goals

- Clone at the expected version with a STALE venv: a foreground run repairs it through the existing bootstrap repair and
  says so. A `--background` run does not rebuild: it reports the stale venv and names `hooks-daemon repair`.
- Clone at the expected version with a matching venv: unchanged, "nothing to do".
- Root `provision.sh` and `.claude/provision.sh` stay byte-identical.

## Non-Goals

- No change to the version-mismatch sync path, to fresh provisioning, or to Plan 00559's background-sync scope.

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: RED test: equal version with a stale venv (foreground repairs; background names the repair) and
  equal version with a matching venv (nothing to do)
- [x] ✅ **Task 1.2**: GREEN in `provision.sh` and its deployed copy
- [x] ✅ **Task 1.3**: release-notes callout

### Phase 2: Delivery

- [x] ✅ **Task 2.1**: targeted QA, merge, verify CI, close #168

## Success Criteria

- [x] The new tests pass after the fix in all three cases; the two stale-venv cases failed before it, and the
  matching-venv case passed before it, as a regression guard on the unchanged path should
- [x] `provision.sh` and `.claude/provision.sh` are identical (the deployed copy is a symlink to the root script)
- [x] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
- [x] Merged to main with green CI; #168 closed

## Delivery & Milestones

- `cfa601263`: fix, tests and release note `017-provision-repairs-a-stale-venv.md`; targeted QA 42/42; CI QA run
  42650039659 and CodeQL 42650039133 success; #168 closed
