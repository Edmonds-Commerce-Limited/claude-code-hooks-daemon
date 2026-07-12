# Plan 00155: performance tuning wave 1 (daemon-side, safe)

**Status**: In Progress
**Created**: 2026-07-12
**Owner**: joseph
**Priority**: Medium
**Themes**: performance
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (small, sequential, TDD)

## Overview

First implementation wave off the back of the Plan 00154 performance research.
This wave takes only the **pure-Python, daemon-side** tuning wins that carry no
forwarder-contract or distribution risk — the changes that cannot regress the
safety-critical hook transport and are fully unit-testable. The larger win
(dropping `jq` from the wrappers, T2) and the `init.sh` slimming (T3) touch the
transport and are deliberately deferred to a later, more heavily gated wave.

Grounding evidence: [Plan 00154 RESEARCH.md](../Completed/00154-daemon-performance-rust-vs-python-research/RESEARCH.md),
tuning catalogue [PYTHON-TUNING.md](../Completed/00154-daemon-performance-rust-vs-python-research/PYTHON-TUNING.md).
Durable hub: [CLAUDE/Performance/README.md](../../Performance/README.md).

Prime directive (from the user): **meaningful performance improvements without
any loss of functionality or stability.** Every change ships with tests proving
behaviour is unchanged, and the daemon-restart + full QA gates must stay green.

## Goals

- **T1** — memoise `is_hooks_daemon_repo` so `daemon_restart_verifier` stops
  forking `git remote get-url origin` on every Bash event (measured ~1.4 ms p50
  per Bash command; ~75% of the Bash-event daemon-side cost).
- **T4** — cut the status-line git subprocess churn: one combined
  `git status --porcelain=v2 --branch` call and/or a short TTL cache keyed by
  repo toplevel, so streaming renders (~every 300 ms) don't fork ~5 git
  processes each time. CPU-churn win (battery/fan), not a latency win.
- **Cleanup** — resolve the legacy one-shot entry
  `src/claude_code_hooks_daemon/hooks/pre_tool_use.py` that crashes against the
  current plugins config schema (a `str` is passed to
  `PluginLoader.load_handlers_from_config`). Dead-or-broken either way.

## Non-Goals

- No `jq` removal (T2), no `init.sh` slimming (T3) — deferred to wave 2; they
  touch the transport contract and need the forwarder acceptance gates.
- No content-scanner rework (T5) — only worth it if large writes are shown to be
  common; not demonstrated.
- No new compiled dependencies (orjson T6), no Rust.
- No behaviour changes to any handler's block/allow decisions.

## Tasks

### Phase 1: T1 — cache is_hooks_daemon_repo ✅

- [x] ✅ **Task 1.1**: RED — failing test asserting `is_hooks_daemon_repo`
  resolves the git remote at most once per workspace root across repeated calls
  (spy/patch the subprocess boundary; assert call count).
- [x] ✅ **Task 1.2**: GREEN — memoise per directory (module-level
  `_REPO_DETECTION_CACHE` dict; detection extracted to `_detect_hooks_daemon_repo`,
  cleared via `_clear_repo_detection_cache`). One fork per daemon lifetime.
- [x] ✅ **Task 1.3**: Verified behaviour unchanged for positive and negative
  detection cases; distinct directories cached separately; False also cached.
- [x] ✅ **Task 1.4**: Full QA 13/13 (9993 tests, 95.5% cov); daemon restart
  RUNNING. No handler decision behaviour changed.

### Phase 2: T4 — status-line git subprocess reduction ✅

- [x] ✅ **Task 2.1**: RED — characterised render fork behaviour in tests
  (4 new `TestGitBranchRenderCache` tests: cache-hit-within-TTL, cwd-keyed
  isolation, TTL=0 disables, expiry re-renders).
- [x] ✅ **Task 2.2**: GREEN — added a short per-cwd render TTL cache
  (`_DEFAULT_RENDER_TTL_SECONDS = 2.0`, config-injectable `render_ttl_seconds`);
  extracted the render body into `_render_git_context`, `handle()` now wraps it
  with `_cached_render`/`_store_render`. Serves streaming renders from cache,
  cutting ~4 git forks per hit.
- [x] ✅ **Task 2.3**: Output proven unchanged — existing colour/icon/ahead-behind/
  stash tests all pass through the cache-miss path; cache hit returns the same
  context list. Updated `test_default_branch_detection_cached` to disable the
  render cache so it still isolates default-branch memoisation.
- [x] ✅ **Task 2.4**: Full QA 13/13 (9997 tests, 95.5% cov); daemon RUNNING;
  live status render verified (`⎇ feature/performance-tuning ✚3`). Reconciled
  the drift-proof `error_hiding` exclusion (function `handle` → `_render_git_context`).

### Phase 3: legacy one-shot entry cleanup

- [ ] ⬜ **Task 3.1**: Confirm the crash and whether the one-shot path is still
  referenced anywhere (hooks wrappers, docs, tests). Decide fix-vs-delete.
- [ ] ⬜ **Task 3.2**: Apply the decision with tests (fix the schema call, or
  remove the dead path and any references) — no silent behaviour change.
- [ ] ⬜ **Task 3.3**: Full QA + daemon restart RUNNING.

### Phase 4: measure & record

- [ ] ⬜ **Task 4.1**: Re-run the relevant Plan 00154 harness probes
  (verifier matches() timing; status render) and record before/after in
  `CLAUDE/Performance/README.md` (and BASELINE if numbers move).

## Success Criteria

- [ ] T1 forks the remote at most once per daemon lifetime; measured Bash-event
  daemon-side p50 drops toward ~0.4 ms.
- [ ] T4 reduces git forks per status render (combined call and/or TTL);
  outputs identical for representative states.
- [ ] Legacy one-shot entry no longer crashes (fixed or removed cleanly).
- [ ] Full QA green (13/13), 95%+ coverage, daemon restarts RUNNING after every
  change, no handler decision behaviour changed.

## Notes & Updates

### 2026-07-12

- Plan scaffolded on branch `feature/performance-tuning`. Wave 1 = safe
  daemon-side wins only (T1, T4, legacy-entry cleanup); T2/T3 deferred to wave 2.
  Reusing the session's existing failsafe recovery cron `d4cb559d` (still live
  from the 00154 session) rather than creating a duplicate.
