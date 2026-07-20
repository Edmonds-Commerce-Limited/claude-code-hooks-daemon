# Plan 00184: venv accounting is symlink-aware and protects the live venv

**Status**: In Progress
**Created**: 2026-07-20
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded (TDD)

## Overview

Live dogfooding data-loss incident. While reclaiming the "170.8 MB reclaimable
legacy venv" that `disk-usage`/`list-venvs` reported, `prune-venvs --legacy --force` deleted the venv the running daemon and hook forwarders were actually
using — because `/workspace/untracked/venv-py311-66bbc57c` was a **symlink** to
the real `/workspace/untracked/venv`. Recovered by rebuilding the correct
fingerprint venv, but the accounting bug is real and severe (it deletes live
venvs).

Two defects in `daemon/cli.py` venv accounting:

1. **Symlink double-count.** `_enumerate_venvs` uses `child.is_dir()` (follows
   symlinks) and `_directory_size_bytes` walks through the symlink into the same
   target, so a symlink and its target are reported as **two** independent venvs
   with the **same** bytes counted twice (341.6 MB shown for one 170.8 MB dir).
2. **Live venv unprotected.** `is_current`/prune protection keys on
   `python_venv_fingerprint` (the management view's slug scheme,
   `workspace-py311-81c29529`), but the daemon + forwarders run the venv chosen
   by the **bootstrap resolver** `resolve_existing_venv_python`
   (`venv-py311-66bbc57c` here). When the two selection schemes disagree (a
   fingerprint-scheme migration plus a leftover symlink), the venv actually in
   use is flagged reclaimable and pruned.

## Goals

- `_enumerate_venvs` dedupes by real path so a symlink + its target count once.
- The venv the **bootstrap resolver** currently resolves to (by real path) is
  ALWAYS treated as current: never flagged reclaimable, never pruned — even when
  its fingerprint-scheme name differs from `python_venv_fingerprint`.
- `prune-venvs` refuses to delete a symlink entry or the resolver-active venv
  (belt-and-braces on top of the broadened `is_current`).
- `disk-usage`/`list-venvs` report honest, de-duplicated sizes.

## Non-Goals

- Reconciling the two fingerprint schemes (`resolve_existing_venv_python` vs
  `python_venv_fingerprint`) — tracked separately; here we only make accounting
  SAFE across the disagreement.
- Auto-deleting anything (Plan 00181 Decision 1 stands: surface, don't delete).

## Design

In `daemon/cli.py`:

- New helper `_resolver_active_venv_realpath(project_root) -> Path | None`:
  call `resolve_existing_venv_python(project_root)`, return
  `python_path.resolve().parent.parent` (venv dir realpath); return `None` when
  it raises (no usable venv).
- `_enumerate_venvs`: record `real_path = child.resolve()` and
  `is_symlink = child.is_symlink()`; **dedupe** entries whose `real_path` match
  (prefer the real directory name over a symlink alias). Mark `is_current` True
  when `real_path == resolver_active_realpath` OR
  `fingerprint == python_venv_fingerprint` (union — never lose the live one).
- `_reclaimable_venv_entries`: unchanged predicate, but now protected by the
  broadened `is_current`; also skip `is_symlink` entries.
- `cmd_prune_venvs`: never add an entry to `to_remove` when it `is_symlink` or
  its `real_path == resolver_active_realpath`; log why it was skipped.

## Tasks

### Phase 1: TDD fix

- [x] ✅ **Task 1.1**: RED — tests in `tests/unit/daemon/test_cli_venv_symlink_accounting.py`
  reproducing the incident: a symlink venv aliasing the resolver-active target ⇒
  (a) `_enumerate_venvs` yields ONE entry for the pair, (b) that entry is
  `is_current`, (c) `_reclaimable_venv_entries` excludes it, (d)
  `cmd_prune_venvs --legacy --force` does NOT delete it, (e) `disk-usage`
  does not double-count.
- [x] ✅ **Task 1.2**: GREEN — implemented the helper + symlink-aware dedupe +
  resolver-active protection + prune guard. Dropped a needless try/except +
  `error_hiding_exclusions.json` entry (verified `resolve_existing_venv_python`
  never raises; the `exists()` guard is the real no-venv signal).
- [x] ✅ **Task 1.3**: Full QA (`./scripts/qa/llm_qa.py all`) 13/13 (10468 tests,
  95.2% cov) + daemon restart RUNNING (PID 1258396). Fresh-venv gap fixed:
  added `types-psutil>=5.9` to `[dev]` + re-locked `uv.lock` (mypy 0 errors).

## Success Criteria

- [ ] A symlinked venv aliasing the live target is never double-counted, never
  flagged reclaimable, never pruned
- [ ] Existing venv tests still pass; all QA green; daemon RUNNING

## Notes & Updates

- Reuses the session-wide failsafe recovery cron `e626acaa` (no duplicate cron).
- Recovery already done live: rebuilt `venv-workspace-py311-81c29529`, daemon
  RUNNING (PID 1197510), forwarders serving.

## Delivery & Milestones

<!-- commit hashes recorded as tasks land -->
